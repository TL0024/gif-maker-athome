# Architecture

GIFmakerAthome is a single-user desktop application delivered through a local Flask web interface. The packaged executable, Python source installation, browser interface, and FFmpeg child process all run on the same Windows computer.

## Runtime flow

1. `app.py` selects an unused loopback port, creates a threaded Werkzeug server on `127.0.0.1`, and opens the browser.
2. `gifmaker.web.create_app` creates fresh import, export, preview, and frame directories below the application data root.
3. The browser loads `templates/index.html`, `static/css/style.css`, and `static/js/app.js` from the local server and receives an opaque page-session identifier.
4. Uploads create a `MediaAsset` immediately. Probing distinguishes video, animated image, and still image assets. URL imports run in a daemon worker, publish extraction/download progress through a short-lived job record, accept only detected video results, prefer a browser-compatible stream, and create an asset when complete. If the imported codec still cannot play in the browser, the backend creates a local H.264 preview while retaining the original video for export.
5. Still images use a dedicated editor and `/api/image-export`. Its default state is WebP, a centered 1:1 crop, 512 × 512 output, and quality 85. Pillow applies EXIF orientation, crop, Lanczos resize, format conversion, alpha handling, and metadata-free output.
6. Video speed changes use `/api/speed`, which accepts 0.5× through 8×, creates a browser-native H.264 working asset with rewritten timestamps, and returns that asset for immediate editor reload. Later speed choices remain relative to the original imported video.
7. Video and animated-image edits use `/api/export` or the frame-sequence APIs. The browser submits validated timing, playback direction, square or circular crop shape, static or interpolated motion crop, size, frame-rate, format, and compression settings. Circle mode requires equal output dimensions and adds an alpha mask after crop/scale processing; the frame extraction graph uses the same mask. Motion crops contain up to 10 independently sized keyframes and use the first and last keyframe times as the output interval. Reverse playback is accepted only for video sources and is applied to the fully cut and cropped stream; frame extraction uses the same graph.
8. `gifmaker.media` builds an FFmpeg filter graph and invokes only the resolved FFmpeg executable without a command shell. Reverse playback adds FFmpeg's sequence-buffering `reverse` filter before frame-rate conversion.
9. The generated asset is served by an opaque identifier and downloaded through the local application.
10. When a page unloads, it sends an authenticated close beacon. The server stops after the last page closes, with a short delay that allows a refreshed page to replace its old session.

## Components

| Component | Responsibility |
| --- | --- |
| `app.py` | Desktop-style startup, free-port selection, browser launch, and graceful server shutdown. |
| `gifmaker/web.py` | Flask configuration, request-token enforcement, browser sessions, background import jobs, response security headers, API routes, and error translation. |
| `gifmaker/media.py` | Media probing, video-only URL validation/import, Pillow image conversion, FFmpeg command construction, speed-adjusted working videos, animation exports, reverse playback, size targeting, frame editing, loop generation, and temporary asset storage. |
| `templates/` and `static/` | Local browser UI; no third-party scripts, fonts, or analytics are loaded. |
| `GIFmakerAthome.spec` | PyInstaller entry point, bundled UI files, icon, version metadata, and imageio-ffmpeg data. |

## Trust boundaries

- The HTTP listener is loopback-only. It is not intended to be exposed to a LAN or the internet.
- Every state-changing API request must include the unpredictable token created for that process.
- Remote imports reject loopback, private, link-local, multicast, reserved, and otherwise non-public resolved addresses. Redirect destinations are validated as well.
- Remote import results must probe as video. Still and animated images are accepted only through the local Upload tab.
- Upload names are normalized, application storage uses generated identifiers, and downloads are served only from registered assets.
- FFmpeg arguments are passed as a list with `shell=False`; the executable path is resolved and checked before every invocation.
- Animation exports remove audio, subtitles, data streams, chapters, and inherited metadata. Still-image exports are rebuilt from decoded pixels without inherited metadata.
- A strict Content Security Policy limits browser resources to the local application.
- Tab-close beacons include the per-run request token, and the server accepts a shutdown request only for a registered page session. Closing one of several open app tabs leaves the server running for the others.

The application processes untrusted media with Pillow, imageio-ffmpeg/FFmpeg, requests, Beautiful Soup, and yt-dlp. Dependency auditing and timely dependency upgrades remain important even though the service is local-only.

## Storage lifecycle and limits

Source runs use `.gifmaker-athome-data/`; packaged runs use `%LOCALAPPDATA%\GIFmakerAthome\cache`. Startup removes the previous temporary workspace, and **Clear cache** removes current imports, browser-compatible previews, extracted frames, and generated files. Users must download outputs they want to retain. Import-job state exists only in process memory and disappears when the local server stops.

Important bounded inputs include a 4 GiB Flask request limit, a 2 GiB URL-download limit, dimensions no larger than 4096 pixels per side or 16,777,216 animation-output pixels, at most 10 motion-crop positions, at most 900 extracted source frames, and at most 18,000 frame hold ticks. Frame editing can collapse visually unchanged runs into one card; each candidate is compared with the run's first decoded RGBA frame so small pixel noise is tolerated without allowing gradual change to accumulate. Export subprocesses also use operation-specific timeouts. Reverse playback buffers the selected decoded sequence, so its memory use scales with selection duration, frame rate, and resolution.

## Packaging

PyInstaller produces one console executable. Console mode is intentional: it shows the local address and keeps application lifetime visible. The last app tab normally stops the server; `Ctrl+C` remains available as a manual fallback. `imageio-ffmpeg` supplies the bundled FFmpeg runtime, so a release user does not need Python or a system FFmpeg installation. See [Third-party credits and licenses](THIRD_PARTY.md) for the runtime acknowledgements and release-license notes.
