"""Live smoke test for an explicitly supplied supported media URL."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from gifmaker.media import ExportOptions, MediaStore, import_media_url


def main() -> None:
    media_url = os.environ.get("GIFMAKER_ATHOME_TEST_MEDIA_URL", "").strip()
    if not media_url:
        raise SystemExit("Set GIFMAKER_ATHOME_TEST_MEDIA_URL to a supported media URL you are authorized to retrieve.")

    with tempfile.TemporaryDirectory(prefix="gifmaker-athome-media-url-") as temporary:
        store = MediaStore(Path(temporary) / "data")
        source = import_media_url(media_url, store)
        duration = min(1.0, source.duration)
        scale = min(1.0, 512 / source.width, 512 / source.height)
        options = ExportOptions(
            start=0.0,
            end=duration,
            discard_middle=False,
            crop_x=0,
            crop_y=0,
            crop_width=source.width,
            crop_height=source.height,
            output_width=max(1, round(source.width * scale)),
            output_height=max(1, round(source.height * scale)),
            output_format="webm",
            fps=30,
            quality=40,
            colors=256,
            max_size_kb=None,
        )
        options.validate(source)
        exported = store.create_export(source, options)
        if exported.path.stat().st_size <= 0 or exported.mime != "video/webm":
            raise RuntimeError("The media URL smoke test did not produce a valid WebM export.")
        print(
            f"Imported {source.width}x{source.height} media and exported "
            f"{exported.width}x{exported.height} WebM ({exported.path.stat().st_size:,} bytes)."
        )


if __name__ == "__main__":
    main()
