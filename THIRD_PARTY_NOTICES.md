# Third-party notices — LocalHub 2.3 Native Player experiment

This experimental Windows build embeds a dynamically loaded `libmpv-2.dll` playback runtime.

## mpv / libmpv

- Project: mpv
- Upstream: https://github.com/mpv-player/mpv
- API documentation: https://mpv.io/manual/master/
- LocalHub uses libmpv only as a dynamically loaded playback backend.

For CI test packages, the DLL is obtained from the `mpv-dev-lgpl-x86_64-*` artifact published by:

- https://github.com/zhongfly/mpv-winbuild

That project describes its `mpv-dev-lgpl-*` artifact as an LGPLv2.1+ libmpv build with an LGPL-compatible FFmpeg configuration. This is sufficient for the current technical experiment, but a production release should pin a specific upstream mpv commit/build recipe and archive the corresponding license/source information alongside the binary.

LocalHub does not modify user media files when playing them through libmpv.
