# GIFmakerAthome

[![Quality gates](https://github.com/TL0024/gif-maker-athome/actions/workflows/security.yml/badge.svg)](https://github.com/TL0024/gif-maker-athome/actions/workflows/security.yml)
[![CodeQL](https://github.com/TL0024/gif-maker-athome/actions/workflows/codeql.yml/badge.svg)](https://github.com/TL0024/gif-maker-athome/actions/workflows/codeql.yml)
[![Latest release](https://img.shields.io/github/v/release/TL0024/gif-maker-athome)](https://github.com/TL0024/gif-maker-athome/releases/latest)

GIFmakerAthome is a local-first Windows editor for turning videos and animated images into GIF, animated WebP, or VP9 WebM files. The interface opens in your browser, while the application and media processing stay on `127.0.0.1` on your computer. You can work with local files or media URLs supported by the installed importer.

## What's new in v1.1.0

Version 1.1.0 adds timed motion-crop paths with up to 10 independently sized positions, draggable numbered timing markers, current-time feedback in the crop preview, and smarter frame editing with visual duplicate grouping plus duplicate/delete controls. It also makes successfully imported videos more reliable to preview by selecting compatible streams and generating a local browser-compatible fallback when needed. See the [changelog](CHANGELOG.md) for the complete release notes.

## Download and run

The easiest option is the ready-to-run Windows executable:

1. Open the [latest release](https://github.com/TL0024/gif-maker-athome/releases/latest).
2. Download `GIFmakerAthome.exe`.
3. Run the executable. It opens GIFmakerAthome in your default browser.
4. Keep the app tab open while editing. Closing the last GIFmakerAthome tab also closes the local server and command window. You can still press `Ctrl+C` in the command window to stop it manually.

The executable includes the application and media tools; Python is not required.
Each release also includes `SHA256SUMS.txt`. To verify the download in PowerShell, run `Get-FileHash .\GIFmakerAthome.exe -Algorithm SHA256` and compare the result with that file.

### Run from source

1. Install Python 3.11 or newer.
2. Double-click `install.bat` once. This creates `.venv` and installs the required packages, including a bundled FFmpeg executable.
3. Double-click `start.bat`.
4. Keep the app tab open while editing. Closing the last GIFmakerAthome tab stops the local server and closes the command window. A browser refresh is safe because the server allows the refreshed page to reconnect before shutting down.

After setup, local-file editing works offline. URL importing requires an internet connection. To update the installed dependencies and compatible-site support, run:

```powershell
.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
```

## Features

- Upload MP4, MOV, WebM, MKV, AVI, GIF, and animated WebP files.
- Import supported media URLs, including direct media links and compatible websites, with live extraction and download progress.
- Start every import with the complete original frame selected; optional free, original, 1:1, 16:9, and 9:16 crop controls remain available.
- Drag or resize the crop frame directly over the media preview.
- Enable **Motion crop** to smoothly pan and zoom through 2–10 independently positioned, sized, and timed crop keyframes.
- Keep a selected time range or remove a selected section from the middle.
- Export adaptive-palette GIF, animated WebP, or silent VP9 WebM.
- Keep the cropped pixels at their original resolution or use 512 × 512, percentage, and custom-size presets.
- Choose frame rates from 1 through 30 FPS and adjust format-specific quality.
- Apply a hard output limit of 256 KB, 512 KB, 1 MB, 2 MB, or a custom size.
- Open a frame editor to reorder, duplicate, delete, and assign hold timing to frames before compiling GIF or WebM.
- Extend a GIF or WebM into a forward-and-reverse loop without repeating the turnaround frame.
- Build a browser-compatible preview locally when the browser cannot play the imported format directly.
- Remove audio, subtitles, data streams, chapters, and inherited metadata from every export.
- Clear imported files, previews, extracted frames, and generated files automatically at startup or manually with **Clear cache**.

## Editing workflow

1. Upload a file or select **Paste a link** and import supported media.
   URL imports show their extraction stage first, then downloaded bytes, percentage, transfer speed, and estimated time when the source provides that information.
2. The crop initially covers the complete source. Drag the crop frame or choose an aspect preset if you want a smaller region. For a moving crop, enable **Motion crop**, set position 1, then use **+ Position** to build a path of up to 10 positions. Every added position inherits the latest position's crop and time so you can extend the motion from where it left off; **− Position** removes the currently selected position while keeping at least one. Motion mode replaces the two range thumbs with numbered timing markers. Select a position tab, then drag its highlighted marker to update that position's **At** time; the other markers remain grey and fixed. At least two positions are required, and the exported animation includes only the time from the first marker through the last marker.
3. Set the start and end controls. **Keep selected range** exports that interval; **Remove selected middle** joins the sections before and after it.
4. Choose GIF, animated WebP, or WebM. WebM, 30 FPS, quality 40, original crop size, and no file-size cap are the defaults.
5. Adjust resolution, FPS, quality, GIF palette, and the optional size cap.
6. Select **Create GIF**, **Create WebP**, or **Create WebM**, then preview and download the result.

### Frame editor

Select GIF or WebM and choose **View all frames** for frame-level control. The working frame list reflects the current cut, crop, resolution, and FPS. You can drag frames into a new order, duplicate or delete any frame card, restore the original sequence, or change a frame's hold value. Consecutive frames are treated as visually unchanged when no more than 3% of pixels differ beyond a small per-channel tolerance. Every candidate is compared with the first frame of its run, preventing slow changes from accumulating unnoticed. A collapsed card's hold equals its source run length, while non-duplicates keep Hold 1, preserving the original duration.

A frame-editor session supports up to 900 source frames and 18,000 total hold ticks. Shorten the selection or reduce FPS if the working clip is too large. Changing the crop, timing, resolution, or FPS makes an existing frame list stale; rebuild it before compiling so the edited sequence matches the current settings.

### Complete loops

After a GIF or WebM export, **Extend into complete loop** creates a second version that plays forward and then backward. It omits the repeated turnaround frame, keeps the output format and dimensions, and adds `-loop` to the download name. The extended result can exceed a file-size cap because its duration is nearly doubled.

## Export and compression details

The size cap is a hard binary limit (`1 KB = 1024 bytes`). GIFmakerAthome first tries the selected settings. If the result is too large, it progressively reduces quality, FPS, and resolution. If the minimum practical settings still cannot satisfy the limit, the incomplete file is removed and the editor asks for a shorter duration or larger cap.

For manually arranged frame sequences, size-cap passes preserve the selected frames and their order. They can reduce palette size or image quality and resolution, but they do not silently discard edited frames.

GIF exports offer four independent optional techniques:

- **Reduce the number of colors** limits the active palette to at most 64 colors.
- **Enable lossy GIF compression** smooths fine detail and uses compact ordered dithering.
- **Optimize unchanged pixels** processes the rectangle that changes between frames.
- **Remove duplicate frames** merges identical consecutive frames while retaining their combined display time.

GIF is the most broadly compatible format but is often the largest. Animated WebP usually preserves smooth color in a smaller file. VP9 WebM is the default and is generally the most efficient option for video-like animation. All exports are silent.

For Telegram video stickers, select WebM, keep the animation at 30 FPS or lower and no longer than 3 seconds, use dimensions no larger than 512 pixels per side with one side exactly 512 pixels, and apply the 256 KB cap. Telegram documents the current requirements in its [WebM/VP9 encoding guide](https://core.telegram.org/stickers/webm-vp9-encoding).

## Local data and network behavior

- The server listens only on `127.0.0.1` using a randomly selected free port.
- Mutating API requests require a new per-run token.
- Each loaded app page has a per-run browser-session identifier. Closing the last app tab requests server shutdown; a short grace period prevents an ordinary refresh from stopping the process.
- The source version stores temporary session data in `.gifmaker-athome-data/`.
- The executable stores temporary session data in `%LOCALAPPDATA%\GIFmakerAthome\cache`.
- Startup recreates the temporary imports, exports, previews, and frame folders. Download anything you want to keep before restarting.
- Link imports reject loopback and private-network addresses.
- There are no accounts, analytics, cloud conversion services, or third-party interface assets.

## Responsible use

Only import and edit media that you own or are authorized to use. Examples include your own uploads, properly licensed material, public-domain media, and content whose source permits retrieval and reuse.

URL compatibility does not grant permission to access, copy, modify, or redistribute media. You are responsible for following applicable laws, copyright requirements, licenses, and the terms of the source providing the media. GIFmakerAthome is not affiliated with or endorsed by any media platform.

## Development and quality gates

Install the development dependencies and run the complete automated suite:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The test suite covers local API protection, browser-tab shutdown and refresh handling, URL-download progress, startup and manual cleanup, upload and download handling, static and independently timed multi-position motion crops, time-range removal, GIF palette generation and optional compression, animated WebP, VP9 WebM, output-size limits, metadata and audio removal, frame extraction and editing, hold timing, and forward/reverse loop generation.

Run the security checks with:

```powershell
.\security-check.ps1
```

The command is the same quality gate used by release builds and CI. It must complete without findings or ignored failures and runs:

- `pip check` for an internally consistent installed dependency set.
- The project dependency policy, including the Pillow 12.3 minimum.
- `pip-audit --strict` against published Python vulnerability advisories.
- Bandit across the application and maintenance scripts.
- Python bytecode compilation to reject syntax errors.
- Ruff formatting plus error, import, bug-risk, modernization, simplification, and project-hygiene rules.
- Strict mypy analysis of the application and scripts.
- Zizmor's pedantic GitHub Actions audit.

GitHub Actions separates those checks into independently enforceable jobs and adds PSScriptAnalyzer, pull-request dependency review, CodeQL analysis for Python and JavaScript, tests on Python 3.11 and 3.13, and a clean PyInstaller build. Third-party actions are pinned to immutable commits, ordinary workflows have read-only repository access, checkout credentials are not persisted, and every job has a time limit. Dependabot proposes grouped Python and Actions updates each week.

The `main` branch requires pull requests and successful quality checks. See [CHANGELOG.md](CHANGELOG.md) for release notes, [CONTRIBUTING.md](CONTRIBUTING.md) for the contributor workflow, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for system design, [docs/CI.md](docs/CI.md) for every automated gate, [docs/RELEASING.md](docs/RELEASING.md) for the release process, [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md) for dependency credits, and [SECURITY.md](SECURITY.md) for vulnerability reporting.

The optional live media-URL smoke test is separate because it uses the network. Supply a URL that you are authorized to retrieve:

```powershell
$env:GIFMAKER_ATHOME_TEST_MEDIA_URL = "https://example.com/path/to/media.mp4"
python -m scripts.smoke_media_url
```

## Build the Windows executable

Run the release script from PowerShell:

```powershell
.\build-release.ps1
```

The script installs the development tools into `.venv`, runs the security checks and tests, and uses `GIFmakerAthome.spec` to create `release\GIFmakerAthome.exe` and `release\SHA256SUMS.txt`. The executable embeds the templates, styles, scripts, icon, and FFmpeg runtime needed by the application.

## Repository layout

- `app.py` starts the local server and opens the browser.
- `gifmaker/` contains the Flask application and media-processing pipeline.
- `templates/` and `static/` contain the interface and application icon.
- `tests/` contains the automated test suite.
- `scripts/` contains the optional live link-import smoke test.
- `docs/` explains the architecture, CI policy, and release process.
- `CHANGELOG.md` records user-visible changes for each release.
- `pyproject.toml`, `security-check.ps1`, and `.github/workflows/security.yml` define and enforce the quality gates.
- `packaging/` and `GIFmakerAthome.spec` contain Windows release metadata.

## License and media rights

GIFmakerAthome does not grant rights to third-party media. Import and export only material you may lawfully access and use; the person operating GIFmakerAthome is responsible for the resulting files and their distribution.

GIFmakerAthome is built with open-source libraries and the FFmpeg executable. The maintainers gratefully acknowledge those projects and their contributors in [Third-party credits and licenses](docs/THIRD_PARTY.md). Their names and license terms remain the property of their respective projects; inclusion here does not imply endorsement.
