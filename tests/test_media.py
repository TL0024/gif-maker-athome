from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from gifmaker.media import (
    MAX_FRAME_EDITOR_FRAMES,
    ExportOptions,
    FrameExportOptions,
    ImportProgress,
    MediaError,
    MediaStore,
    _download_direct,
    _run_ffmpeg,
    build_filter_graph,
    ffmpeg_executable,
    validate_public_url,
)


def test_ffmpeg_runner_rejects_a_different_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gifmaker.media.ffmpeg_executable", lambda: "trusted-ffmpeg.exe")
    with pytest.raises(MediaError, match="trusted FFmpeg"):
        _run_ffmpeg(["different-program.exe", "-version"], 1)


def test_direct_download_reports_byte_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        url = "https://example.com/animation.gif"

        def __init__(self) -> None:
            self.headers = {"Content-Length": "6", "Content-Type": "image/gif"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            assert chunk_size == 1024 * 1024
            yield b"GIF"
            yield b"89a"

    monkeypatch.setattr("gifmaker.media.requests.get", lambda *_args, **_kwargs: FakeResponse())
    monkeypatch.setattr("gifmaker.media.validate_public_url", lambda value: value)
    reports: list[ImportProgress] = []

    downloaded = _download_direct("https://example.com/animation.gif", tmp_path, reports.append)

    assert downloaded.read_bytes() == b"GIF89a"
    assert [report.stage for report in reports] == ["downloading", "downloading", "downloading", "processing"]
    assert reports[-2].downloaded_bytes == 6
    assert reports[-2].total_bytes == 6


def make_animated_gif(path: Path, size: tuple[int, int] = (80, 60)) -> None:
    frames = [
        Image.new("RGB", size, "#ffcc42"),
        Image.new("RGB", size, "#4ecdc4"),
        Image.new("RGB", size, "#725cff"),
    ]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=100, loop=0)


def sample_options(**changes) -> ExportOptions:
    values = {
        "start": 0.5,
        "end": 2.5,
        "discard_middle": False,
        "crop_x": 10,
        "crop_y": 5,
        "crop_width": 120,
        "crop_height": 80,
        "output_width": 60,
        "output_height": 40,
        "output_format": "gif",
        "fps": 12,
        "colors": 192,
        "quality": 85,
    }
    values.update(changes)
    return ExportOptions(**values)


def test_keep_filter_contains_trim_crop_scale_and_palette() -> None:
    graph = build_filter_graph(sample_options(), duration=3)
    assert "trim=start=0.5:end=2.5" in graph
    assert "crop=120:80:10:5" in graph
    assert "scale=60:40:flags=lanczos" in graph
    assert "fps=12" in graph
    assert "palettegen=max_colors=192" in graph
    assert "hqdn3d" not in graph
    assert "diff_mode=rectangle" not in graph


def test_optional_gif_compression_filters_are_disabled_by_default_and_independently_enabled() -> None:
    graph = build_filter_graph(
        sample_options(
            colors=256,
            reduce_colors=True,
            lossy_gif=True,
            optimize_unchanged_pixels=True,
        ),
        duration=3,
    )
    assert "hqdn3d=1.5:1.5:6:6" in graph
    assert "palettegen=max_colors=64" in graph
    assert "dither=bayer:bayer_scale=5" in graph
    assert "diff_mode=rectangle" in graph


def test_webp_filter_uses_direct_prepared_frames_without_gif_palette() -> None:
    graph = build_filter_graph(sample_options(output_format="webp", fps=30), duration=3)
    assert "fps=30[prepared]" in graph
    assert "[prepared]format=yuv420p[outv]" in graph
    assert "palettegen" not in graph


def test_webm_filter_preserves_alpha_capable_pixel_format() -> None:
    graph = build_filter_graph(sample_options(output_format="webm", fps=30), duration=3)
    assert "fps=30[prepared]" in graph
    assert "[prepared]format=yuva420p[outv]" in graph
    assert "palettegen" not in graph


def test_discard_filter_joins_both_outer_segments() -> None:
    graph = build_filter_graph(sample_options(discard_middle=True), duration=3)
    assert "trim=start=0:end=0.5" in graph
    assert "trim=start=2.5:end=3" in graph
    assert "[before][after]concat=n=2:v=1:a=0[cut]" in graph


def test_discard_filter_supports_removing_from_beginning() -> None:
    graph = build_filter_graph(sample_options(start=0, end=1, discard_middle=True), duration=3)
    assert "[after]crop=" in graph
    assert "concat=" not in graph


def test_private_link_is_rejected() -> None:
    with pytest.raises(MediaError, match="private network"):
        validate_public_url("http://127.0.0.1/video.mp4")


def test_store_probes_animated_gif(tmp_path: Path) -> None:
    source = tmp_path / "source.gif"
    make_animated_gif(source)
    store = MediaStore(tmp_path / "data")
    asset = store.register(source, "Friendly name.gif")
    assert (asset.width, asset.height) == (80, 60)
    assert asset.duration == pytest.approx(0.3, abs=0.02)
    assert asset.kind == "image"


def test_media_store_clears_all_cache_files_on_startup_and_on_demand(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    stale = cache_root / "legacy" / "stale.tmp"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old cache")

    store = MediaStore(cache_root)
    assert not stale.exists()
    assert store.startup_cleanup == {"files": 1, "bytes": 9}
    assert all(
        directory.is_dir() for directory in (store.import_dir, store.export_dir, store.preview_dir, store.frame_dir)
    )

    generated = store.export_dir / "temporary.bin"
    generated.write_bytes(b"12345")
    cleared = store.clear_all()
    assert cleared == {"files": 1, "bytes": 5}
    assert list(store.import_dir.iterdir()) == []
    assert list(store.export_dir.iterdir()) == []
    assert list(store.preview_dir.iterdir()) == []
    assert list(store.frame_dir.iterdir()) == []


def test_export_payload_defaults_to_webm_and_optional_optimizations_off(tmp_path: Path) -> None:
    source = tmp_path / "source.gif"
    make_animated_gif(source)
    asset = MediaStore(tmp_path / "data").register(source)
    options = ExportOptions.from_payload({}, asset)
    assert options.output_format == "webm"
    assert options.fps == 30
    assert options.quality == 40
    assert options.max_size_kb is None
    assert options.reduce_colors is False
    assert options.lossy_gif is False
    assert options.optimize_unchanged_pixels is False
    assert options.remove_duplicate_frames is False
    with pytest.raises(MediaError, match="between 16 KB"):
        ExportOptions.from_payload({"max_size_kb": 15}, asset)


def test_frame_editor_extracts_reorders_holds_deletes_and_compiles_gif_and_webm(tmp_path: Path) -> None:
    source_path = tmp_path / "source.gif"
    make_animated_gif(source_path)
    store = MediaStore(tmp_path / "data")
    source = store.register(source_path, "Friendly name.gif")
    extraction = ExportOptions(
        start=0,
        end=source.duration,
        discard_middle=False,
        crop_x=0,
        crop_y=0,
        crop_width=source.width,
        crop_height=source.height,
        output_width=40,
        output_height=30,
        output_format="webm",
        fps=20,
    )
    sequence = store.create_frame_sequence(source, extraction)

    assert len(sequence.frames) >= 4
    assert (sequence.width, sequence.height, sequence.fps) == (40, 30, 20)
    with Image.open(sequence.frames[0]) as extracted:
        assert extracted.size == (40, 30)

    selection = [
        {"id": sequence.frames[-1].stem, "hold": 1},
        {"id": sequence.frames[0].stem, "hold": 2},
    ]
    compiled = store.create_frame_export(
        sequence,
        selection,
        FrameExportOptions(
            output_format="gif",
            output_width=sequence.width,
            output_height=sequence.height,
            colors=64,
        ),
    )
    assert compiled.name == "Friendly name.gif"
    assert compiled.duration == pytest.approx(0.15, abs=0.08)
    with Image.open(compiled.path) as animation:
        animation.seek(0)
        first = animation.convert("RGB").getpixel((20, 15))
        animation.seek(animation.n_frames - 1)
        last = animation.convert("RGB").getpixel((20, 15))
    assert first[2] > first[0]
    assert last[0] > last[2]

    webm = store.create_frame_export(
        sequence,
        selection,
        FrameExportOptions(
            output_format="webm",
            output_width=sequence.width,
            output_height=sequence.height,
            quality=40,
        ),
    )
    assert webm.name == "Friendly name.webm"
    assert webm.mime == "video/webm"
    assert webm.duration == pytest.approx(0.15, abs=0.12)

    with pytest.raises(MediaError, match="invalid or repeated"):
        store.create_frame_export(
            sequence,
            [{"id": sequence.frames[0].stem}, {"id": sequence.frames[0].stem}],
            FrameExportOptions("gif", sequence.width, sequence.height),
        )

    long_source = replace(source, duration=(MAX_FRAME_EDITOR_FRAMES + 1) / 60)
    too_long = replace(extraction, end=long_source.duration, fps=60)
    with pytest.raises(MediaError, match="supports up to"):
        store.create_frame_sequence(long_source, too_long)


def test_real_ffmpeg_exports_gif_webp_and_webm_with_crop_resize_and_middle_removal(tmp_path: Path) -> None:
    source_path = tmp_path / "sample.mp4"
    create = subprocess.run(
        [
            ffmpeg_executable(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=44100",
            "-t",
            "3",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-metadata",
            "title=Remove this metadata",
            "-y",
            str(source_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert create.returncode == 0, create.stderr
    source_inspected = subprocess.run(
        [ffmpeg_executable(), "-hide_banner", "-i", str(source_path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert "Audio: aac" in source_inspected.stderr
    assert "Remove this metadata" in source_inspected.stderr

    store = MediaStore(tmp_path / "data")
    source = store.register(source_path, "My Holiday Clip.mp4")
    options = sample_options(start=0.8, end=2.2, discard_middle=True)
    options.validate(source)
    gif_result = store.create_export(source, options)

    assert gif_result.path.read_bytes().startswith(b"GIF8")
    assert gif_result.name == "My Holiday Clip.gif"
    assert (gif_result.width, gif_result.height) == (60, 40)
    assert gif_result.duration == pytest.approx(1.6, abs=0.25)

    optimized_gif = store.create_export(
        source,
        replace(
            options,
            reduce_colors=True,
            lossy_gif=True,
            optimize_unchanged_pixels=True,
            remove_duplicate_frames=True,
        ),
    )
    assert optimized_gif.path.read_bytes().startswith(b"GIF8")
    assert (optimized_gif.width, optimized_gif.height) == (60, 40)

    gif_loop = store.create_pingpong_loop(gif_result)
    assert gif_loop.path.read_bytes().startswith(b"GIF8")
    assert gif_loop.name == "My Holiday Clip-loop.gif"
    assert (gif_loop.width, gif_loop.height) == (gif_result.width, gif_result.height)
    assert gif_loop.duration == pytest.approx(gif_result.duration * 2, abs=0.25)
    with Image.open(gif_result.path) as forward_gif, Image.open(gif_loop.path) as loop_gif:
        assert loop_gif.n_frames == forward_gif.n_frames * 2 - 1
    assert gif_loop.duration < gif_result.duration * 2

    webp_options = replace(options, output_format="webp", fps=30, quality=85)
    webp_result = store.create_export(source, webp_options)
    webp_header = webp_result.path.read_bytes()[:12]
    assert webp_header[:4] == b"RIFF"
    assert webp_header[8:12] == b"WEBP"
    assert webp_result.mime == "image/webp"
    assert webp_result.name == "My Holiday Clip.webp"
    assert (webp_result.width, webp_result.height) == (60, 40)
    assert webp_result.duration == pytest.approx(1.6, abs=0.25)

    webm_options = replace(options, output_format="webm", fps=30, quality=85)
    webm_result = store.create_export(source, webm_options)
    assert webm_result.path.read_bytes()[:4] == b"\x1aE\xdf\xa3"
    assert webm_result.mime == "video/webm"
    assert webm_result.name == "My Holiday Clip.webm"
    assert webm_result.kind == "video"
    assert (webm_result.width, webm_result.height) == (60, 40)
    assert webm_result.duration == pytest.approx(1.6, abs=0.25)
    inspected = subprocess.run(
        [ffmpeg_executable(), "-hide_banner", "-i", str(webm_result.path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert "Video: vp9" in inspected.stderr
    assert "Audio:" not in inspected.stderr
    assert "Remove this metadata" not in inspected.stderr

    webm_loop = store.create_pingpong_loop(webm_result)
    assert webm_loop.path.read_bytes()[:4] == b"\x1aE\xdf\xa3"
    assert webm_loop.name == "My Holiday Clip-loop.webm"
    assert (webm_loop.width, webm_loop.height) == (webm_result.width, webm_result.height)
    assert webm_loop.duration == pytest.approx(webm_result.duration * 2, abs=0.25)
    assert webm_loop.duration < webm_result.duration * 2

    with pytest.raises(MediaError, match="only for GIF and WebM"):
        store.create_pingpong_loop(webp_result)

    capped_options = replace(
        options,
        start=0,
        end=source.duration,
        discard_middle=False,
        crop_x=0,
        crop_y=0,
        crop_width=source.width,
        crop_height=source.height,
        output_width=source.width,
        output_height=source.height,
        fps=30,
        colors=256,
        max_size_kb=32,
    )
    capped_result = store.create_export(source, capped_options)
    assert capped_result.path.stat().st_size <= 32 * 1024
    assert capped_result.width < source.width or capped_result.height < source.height

    for capped_format in ("webp", "webm"):
        capped_modern = store.create_export(
            source,
            replace(capped_options, output_format=capped_format, max_size_kb=24, quality=85),
        )
        assert capped_modern.path.stat().st_size <= 24 * 1024


def test_duplicate_gif_frames_are_merged_without_losing_total_duration(tmp_path: Path) -> None:
    source_path = tmp_path / "still.mp4"
    created = subprocess.run(
        [
            ffmpeg_executable(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:size=64x64:rate=10",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(source_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert created.returncode == 0, created.stderr
    store = MediaStore(tmp_path / "dedupe-data")
    source = store.register(source_path)
    base = ExportOptions(
        start=0,
        end=2,
        discard_middle=False,
        crop_x=0,
        crop_y=0,
        crop_width=64,
        crop_height=64,
        output_width=64,
        output_height=64,
        output_format="gif",
        fps=10,
    )
    regular = store.create_export(source, base)
    deduplicated = store.create_export(source, replace(base, remove_duplicate_frames=True))
    with Image.open(regular.path) as image:
        regular_frames = image.n_frames
    with Image.open(deduplicated.path) as image:
        deduplicated_frames = image.n_frames
    assert regular_frames > deduplicated_frames
    assert deduplicated_frames == 1
    assert deduplicated.duration == pytest.approx(regular.duration, abs=0.15)
