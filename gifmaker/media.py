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
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageChops
from werkzeug.utils import secure_filename

if TYPE_CHECKING:
    from yt_dlp import _Params


class MediaError(RuntimeError):
    """A user-facing media import or conversion error."""


@dataclass(frozen=True)
class ImportProgress:
    """Progress reported while a remote media URL is resolved and downloaded."""

    stage: str
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed_bytes_per_second: float | None = None
    eta_seconds: int | None = None
    detail: str = ""

    def as_api_dict(self) -> dict[str, Any]:
        return asdict(self)


ImportProgressCallback = Callable[[ImportProgress], None]
MAX_MOTION_CROP_KEYFRAMES = 10


def _report_import_progress(
    callback: ImportProgressCallback | None,
    stage: str,
    *,
    downloaded_bytes: int = 0,
    total_bytes: int | None = None,
    speed_bytes_per_second: float | None = None,
    eta_seconds: int | None = None,
    detail: str = "",
) -> None:
    if callback is not None:
        callback(
            ImportProgress(
                stage=stage,
                downloaded_bytes=max(0, downloaded_bytes),
                total_bytes=total_bytes if total_bytes and total_bytes > 0 else None,
                speed_bytes_per_second=speed_bytes_per_second,
                eta_seconds=eta_seconds,
                detail=detail,
            )
        )


@dataclass(frozen=True)
class MediaInfo:
    width: int
    height: int
    duration: float
    kind: str
    mime: str
    codec: str | None = None


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
    codec: str | None = None

    @property
    def browser_preview_required(self) -> bool:
        """Whether the source needs transcoding before browsers can display it reliably."""
        if self.kind != "video":
            return False
        browser_native_formats = {
            ("video/mp4", "h264"),
            ("video/webm", "vp8"),
            ("video/webm", "vp9"),
        }
        return (self.mime, self.codec or "") not in browser_native_formats

    def as_api_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("path")
        data["duration"] = round(self.duration, 3)
        data["size"] = self.path.stat().st_size if self.path.exists() else 0
        data["browser_preview_required"] = self.browser_preview_required
        return data


@dataclass(frozen=True)
class MotionCropKeyframe:
    x: int
    y: int
    width: int
    height: int
    progress: float | None = None


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
    motion_crop: bool = False
    crop_end_x: int = 0
    crop_end_y: int = 0
    motion_crop_keyframes: tuple[MotionCropKeyframe, ...] = ()
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
            raw_keyframes = payload.get("motion_crop_keyframes") or ()
            if not isinstance(raw_keyframes, (list, tuple)):
                raise TypeError("motion crop keyframes must be a list")
            keyframes = tuple(
                MotionCropKeyframe(
                    x=int(item["x"]),
                    y=int(item["y"]),
                    width=int(item["width"]),
                    height=int(item["height"]),
                    progress=None if item.get("progress") is None else float(item["progress"]),
                )
                for item in raw_keyframes
                if isinstance(item, Mapping)
            )
            if len(keyframes) != len(raw_keyframes):
                raise TypeError("every motion crop keyframe must be an object")
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
                motion_crop=bool(payload.get("motion_crop", False)),
                crop_end_x=int(payload.get("crop_end_x", payload.get("crop_x", 0))),
                crop_end_y=int(payload.get("crop_end_y", payload.get("crop_y", 0))),
                motion_crop_keyframes=keyframes,
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
        except (KeyError, TypeError, ValueError) as exc:
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
        if self.motion_crop and not 2 <= len(self.resolved_motion_crop_keyframes()) <= MAX_MOTION_CROP_KEYFRAMES:
            raise MediaError(f"Motion crop requires between 2 and {MAX_MOTION_CROP_KEYFRAMES} positions.")
        if self.motion_crop:
            keyframes = self.resolved_motion_crop_keyframes()
            progresses = [float(keyframe.progress or 0) for keyframe in keyframes]
            if any(not math.isfinite(progress) or progress < 0 or progress > 1 for progress in progresses) or any(
                current < previous for previous, current in pairwise(progresses)
            ):
                raise MediaError("Motion crop timings must not move backward and must stay within the output.")
            if progresses[-1] <= progresses[0]:
                raise MediaError("The last motion crop position must be later than the first position.")
            for keyframe in keyframes:
                if (
                    keyframe.width < 1
                    or keyframe.height < 1
                    or keyframe.x < 0
                    or keyframe.y < 0
                    or keyframe.x + keyframe.width > media.width
                    or keyframe.y + keyframe.height > media.height
                ):
                    raise MediaError("A motion crop position extends outside the source.")
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

    def resolved_motion_crop_keyframes(self) -> tuple[MotionCropKeyframe, ...]:
        if self.motion_crop_keyframes:
            count = len(self.motion_crop_keyframes)
            return tuple(
                replace(
                    keyframe,
                    progress=keyframe.progress if keyframe.progress is not None else index / max(1, count - 1),
                )
                for index, keyframe in enumerate(self.motion_crop_keyframes)
            )
        return (
            MotionCropKeyframe(self.crop_x, self.crop_y, self.crop_width, self.crop_height, 0),
            MotionCropKeyframe(self.crop_end_x, self.crop_end_y, self.crop_width, self.crop_height, 1),
        )


@dataclass(frozen=True)
class FrameSequence:
    id: str
    directory: Path
    source_name: str
    width: int
    height: int
    fps: int
    frames: tuple[Path, ...]
    holds: tuple[int, ...]


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
    # A source that Pillow cannot identify as animated falls through to FFmpeg probing.
    with suppress(OSError, ValueError), Image.open(path) as image:
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
        codec = str(metadata.get("codec") or "").strip().lower() or None
        return MediaInfo(int(size[0]), int(size[1]), duration, "video", mime, codec)
    except (ImportError, OSError, RuntimeError, StopIteration, ValueError) as exc:
        raise MediaError("This file is not a readable video or animated image.") from exc


def _num(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _selected_output_duration(options: ExportOptions, duration: float) -> float:
    if options.discard_middle:
        return options.start + max(0, duration - options.end)
    return max(0, options.end - options.start)


def _motion_crop_time_window(options: ExportOptions, duration: float) -> tuple[float, float]:
    selected_duration = _selected_output_duration(options, duration)
    if not options.motion_crop:
        return 0, selected_duration
    keyframes = options.resolved_motion_crop_keyframes()
    first_progress = keyframes[0].progress
    last_progress = keyframes[-1].progress
    return (
        selected_duration * (0 if first_progress is None else first_progress),
        selected_duration * (1 if last_progress is None else last_progress),
    )


def _motion_crop_output_duration(options: ExportOptions, duration: float) -> float:
    start, end = _motion_crop_time_window(options, duration)
    return max(0, end - start)


def _motion_crop_window_filter(options: ExportOptions, duration: float) -> str:
    if not options.motion_crop:
        return ""
    selected_duration = _selected_output_duration(options, duration)
    start, end = _motion_crop_time_window(options, duration)
    if start <= 1e-9 and end >= selected_duration - 1e-9:
        return ""
    return f",trim=start={_num(start)}:end={_num(end)},setpts=PTS-STARTPTS"


def _keyframed_expression(
    keyframes: tuple[MotionCropKeyframe, ...],
    attribute: str,
    duration: float,
) -> str:
    values = [int(getattr(keyframe, attribute)) for keyframe in keyframes]
    if len(set(values)) == 1:
        return str(values[0])
    expression = str(values[-1])
    for index in range(len(values) - 2, -1, -1):
        start_value = keyframes[index].progress
        end_value = keyframes[index + 1].progress
        start_progress = 0.0 if start_value is None else start_value
        end_progress = 1.0 if end_value is None else end_value
        segment_start = duration * start_progress
        segment_end = duration * end_progress
        segment_duration = segment_end - segment_start
        if segment_duration <= 1e-9:
            continue
        elapsed = "t" if math.isclose(segment_start, 0, abs_tol=1e-9) else f"(t-{_num(segment_start)})"
        interpolation = f"{values[index]}+({values[index + 1] - values[index]})*{elapsed}/{_num(segment_duration)}"
        expression = f"if(lt(t,{_num(segment_end)}),{interpolation},{expression})"
    first_progress = keyframes[0].progress or 0
    if first_progress > 0:
        expression = f"if(lt(t,{_num(duration * first_progress)}),{values[0]},{expression})"
    return expression


def _crop_and_scale_filter(options: ExportOptions, duration: float) -> str:
    static = (
        f"crop={options.crop_width}:{options.crop_height}:{options.crop_x}:{options.crop_y},"
        f"scale={options.output_width}:{options.output_height}:flags=lanczos"
    )
    if not options.motion_crop:
        return static

    keyframes = options.resolved_motion_crop_keyframes()
    if len(set(keyframes)) == 1:
        return static

    travel_duration = max(0.001, _selected_output_duration(options, duration))
    x_expression = _keyframed_expression(keyframes, "x", travel_duration)
    y_expression = _keyframed_expression(keyframes, "y", travel_duration)
    width_expression = _keyframed_expression(keyframes, "width", travel_duration)
    height_expression = _keyframed_expression(keyframes, "height", travel_duration)
    fixed_size = len({(keyframe.width, keyframe.height) for keyframe in keyframes}) == 1
    if fixed_size:
        return (
            f"crop={keyframes[0].width}:{keyframes[0].height}:"
            f"'{x_expression}':'{y_expression}',"
            f"scale={options.output_width}:{options.output_height}:flags=lanczos"
        )

    scaled_x = f"({x_expression})*{options.output_width}/({width_expression})"
    scaled_y = f"({y_expression})*{options.output_height}/({height_expression})"
    return (
        f"scale=w='iw*{options.output_width}/({width_expression})':"
        f"h='ih*{options.output_height}/({height_expression})':flags=lanczos:eval=frame,"
        f"crop={options.output_width}:{options.output_height}:'{scaled_x}':'{scaled_y}'"
    )


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

    processing = f"{source}{_crop_and_scale_filter(options, duration)}{_motion_crop_window_filter(options, duration)}"
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
        f"{source}{_crop_and_scale_filter(options, duration)}"
        f"{_motion_crop_window_filter(options, duration)},"
        f"fps={options.fps}:eof_action=pass,format=rgba[outv]"
    )
    return ";".join(filters)


def extract_frame_sequence(
    source: MediaAsset,
    output_directory: Path,
    options: ExportOptions,
) -> tuple[Path, ...]:
    """Extract every frame in the current working clip as a lossless local PNG."""
    expected_frames = max(1, math.ceil(_motion_crop_output_duration(options, source.duration) * options.fps))
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


_FRAME_CHANNEL_DELTA = 16
_FRAME_CHANGED_PIXEL_RATIO = 0.03
_FRAME_DIFF_LUT = [0 if value <= _FRAME_CHANNEL_DELTA else 255 for value in range(256)]


def _frames_visually_equivalent(reference: Image.Image, candidate: Image.Image) -> bool:
    if reference.size != candidate.size:
        return False
    difference = ImageChops.difference(reference, candidate)
    bands = difference.split()
    changed_mask = bands[0].point(_FRAME_DIFF_LUT)
    for band in bands[1:]:
        changed_mask = ImageChops.lighter(changed_mask, band.point(_FRAME_DIFF_LUT))
    changed_pixels = changed_mask.histogram()[255]
    allowed_changed_pixels = max(1, math.floor(reference.width * reference.height * _FRAME_CHANGED_PIXEL_RATIO))
    return changed_pixels <= allowed_changed_pixels


def _collapse_consecutive_frames(frames: tuple[Path, ...]) -> tuple[tuple[Path, ...], tuple[int, ...]]:
    """Collapse visually unchanged runs while anchoring every comparison to the run's first frame."""
    unique_frames: list[Path] = []
    run_lengths: list[int] = []
    run_reference: Image.Image | None = None
    for frame in frames:
        with Image.open(frame) as image:
            candidate = image.convert("RGBA")
            candidate.load()
        if run_reference is not None and _frames_visually_equivalent(run_reference, candidate):
            run_lengths[-1] += 1
            candidate.close()
        else:
            if run_reference is not None:
                run_reference.close()
            unique_frames.append(frame)
            run_lengths.append(1)
            run_reference = candidate
    if run_reference is not None:
        run_reference.close()
    collapsed_frames: list[Path] = []
    holds: list[int] = []
    for frame, run_length in zip(unique_frames, run_lengths, strict=True):
        if run_length == 1:
            collapsed_frames.append(frame)
            holds.append(1)
            continue
        remaining = run_length
        while remaining:
            collapsed_frames.append(frame)
            holds.append(min(300, remaining))
            remaining -= holds[-1]
    return tuple(collapsed_frames), tuple(holds)


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
            codec=info.codec,
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
            extracted_frames = extract_frame_sequence(source, directory, options)
            frames, holds = _collapse_consecutive_frames(extracted_frames)
            sequence = FrameSequence(
                id=sequence_id,
                directory=directory,
                source_name=source.name,
                width=options.output_width,
                height=options.output_height,
                fps=options.fps,
                frames=frames,
                holds=holds,
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
        if len(selection) > MAX_FRAME_EDITOR_FRAMES:
            raise MediaError(f"The edited frame list can contain at most {MAX_FRAME_EDITOR_FRAMES} frame cards.")

        available = {path.stem: path for path in sequence.frames}
        ordered: list[tuple[Path, int]] = []
        total_output_frames = 0
        for item in selection:
            if not isinstance(item, dict):
                raise MediaError("The edited frame list is invalid.")
            frame_id = str(item.get("id") or "")
            if frame_id not in available:
                raise MediaError("The edited frame list contains an invalid frame.")
            try:
                raw_hold = item.get("hold", 1)
                hold = int(raw_hold)
                if float(raw_hold) != hold:
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise MediaError("Each frame hold must be a whole number.") from exc
            if not 1 <= hold <= 300:
                raise MediaError("Each frame hold must be between 1 and 300 ticks.")
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


def _download_direct(
    url: str,
    destination_dir: Path,
    progress_callback: ImportProgressCallback | None = None,
) -> Path:
    destination: Path | None = None
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
            _report_import_progress(
                progress_callback,
                "downloading",
                total_bytes=length,
                detail="Downloading media from the source…",
            )
            with destination.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > _MAX_DOWNLOAD_BYTES:
                        raise MediaError("The linked media is larger than the 2 GB import limit.")
                    output.write(chunk)
                    _report_import_progress(
                        progress_callback,
                        "downloading",
                        downloaded_bytes=downloaded,
                        total_bytes=length,
                        detail="Downloading media from the source…",
                    )
            _report_import_progress(
                progress_callback,
                "processing",
                downloaded_bytes=downloaded,
                total_bytes=length,
                detail="Checking the downloaded media…",
            )
            return destination
    except requests.RequestException as exc:
        if destination is not None:
            destination.unlink(missing_ok=True)
        raise MediaError(f"The media link could not be downloaded: {exc}") from exc
    except Exception:
        if destination is not None:
            destination.unlink(missing_ok=True)
        raise


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


def _download_with_ytdlp(
    url: str,
    destination_dir: Path,
    progress_callback: ImportProgressCallback | None = None,
) -> tuple[Path, str]:
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError as exc:
        raise MediaError("Link importing is not installed. Run install.bat and try again.") from exc

    prefix = uuid.uuid4().hex
    template = str(destination_dir / f"{prefix}.%(ext)s")

    def report_ytdlp_progress(data: Mapping[str, Any]) -> None:
        status = str(data.get("status") or "")
        if status == "downloading":
            downloaded = int(data.get("downloaded_bytes") or 0)
            total_value = data.get("total_bytes") or data.get("total_bytes_estimate")
            total = int(total_value) if total_value else None
            speed_value = data.get("speed")
            eta_value = data.get("eta")
            _report_import_progress(
                progress_callback,
                "downloading",
                downloaded_bytes=downloaded,
                total_bytes=total,
                speed_bytes_per_second=float(speed_value) if speed_value else None,
                eta_seconds=int(eta_value) if eta_value is not None else None,
                detail="Downloading media from the source…",
            )
        elif status == "finished":
            _report_import_progress(
                progress_callback,
                "processing",
                downloaded_bytes=int(data.get("downloaded_bytes") or 0),
                total_bytes=int(data.get("total_bytes") or 0) or None,
                detail="Preparing the downloaded media…",
            )

    options: _Params = {
        # Prefer H.264 when the source offers it because every supported desktop
        # browser can decode it. Higher-ranked HEVC/AV1 variants remain valid
        # fallbacks and are transcoded lazily for the in-browser preview.
        "format": (
            "bestvideo[ext=mp4][vcodec^=avc]/bestvideo[ext=mp4][vcodec^=h264]/"
            "best[ext=mp4][vcodec^=avc]/best[ext=mp4][vcodec^=h264]/"
            "bestvideo[ext=mp4]/bestvideo/best[ext=mp4]/best"
        ),
        "outtmpl": template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "ffmpeg_location": str(Path(ffmpeg_executable()).parent),
        "progress_hooks": [report_ytdlp_progress],
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


def import_media_url(
    url: str,
    store: MediaStore,
    progress_callback: ImportProgressCallback | None = None,
) -> MediaAsset:
    _report_import_progress(progress_callback, "extracting", detail="Finding downloadable media…")
    clean_url = validate_public_url(url)
    parsed = urllib.parse.urlsplit(clean_url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in _DIRECT_EXTENSIONS:
        path = _download_direct(clean_url, store.import_dir, progress_callback)
        return store.register(path, Path(parsed.path).name or "linked-media")

    extraction_errors: list[str] = []
    if parsed.hostname and parsed.hostname.lower() in _SOCIAL_HOSTS:
        embedded = _embedded_media_url(clean_url)
        if embedded:
            try:
                embedded = validate_public_url(embedded)
                path = _download_direct(embedded, store.import_dir, progress_callback)
                return store.register(path, Path(urllib.parse.urlsplit(embedded).path).name or "linked-media")
            except MediaError as exc:
                extraction_errors.append(str(exc))

    try:
        path, title = _download_with_ytdlp(clean_url, store.import_dir, progress_callback)
        return store.register(path, f"{title}{path.suffix}")
    except MediaError as exc:
        extraction_errors.append(str(exc))

    embedded = _embedded_media_url(clean_url)
    if embedded:
        try:
            embedded = validate_public_url(embedded)
            path = _download_direct(embedded, store.import_dir, progress_callback)
            return store.register(path, Path(urllib.parse.urlsplit(embedded).path).name or "linked-media")
        except MediaError as exc:
            extraction_errors.append(str(exc))

    detail = extraction_errors[-1] if extraction_errors else "No media was found on that page."
    raise MediaError(detail)
