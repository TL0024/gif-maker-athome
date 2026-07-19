# Continuous integration

Pull requests and `main` pushes run two GitHub Actions workflows. Scheduled runs repeat the checks so new dependency advisories and static-analysis findings are detected without waiting for a source change.

## Required quality gates

| Check | What it enforces |
| --- | --- |
| Python static analysis | Dependency consistency and policy, bytecode compilation, Ruff formatting/linting, and strict mypy. |
| Dependency and security analysis | `pip-audit --strict` for runtime advisories and Bandit for insecure Python patterns. |
| GitHub Actions security analysis | Zizmor in pedantic mode over every workflow. |
| PowerShell static analysis | PSScriptAnalyzer warnings and errors, except intentional `Write-Host` status output. |
| Tests (Python 3.11/3.13) | The complete automated suite on the oldest documented runtime and a current runtime. |
| Windows executable build | A clean PyInstaller build followed by artifact upload and SHA-256 reporting. |
| Dependency review | Pull-request dependency changes must not introduce a known moderate-or-higher vulnerability. |
| CodeQL (Python/JavaScript) | GitHub's security-and-quality query suite over backend and browser code. |

The local `security-check.ps1` command mirrors all portable Python and workflow checks. PSScriptAnalyzer, dependency review, CodeQL, and the clean hosted Windows build remain CI checks because they depend on runner or GitHub services.

## Workflow hardening

- Every external action is pinned to a full immutable commit SHA.
- Checkout credentials are never persisted.
- Ordinary workflows receive only read-only repository contents.
- The release workflow is the sole workflow with `contents: write`, needed to create a release for an already-pushed version tag.
- Jobs have explicit timeouts and concurrent superseded runs are cancelled.
- Build artifacts expire after 14 days; durable binaries belong on a tagged GitHub release.

## Dependency maintenance

Dependabot checks Python packages and GitHub Actions weekly, grouping each ecosystem into a manageable pull request. Dependency updates go through the same required gates as source changes.
