# Contributing to GIFmakerAthome

Contributions that improve the local editing experience, format compatibility, documentation, tests, or security are welcome.

## Set up a development environment

GIFmakerAthome supports Python 3.11 and newer. On Windows, run `install.bat` to create `.venv` and install the runtime dependencies. Install the complete contributor toolset with:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Start the application with `start.bat`, or run it directly:

```powershell
.venv\Scripts\python.exe app.py
```

The development server is local-only. Temporary inputs and generated files are recreated when the application starts, so save any output you want to keep.

## Validate a change

Run the complete static and security gate:

```powershell
.\security-check.ps1
```

Then run the tests:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

The local gate checks dependency consistency and minimum versions, known dependency advisories, Python security patterns, syntax and formatting, lint and import rules, strict typing, and GitHub Actions security. CI additionally runs PSScriptAnalyzer, dependency review, CodeQL for Python and JavaScript, both supported test versions, and a clean Windows executable build. See [docs/CI.md](docs/CI.md) for the complete check list.

Create changes on a topic branch and open a pull request against `main`. The protected branch requires the current branch to be up to date, all required checks to pass, and all review conversations to be resolved. Do not bypass a failed gate to publish a release.

When changing media processing, add or update a focused automated test. The optional live URL smoke test requires an authorized test URL and is intentionally not part of CI:

```powershell
$env:GIFMAKER_ATHOME_TEST_MEDIA_URL = "https://example.com/path/to/media.mp4"
.venv\Scripts\python.exe -m scripts.smoke_media_url
```

## Build a release candidate

After all checks pass, build the Windows executable with:

```powershell
.\build-release.ps1
```

The outputs are `release\GIFmakerAthome.exe` and `release\SHA256SUMS.txt`. Do not commit generated executables, build directories, virtual environments, caches, or temporary media. Maintainers publish releases by following [docs/RELEASING.md](docs/RELEASING.md).

## Contribution scope

Keep user-facing URL import language generic and focused on supported media sources. Do not add third-party branding or imply that GIFmakerAthome is affiliated with a media service. Documentation and features should remind users to import only media they own or are permitted to use.
