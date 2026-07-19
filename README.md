# GIFmakerAthome

GIFmakerAthome is a local-first Windows editor for turning videos and animated images into GIF, animated WebP, or VP9 WebM files. The interface opens in your browser, while the application and media processing stay on `127.0.0.1` on your computer. You can work with local files or media URLs supported by the installed importer.

## Download and run

The easiest option is the ready-to-run Windows executable:

1. Open the [latest release](https://github.com/TL0024/gif-maker-athome/releases/latest).
2. Download `GIFmakerAthome.exe`.
3. Run the executable. It opens GIFmakerAthome in your default browser.
4. Keep the command window open while editing. Close it or press `Ctrl+C` to stop the application.

The executable includes the application and media tools; Python is not required.

### Run from source

1. Install Python 3.11 or newer.
2. Double-click `install.bat` once. This creates `.venv` and installs the required packages, including a bundled FFmpeg executable.
3. Double-click `start.bat`.
4. Keep the command window open while editing. Close it or press `Ctrl+C` to stop the application.

After setup, local-file editing works offline. URL importing requires an internet connection. To update the installed dependencies and compatible-site support, run:

```powershell
.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
```

## Features

- Upload MP4, MOV, WebM, MKV, AVI, GIF, and animated WebP files.
- Import supported media URLs, including direct media links and compatible websites.
- Start every import with the complete original frame selected; optional free, original, 1:1, 16:9, and 9:16 crop controls remain available.
- Drag or resize the crop frame directly over the media preview.
- Keep a selected time range or remove a selected section from the middle.
- Export adaptive-palette GIF, animated WebP, or silent VP9 WebM.
- Keep the cropped pixels at their original resolution or use 512 × 512, percentage, and custom-size presets.
- Choose frame rates from 1 through 30 FPS and adjust format-specific quality.
- Apply a hard output limit of 256 KB, 512 KB, 1 MB, 2 MB, or a custom size.
- Open a frame editor to reorder frames, delete frames, and assign per-frame hold timing before compiling GIF or WebM.
- Extend a GIF or WebM into a forward-and-reverse loop without repeating the turnaround frame.
- Build a browser-compatible preview locally when the browser cannot play the imported format directly.
- Remove audio, subtitles, data streams, chapters, and inherited metadata from every export.
- Clear imported files, previews, extracted frames, and generated files automatically at startup or manually with **Clear cache**.

## Editing workflow

1. Upload a file or select **Paste a link** and import supported media.
2. The crop initially covers the complete source. Drag the crop frame or choose an aspect preset if you want a smaller region.
3. Set the start and end controls. **Keep selected range** exports that interval; **Remove selected middle** joins the sections before and after it.
4. Choose GIF, animated WebP, or WebM. WebM, 30 FPS, quality 40, original crop size, and no file-size cap are the defaults.
5. Adjust resolution, FPS, quality, GIF palette, and the optional size cap.
6. Select **Create GIF**, **Create WebP**, or **Create WebM**, then preview and download the result.

### Frame editor

Select GIF or WebM and choose **View all frames** for frame-level control. The working frame list reflects the current cut, crop, resolution, and FPS. You can drag frames into a new order, delete unwanted frames, restore the original sequence, or increase a frame's hold value. A hold of 1 is one tick at the selected FPS.

A frame-editor session supports up to 900 source frames and 9,000 total hold ticks. Shorten the selection or reduce FPS if the working clip is too large. Changing the crop, timing, resolution, or FPS makes an existing frame list stale; rebuild it before compiling so the edited sequence matches the current settings.

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

The test suite covers local API protection, startup and manual cleanup, upload and download handling, crop and resize filters, time-range removal, GIF palette generation and optional compression, animated WebP, VP9 WebM, output-size limits, metadata and audio removal, frame extraction and editing, hold timing, and forward/reverse loop generation.

Run the security checks with:

```powershell
.\security-check.ps1
```

The command is the same quality gate used by release builds and CI. It must complete without findings or ignored failures and runs:

- `pip check` for an internally consistent installed dependency set.
- The project dependency policy, including the Pillow 12.3 minimum.
- `pip-audit --strict` against published Python vulnerability advisories.
- Bandit across the application and maintenance scripts.
- Ruff with error, import, bug-risk, modernization, simplification, and project-hygiene rules.
- Strict mypy analysis of the application and scripts.
- Zizmor's pedantic GitHub Actions audit.

GitHub Actions runs the complete analysis for pushes and pull requests and every week. It also runs the test suite independently on Python 3.11 and 3.13. Third-party actions are pinned to immutable commits, the workflow has read-only repository access, checkout credentials are not persisted, and every job has a time limit. See [CONTRIBUTING.md](CONTRIBUTING.md) for the contributor workflow and [SECURITY.md](SECURITY.md) for vulnerability reporting and supported versions.

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

The script installs the development tools into `.venv`, runs the security checks and tests, and uses `GIFmakerAthome.spec` to create `release\GIFmakerAthome.exe`. The executable embeds the templates, styles, scripts, icon, and FFmpeg runtime needed by the application.

## Repository layout

- `app.py` starts the local server and opens the browser.
- `gifmaker/` contains the Flask application and media-processing pipeline.
- `templates/` and `static/` contain the interface and application icon.
- `tests/` contains the automated test suite.
- `scripts/` contains the optional live link-import smoke test.
- `pyproject.toml`, `security-check.ps1`, and `.github/workflows/security.yml` define and enforce the quality gates.
- `packaging/` and `GIFmakerAthome.spec` contain Windows release metadata.

## License and media rights

GIFmakerAthome does not grant rights to third-party media. Import and export only material you may lawfully access and use; the person operating GIFmakerAthome is responsible for the resulting files and their distribution.
