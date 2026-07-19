# Security policy

## Supported versions

Security fixes are applied to the latest release and the current `main` branch. Update to the newest release before reporting a problem that may already have been corrected.

## Reporting a vulnerability

Please use GitHub's private vulnerability-reporting feature for this repository. Include the affected version, impact, reproduction steps, and a minimal proof of concept when practical. Do not open a public issue for an undisclosed vulnerability.

Allow time to reproduce and correct the issue before public disclosure. Reports about third-party media availability, a source website's access policy, or media copyright are not application security vulnerabilities.

## Security boundaries

GIFmakerAthome is a local application. Its web interface binds to `127.0.0.1`, uses a random port and per-run request token, and rejects URL imports that resolve to loopback or private-network addresses. Imported and generated media remain in app-owned temporary directories until downloaded or cleared.

Every export removes inherited metadata and non-video streams. Nevertheless, treat imported media as untrusted, keep GIFmakerAthome and its dependencies current, and retrieve media only from sources you trust and are authorized to use.

## Automated checks

Release builds and GitHub Actions enforce dependency consistency and security-version policy, vulnerability auditing, Bandit, Ruff formatting and linting, strict mypy, PSScriptAnalyzer, Zizmor, CodeQL for Python and browser JavaScript, dependency review, the automated test suite, and a clean Windows package build. Scheduled workflows repeat the advisory and static-analysis checks weekly so newly published findings are surfaced even when the source has not changed.
