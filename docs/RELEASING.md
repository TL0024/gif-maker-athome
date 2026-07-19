# Releasing

Releases use semantic version tags such as `v1.0.0`. The application version in `gifmaker/__init__.py` and Windows file metadata in `packaging/windows_version_info.txt` must match the intended tag.

## Release checklist

1. Update the application version, Windows version metadata, and user-facing release notes when needed.
2. Run `security-check.ps1` and `python -m pytest -q` locally.
3. Run `build-release.ps1` and smoke-test `release\GIFmakerAthome.exe` on Windows.
4. Compare `Get-FileHash release\GIFmakerAthome.exe -Algorithm SHA256` with `release\SHA256SUMS.txt`.
5. Open and merge a pull request. Do not tag an unmerged commit or bypass a required check.
6. Create and push an annotated `vMAJOR.MINOR.PATCH` tag on the verified `main` commit.
7. Confirm the **Release Windows executable** workflow publishes `GIFmakerAthome.exe` and `SHA256SUMS.txt` on the GitHub release.
8. Download the published executable, verify its checksum, and perform a final launch/upload/export smoke test.

The tag workflow repeats the security gate and tests before building. It creates generated release notes and uploads only the executable and checksum. Generated `build/` and `release/` directories remain ignored and are never committed.

## Recovery

If the tag workflow fails, correct the problem through a new pull request. Delete and recreate an unpublished tag only when it is safe and no user could have consumed it. For a published release, use a new patch version so the released tag and checksum remain immutable.
