# LocalHub

**Turn a folder of local videos and images into a private Pornhub-style media site — automatically, locally, and offline.**

Drop `LocalHub.exe` into your media folder and double-click it. LocalHub scans the folder, opens a local website in your browser, and lets you browse, play, tag, rate, favorite, rename, and move your media without uploading anything.

**One EXE. No import. No server setup. No account. No cloud.**

[English](README.md) · [简体中文](README.zh-CN.md)

[![Build Windows EXE](https://github.com/dudulu2/Local-hub/actions/workflows/build-windows.yml/badge.svg)](https://github.com/dudulu2/Local-hub/actions/workflows/build-windows.yml)

## What it feels like

LocalHub is not meant to feel like a database or a file manager. It is designed to feel like a private media website built from the folders you already have.

- **Website-style browsing** — home feed, folders, search, favorites, continue watching, and a full player.
- **Organize while watching** — add tags, rate, rename, favorite, and move files without leaving the viewing flow.
- **Drag to classify** — drag a video directly onto a folder in the sidebar to move it there.
- **Photo packs** — folders with multiple images are automatically grouped into a single album/card instead of flooding the page.
- **Zero setup** — put one EXE in the media root and run it.
- **Local by default** — LocalHub binds to `127.0.0.1` by default and does not upload your media.

## Quick start

1. Download `LocalHub.exe` from [GitHub Releases](https://github.com/dudulu2/Local-hub/releases).
2. Put it in the root folder that contains your videos and images.
3. Double-click `LocalHub.exe`.
4. LocalHub opens automatically in your browser.
5. Use the Windows tray icon to reopen the site, open the media folder, or exit LocalHub.

```text
Media/
├─ LocalHub.exe
├─ video-a.mp4
├─ Collection/
│  ├─ episode-01.mp4
│  └─ episode-02.mp4
└─ Photo-Pack/
   ├─ 001.jpg
   ├─ 002.jpg
   └─ 003.jpg
```

## Windows SmartScreen warning

Current public builds of `LocalHub.exe` are **not code-signed with a commercial certificate**. On some Windows PCs, Microsoft Defender SmartScreen may therefore show **Windows protected your PC** or **Unknown publisher** the first time you run it.

This is a reputation/signing warning for an unsigned application. It is not, by itself, a malware detection.

If you downloaded the EXE from this repository's official Release page:

1. Click **More info** in the SmartScreen dialog.
2. Confirm the application is `LocalHub.exe`.
3. Optionally verify its SHA256 hash.
4. Choose **Run anyway** if you want to continue.

Every official build also includes `SHA256.txt`:

```powershell
Get-FileHash .\LocalHub.exe -Algorithm SHA256
```

Compare the result with the hash published in the same Release.

You do **not** need to disable Windows Defender or whitelist your entire media folder.

More details: [`docs/windows-smartscreen.md`](docs/windows-smartscreen.md)

## Features

### Browse local media like a website

- Lightweight home feed
- Folder navigation
- All videos view
- Photo packs / albums
- Search
- Favorites
- Continue watching
- Real pagination instead of loading the whole library at once

### Organize without breaking the viewing experience

- Quick tags directly on media cards
- Ratings
- Favorites
- Playback progress
- Rename files while preserving extensions
- Move files into existing folders
- Drag videos onto sidebar folders to classify them
- Preserve favorites and playback progress after rename/move operations
- Never overwrite an existing file with the same name

### Automatic photo-pack mode

When a folder contains two or more images, LocalHub can represent them as one photo-pack card:

- one cover instead of hundreds of image cards;
- full images are loaded only after opening the pack;
- videos in mixed folders still appear as normal video items.

## Designed for large local libraries

LocalHub avoids attaching a real `<video>` element to every card.

### Lightweight catalog

On first run, LocalHub creates a small metadata index:

```text
.localhub/
├─ metadata.json     # tags and related metadata
├─ catalog-v2.json   # lightweight media catalog snapshot
└─ runtime.json      # current runtime information; removed on exit
```

On later launches, the cached catalog can make the interface available quickly while the real folders are refreshed in the background.

### On-demand thumbnails

Thumbnail generation prefers:

1. Windows Shell / Explorer shared thumbnail cache
2. lightweight PIL resizing for images
3. fast FFmpeg single-frame extraction for videos when needed

The frontend requests thumbnails around the current viewport instead of opening every media file at once.

### Load video only when you actually play it

Media files are requested only after opening the player. LocalHub supports HTTP Range requests, so large videos can seek without loading the entire file into memory first.

## Supported formats

**Images**

`jpg jpeg png webp gif avif bmp svg`

**Videos**

`mp4 webm m4v mov mkv avi ogv mpeg mpg ts`

> A supported file extension does not guarantee that every browser can decode every internal video/audio codec. Direct playback still depends on browser and local codec support.

## Privacy and local-file safety

- Binds to `127.0.0.1` by default
- No account required
- No media upload
- Tags are stored in `.localhub/metadata.json`
- Media-file metadata is not rewritten
- Rename and move operations really change local file paths

Treat rename and move actions the same way you would in a file manager.

## Build the Windows EXE

Regular users do not need Python. Developers can build locally with:

```powershell
.\build_windows.ps1
```

GitHub Actions validates Python and frontend JavaScript, runs catalog/preview/compatibility/metadata smoke tests, builds the single-file Windows GUI executable, generates SHA256, and uploads the build artifact.

Pushing a `v*` tag automatically creates a GitHub Release containing `LocalHub.exe` and `SHA256.txt`.

## Project direction

LocalHub is intentionally not trying to become a heavy media database.

Its goal is simple:

> **Your files stay ordinary files. LocalHub makes them feel like a private media website.**

Current priorities are better playback compatibility, smoother keyboard navigation, faster bulk organization, an optional LAN mode, and continued performance work for larger libraries.

## Feedback

When reporting a problem, please include:

- Windows version
- LocalHub version / Release name
- media extension and codec information if known
- steps to reproduce
- whether the same file plays directly in your browser

Please do not upload private media files to an issue.

---

*“Pornhub-style” describes the familiar card/grid browsing pattern and interaction style only. LocalHub is an independent project and is not affiliated with Pornhub.*
