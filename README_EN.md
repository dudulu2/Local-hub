<div align="center">

<img src="docs/images/logo.png" width="128" alt="LocalHub logo">

# LocalHub

### Turn the videos, images and image folders on your drive into a private media hub

**Local-first · Local AI tagging · Media wall · Local recommendations · Playback & organization · Single Windows EXE**

[中文](README.md) · [Download latest](../../releases/latest) · [Release notes](RELEASE_NOTES.md)

[![Version](https://img.shields.io/badge/stable-2.4.0-f59e0b)](../../releases/latest)
![Windows](https://img.shields.io/badge/Windows-x64-222222)
![Local First](https://img.shields.io/badge/local--first-127.0.0.1-222222)
![AI Tag](https://img.shields.io/badge/AI%20Tag-local-222222)

</div>

![LocalHub home](docs/images/home.webp)

## Your library should be more than filenames

Once a drive contains hundreds or thousands of videos and images, playback is rarely the real problem. Finding, rediscovering and organizing them is.

LocalHub keeps the files where they already are and adds a usable media-library interface on top.

```text
Normal folders
video_001.mp4
final_final2.mp4
New Folder (4)
IMG_2381.jpg
        ↓
LocalHub
covers · tags · search · favorites · continue watching · local recommendations
```

## What LocalHub does

| | Feature | What it gives you |
|---|---|---|
| 🤖 | **Local AI tagging** | A lightweight local model can classify media and generate searchable tags without uploading your media |
| 🎞️ | **Private media wall** | Browse videos, images and image folders visually instead of hunting through filenames |
| #️⃣ | **Tags & categories** | Aggregate tags by frequency, filter the library, and edit tags whenever you want |
| ✨ | **Local recommendations** | Rediscover media from local metadata and content relationships |
| ▶️ | **Player** | Resume playback, speed control, volume, fullscreen, system player and compatibility handling |
| 📁 | **Organize while browsing** | Rename, move, favorite and rate media directly from the library |
| 🖼️ | **Images / image-folder reader** | Treat image directories as readable packs, including long pages and comic-style content |
| 🔎 | **Search** | Search filenames, folders and tags together |

### Local AI, without sending your media to a cloud service

![LocalHub tag browser](docs/images/tags.webp)

The AI Tag workflow is designed to stay local:

- the optional lightweight model is downloaded separately (around 200MB; size may change);
- recognition and tag matching run on your PC;
- a high-end GPU is not a requirement;
- generated tags are stored in LocalHub's local metadata.

> You obviously need a network connection to download the app or optional model. **Using LocalHub to manage and analyze your own media does not require uploading that media to a remote service.**

### Playback, tags, favorites and recommendations in one place

![LocalHub player](docs/images/player.webp)

On the playback page you can:

- watch and resume a video;
- review or edit tags;
- favorite it;
- open organization controls;
- browse local recommendations;
- fall back to the system player when useful.

## Start in 3 steps

1. Download `LocalHub.exe` from [Releases](../../releases/latest).
2. Put the EXE in the root of your media library.
3. Double-click it. LocalHub opens the local web interface automatically.

```text
Your library/
├─ LocalHub.exe
├─ Videos/
├─ Photos/
├─ Courses/
└─ whatever folders you already use/
```

No Python, Node.js or manual web-server setup is required for normal users.

## What “local-first” means

LocalHub binds to:

```text
127.0.0.1
```

by default, so the interface is available only on the current machine.

Core principles:

- no account required;
- no need to upload media to a server;
- tags, ratings, favorites and watch progress stay local;
- search uses a local index;
- AI Tag runs locally;
- original media stays in your own folders.

LocalHub is not cloud storage and does not take ownership of your media layout.

## Built for larger libraries

LocalHub does not push thousands of media items into the browser at once.

It uses a lightweight index and demand-driven loading:

- only a small set is shown on the home page;
- video, folder and search views are paginated;
- thumbnails are generated on demand;
- hover preview work is limited to the active target;
- later launches can show the saved index first and refresh the real directory in the background.

## Video compatibility

Browsers cannot natively play every `AVI / MPG / TS / MKV` file. LocalHub checks the actual media stream and chooses the least invasive path:

```text
Browser-friendly
→ play directly

Codec is usable, container is awkward
→ local remux

Codec is not browser-friendly
→ create a local compatible copy
```

The original file is not overwritten.

### Supported formats

**Video**

`mp4` `webm` `m4v` `mov` `mkv` `avi` `ogv` `mpeg` `mpg` `ts`

**Images**

`jpg` `jpeg` `png` `webp` `gif` `avif` `bmp` `svg`

## Real file operations

Rename and Move affect real files, not just display names in a database.

LocalHub adds safeguards such as preserving extensions and blocking same-name overwrites, while migrating local metadata when paths change.

Keep normal backups for important media.

## Windows SmartScreen

Public builds are not currently signed with a commercial code-signing certificate, so Windows SmartScreen may show an “Unknown publisher” warning on first launch.

Official releases include a SHA256 file for integrity verification.

## For developers

Normal users only need the Windows EXE from Releases.

Build from source:

```powershell
.\build_windows.ps1
```

The repository includes automated checks for indexing, playback, thumbnails, tags/ratings, file operations and the single-file Windows package.

The source is visible here for security review, learning and improvement proposals.

---

<div align="center">

### LocalHub

**Your files. Your library. Your machine.**

[Download latest](../../releases/latest) · [中文 README](README.md)

</div>
