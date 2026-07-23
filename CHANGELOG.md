# Changelog

All notable changes to GIFmakerAthome are documented here. Releases follow semantic versioning.

## [1.1.0] - 2026-07-24

### Added

- Motion crop paths with up to 10 independently positioned, sized, and timed crop positions.
- Numbered, draggable motion-timing markers that keep inactive positions visible and make the selected position's time directly editable.
- The current video timestamp below the crop preview resolution.
- Frame-card duplication and deletion for any frame in the frame editor.
- Visual near-duplicate frame grouping that preserves the source duration with hold ticks.
- Live extraction and download progress for media URL imports.

### Changed

- Motion-crop exports now begin at the first position marker and end at the last position marker.
- New motion-crop positions inherit the preceding position's crop and time, while position timing remains fully adjustable.
- Frame grouping compares each candidate with the first frame in its run and tolerates small imperceptible pixel changes, preventing both one-pixel noise and slow cumulative drift from producing misleading groups.
- Closing the last application tab now shuts down the local server, with a grace period that keeps ordinary browser refreshes working.

### Fixed

- Added a locally generated browser-compatible preview when a successfully imported video uses a codec that the browser cannot display directly.
- Prefer broadly compatible H.264 streams during URL extraction when a source offers multiple video variants.

## [1.0.0] - 2026-07-19

- Initial public release with local file and URL imports, crop and time editing, GIF/animated WebP/VP9 WebM export, size targeting, frame editing, complete-loop generation, and a packaged Windows executable.

[1.1.0]: https://github.com/TL0024/gif-maker-athome/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/TL0024/gif-maker-athome/releases/tag/v1.0.0
