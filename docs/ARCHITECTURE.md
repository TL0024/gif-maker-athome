# Architecture

GIFmakerAthome is a single-user desktop application delivered through a local Flask web interface. The packaged executable, Python source installation, browser interface, and FFmpeg child process all run on the same Windows computer.

## Runtime flow

1. `app.py` selects an unused loopback port, opens the browser, and starts Flask on `127.0.0.1`.
2. `gifmaker.web.create_app` creates fresh import, export, preview, and frame directories below the application data root.
3. The browser loads `templates/index.html`, `static/css/style.css`, and `static/js/app.js` from the local server.
4. Upload or URL-import routes create a `MediaAsset` managed by `MediaStore`.
5. The editor submits validated timing, crop, size, frame-rate, format, and compression settings.
6. `gifmaker.media` builds an FFmpeg filter graph and invokes only the resolved FFmpeg executable without a command shell.
7. The generated asset is served by an opaque identifier and downloaded through the local application.

## Components

| Component | Responsibility |
| --- | --- |
| `app.py` | Desktop-style startup, free-port selection, and browser launch. |
| `gifmaker/web.py` | Flask configuration, request-token enforcement, response security headers, API routes, and error translation. |
| `gifmaker/media.py` | Media probing, URL validation/import, FFmpeg command construction, exports, size targeting, frame editing, loop generation, and temporary asset storage. |
| `templates/` and `static/` | Local browser UI; no third-party scripts, fonts, or analytics are loaded. |
| `GIFmakerAthome.spec` | PyInstaller entry point, bundled UI files, icon, version metadata, and imageio-ffmpeg data. |

## Trust boundaries

- The HTTP listener is loopback-only. It is not intended to be exposed to a LAN or the internet.
- Every state-changing API request must include the unpredictable token created for that process.
- Remote imports reject loopback, private, link-local, multicast, reserved, and otherwise non-public resolved addresses. Redirect destinations are validated as well.
- Upload names are normalized, application storage uses generated identifiers, and downloads are served only from registered assets.
- FFmpeg arguments are passed as a list with `shell=False`; the executable path is resolved and checked before every invocation.
- Exports remove audio, subtitles, data streams, chapters, and inherited metadata.
- A strict Content Security Policy limits browser resources to the local application.

The application processes untrusted media with Pillow, imageio-ffmpeg/FFmpeg, requests, Beautiful Soup, and yt-dlp. Dependency auditing and timely dependency upgrades remain important even though the service is local-only.

## Storage lifecycle and limits

Source runs use `.gifmaker-athome-data/`; packaged runs use `%LOCALAPPDATA%\GIFmakerAthome\cache`. Startup removes the previous temporary workspace, and **Clear cache** removes current imports, previews, extracted frames, and generated files. Users must download outputs they want to retain.

Important bounded inputs include a 4 GiB Flask request limit, a 2 GiB URL-download limit, dimensions no larger than 4096 pixels per side or 16,777,216 output pixels, at most 900 extracted source frames, and at most 18,000 frame hold ticks. Export subprocesses also use operation-specific timeouts.

## Packaging

PyInstaller produces one console executable. Console mode is intentional: it shows the local address, keeps application lifetime visible, and lets the user stop the server with `Ctrl+C`. `imageio-ffmpeg` supplies the bundled FFmpeg runtime, so a release user does not need Python or a system FFmpeg installation.
