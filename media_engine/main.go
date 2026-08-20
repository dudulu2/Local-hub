package main

import (
    "bufio"
    "context"
    "encoding/json"
    "errors"
    "flag"
    "fmt"
    "io"
    "mime"
    "net"
    "net/http"
    "os"
    "os/exec"
    "path/filepath"
    "strconv"
    "strings"
    "sync"
    "syscall"
    "time"
)

type engine struct {
    root   string
    ffmpeg string
}

type startupInfo struct {
    Port int `json:"port"`
}

func main() {
    rootFlag := flag.String("root", ".", "media root")
    ffmpegFlag := flag.String("ffmpeg", "ffmpeg", "ffmpeg executable")
    portFlag := flag.Int("port", 0, "listen port; 0 chooses a free loopback port")
    flag.Parse()

    root, err := filepath.Abs(*rootFlag)
    if err != nil {
        fatal(err)
    }
    root, err = filepath.EvalSymlinks(root)
    if err != nil {
        fatal(err)
    }
    stat, err := os.Stat(root)
    if err != nil || !stat.IsDir() {
        fatal(fmt.Errorf("invalid media root: %s", root))
    }

    listener, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", *portFlag))
    if err != nil {
        fatal(err)
    }
    port := listener.Addr().(*net.TCPAddr).Port
    enc := json.NewEncoder(os.Stdout)
    _ = enc.Encode(startupInfo{Port: port})

    e := &engine{root: root, ffmpeg: *ffmpegFlag}
    mux := http.NewServeMux()
    mux.HandleFunc("/health", e.health)
    mux.HandleFunc("/direct", e.direct)
    mux.HandleFunc("/transcode.mp4", e.transcode)

    server := &http.Server{
        Handler:           withCORS(mux),
        ReadHeaderTimeout: 5 * time.Second,
        IdleTimeout:       30 * time.Second,
    }

    // The Python parent keeps this process' stdin pipe open. When LocalHub exits,
    // Windows closes the pipe and the helper shuts itself down as well.
    go func() {
        _, _ = io.Copy(io.Discard, os.Stdin)
        ctx, cancel := context.WithTimeout(context.Background(), 1200*time.Millisecond)
        defer cancel()
        _ = server.Shutdown(ctx)
    }()

    if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
        fatal(err)
    }
}

func fatal(err error) {
    fmt.Fprintln(os.Stderr, "LocalHub media engine:", err)
    os.Exit(1)
}

func withCORS(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.Header().Set("Access-Control-Allow-Origin", "*")
        w.Header().Set("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        w.Header().Set("Access-Control-Allow-Headers", "Range, Content-Type")
        w.Header().Set("Access-Control-Expose-Headers", "Accept-Ranges, Content-Range, Content-Length, Content-Type")
        w.Header().Set("X-Content-Type-Options", "nosniff")
        if r.Method == http.MethodOptions {
            w.WriteHeader(http.StatusNoContent)
            return
        }
        next.ServeHTTP(w, r)
    })
}

func (e *engine) health(w http.ResponseWriter, r *http.Request) {
    w.Header().Set("Content-Type", "application/json")
    w.Header().Set("Cache-Control", "no-store")
    _, _ = io.WriteString(w, `{"ok":true,"engine":"localhub-v4"}`)
}

func (e *engine) resolve(raw string) (string, error) {
    raw = strings.ReplaceAll(strings.TrimSpace(raw), "\\", "/")
    raw = strings.TrimLeft(raw, "/")
    if raw == "" {
        return "", errors.New("missing media path")
    }
    clean := filepath.Clean(filepath.FromSlash(raw))
    if clean == "." || filepath.IsAbs(clean) {
        return "", errors.New("invalid media path")
    }
    candidate := filepath.Join(e.root, clean)
    candidate, err := filepath.Abs(candidate)
    if err != nil {
        return "", err
    }
    rel, err := filepath.Rel(e.root, candidate)
    if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
        return "", errors.New("media path escapes root")
    }
    stat, err := os.Stat(candidate)
    if err != nil || !stat.Mode().IsRegular() {
        return "", os.ErrNotExist
    }
    return candidate, nil
}

func (e *engine) direct(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodGet && r.Method != http.MethodHead {
        http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
        return
    }
    filePath, err := e.resolve(r.URL.Query().Get("path"))
    if err != nil {
        http.NotFound(w, r)
        return
    }
    if ct := mime.TypeByExtension(strings.ToLower(filepath.Ext(filePath))); ct != "" {
        w.Header().Set("Content-Type", ct)
    }
    w.Header().Set("Content-Disposition", fmt.Sprintf("inline; filename=%q", filepath.Base(filePath)))
    w.Header().Set("Cache-Control", "private, max-age=0")
    // Go's standard library owns Range parsing, conditional requests and
    // cancellation here. Python is intentionally not in the media data path.
    http.ServeFile(w, r, filePath)
}

func (e *engine) transcode(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodGet {
        http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
        return
    }
    filePath, err := e.resolve(r.URL.Query().Get("path"))
    if err != nil {
        http.NotFound(w, r)
        return
    }

    start := 0.0
    if raw := r.URL.Query().Get("start"); raw != "" {
        if parsed, parseErr := strconv.ParseFloat(raw, 64); parseErr == nil && parsed > 0 {
            start = parsed
        }
    }
    mode := strings.ToLower(strings.TrimSpace(r.URL.Query().Get("mode")))
    if mode != "remux" {
        mode = "transcode"
    }

    args := []string{"-hide_banner", "-loglevel", "error", "-nostdin", "-fflags", "+genpts"}
    if start > 0 {
        args = append(args, "-ss", strconv.FormatFloat(start, 'f', 3, 64))
        if mode == "remux" {
            args = append(args, "-noaccurate_seek")
        }
    }
    args = append(args,
        "-i", filePath,
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-sn", "-dn",
    )

    if mode == "remux" {
        args = append(args,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "160k", "-ac", "2",
        )
    } else {
        args = append(args,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "25",
            "-pix_fmt", "yuv420p",
            "-sc_threshold", "0",
            "-force_key_frames", "expr:gte(t,n_forced*2)",
            "-c:a", "aac", "-b:a", "160k", "-ac", "2",
        )
    }

    args = append(args,
        "-avoid_negative_ts", "make_zero",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4",
        "pipe:1",
    )

    ctx := r.Context()
    cmd := exec.CommandContext(ctx, e.ffmpeg, args...)
    hideConsole(cmd)
    stdout, err := cmd.StdoutPipe()
    if err != nil {
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    stderr, err := cmd.StderrPipe()
    if err != nil {
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    if err := cmd.Start(); err != nil {
        http.Error(w, err.Error(), http.StatusBadRequest)
        return
    }

    var stderrText strings.Builder
    var stderrMu sync.Mutex
    stderrDone := make(chan struct{})
    go func() {
        defer close(stderrDone)
        scanner := bufio.NewScanner(stderr)
        for scanner.Scan() {
            line := scanner.Text()
            stderrMu.Lock()
            if stderrText.Len() < 8192 {
                stderrText.WriteString(line)
                stderrText.WriteByte('\n')
            }
            stderrMu.Unlock()
        }
    }()

    w.Header().Set("Content-Type", "video/mp4")
    w.Header().Set("Cache-Control", "no-store")
    w.Header().Set("Accept-Ranges", "none")
    w.Header().Set("X-LocalHub-Stream", mode)
    w.WriteHeader(http.StatusOK)

    buffer := make([]byte, 256*1024)
    flusher, _ := w.(http.Flusher)
    for {
        n, readErr := stdout.Read(buffer)
        if n > 0 {
            if _, writeErr := w.Write(buffer[:n]); writeErr != nil {
                _ = cmd.Process.Kill()
                break
            }
            if flusher != nil {
                flusher.Flush()
            }
        }
        if readErr != nil {
            if !errors.Is(readErr, io.EOF) {
                _ = cmd.Process.Kill()
            }
            break
        }
    }

    waitErr := cmd.Wait()
    select {
    case <-stderrDone:
    case <-time.After(300 * time.Millisecond):
    }
    if waitErr != nil && ctx.Err() == nil {
        stderrMu.Lock()
        detail := strings.TrimSpace(stderrText.String())
        stderrMu.Unlock()
        if detail != "" {
            fmt.Fprintln(os.Stderr, "transcode failed:", detail)
        }
    }
}

func hideConsole(cmd *exec.Cmd) {
    if cmd == nil {
        return
    }
    // CREATE_NO_WINDOW on Windows; SysProcAttr is ignored by other targets only
    // when GOOS is windows, so keep the build-specific value in a helper file.
    applyPlatformProcessFlags(cmd)
}

func applyPlatformProcessFlags(cmd *exec.Cmd) {
    if os.PathSeparator == '\\' {
        cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
    }
}
