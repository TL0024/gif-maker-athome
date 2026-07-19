from __future__ import annotations

import ipaddress
import math
import mimetypes
import os
import re
import shutil
import socket

# subprocess use is restricted to the verified FFmpeg runner below.
import subprocess  # nosec B404
import threading
import time
import urllib.parse
import uuid
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import requests
from bs4 import BeautifulSoup
from PIL import Image
from werkzeug.utils import secure_filename

if TYPE_CHECKING:
    from yt_dlp import _Params


class MediaError(RuntimeError):
    """A user-facing media import or conversion error."""


@dataclass(frozen=True)
class MediaInfo:
    width: int
    height: int
    duration: float
    kind: str
    mime: str


@dataclass(frozen=True)
class MediaAsset:
    id: str
    path: Path
    name: str
    width: int
    height: int
    duration: float
    kind: str
    mime: str

    def as_api_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("path")
        data["duration"] = round(self.duration, 3)
        data["size"] = self.path.stat().st_size if self.path.exists() else 0
        return data


@dataclass(frozen=True)
class ExportOptions:
    start: float
    end: float
    discard_middle: bool
    crop_x: int
    crop_y: int
    crop_width: int
    crop_height: int
    output_width: int
    output_height: int
    output_format: str = "webm"
    fps: int = 30
    colors: int = 256
    quality: int = 40
    max_size_kb: int | None = None
    reduce_colors: bool = False
    lossy_gif: bool = False
    optimize_unchanged_pixels: bool = False
    remove_duplicate_frames: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any], media: MediaAsset) -> ExportOptions:
        try:
            options = cls(
                start=float(payload.get("start", 0)),
                end=float(payload.get("end", media.duration)),
                discard_middle=bool(payload.get("discard_middle", False)),
                crop_x=int(payload.get("crop_x", 0)),
                crop_y=int(payload.get("crop_y", 0)),
                crop_width=int(payload.get("crop_width", media.width)),
                crop_height=int(payload.get("crop_height", media.height)),
                output_width=int(payload.get("output_width", media.width)),
                output_height=int(payload.get("output_height", media.height)),
                output_format=str(payload.get("output_format", "webm")).strip().lower(),
                fps=int(payload.get("fps", 30)),
                colors=int(payload.get("colors", 256)),
                quality=int(payload.get("quality", 40)),
                max_size_kb=(None if payload.get("max_size_kb") in {None, "", 0, "0"} else int(payload["max_size_kb"])),
                reduce_colors=bool(payload.get("reduce_colors", False)),
                lossy_gif=bool(payload.get("lossy_gif", False)),
                optimize_unchanged_pixels=bool(payload.get("optimize_unchanged_pixels", False)),
                remove_duplicate_frames=bool(payload.get("remove_duplicate_frames", False)),
            )
        except (TypeError, ValueError) as exc:
            raise MediaError("One or more export settings are invalid.") from exc
        options.validate(media)
        return options

    def validate(self, media: MediaAsset) -> None:
        tolerance = 0.05
        if self.start < 0 or self.end > media.duration + tolerance or self.end <= self.start:
            raise MediaError("Choose an end time that is after the start time and inside the media duration.")
        if self.discard_middle and self.start <= tolerance and self.end >= media.duration - tolerance:
            raise MediaError("Removing that interval would leave no frames. Shorten the removed interval.")
        if self.crop_width < 1 or self.crop_height < 1 or self.crop_x < 0 or self.crop_y < 0:
            raise MediaError("The crop rectangle is invalid.")
        if self.crop_x + self.crop_width > media.width or self.crop_y + self.crop_height > media.height:
            raise MediaError("The crop rectangle extends outside the source.")
        if not (1 <= self.output_width <= 4096 and 1 <= self.output_height <= 4096):
            raise MediaError("Output dimensions must be between 1 and 4096 pixels.")
        if self.output_width * self.output_height > 16_777_216:
            raise MediaError("The selected output resolution is too large.")
        if not 1 <= self.fps <= 60:
            raise MediaError("Frame rate must be between 1 and 60 FPS.")
        if self.output_format not in {"gif", "webp", "webm"}:
            raise MediaError("Output format must be GIF, WebP, or WebM.")
        if not 2 <= self.colors <= 256:
            raise MediaError("Palette size must be between 2 and 256 colors.")
        if not 1 <= self.quality <= 100:
            raise MediaError("WebP/WebM quality must be between 1 and 100.")
        if self.max_size_kb is not None and not 16 <= self.max_size_kb <= 1_048_576:
            raise MediaError("File-size cap must be between 16 KB and 1 GB.")


@dataclass(frozen=True)
class FrameSequence:
    id: str
    directory: Path
    source_name: str
    width: int
    height: int
    fps: int
    frames: tuple[Path, ...]


@dataclass(frozen=True)
class FrameExportOptions:
    output_format: str
    output_width: int
    output_height: int
    colors: int = 256
    quality: int = 40
    max_size_kb: int | None = None
    reduce_colors: bool = False
    lossy_gif: bool = False
    optimize_unchanged_pixels: bool = False
    remove_duplicate_frames: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any], sequence: FrameSequence) -> FrameExportOptions:
        try:
            options = cls(
                output_format=str(payload.get("output_format", "webm")).strip().lower(),
                output_width=sequence.width,
                output_height=sequence.height,
                colors=int(payload.get("colors", 256)),
                quality=int(payload.get("quality", 40)),
                max_size_kb=(None if payload.get("max_size_kb") in {None, "", 0, "0"} else int(payload["max_size_kb"])),
                reduce_colors=bool(payload.get("reduce_colors", False)),
                lossy_gif=bool(payload.get("lossy_gif", False)),
                optimize_unchanged_pixels=bool(payload.get("optimize_unchanged_pixels", False)),
                remove_duplicate_frames=bool(payload.get("remove_duplicate_frames", False)),
            )
        except (TypeError, ValueError) as exc:
            raise MediaError("One or more frame-export settings are invalid.") from exc
        options.validate()
        return options

    def validate(self) -> None:
        if self.output_format not in {"gif", "webm"}:
            raise MediaError("The frame editor can export only GIF or WebM.")
        if not (1 <= self.output_width <= 4096 and 1 <= self.output_height <= 4096):
            raise MediaError("Output dimensions must be between 1 and 4096 pixels.")
        if not 2 <= self.colors <= 256:
            raise MediaError("Palette size must be between 2 and 256 colors.")
        if not 1 <= self.quality <= 100:
            raise MediaError("WebM quality must be between 1 and 100.")
        if self.max_size_kb is not None and not 16 <= self.max_size_kb <= 1_048_576:
            raise MediaError("File-size cap must be between 16 KB and 1 GB.")


def ffmpeg_executable() -> str:
    """Return imageio-ffmpeg's bundled executable, with a system fallback."""
    try:
        import imageio_ffmpeg  # type: ignore[import-untyped]

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except (ImportError, RuntimeError) as exc:
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            return system_ffmpeg
        raise MediaError("FFmpeg is unavailable. Run install.bat (or install requirements.txt) and try again.") from exc


def _run_ffmpeg(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    """Run only the selected FFmpeg executable without invoking a command shell."""
    trusted_executable = Path(ffmpeg_executable()).resolve()
    if (
        not command
        or any(not isinstance(argument, str) for argument in command)
        or Path(command[0]).resolve() != trusted_executable
    ):
        raise MediaError("The media command did not use the trusted FFmpeg executable.")
    # The executable is verified above and command-shell processing remains disabled.
    return subprocess.run(  # nosec B603
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )


def probe_media(path: Path) -> MediaInfo:
    """Read dimensions and duration without modifying the source."""
    try:
        with Image.open(path) as image:
            if getattr(image, "is_animated", False) or image.format in {"GIF", "WEBP"}:
                duration_ms = 0
                frames = getattr(image, "n_frames", 1)
                for index in range(frames):
                    image.seek(index)
                    duration_ms += int(image.info.get("duration", 100))
                return MediaInfo(
                    width=image.width,
                    height=image.height,
                    duration=max(duration_ms / 1000, 0.1),
                    kind="image",
                    mime=Image.MIME.get(image.format or "", "image/gif"),
                )
    except (OSError, ValueError):
        pass

    try:
        import imageio_ffmpeg

        frames = imageio_ffmpeg.read_frames(str(path), pix_fmt="rgb24")
        metadata = next(frames)
        frames.close()
        size = metadata.get("source_size") or metadata.get("size")
        duration = float(metadata.get("duration") or 0)
        if not size or duration <= 0:
            raise ValueError("missing dimensions or duration")
        mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
        return MediaInfo(int(size[0]), int(size[1]), duration, "video", mime)
    except (ImportError, OSError, RuntimeError, StopIteration, ValueError) as exc:
        raise MediaError("This file is not a readable video or animated image.") from exc


def _num(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def build_filter_graph(options: ExportOptions, duration: float) -> str:
    """Build the FFmpeg graph for trim/remove, crop, scale, and the selected encoder."""
    filters: list[str] = []
    if not options.discard_middle:
        filters.append(f"[0:v]trim=start={_num(options.start)}:end={_num(options.end)},setpts=PTS-STARTPTS[cut]")
        source = "[cut]"
    else:
        segment_labels: list[str] = []
        if options.start > 0.001:
            filters.append(f"[0:v]trim=start=0:end={_num(options.start)},setpts=PTS-STARTPTS[before]")
            segment_labels.append("[before]")
        if options.end < duration - 0.001:
            filters.append(f"[0:v]trim=start={_num(options.end)}:end={_num(duration)},setpts=PTS-STARTPTS[after]")
            segment_labels.append("[after]")
        if len(segment_labels) == 2:
            filters.append("[before][after]concat=n=2:v=1:a=0[cut]")
            source = "[cut]"
        elif segment_labels:
            source = segment_labels[0]
        else:
            raise MediaError("Removing that interval would leave no frames.")

    processing = (
        f"{source}crop={options.crop_width}:{options.crop_height}:"
        f"{options.crop_x}:{options.crop_y},"
        f"scale={options.output_width}:{options.output_height}:flags=lanczos"
    )
    if options.output_format == "gif" and options.lossy_gif:
        processing += ",hqdn3d=1.5:1.5:6:6"
    filters.append(f"{processing},fps={options.fps}[prepared]")
    if options.output_format == "gif":
        palette_colors = min(options.colors, 64) if options.reduce_colors else options.colors
        filters.append("[prepared]split[gif_frames][palette_source]")
        filters.append(f"[palette_source]palettegen=max_colors={palette_colors}:stats_mode=diff[palette]")
        palette_use = "[gif_frames][palette]paletteuse="
        palette_use += "dither=bayer:bayer_scale=5" if options.lossy_gif else "dither=sierra2_4a"
        if options.optimize_unchanged_pixels:
            palette_use += ":diff_mode=rectangle"
        filters.append(f"{palette_use}[outv]")
    else:
        pixel_format = "yuva420p" if options.output_format == "webm" else "yuv420p"
        filters.append(f"[prepared]format={pixel_format}[outv]")
    return ";".join(filters)


def _encode_animation_once(source: MediaAsset, output_path: Path, options: ExportOptions) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg_executable(), "-hide_banner", "-loglevel", "error"]
    if source.path.suffix.lower() == ".gif":
        command.extend(["-ignore_loop", "1"])
    command.extend(
        [
            "-i",
            str(source.path),
            "-filter_complex",
            build_filter_graph(options, source.duration),
            "-map",
            "[outv]",
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-an",
            "-sn",
            "-dn",
        ]
    )
    if options.output_format == "webp":
        command.extend(
            [
                "-c:v",
                "libwebp_anim",
                "-lossless",
                "0",
                "-q:v",
                str(options.quality),
                "-compression_level",
                "6",
                "-loop",
                "0",
            ]
        )
    elif options.output_format == "webm":
        webm_crf = max(4, min(63, round(62 - options.quality * 0.4)))
        command.extend(
            [
                "-c:v",
                "libvpx-vp9",
                "-b:v",
                "0",
                "-crf",
                str(webm_crf),
                "-deadline",
                "good",
                "-cpu-used",
                "2",
                "-row-mt",
                "1",
                "-threads",
                "0",
            ]
        )
    else:
        command.extend(["-loop", "0"])
    command.extend(["-y", str(output_path)])
    try:
        result = _run_ffmpeg(command, 600)
    except subprocess.TimeoutExpired as exc:
        raise MediaError("Animation creation timed out. Try a shorter duration or smaller resolution.") from exc
    if result.returncode != 0 or not output_path.exists():
        detail = (result.stderr or "Unknown FFmpeg error").strip().splitlines()[-1]
        raise MediaError(f"{options.output_format.upper()} creation failed: {detail[:500]}")
    if options.output_format == "gif" and options.remove_duplicate_frames:
        _remove_duplicate_gif_frames(output_path)


def _remove_duplicate_gif_frames(path: Path) -> None:
    """Merge consecutive identical GIF frames while preserving their combined delay."""
    temporary = path.with_name(f"{path.stem}-deduplicated.gif")
    frames: list[Image.Image] = []
    durations: list[int] = []
    previous_pixels: bytes | None = None
    original_count = 0
    try:
        with Image.open(path) as image:
            loop = int(image.info.get("loop", 0))
            for index in range(getattr(image, "n_frames", 1)):
                image.seek(index)
                original_count += 1
                duration = max(10, int(image.info.get("duration", 100)))
                frame = image.convert("RGBA")
                pixels = frame.tobytes()
                if previous_pixels == pixels and durations:
                    durations[-1] += duration
                    continue
                frames.append(frame.copy())
                durations.append(duration)
                previous_pixels = pixels
        if len(frames) == original_count or not frames:
            return
        frames[0].save(
            temporary,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=loop,
            disposal=2,
            optimize=True,
        )
        os.replace(temporary, path)
    except (OSError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        raise MediaError("Duplicate GIF frames could not be optimized.") from exc


def _smaller_export_options(options: ExportOptions, target_bytes: int, actual_bytes: int) -> ExportOptions:
    """Choose a materially smaller next pass while preserving the selected aspect ratio."""
    ratio = max(0.001, min(0.999, target_bytes / max(actual_bytes, 1)))
    dimension_factor = max(0.5, min(0.92, math.sqrt(ratio * 0.88)))
    fps_factor = max(0.62, min(0.92, ratio**0.18))

    def shrink_dimension(value: int) -> int:
        minimum = min(value, 8)
        reduced = max(minimum, math.floor(value * dimension_factor))
        if reduced >= value and value > minimum:
            reduced = value - 1
        if options.output_format == "webm" and reduced > 2 and reduced % 2:
            reduced -= 1
        return max(1, reduced)

    minimum_fps = min(options.fps, 1)
    reduced_fps = max(minimum_fps, math.floor(options.fps * fps_factor))
    if reduced_fps >= options.fps and options.fps > minimum_fps:
        reduced_fps = options.fps - 1

    if options.output_format == "gif":
        color_factor = max(0.45, min(0.85, ratio**0.24))
        reduced_colors = max(8, math.floor(options.colors * color_factor))
        if reduced_colors >= options.colors and options.colors > 8:
            reduced_colors = max(8, options.colors - 8)
        reduced_quality = options.quality
    else:
        quality_drop = max(5, math.ceil((1 - ratio) * 30))
        reduced_quality = max(1, options.quality - quality_drop)
        reduced_colors = options.colors

    return replace(
        options,
        output_width=shrink_dimension(options.output_width),
        output_height=shrink_dimension(options.output_height),
        fps=reduced_fps,
        colors=reduced_colors,
        quality=reduced_quality,
    )


def export_animation(source: MediaAsset, output_path: Path, options: ExportOptions) -> None:
    """Encode once at requested quality, then adapt only when a hard size cap is enabled."""
    current = options
    target_bytes = options.max_size_kb * 1024 if options.max_size_kb is not None else None
    for _attempt in range(7):
        _encode_animation_once(source, output_path, current)
        actual_bytes = output_path.stat().st_size
        if target_bytes is None or actual_bytes <= target_bytes:
            return
        smaller = _smaller_export_options(current, target_bytes, actual_bytes)
        if smaller == current:
            break
        current = smaller

    output_path.unlink(missing_ok=True)
    raise MediaError(
        f"This animation could not fit under {options.max_size_kb} KB. "
        "Choose a shorter duration or a larger file-size cap."
    )


MAX_FRAME_EDITOR_FRAMES = 900
MAX_FRAME_EDITOR_OUTPUT_FRAMES = 18_000


def _selected_output_duration(options: ExportOptions, duration: float) -> float:
    if options.discard_middle:
        return options.start + max(0, duration - options.end)
    return max(0, options.end - options.start)


def build_frame_extraction_graph(options: ExportOptions, duration: float) -> str:
    """Build the selected cut/crop/resize/FPS graph used by the visual frame editor."""
    filters: list[str] = []
    if not options.discard_middle:
        filters.append(f"[0:v]trim=start={_num(options.start)}:end={_num(options.end)},setpts=PTS-STARTPTS[cut]")
        source = "[cut]"
    else:
        segment_labels: list[str] = []
        if options.start > 0.001:
            filters.append(f"[0:v]trim=start=0:end={_num(options.start)},setpts=PTS-STARTPTS[before]")
            segment_labels.append("[before]")
        if options.end < duration - 0.001:
            filters.append(f"[0:v]trim=start={_num(options.end)}:end={_num(duration)},setpts=PTS-STARTPTS[after]")
            segment_labels.append("[after]")
        if len(segment_labels) == 2:
            filters.append("[before][after]concat=n=2:v=1:a=0[cut]")
            source = "[cut]"
        elif segment_labels:
            source = segment_labels[0]
        else:
            raise MediaError("Removing that interval would leave no frames.")

    filters.append(
        f"{source}crop={options.crop_width}:{options.crop_height}:"
        f"{options.crop_x}:{options.crop_y},"
        f"scale={options.output_width}:{options.output_height}:flags=lanczos,"
        f"fps={options.fps}:eof_action=pass,format=rgba[outv]"
    )
    return ";".join(filters)


def extract_frame_sequence(
    source: MediaAsset,
    output_directory: Path,
    options: ExportOptions,
) -> tuple[Path, ...]:
    """Extract every frame in the current working clip as a lossless local PNG."""
    expected_frames = max(1, math.ceil(_selected_output_duration(options, source.duration) * options.fps))
    if expected_frames > MAX_FRAME_EDITOR_FRAMES:
        raise MediaError(
            f"The frame editor supports up to {MAX_FRAME_EDITOR_FRAMES} frames at once. "
            "Shorten the selected duration or choose a lower FPS."
        )
    output_directory.mkdir(parents=True, exist_ok=False)
    pattern = output_directory / "frame-%06d.png"
    command = [ffmpeg_executable(), "-hide_banner", "-loglevel", "error"]
    if source.path.suffix.lower() == ".gif":
        command.extend(["-ignore_loop", "1"])
    command.extend(
        [
            "-i",
            str(source.path),
            "-filter_complex",
            build_frame_extraction_graph(options, source.duration),
            "-map",
            "[outv]",
            "-vsync",
            "0",
            "-compression_level",
            "3",
            "-y",
            str(pattern),
        ]
    )
    try:
        result = _run_ffmpeg(command, 900)
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(output_directory, ignore_errors=True)
        raise MediaError("Frame extraction timed out. Try a shorter clip or smaller resolution.") from exc
    frames = tuple(sorted(output_directory.glob("frame-*.png")))
    if result.returncode != 0 or not frames:
        shutil.rmtree(output_directory, ignore_errors=True)
        detail = (result.stderr or "Unknown FFmpeg error").strip().splitlines()[-1]
        raise MediaError(f"Frames could not be extracted: {detail[:500]}")
    if len(frames) > MAX_FRAME_EDITOR_FRAMES:
        shutil.rmtree(output_directory, ignore_errors=True)
        raise MediaError(
            f"This selection produced more than {MAX_FRAME_EDITOR_FRAMES} frames. Shorten it or choose a lower FPS."
        )
    return frames


def _encode_ordered_frames_once(
    input_pattern: Path,
    frame_count: int,
    fps: int,
    output_path: Path,
    options: FrameExportOptions,
) -> None:
    processing = f"[0:v]scale={options.output_width}:{options.output_height}:flags=lanczos"
    if options.output_format == "gif" and options.lossy_gif:
        processing += ",hqdn3d=1.5:1.5:6:6"
    filters = [f"{processing}[prepared]"]
    if options.output_format == "gif":
        palette_colors = min(options.colors, 64) if options.reduce_colors else options.colors
        filters.extend(
            [
                "[prepared]split[gif_frames][palette_source]",
                f"[palette_source]palettegen=max_colors={palette_colors}:stats_mode=full[palette]",
            ]
        )
        palette_use = "[gif_frames][palette]paletteuse="
        palette_use += "dither=bayer:bayer_scale=5" if options.lossy_gif else "dither=sierra2_4a"
        if options.optimize_unchanged_pixels:
            palette_use += ":diff_mode=rectangle"
        filters.append(f"{palette_use}[outv]")
    else:
        filters.append("[prepared]format=yuva420p[outv]")

    command = [
        ffmpeg_executable(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-framerate",
        str(fps),
        "-start_number",
        "1",
        "-i",
        str(input_pattern),
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[outv]",
        "-frames:v",
        str(frame_count),
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-an",
        "-sn",
        "-dn",
    ]
    if options.output_format == "webm":
        webm_crf = max(4, min(63, round(62 - options.quality * 0.4)))
        command.extend(
            [
                "-c:v",
                "libvpx-vp9",
                "-b:v",
                "0",
                "-crf",
                str(webm_crf),
                "-deadline",
                "good",
                "-cpu-used",
                "2",
                "-row-mt",
                "1",
                "-threads",
                "0",
            ]
        )
    else:
        command.extend(["-loop", "0"])
    command.extend(["-y", str(output_path)])
    try:
        result = _run_ffmpeg(command, 900)
    except subprocess.TimeoutExpired as exc:
        output_path.unlink(missing_ok=True)
        raise MediaError("Frame compilation timed out. Try fewer frames or a smaller resolution.") from exc
    if result.returncode != 0 or not output_path.exists():
        output_path.unlink(missing_ok=True)
        detail = (result.stderr or "Unknown FFmpeg error").strip().splitlines()[-1]
        raise MediaError(f"Frame compilation failed: {detail[:500]}")
    if options.output_format == "gif" and options.remove_duplicate_frames:
        _remove_duplicate_gif_frames(output_path)


def _smaller_frame_export_options(
    options: FrameExportOptions,
    target_bytes: int,
    actual_bytes: int,
) -> FrameExportOptions:
    ratio = max(0.001, min(0.999, target_bytes / max(actual_bytes, 1)))
    dimension_factor = max(0.5, min(0.92, math.sqrt(ratio * 0.88)))

    def shrink_dimension(value: int) -> int:
        minimum = min(value, 8)
        reduced = max(minimum, math.floor(value * dimension_factor))
        if reduced >= value and value > minimum:
            reduced = value - 1
        if options.output_format == "webm" and reduced > 2 and reduced % 2:
            reduced -= 1
        return max(1, reduced)

    if options.output_format == "gif":
        color_factor = max(0.45, min(0.85, ratio**0.24))
        colors = max(8, math.floor(options.colors * color_factor))
        if colors >= options.colors and options.colors > 8:
            colors = max(8, options.colors - 8)
        quality = options.quality
    else:
        quality = max(1, options.quality - max(5, math.ceil((1 - ratio) * 30)))
        colors = options.colors
    return replace(
        options,
        output_width=shrink_dimension(options.output_width),
        output_height=shrink_dimension(options.output_height),
        colors=colors,
        quality=quality,
    )


def export_ordered_frames(
    input_pattern: Path,
    frame_count: int,
    fps: int,
    output_path: Path,
    options: FrameExportOptions,
) -> None:
    """Compile a reordered/trimmed frame list, adapting quality for an optional hard cap."""
    current = options
    target_bytes = options.max_size_kb * 1024 if options.max_size_kb is not None else None
    for _attempt in range(7):
        _encode_ordered_frames_once(input_pattern, frame_count, fps, output_path, current)
        actual_bytes = output_path.stat().st_size
        if target_bytes is None or actual_bytes <= target_bytes:
            return
        smaller = _smaller_frame_export_options(current, target_bytes, actual_bytes)
        if smaller == current:
            break
        current = smaller
    output_path.unlink(missing_ok=True)
    raise MediaError(
        f"This edited animation could not fit under {options.max_size_kb} KB without removing frames. "
        "Delete more frames, lower the resolution, or choose a larger cap."
    )


def export_pingpong_loop(source: MediaAsset, output_path: Path, output_format: str) -> None:
    """Append the complete reversed animation to create a forward/backward loop."""
    if output_format not in {"gif", "webm"}:
        raise MediaError("Loop extension is available only for GIF and WebM exports.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filters = [
        "[0:v]split[forward_source][reverse_source]",
        "[forward_source]setpts=PTS-STARTPTS[forward]",
        "[reverse_source]reverse,trim=start_frame=1,setpts=PTS-STARTPTS[reversed]",
        "[forward][reversed]concat=n=2:v=1:a=0[pingpong]",
    ]
    if output_format == "gif":
        filters.extend(
            [
                "[pingpong]split[loop_frames][palette_source]",
                "[palette_source]palettegen=max_colors=256:stats_mode=diff[palette]",
                "[loop_frames][palette]paletteuse=dither=sierra2_4a:diff_mode=rectangle[outv]",
            ]
        )
    else:
        filters.append("[pingpong]format=yuva420p[outv]")

    command = [ffmpeg_executable(), "-hide_banner", "-loglevel", "error"]
    if source.path.suffix.lower() == ".gif":
        command.extend(["-ignore_loop", "1"])
    command.extend(
        [
            "-i",
            str(source.path),
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[outv]",
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-an",
            "-sn",
            "-dn",
        ]
    )
    if output_format == "webm":
        command.extend(
            [
                "-c:v",
                "libvpx-vp9",
                "-b:v",
                "0",
                "-crf",
                "28",
                "-deadline",
                "good",
                "-cpu-used",
                "2",
                "-row-mt",
                "1",
                "-threads",
                "0",
            ]
        )
    else:
        command.extend(["-loop", "0"])
    command.extend(["-y", str(output_path)])
    try:
        result = _run_ffmpeg(command, 900)
    except subprocess.TimeoutExpired as exc:
        output_path.unlink(missing_ok=True)
        raise MediaError("Loop extension timed out. Try a shorter animation.") from exc
    if result.returncode != 0 or not output_path.exists():
        output_path.unlink(missing_ok=True)
        detail = (result.stderr or "Unknown FFmpeg error").strip().splitlines()[-1]
        raise MediaError(f"Loop extension failed: {detail[:500]}")


class MediaStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        if self.root.parent == self.root:
            raise MediaError("The cache directory cannot be a filesystem root.")
        self.import_dir = self.root / "imports"
        self.export_dir = self.root / "exports"
        self.preview_dir = self.root / "previews"
        self.frame_dir = self.root / "frames"
        self._assets: dict[str, MediaAsset] = {}
        self._previews: dict[str, Path] = {}
        self._frame_sequences: dict[str, FrameSequence] = {}
        self._lock = threading.RLock()
        self.startup_cleanup = self.clear_all()

    def clear_all(self) -> dict[str, int]:
        """Delete every app-owned cache artifact and recreate empty working directories."""
        removed_files = 0
        removed_bytes = 0
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            for child in list(self.root.iterdir()):
                if child.is_symlink():
                    removed_files += 1
                    with suppress(OSError):
                        removed_bytes += child.lstat().st_size
                    self._remove_cache_path(child)
                    continue
                if child.is_dir():
                    for directory, _subdirectories, filenames in os.walk(child, followlinks=False):
                        for filename in filenames:
                            removed_files += 1
                            with suppress(OSError):
                                removed_bytes += (Path(directory) / filename).stat().st_size
                    self._remove_cache_path(child)
                else:
                    removed_files += 1
                    with suppress(OSError):
                        removed_bytes += child.stat().st_size
                    self._remove_cache_path(child)
            self._assets.clear()
            self._previews.clear()
            self._frame_sequences.clear()
            for cache_directory in (self.import_dir, self.export_dir, self.preview_dir, self.frame_dir):
                cache_directory.mkdir(parents=True, exist_ok=True)
        return {"files": removed_files, "bytes": removed_bytes}

    @staticmethod
    def _remove_cache_path(path: Path) -> None:
        for attempt in range(4):
            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
                return
            except PermissionError as exc:
                if attempt == 3:
                    raise MediaError(
                        "A cache file is still in use. Stop its preview or download, then try Clear cache again."
                    ) from exc
                time.sleep(0.1 * (attempt + 1))

    def allocate_import_path(self, original_name: str) -> Path:
        safe_name = secure_filename(original_name) or "media.bin"
        suffix = Path(safe_name).suffix[:12].lower()
        return self.import_dir / f"{uuid.uuid4().hex}{suffix}"

    def register(self, path: Path, name: str | None = None) -> MediaAsset:
        info = probe_media(path)
        original_name = str(name or path.name).replace("\\", "/").rsplit("/", 1)[-1]
        display_name = "".join(character for character in original_name if character >= " " and character not in "\x7f")
        display_name = display_name.strip() or path.name
        asset = MediaAsset(
            id=uuid.uuid4().hex,
            path=path.resolve(),
            name=display_name,
            width=info.width,
            height=info.height,
            duration=info.duration,
            kind=info.kind,
            mime=info.mime,
        )
        with self._lock:
            self._assets[asset.id] = asset
        return asset

    def get(self, asset_id: str) -> MediaAsset:
        with self._lock:
            asset = self._assets.get(asset_id)
        if not asset or not asset.path.exists():
            raise MediaError("That media item is no longer available. Import it again.")
        return asset

    def create_export(self, source: MediaAsset, options: ExportOptions) -> MediaAsset:
        with self._lock:
            output = self.export_dir / f"gifmaker-athome-{uuid.uuid4().hex[:10]}.{options.output_format}"
            export_animation(source, output, options)
            source_stem = Path(source.name).stem.strip() or "animation"
            download_name = f"{source_stem}.{options.output_format}"
            return self.register(output, download_name)

    def create_frame_sequence(self, source: MediaAsset, options: ExportOptions) -> FrameSequence:
        with self._lock:
            sequence_id = uuid.uuid4().hex
            directory = self.frame_dir / sequence_id
            frames = extract_frame_sequence(source, directory, options)
            sequence = FrameSequence(
                id=sequence_id,
                directory=directory,
                source_name=source.name,
                width=options.output_width,
                height=options.output_height,
                fps=options.fps,
                frames=frames,
            )
            self._frame_sequences[sequence.id] = sequence
            return sequence

    def get_frame_sequence(self, sequence_id: str) -> FrameSequence:
        with self._lock:
            sequence = self._frame_sequences.get(sequence_id)
        if not sequence or not sequence.directory.exists():
            raise MediaError("That frame editor session is no longer available. Build the frames again.")
        return sequence

    def get_frame(self, sequence: FrameSequence, frame_id: str) -> Path:
        frame = next((path for path in sequence.frames if path.stem == frame_id), None)
        if frame is None or not frame.exists():
            raise MediaError("That frame is no longer available.")
        return frame

    def create_frame_export(
        self,
        sequence: FrameSequence,
        selection: Any,
        options: FrameExportOptions,
    ) -> MediaAsset:
        if not isinstance(selection, list) or not selection:
            raise MediaError("Keep at least one frame before compiling the animation.")
        if len(selection) > len(sequence.frames):
            raise MediaError("The edited frame list contains more frames than the source sequence.")

        available = {path.stem: path for path in sequence.frames}
        ordered: list[tuple[Path, int]] = []
        seen: set[str] = set()
        total_output_frames = 0
        for item in selection:
            if not isinstance(item, dict):
                raise MediaError("The edited frame list is invalid.")
            frame_id = str(item.get("id") or "")
            if frame_id not in available or frame_id in seen:
                raise MediaError("The edited frame list contains an invalid or repeated frame.")
            try:
                raw_hold = item.get("hold", 1)
                hold = int(raw_hold)
                if float(raw_hold) != hold:
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise MediaError("Each frame hold must be a whole number.") from exc
            if not 1 <= hold <= 300:
                raise MediaError("Each frame hold must be between 1 and 300 ticks.")
            seen.add(frame_id)
            ordered.append((available[frame_id], hold))
            total_output_frames += hold
        if total_output_frames > MAX_FRAME_EDITOR_OUTPUT_FRAMES:
            raise MediaError(
                f"The edited sequence can contain at most {MAX_FRAME_EDITOR_OUTPUT_FRAMES:,} total hold ticks."
            )

        with self._lock:
            working = sequence.directory / f"compile-{uuid.uuid4().hex}"
            working.mkdir(parents=True, exist_ok=False)
            output = self.export_dir / f"gifmaker-athome-frames-{uuid.uuid4().hex[:10]}.{options.output_format}"
            frame_number = 1
            try:
                for source_path, hold in ordered:
                    for _repeat in range(hold):
                        destination = working / f"ordered-{frame_number:06d}.png"
                        try:
                            os.link(source_path, destination)
                        except OSError:
                            shutil.copyfile(source_path, destination)
                        frame_number += 1
                export_ordered_frames(
                    working / "ordered-%06d.png",
                    total_output_frames,
                    sequence.fps,
                    output,
                    options,
                )
            finally:
                shutil.rmtree(working, ignore_errors=True)
            source_stem = Path(sequence.source_name).stem.strip() or "animation"
            return self.register(output, f"{source_stem}.{options.output_format}")

    def create_pingpong_loop(self, source: MediaAsset) -> MediaAsset:
        with self._lock:
            output_format = source.path.suffix.lower().lstrip(".")
            if output_format not in {"gif", "webm"}:
                raise MediaError("Loop extension is available only for GIF and WebM exports.")
            output = self.export_dir / f"gifmaker-athome-loop-{uuid.uuid4().hex[:10]}.{output_format}"
            export_pingpong_loop(source, output, output_format)
            source_stem = Path(source.name).stem.strip() or "animation"
            return self.register(output, f"{source_stem}-loop.{output_format}")

    def create_preview(self, source: MediaAsset) -> Path:
        with self._lock:
            existing = self._previews.get(source.id)
            if existing and existing.exists():
                return existing
            output = self.preview_dir / f"{source.id}.mp4"
            command = [
                ffmpeg_executable(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source.path),
                "-vf",
                "scale='min(1280,iw)':-2:flags=lanczos",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "28",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-y",
                str(output),
            ]
            result = _run_ffmpeg(command, 600)
            if result.returncode != 0 or not output.exists():
                detail = (result.stderr or "Unknown FFmpeg error").strip().splitlines()[-1]
                raise MediaError(f"A browser preview could not be created: {detail[:400]}")
            self._previews[source.id] = output
            return output

    def get_preview(self, source: MediaAsset) -> Path:
        with self._lock:
            preview = self._previews.get(source.id)
        if not preview or not preview.exists():
            raise MediaError("Create the compatibility preview before requesting it.")
        return preview


_DIRECT_EXTENSIONS = {
    ".mp4",
    ".webm",
    ".mov",
    ".mkv",
    ".avi",
    ".m4v",
    ".gif",
    ".webp",
}
_SOCIAL_HOSTS = {"tenor.com", "www.tenor.com", "giphy.com", "www.giphy.com", "imgur.com"}
_MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GIFmakerAthome/1.0"


def validate_public_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value.strip())
    except ValueError as exc:
        raise MediaError("Enter a valid http:// or https:// link.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise MediaError("Enter a valid public http:// or https:// link.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise MediaError("The link's host could not be resolved.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if any(
            (
                ip.is_private,
                ip.is_loopback,
                ip.is_link_local,
                ip.is_multicast,
                ip.is_reserved,
                ip.is_unspecified,
            )
        ):
            raise MediaError("Links to this local or private network address are not allowed.")
    return urllib.parse.urlunsplit(parsed)


def _suffix_for_response(response: requests.Response, url: str) -> str:
    suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if suffix in _DIRECT_EXTENSIONS:
        return suffix
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    known = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    return known.get(content_type, mimetypes.guess_extension(content_type) or ".bin")


def _download_direct(url: str, destination_dir: Path) -> Path:
    try:
        with requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            stream=True,
            timeout=(15, 90),
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            validate_public_url(response.url)
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type:
                raise MediaError("That link is a web page, not a direct media file.")
            length = int(response.headers.get("Content-Length") or 0)
            if length > _MAX_DOWNLOAD_BYTES:
                raise MediaError("The linked media is larger than the 2 GB import limit.")
            suffix = _suffix_for_response(response, response.url)
            destination = destination_dir / f"{uuid.uuid4().hex}{suffix}"
            downloaded = 0
            with destination.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > _MAX_DOWNLOAD_BYTES:
                        raise MediaError("The linked media is larger than the 2 GB import limit.")
                    output.write(chunk)
            return destination
    except requests.RequestException as exc:
        raise MediaError(f"The media link could not be downloaded: {exc}") from exc


def _embedded_media_url(page_url: str) -> str | None:
    try:
        response = requests.get(
            page_url,
            headers={"User-Agent": _USER_AGENT},
            timeout=(15, 45),
            allow_redirects=True,
        )
        response.raise_for_status()
        validate_public_url(response.url)
        if len(response.content) > 8 * 1024 * 1024:
            return None
    except requests.RequestException:
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    keys = (
        ("property", "og:video:secure_url"),
        ("property", "og:video:url"),
        ("property", "og:video"),
        ("name", "twitter:player:stream"),
        ("property", "og:image:secure_url"),
        ("property", "og:image"),
    )
    for attribute, key in keys:
        tag = soup.find("meta", attrs={attribute: key})
        if tag and tag.get("content"):
            return urllib.parse.urljoin(response.url, str(tag["content"]))
    return None


def _download_with_ytdlp(url: str, destination_dir: Path) -> tuple[Path, str]:
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError as exc:
        raise MediaError("Link importing is not installed. Run install.bat and try again.") from exc

    prefix = uuid.uuid4().hex
    template = str(destination_dir / f"{prefix}.%(ext)s")
    options: _Params = {
        "format": "bestvideo[ext=mp4]/bestvideo/best[ext=mp4]/best",
        "outtmpl": template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "ffmpeg_location": str(Path(ffmpeg_executable()).parent),
    }
    try:
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            if info is None:
                raise MediaError("No downloadable media was found at that link.")
            title = str(info.get("title") or "linked-media")
    except DownloadError as exc:
        message = re.sub(r"\s+", " ", str(exc)).strip()
        raise MediaError(f"The link extractor could not download this page: {message[:500]}") from exc
    candidates = [path for path in destination_dir.glob(f"{prefix}.*") if path.is_file() and ".part" not in path.name]
    if not candidates:
        raise MediaError("The link extractor finished without producing a media file.")
    return max(candidates, key=lambda path: path.stat().st_size), title


def import_media_url(url: str, store: MediaStore) -> MediaAsset:
    clean_url = validate_public_url(url)
    parsed = urllib.parse.urlsplit(clean_url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in _DIRECT_EXTENSIONS:
        path = _download_direct(clean_url, store.import_dir)
        return store.register(path, Path(parsed.path).name or "linked-media")

    extraction_errors: list[str] = []
    if parsed.hostname and parsed.hostname.lower() in _SOCIAL_HOSTS:
        embedded = _embedded_media_url(clean_url)
        if embedded:
            try:
                embedded = validate_public_url(embedded)
                path = _download_direct(embedded, store.import_dir)
                return store.register(path, Path(urllib.parse.urlsplit(embedded).path).name or "linked-media")
            except MediaError as exc:
                extraction_errors.append(str(exc))

    try:
        path, title = _download_with_ytdlp(clean_url, store.import_dir)
        return store.register(path, f"{title}{path.suffix}")
    except MediaError as exc:
        extraction_errors.append(str(exc))

    embedded = _embedded_media_url(clean_url)
    if embedded:
        try:
            embedded = validate_public_url(embedded)
            path = _download_direct(embedded, store.import_dir)
            return store.register(path, Path(urllib.parse.urlsplit(embedded).path).name or "linked-media")
        except MediaError as exc:
            extraction_errors.append(str(exc))

    detail = extraction_errors[-1] if extraction_errors else "No media was found on that page."
    raise MediaError(detail)
