(() => {
  "use strict";

  const token = document.querySelector('meta[name="gifmaker-athome-token"]').content;
  const browserSessionId = document.querySelector('meta[name="gifmaker-athome-browser-session"]').content;
  const $ = (id) => document.getElementById(id);
  const MAX_MOTION_CROP_KEYFRAMES = 10;
  const MAX_FRAME_EDITOR_CARDS = 900;
  const elements = {
    hero: $("heroSection"), importPanel: $("importPanel"), loading: $("loadingPanel"),
    loadingTitle: $("loadingTitle"), loadingDetail: $("loadingDetail"),
    loadingProgress: $("loadingProgress"), loadingProgressBar: $("loadingProgressBar"),
    loadingProgressText: $("loadingProgressText"), editor: $("editor"),
    result: $("resultPanel"), fileInput: $("fileInput"), dropZone: $("dropZone"),
    linkInput: $("linkInput"), importLinkButton: $("importLinkButton"), mediaName: $("mediaName"),
    mediaMeta: $("mediaMeta"), stage: $("mediaStage"), video: $("videoPreview"),
    image: $("imagePreview"), previewError: $("previewError"), cropBox: $("cropBox"),
    cropSize: $("cropSize"), currentTimestamp: $("currentTimestamp"),
    motionCropBar: $("motionCropBar"), motionCropEnabled: $("motionCropEnabled"),
    motionCropKeyframes: $("motionCropKeyframes"), addMotionCropKeyframe: $("addMotionCropKeyframe"),
    removeMotionCropKeyframe: $("removeMotionCropKeyframe"), motionCropTiming: $("motionCropTiming"),
    motionCropHint: $("motionCropHint"),
    startRange: $("startRange"), endRange: $("endRange"),
    startNumber: $("startNumber"), endNumber: $("endNumber"), rangeFill: $("rangeFill"),
    motionTimelineMarkers: $("motionTimelineMarkers"),
    selectedDuration: $("selectedDuration"), totalDurationLabel: $("totalDurationLabel"),
    modeHint: $("modeHint"), previewSelectionButton: $("previewSelectionButton"),
    openFrameEditorButton: $("openFrameEditorButton"), frameEditorPanel: $("frameEditorPanel"),
    closeFrameEditorButton: $("closeFrameEditorButton"), frameEditorSummary: $("frameEditorSummary"),
    frameEditorStatus: $("frameEditorStatus"), frameGrid: $("frameGrid"),
    resetFramesButton: $("resetFramesButton"), exportFramesButton: $("exportFramesButton"),
    outputFormat: $("outputFormat"), formatBadge: $("formatBadge"), formatNote: $("formatNote"),
    qualityControl: $("qualityControl"), qualityLabel: $("qualityLabel"),
    gifColorsControl: $("gifColorsControl"), qualitySelect: $("qualitySelect"),
    gifCompressionPanel: $("gifCompressionPanel"), gifCompressionNote: $("gifCompressionNote"),
    reduceColorsOption: $("reduceColorsOption"), lossyGifOption: $("lossyGifOption"),
    optimizePixelsOption: $("optimizePixelsOption"), removeDuplicatesOption: $("removeDuplicatesOption"),
    resolutionSelect: $("resolutionSelect"), outputWidth: $("outputWidth"),
    outputHeight: $("outputHeight"), dimensionLock: $("dimensionLock"),
    resolutionNote: $("resolutionNote"), fpsSelect: $("fpsSelect"), colorsSelect: $("colorsSelect"),
    sizeLimitSelect: $("sizeLimitSelect"), customSizeLimitControl: $("customSizeLimitControl"),
    customSizeLimit: $("customSizeLimit"),
    outputSummary: $("outputSummary"), outputDurationSummary: $("outputDurationSummary"),
    exportButton: $("exportButton"), exportButtonLabel: $("exportButtonLabel"),
    exportButtonIcon: $("exportButtonIcon"), replaceButton: $("replaceButton"), resultImage: $("resultImage"),
    resultVideo: $("resultVideo"),
    resultTitle: $("resultTitle"), resultMeta: $("resultMeta"), downloadButton: $("downloadButton"),
    downloadLabel: $("downloadLabel"),
    extendLoopButton: $("extendLoopButton"),
    editAgainButton: $("editAgainButton"), startOverButton: $("startOverButton"),
    clearCacheButton: $("clearCacheButton"), toast: $("toast"), toastIcon: $("toastIcon"),
    toastMessage: $("toastMessage"), toastClose: $("toastClose")
  };

  const state = {
    asset: null,
    crop: { x: 0, y: 0, w: 100, h: 100 },
    cropAspect: null,
    motionCropEnabled: false,
    motionCropIndex: 0,
    motionCropKeyframes: [],
    motionCropTimings: [],
    motionTimelineDrag: null,
    dimensionLocked: true,
    previewing: false,
    discardJumped: false,
    previewFallbackTried: false,
    cropPointer: null,
    resultAsset: null,
    forwardAsset: null,
    extendedAsset: null,
    forwardResultTitle: "",
    forwardResultMeta: "",
    loopExtended: false,
    frameSequence: null,
    frameItems: [],
    originalFrameItems: [],
    frameSignature: "",
    draggedFrameId: null,
    frameInstanceSerial: 0,
    frameEditorBusy: false
  };

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("X-GIFmakerAthome-Token", token);
    if (options.body && typeof options.body === "string") headers.set("Content-Type", "application/json");
    const response = await fetch(path, { ...options, headers });
    let data = {};
    try { data = await response.json(); } catch (_) { /* A proxy or server failure may not be JSON. */ }
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
    return data;
  }

  function showToast(message, type = "error") {
    elements.toastMessage.textContent = message;
    elements.toast.classList.toggle("success", type === "success");
    elements.toastIcon.textContent = type === "success" ? "✓" : "!";
    elements.toast.hidden = false;
  }

  function hideToast() { elements.toast.hidden = true; }

  function setLoading(active, title = "Importing media…", detail = "Long or high-resolution videos can take a moment.") {
    elements.loadingTitle.textContent = title;
    elements.loadingDetail.textContent = detail;
    elements.loading.hidden = !active;
    elements.loadingProgress.hidden = true;
    elements.loadingProgress.classList.remove("indeterminate");
    elements.loadingProgress.removeAttribute("aria-valuenow");
    elements.loadingProgressBar.style.width = "0";
    elements.loadingProgressText.textContent = "";
    if (active) {
      elements.clearCacheButton.disabled = true;
      elements.hero.hidden = true;
      elements.importPanel.hidden = true;
      elements.editor.hidden = true;
      elements.result.hidden = true;
    }
  }

  function updateImportProgress(job) {
    const downloaded = Number(job.downloaded_bytes) || 0;
    const total = Number(job.total_bytes) || 0;
    const speed = Number(job.speed_bytes_per_second) || 0;
    const eta = job.eta_seconds == null ? null : Number(job.eta_seconds);
    const hasTotal = total > 0;
    elements.loadingProgress.hidden = false;
    elements.loadingProgress.classList.toggle("indeterminate", !hasTotal);

    if (job.stage === "downloading") elements.loadingTitle.textContent = "Downloading linked media…";
    else if (job.stage === "processing") elements.loadingTitle.textContent = "Preparing linked media…";
    else elements.loadingTitle.textContent = "Extracting linked media…";
    elements.loadingDetail.textContent = job.detail || "This is the only step that needs an internet connection.";

    const parts = [];
    if (hasTotal) {
      const percent = Math.min(100, Math.max(0, (downloaded / total) * 100));
      elements.loadingProgressBar.style.width = `${percent.toFixed(1)}%`;
      elements.loadingProgress.setAttribute("aria-valuenow", String(Math.round(percent)));
      parts.push(`${Math.round(percent)}%`, `${readableBytes(downloaded)} of ${readableBytes(total)}`);
    } else {
      elements.loadingProgressBar.style.width = "";
      elements.loadingProgress.removeAttribute("aria-valuenow");
      if (downloaded > 0) parts.push(`${readableBytes(downloaded)} downloaded`);
    }
    if (speed > 0) parts.push(`${readableBytes(speed)}/s`);
    if (eta !== null && Number.isFinite(eta) && eta >= 0) parts.push(`${formatClock(eta)} remaining`);
    elements.loadingProgressText.textContent = parts.join(" · ");
  }

  function delay(milliseconds) {
    return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  }

  function restoreImporter() {
    elements.clearCacheButton.disabled = false;
    elements.loading.hidden = true;
    elements.editor.hidden = true;
    elements.result.hidden = true;
    elements.hero.hidden = false;
    elements.importPanel.hidden = false;
  }

  function formatClock(seconds) {
    const safe = Math.max(0, Number(seconds) || 0);
    const minutes = Math.floor(safe / 60);
    const remainder = Math.floor(safe % 60);
    const hours = Math.floor(minutes / 60);
    if (hours) return `${hours}:${String(minutes % 60).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
    return `${minutes}:${String(remainder).padStart(2, "0")}`;
  }

  function formatTimestamp(seconds) {
    const safe = Math.max(0, Number(seconds) || 0);
    const totalCentiseconds = Math.round(safe * 100);
    const wholeSeconds = Math.floor(totalCentiseconds / 100);
    const minutes = Math.floor(wholeSeconds / 60);
    const remainder = wholeSeconds % 60;
    const centiseconds = totalCentiseconds % 100;
    const precise = `${String(remainder).padStart(2, "0")}.${String(centiseconds).padStart(2, "0")}`;
    const hours = Math.floor(minutes / 60);
    if (hours) return `${hours}:${String(minutes % 60).padStart(2, "0")}:${precise}`;
    return `${minutes}:${precise}`;
  }

  function updatePreviewTimestamp(seconds = elements.video.currentTime) {
    elements.currentTimestamp.textContent = formatTimestamp(seconds);
  }

  function readableBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return "";
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
    return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
  }

  function minimumGap() {
    return Math.min(0.05, Math.max(0.01, (state.asset?.duration || 1) / 10));
  }

  function selectedTimes() {
    return { start: Number(elements.startRange.value), end: Number(elements.endRange.value) };
  }

  function isDiscardMode() {
    return document.querySelector('input[name="cutMode"]:checked').value === "discard";
  }

  function outputDuration() {
    if (!state.asset) return 0;
    const { start, end } = selectedTimes();
    return isDiscardMode() ? start + Math.max(0, state.asset.duration - end) : Math.max(0, end - start);
  }

  function finalOutputDuration() {
    const duration = outputDuration();
    if (!state.motionCropEnabled || !state.motionCropTimings.length) return duration;
    const first = state.motionCropTimings[0];
    const last = state.motionCropTimings[state.motionCropTimings.length - 1];
    return duration * Math.max(0, last - first);
  }

  function updateTimeline() {
    if (!state.asset) return;
    const duration = state.asset.duration;
    const { start, end } = selectedTimes();
    elements.startNumber.value = start.toFixed(2);
    elements.endNumber.value = end.toFixed(2);
    const startPct = (start / duration) * 100;
    const endPct = (end / duration) * 100;
    elements.rangeFill.style.left = `${startPct}%`;
    elements.rangeFill.style.width = `${Math.max(0, endPct - startPct)}%`;
    const resultDuration = finalOutputDuration();
    elements.selectedDuration.textContent = `${resultDuration.toFixed(2)}s output`;
    elements.modeHint.textContent = isDiscardMode()
      ? `The ${Math.max(0, end - start).toFixed(2)}s middle interval is removed; both outer parts are joined.`
      : "Only the selected interval becomes the animation.";
    if (state.motionCropEnabled) {
      updateMotionCropControls();
    }
    updateOutputSummary();
  }

  function setTimes(start, end, seekTo = null) {
    if (!state.asset) return;
    const duration = state.asset.duration;
    const gap = minimumGap();
    let cleanStart = Math.max(0, Math.min(Number(start) || 0, duration - gap));
    let cleanEnd = Math.max(gap, Math.min(Number(end) || duration, duration));
    if (cleanEnd - cleanStart < gap) {
      if (seekTo === "start") cleanStart = Math.max(0, cleanEnd - gap);
      else cleanEnd = Math.min(duration, cleanStart + gap);
    }
    elements.startRange.value = cleanStart.toFixed(3);
    elements.endRange.value = cleanEnd.toFixed(3);
    updateTimeline();
    if (state.asset.kind === "video" && seekTo) {
      elements.video.currentTime = seekTo === "start" ? cleanStart : Math.max(cleanStart, cleanEnd - 0.02);
    }
  }

  function cloneCrop(crop) {
    return { x: crop.x, y: crop.y, w: crop.w, h: crop.h };
  }

  function fitCrop(crop) {
    const width = Math.max(4, Math.min(100, crop.w));
    const height = Math.max(4, Math.min(100, crop.h));
    return {
      x: Math.max(0, Math.min(100 - width, crop.x)),
      y: Math.max(0, Math.min(100 - height, crop.y)),
      w: width,
      h: height
    };
  }

  function cropPixels(crop = state.crop) {
    if (!state.asset) return { x: 0, y: 0, w: 1, h: 1 };
    const x = Math.round(state.asset.width * crop.x / 100);
    const y = Math.round(state.asset.height * crop.y / 100);
    const right = Math.round(state.asset.width * (crop.x + crop.w) / 100);
    const bottom = Math.round(state.asset.height * (crop.y + crop.h) / 100);
    return {
      x: Math.min(x, state.asset.width - 1),
      y: Math.min(y, state.asset.height - 1),
      w: Math.max(1, Math.min(state.asset.width - x, right - x)),
      h: Math.max(1, Math.min(state.asset.height - y, bottom - y))
    };
  }

  function outputReferenceCropPixels() {
    const crop =
      state.motionCropEnabled && state.motionCropKeyframes.length ? state.motionCropKeyframes[0] : state.crop;
    return cropPixels(crop);
  }

  function paintCrop(crop) {
    if (!state.asset) return;
    Object.assign(elements.cropBox.style, {
      left: `${crop.x}%`, top: `${crop.y}%`, width: `${crop.w}%`, height: `${crop.h}%`
    });
    const [top, left, right, bottom] = document.querySelectorAll(".crop-shade");
    Object.assign(top.style, { left: "0", top: "0", width: "100%", height: `${crop.y}%` });
    Object.assign(bottom.style, { left: "0", top: `${crop.y + crop.h}%`, width: "100%", height: `${100 - crop.y - crop.h}%` });
    Object.assign(left.style, { left: "0", top: `${crop.y}%`, width: `${crop.x}%`, height: `${crop.h}%` });
    Object.assign(right.style, { left: `${crop.x + crop.w}%`, top: `${crop.y}%`, width: `${100 - crop.x - crop.w}%`, height: `${crop.h}%` });
    const pixels = cropPixels(crop);
    elements.cropSize.textContent = `${pixels.w} × ${pixels.h}`;
  }

  function renderCrop() {
    paintCrop(state.crop);
    syncResolutionFromCrop();
  }

  function syncMotionCropKeyframe() {
    if (!state.motionCropEnabled) return;
    const active = fitCrop(state.crop);
    state.crop = active;
    state.motionCropKeyframes[state.motionCropIndex] = cloneCrop(active);
  }

  function renderMotionTimelineMarkers() {
    elements.motionTimelineMarkers.replaceChildren();
    elements.motionTimelineMarkers.hidden = !state.motionCropEnabled;
    if (!state.motionCropEnabled || !state.asset) return;
    state.motionCropTimings.forEach((progress, index) => {
      const sourceTime = motionCropSourceTime(progress);
      const marker = document.createElement("button");
      marker.type = "button";
      const active = index === state.motionCropIndex;
      const dragging = active && state.motionTimelineDrag?.index === index;
      marker.className = `motion-timeline-marker${active ? " active" : ""}${dragging ? " dragging" : ""}`;
      marker.dataset.motionCropIndex = String(index);
      marker.style.left = `${Math.max(0, Math.min(100, sourceTime / state.asset.duration * 100))}%`;
      marker.textContent = String(index + 1);
      marker.title = active
        ? `Drag position ${index + 1} to change its timing (${formatTimestamp(sourceTime)})`
        : `Select motion position ${index + 1} at ${formatTimestamp(sourceTime)}`;
      marker.setAttribute("aria-label", marker.title);
      marker.setAttribute("aria-current", String(active));
      elements.motionTimelineMarkers.append(marker);
    });
  }

  function updateMotionCropControls() {
    const enabled = state.motionCropEnabled;
    elements.motionCropEnabled.checked = enabled;
    elements.startRange.hidden = enabled;
    elements.endRange.hidden = enabled;
    elements.motionCropKeyframes.replaceChildren();
    state.motionCropKeyframes.forEach((_crop, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `motion-keyframe${enabled && index === state.motionCropIndex ? " active" : ""}`;
      button.dataset.motionCropIndex = String(index);
      button.disabled = !enabled;
      const number = index + 1;
      button.textContent = String(number);
      button.setAttribute("aria-label", `Edit motion crop position ${number}`);
      button.setAttribute("aria-pressed", String(enabled && index === state.motionCropIndex));
      elements.motionCropKeyframes.append(button);
    });
    elements.addMotionCropKeyframe.disabled =
      !enabled || state.motionCropKeyframes.length >= MAX_MOTION_CROP_KEYFRAMES;
    elements.removeMotionCropKeyframe.disabled =
      !enabled || state.motionCropKeyframes.length <= 1;
    const duration = outputDuration();
    const progress = state.motionCropTimings[state.motionCropIndex] || 0;
    elements.motionCropTiming.value = (progress * duration).toFixed(2);
    elements.motionCropTiming.max = duration.toFixed(3);
    elements.motionCropTiming.disabled = !enabled;
    elements.motionCropHint.textContent = !enabled
      ? "Turn on to add up to 10 pan and zoom positions."
      : state.motionCropKeyframes.length === 1
        ? "Set position 1, then add another position to create motion."
        : `Position ${state.motionCropIndex + 1} of ${state.motionCropKeyframes.length}. ` +
          "Edit its crop above, or drag its highlighted timeline number. New positions continue from the latest.";
    renderMotionTimelineMarkers();
  }

  function motionCropSourceTime(progress) {
    const { start, end } = selectedTimes();
    const outputTime = progress * outputDuration();
    const sourceTime = isDiscardMode()
      ? outputTime <= start ? outputTime : end + outputTime - start
      : start + outputTime;
    return Math.max(0, Math.min(state.asset.duration, sourceTime));
  }

  function motionCropKeyframeTime(index) {
    const progress = state.motionCropTimings[index] || 0;
    return Math.min(Math.max(0, state.asset.duration - 0.02), motionCropSourceTime(progress));
  }

  function selectMotionCropKeyframe(index, seek = true) {
    if (!state.motionCropEnabled) return;
    if (state.previewing) stopPreviewCut();
    state.motionCropIndex = Math.max(0, Math.min(state.motionCropKeyframes.length - 1, index));
    state.crop = cloneCrop(state.motionCropKeyframes[state.motionCropIndex] || state.crop);
    updateMotionCropControls();
    renderCrop();
    const keyframeTime = motionCropKeyframeTime(state.motionCropIndex);
    if (seek && state.asset?.kind === "video" && elements.video.readyState > 0) {
      elements.video.currentTime = keyframeTime;
    }
  }

  function setMotionCropEnabled(enabled) {
    if (state.previewing) stopPreviewCut();
    state.motionTimelineDrag = null;
    state.motionCropEnabled = enabled;
    if (enabled) {
      state.motionCropKeyframes = [cloneCrop(state.crop)];
      state.motionCropTimings = [0];
      state.motionCropIndex = 0;
      selectMotionCropKeyframe(0);
    } else {
      state.motionCropKeyframes = [];
      state.motionCropTimings = [];
      state.motionCropIndex = 0;
      updateMotionCropControls();
      renderCrop();
    }
    updateTimeline();
  }

  function interpolateCrop(start, end, progress) {
    return {
      x: start.x + (end.x - start.x) * progress,
      y: start.y + (end.y - start.y) * progress,
      w: start.w + (end.w - start.w) * progress,
      h: start.h + (end.h - start.h) * progress
    };
  }

  function addMotionCropKeyframe() {
    if (!state.motionCropEnabled || state.motionCropKeyframes.length >= MAX_MOTION_CROP_KEYFRAMES) return;
    const previousIndex = state.motionCropKeyframes.length - 1;
    state.motionCropKeyframes.push(cloneCrop(state.motionCropKeyframes[previousIndex]));
    state.motionCropTimings.push(state.motionCropTimings[previousIndex]);
    selectMotionCropKeyframe(previousIndex + 1);
    updateTimeline();
  }

  function removeMotionCropKeyframe() {
    if (!state.motionCropEnabled || state.motionCropKeyframes.length <= 1) return;
    state.motionCropKeyframes.splice(state.motionCropIndex, 1);
    state.motionCropTimings.splice(state.motionCropIndex, 1);
    selectMotionCropKeyframe(Math.min(state.motionCropIndex, state.motionCropKeyframes.length - 1));
    updateTimeline();
  }

  function setMotionCropTiming(seconds) {
    const index = state.motionCropIndex;
    if (!state.motionCropEnabled) return;
    const duration = outputDuration();
    if (duration <= 0) return;
    const requestedSeconds = Number(seconds);
    if (!String(seconds).trim() || !Number.isFinite(requestedSeconds)) {
      updateMotionCropControls();
      return;
    }
    const minimum = index > 0 ? state.motionCropTimings[index - 1] : 0;
    const maximum = index < state.motionCropKeyframes.length - 1
      ? state.motionCropTimings[index + 1]
      : 1;
    state.motionCropTimings[index] = Math.max(minimum, Math.min(maximum, requestedSeconds / duration));
    updateTimeline();
    const keyframeTime = motionCropKeyframeTime(index);
    if (state.asset?.kind === "video" && elements.video.readyState > 0) {
      elements.video.currentTime = keyframeTime;
    }
  }

  function motionCropProgress(sourceTime) {
    const { start, end } = selectedTimes();
    const duration = outputDuration();
    if (duration <= 0) return 0;
    let outputTime;
    if (isDiscardMode()) {
      if (sourceTime <= start) outputTime = sourceTime;
      else if (sourceTime >= end) outputTime = start + sourceTime - end;
      else outputTime = start;
    } else {
      outputTime = sourceTime - start;
    }
    return Math.max(0, Math.min(1, outputTime / duration));
  }

  function setMotionCropTimingFromPointer(event) {
    const drag = state.motionTimelineDrag;
    if (
      !drag ||
      drag.pointerId !== event.pointerId ||
      drag.index !== state.motionCropIndex ||
      !state.asset
    ) return;
    const bounds = elements.motionTimelineMarkers.getBoundingClientRect();
    if (bounds.width <= 0) return;
    const timelineProgress = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
    const sourceTime = timelineProgress * state.asset.duration;
    setMotionCropTiming(motionCropProgress(sourceTime) * outputDuration());
  }

  function finishMotionTimelineDrag(event) {
    if (!state.motionTimelineDrag || state.motionTimelineDrag.pointerId !== event.pointerId) return;
    state.motionTimelineDrag = null;
    if (elements.motionTimelineMarkers.hasPointerCapture(event.pointerId)) {
      elements.motionTimelineMarkers.releasePointerCapture(event.pointerId);
    }
    renderMotionTimelineMarkers();
  }

  function updateMotionCropPreview() {
    if (!state.motionCropEnabled || !state.previewing || state.motionCropKeyframes.length < 2) return;
    const progress = motionCropProgress(elements.video.currentTime);
    if (progress <= state.motionCropTimings[0]) {
      paintCrop(state.motionCropKeyframes[0]);
      return;
    }
    const lastIndex = state.motionCropTimings.length - 1;
    if (progress >= state.motionCropTimings[lastIndex]) {
      paintCrop(state.motionCropKeyframes[lastIndex]);
      return;
    }
    let endIndex = state.motionCropTimings.findIndex((timing, index) => index > 0 && progress <= timing);
    if (endIndex < 0) endIndex = lastIndex;
    const startIndex = Math.max(0, endIndex - 1);
    const segmentDuration = state.motionCropTimings[endIndex] - state.motionCropTimings[startIndex];
    const localProgress = segmentDuration > 0
      ? (progress - state.motionCropTimings[startIndex]) / segmentDuration
      : 0;
    paintCrop(interpolateCrop(
      state.motionCropKeyframes[startIndex],
      state.motionCropKeyframes[startIndex + 1],
      localProgress
    ));
  }

  function restoreMotionCropEditor() {
    if (!state.motionCropEnabled) return;
    state.crop = cloneCrop(state.motionCropKeyframes[state.motionCropIndex] || state.crop);
    renderCrop();
  }

  function applyCropAspect(value) {
    document.querySelectorAll("[data-aspect]").forEach((button) => {
      button.classList.toggle("active", button.dataset.aspect === value);
    });
    if (value === "free") {
      state.cropAspect = null;
      return;
    }
    const target = value === "original" ? state.asset.width / state.asset.height : Number(value);
    state.cropAspect = target;
    const sourceRatio = state.asset.width / state.asset.height;
    const current = state.crop;
    const centerX = current.x + current.w / 2;
    const centerY = current.y + current.h / 2;
    let width = current.w;
    let height = width * sourceRatio / target;
    if (height > current.h) {
      height = current.h;
      width = height * target / sourceRatio;
    }
    state.crop = {
      x: Math.max(0, Math.min(100 - width, centerX - width / 2)),
      y: Math.max(0, Math.min(100 - height, centerY - height / 2)),
      w: width,
      h: height
    };
    syncMotionCropKeyframe();
    renderCrop();
  }

  function resizeLocked(pointerX, pointerY, handle, original) {
    const sourceRatio = state.asset.width / state.asset.height;
    const target = state.cropAspect;
    const fromLeft = handle.includes("w");
    const fromTop = handle.includes("n");
    const anchorX = fromLeft ? original.x + original.w : original.x;
    const anchorY = fromTop ? original.y + original.h : original.y;
    const widthFromX = Math.abs(pointerX - anchorX);
    const widthFromY = Math.abs(pointerY - anchorY) * target / sourceRatio;
    let width = Math.abs(widthFromX - original.w) >= Math.abs(widthFromY - original.w) ? widthFromX : widthFromY;
    const minWidth = Math.max(4, 4 * target / sourceRatio);
    const maxWidth = fromLeft ? anchorX : 100 - anchorX;
    const maxHeight = fromTop ? anchorY : 100 - anchorY;
    width = Math.max(minWidth, Math.min(width, maxWidth, maxHeight * target / sourceRatio));
    const height = width * sourceRatio / target;
    return {
      x: fromLeft ? anchorX - width : anchorX,
      y: fromTop ? anchorY - height : anchorY,
      w: width,
      h: height
    };
  }

  function onCropPointerDown(event) {
    if (!state.asset || state.previewing) return;
    event.preventDefault();
    elements.cropBox.setPointerCapture(event.pointerId);
    const rect = elements.stage.getBoundingClientRect();
    state.cropPointer = {
      id: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      stageWidth: rect.width,
      stageHeight: rect.height,
      handle: event.target.dataset.handle || "move",
      original: { ...state.crop }
    };
  }

  function onCropPointerMove(event) {
    const pointer = state.cropPointer;
    if (!pointer || pointer.id !== event.pointerId) return;
    const dx = (event.clientX - pointer.startX) / pointer.stageWidth * 100;
    const dy = (event.clientY - pointer.startY) / pointer.stageHeight * 100;
    const original = pointer.original;
    if (pointer.handle === "move") {
      state.crop = {
        ...original,
        x: Math.max(0, Math.min(100 - original.w, original.x + dx)),
        y: Math.max(0, Math.min(100 - original.h, original.y + dy))
      };
    } else if (state.cropAspect) {
      const rect = elements.stage.getBoundingClientRect();
      const pointX = (event.clientX - rect.left) / rect.width * 100;
      const pointY = (event.clientY - rect.top) / rect.height * 100;
      state.crop = resizeLocked(pointX, pointY, pointer.handle, original);
    } else {
      const min = 4;
      const fromLeft = pointer.handle.includes("w");
      const fromTop = pointer.handle.includes("n");
      const farX = original.x + original.w;
      const farY = original.y + original.h;
      let x = fromLeft ? Math.max(0, Math.min(farX - min, original.x + dx)) : original.x;
      let y = fromTop ? Math.max(0, Math.min(farY - min, original.y + dy)) : original.y;
      let right = fromLeft ? farX : Math.max(original.x + min, Math.min(100, farX + dx));
      let bottom = fromTop ? farY : Math.max(original.y + min, Math.min(100, farY + dy));
      state.crop = { x, y, w: right - x, h: bottom - y };
    }
    syncMotionCropKeyframe();
    renderCrop();
  }

  function finishCropPointer(event) {
    if (state.cropPointer?.id === event.pointerId) state.cropPointer = null;
  }

  function syncResolutionFromCrop() {
    if (!state.asset) return;
    const crop = outputReferenceCropPixels();
    const mode = elements.resolutionSelect.value;
    if (mode !== "custom") {
      const squarePreset = mode === "512square";
      const factor = mode === "original" || squarePreset ? 1 : Number(mode);
      elements.outputWidth.value = squarePreset ? 512 : Math.max(1, Math.round(crop.w * factor));
      elements.outputHeight.value = squarePreset ? 512 : Math.max(1, Math.round(crop.h * factor));
      elements.outputWidth.disabled = true;
      elements.outputHeight.disabled = true;
      elements.resolutionNote.textContent = squarePreset
        ? "Exports a square 512 × 512 animation. Selecting this preset also applies a 1:1 crop."
        : mode === "original"
        ? "No resizing—the cropped pixels stay at source resolution."
        : `Scaled to ${Math.round(factor * 100)}% of the cropped source.`;
    } else {
      elements.outputWidth.disabled = false;
      elements.outputHeight.disabled = false;
      if (!elements.outputWidth.value || !elements.outputHeight.value) {
        elements.outputWidth.value = crop.w;
        elements.outputHeight.value = crop.h;
      } else if (state.dimensionLocked) {
        elements.outputHeight.value = Math.max(1, Math.round(Number(elements.outputWidth.value) * crop.h / crop.w));
      }
      elements.resolutionNote.textContent = "Custom dimensions use high-quality Lanczos resizing.";
    }
    updateOutputSummary();
  }

  function updateOutputSummary() {
    if (!state.asset) return;
    const width = Number(elements.outputWidth.value) || outputReferenceCropPixels().w;
    const height = Number(elements.outputHeight.value) || outputReferenceCropPixels().h;
    const paletteBased = elements.outputFormat.value === "gif";
    elements.outputSummary.textContent = `${elements.outputFormat.value.toUpperCase()} · ${width} × ${height} · ${elements.fpsSelect.value} FPS`;
    const detail = paletteBased
      ? `${finalOutputDuration().toFixed(2)} seconds · ${elements.colorsSelect.value} colors`
      : `${finalOutputDuration().toFixed(2)} seconds · quality ${elements.qualitySelect.value}`;
    const cap = selectedSizeCap();
    const techniqueCount = elements.outputFormat.value === "gif"
      ? gifTechniqueInputs().filter((input) => input.checked).length
      : 0;
    elements.outputDurationSummary.textContent = `${detail}${techniqueCount ? ` · ${techniqueCount} auto optimization${techniqueCount === 1 ? "" : "s"}` : ""}${cap ? ` · cap ≤ ${cap} KB` : ""}`;
    updateFrameEditorSummary();
  }

  function gifTechniqueInputs() {
    return [
      elements.reduceColorsOption,
      elements.lossyGifOption,
      elements.optimizePixelsOption,
      elements.removeDuplicatesOption
    ];
  }

  function selectedSizeCap() {
    const mode = elements.sizeLimitSelect.value;
    if (mode === "none") return null;
    return mode === "custom" ? Number(elements.customSizeLimit.value) : Number(mode);
  }

  function updateSizeLimitControls() {
    elements.customSizeLimitControl.hidden = elements.sizeLimitSelect.value !== "custom";
    updateOutputSummary();
  }

  function updateFormatControls() {
    const format = elements.outputFormat.value;
    const formatName = { gif: "GIF", webp: "WebP", webm: "WebM" }[format] || "GIF";
    elements.formatBadge.textContent = formatName.toUpperCase();
    elements.qualityControl.hidden = format === "gif";
    elements.gifColorsControl.hidden = format !== "gif";
    elements.qualityLabel.textContent = format === "webm" ? "WebM quality" : "WebP quality";
    elements.formatNote.textContent = {
      gif: "GIF offers the widest compatibility with an adaptive color palette.",
      webp: "Animated WebP usually produces smaller files with smoother color.",
      webm: "VP9 WebM has no audio. Telegram video stickers must be 3 seconds or less, at most 30 FPS, and no larger than 256 KB."
    }[format];
    const gifSelected = format === "gif";
    elements.gifCompressionPanel.classList.toggle("unavailable", !gifSelected);
    gifTechniqueInputs().forEach((input) => { input.disabled = !gifSelected; });
    elements.gifCompressionNote.textContent = gifSelected
      ? "All techniques are optional and remain off until selected."
      : "Switch the output format to GIF to use these techniques.";
    elements.exportButtonLabel.textContent = `Create ${formatName}`;
    updateOutputSummary();
  }

  function configureMedia(asset) {
    resetFrameEditor();
    state.asset = asset;
    state.resultAsset = null;
    state.forwardAsset = null;
    state.extendedAsset = null;
    state.loopExtended = false;
    state.crop = { x: 0, y: 0, w: 100, h: 100 };
    state.cropAspect = null;
    state.motionCropEnabled = false;
    state.motionCropIndex = 0;
    state.motionCropKeyframes = [];
    state.motionCropTimings = [];
    state.motionTimelineDrag = null;
    state.previewFallbackTried = false;
    state.previewing = false;
    elements.previewError.hidden = true;
    elements.mediaName.textContent = asset.name;
    elements.mediaMeta.textContent = `${asset.width} × ${asset.height} · ${formatClock(asset.duration)} · ${asset.kind === "video" ? "Video" : "Animated image"}`;
    elements.stage.style.setProperty("--ratio", asset.width / asset.height);

    elements.video.pause();
    elements.video.removeAttribute("src");
    elements.image.removeAttribute("src");
    elements.video.hidden = asset.kind !== "video";
    elements.image.hidden = asset.kind === "video";
    elements.currentTimestamp.hidden = asset.kind !== "video";
    elements.motionCropBar.hidden = asset.kind !== "video";
    updateMotionCropControls();
    updatePreviewTimestamp(0);
    if (asset.kind === "video") {
      if (asset.browser_preview_required) {
        void createFallbackPreview();
      } else {
        elements.video.src = asset.media_url;
        elements.video.load();
      }
    } else {
      elements.image.src = asset.media_url;
    }

    const duration = asset.duration;
    for (const input of [
      elements.startRange,
      elements.endRange,
      elements.startNumber,
      elements.endNumber
    ]) {
      input.max = duration.toFixed(3);
    }
    elements.startRange.value = "0";
    elements.endRange.value = duration.toFixed(3);
    elements.totalDurationLabel.textContent = formatClock(duration);
    document.querySelector('input[name="cutMode"][value="keep"]').checked = true;
    elements.outputFormat.value = "webm";
    elements.fpsSelect.value = "30";
    elements.qualitySelect.value = "40";
    elements.sizeLimitSelect.value = "none";
    elements.customSizeLimitControl.hidden = true;
    elements.resolutionSelect.value = "original";
    gifTechniqueInputs().forEach((input) => { input.checked = false; });
    updateFormatControls();
    applyCropAspect("original");
    updateTimeline();
    elements.loading.hidden = true;
    elements.clearCacheButton.disabled = false;
    elements.hero.hidden = true;
    elements.importPanel.hidden = true;
    elements.result.hidden = true;
    elements.editor.hidden = false;
    elements.editor.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function uploadFile(file) {
    if (!file) return;
    setLoading(true, "Reading your media…", "The file stays on this computer.");
    const body = new FormData();
    body.append("file", file);
    try {
      const data = await api("/api/upload", { method: "POST", body });
      configureMedia(data.asset);
    } catch (error) {
      restoreImporter();
      showToast(error.message);
    } finally {
      elements.fileInput.value = "";
    }
  }

  async function importLink() {
    const url = elements.linkInput.value.trim();
    if (!url) { showToast("Paste a supported media URL first."); return; }
    setLoading(true, "Extracting linked media…", "This is the only step that needs an internet connection.");
    updateImportProgress({ stage: "extracting", detail: "Finding downloadable media…" });
    try {
      const started = await api("/api/import", { method: "POST", body: JSON.stringify({ url }) });
      let data = started;
      while (data.job.status === "running") {
        updateImportProgress(data.job);
        await delay(250);
        data = await api(`/api/import/${data.job.id}`);
      }
      updateImportProgress(data.job);
      if (data.job.status === "failed") throw new Error(data.job.error || "The linked media could not be imported.");
      configureMedia(data.asset);
    } catch (error) {
      restoreImporter();
      document.querySelector('[data-tab="link"]').click();
      showToast(error.message);
    }
  }

  async function createFallbackPreview() {
    const asset = state.asset;
    if (!asset || state.previewFallbackTried || asset.kind !== "video") return;
    state.previewFallbackTried = true;
    elements.previewError.textContent = "This format is not browser-native. Creating a local compatibility preview…";
    elements.previewError.hidden = false;
    try {
      const data = await api(`/api/media/${asset.id}/preview`, { method: "POST" });
      if (!state.asset || state.asset.id !== asset.id) return;
      elements.video.src = data.preview_url;
      elements.video.load();
      elements.previewError.hidden = true;
    } catch (error) {
      if (!state.asset || state.asset.id !== asset.id) return;
      elements.previewError.textContent = error.message;
    }
  }

  function sourceEditPayload() {
    const keyframeCrops = state.motionCropEnabled ? state.motionCropKeyframes : [state.crop];
    const pixelKeyframes = keyframeCrops.map((crop) => cropPixels(crop));
    const crop = pixelKeyframes[0];
    const lastCrop = pixelKeyframes[pixelKeyframes.length - 1];
    const { start, end } = selectedTimes();
    return {
      media_id: state.asset.id,
      start,
      end,
      discard_middle: isDiscardMode(),
      crop_x: crop.x,
      crop_y: crop.y,
      crop_width: crop.w,
      crop_height: crop.h,
      motion_crop: state.motionCropEnabled,
      crop_end_x: lastCrop.x,
      crop_end_y: lastCrop.y,
      motion_crop_keyframes: state.motionCropEnabled
        ? pixelKeyframes.map((keyframe, index) => ({
            x: keyframe.x,
            y: keyframe.y,
            width: keyframe.w,
            height: keyframe.h,
            progress: state.motionCropTimings[index]
          }))
        : [],
      output_width: Number(elements.outputWidth.value),
      output_height: Number(elements.outputHeight.value),
      output_format: elements.outputFormat.value,
      fps: Number(elements.fpsSelect.value)
    };
  }

  function frameExportSettingsPayload() {
    return {
      output_format: elements.outputFormat.value,
      colors: Number(elements.colorsSelect.value),
      quality: Number(elements.qualitySelect.value),
      max_size_kb: selectedSizeCap(),
      reduce_colors: elements.reduceColorsOption.checked,
      lossy_gif: elements.lossyGifOption.checked,
      optimize_unchanged_pixels: elements.optimizePixelsOption.checked,
      remove_duplicate_frames: elements.removeDuplicatesOption.checked
    };
  }

  function hasCompleteMotionCrop() {
    return !state.motionCropEnabled || state.motionCropKeyframes.length >= 2;
  }

  function requireCompleteMotionCrop() {
    if (!hasCompleteMotionCrop()) {
      showToast("Add another position to finish the motion crop.");
      return false;
    }
    if (
      state.motionCropEnabled &&
      state.motionCropTimings[state.motionCropTimings.length - 1] <= state.motionCropTimings[0]
    ) {
      showToast("Move the last position later than the first position.");
      return false;
    }
    return true;
  }

  function currentFrameSignature() {
    if (!state.asset) return "";
    const payload = sourceEditPayload();
    delete payload.output_format;
    return JSON.stringify(payload);
  }

  function resetFrameEditor() {
    state.frameSequence = null;
    state.frameItems = [];
    state.originalFrameItems = [];
    state.frameSignature = "";
    state.draggedFrameId = null;
    state.frameInstanceSerial = 0;
    state.frameEditorBusy = false;
    elements.frameGrid.replaceChildren();
    elements.frameEditorPanel.hidden = true;
    elements.frameEditorStatus.className = "frame-editor-status";
    elements.frameEditorStatus.textContent = "";
    elements.openFrameEditorButton.disabled = false;
    elements.openFrameEditorButton.textContent = "View all frames";
  }

  function resetToImport() {
    resetFrameEditor();
    state.previewing = false;
    elements.video.pause();
    elements.video.removeAttribute("src");
    elements.resultImage.removeAttribute("src");
    elements.resultVideo.pause();
    elements.resultVideo.removeAttribute("src");
    state.asset = null;
    state.resultAsset = null;
    state.forwardAsset = null;
    state.extendedAsset = null;
    state.forwardResultTitle = "";
    state.forwardResultMeta = "";
    state.loopExtended = false;
    elements.linkInput.value = "";
    restoreImporter();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function updateFrameEditorSummary() {
    if (!state.frameSequence) return;
    const totalTicks = state.frameItems.reduce((sum, frame) => sum + frame.hold, 0);
    const duration = totalTicks / state.frameSequence.fps;
    const stale = state.frameSignature !== currentFrameSignature();
    const format = elements.outputFormat.value;
    const supported = format === "gif" || format === "webm";
    const formatName = format === "gif" ? "GIF" : format === "webm" ? "WebM" : "GIF or WebM";
    elements.frameEditorSummary.textContent =
      `${state.frameItems.length} frame cards · ` +
      `${totalTicks} hold ticks · ${duration.toFixed(2)}s at ${state.frameSequence.fps} FPS.`;
    elements.frameEditorStatus.className = `frame-editor-status${stale || !supported ? " stale" : ""}`;
    if (stale) {
      elements.frameEditorStatus.textContent = "Crop, timing, resolution, or FPS changed. Build the frame list again before compiling.";
    } else if (!supported) {
      elements.frameEditorStatus.textContent = "Choose GIF or WebM in Export settings to compile edited frames.";
    } else {
      elements.frameEditorStatus.textContent =
        "Drag cards into any order, duplicate or delete any card, and adjust its Hold ticks.";
    }
    elements.exportFramesButton.textContent = `Compile edited ${formatName}`;
    elements.exportFramesButton.disabled = state.frameEditorBusy || stale || !supported || !state.frameItems.length;
    elements.resetFramesButton.disabled = state.frameEditorBusy;
  }

  function createFrameItem(frame) {
    state.frameInstanceSerial += 1;
    const hold = Math.max(1, Math.min(300, Math.round(Number(frame.hold) || 1)));
    return { ...frame, hold, instanceId: `frame-item-${state.frameInstanceSerial}` };
  }

  function renderFrameGrid() {
    const fragment = document.createDocumentFragment();
    state.frameItems.forEach((frame, index) => {
      const card = document.createElement("article");
      card.className = "frame-card";
      card.draggable = true;
      card.dataset.frameId = frame.instanceId;
      card.setAttribute("aria-label", `Frame ${index + 1}. Drag to reorder.`);

      const thumbnail = document.createElement("div");
      thumbnail.className = "frame-thumb";
      const image = document.createElement("img");
      image.src = frame.url;
      image.alt = `Frame ${index + 1}`;
      image.loading = "lazy";
      image.decoding = "async";
      const number = document.createElement("span");
      number.className = "frame-number";
      number.textContent = String(index + 1);
      const actions = document.createElement("div");
      actions.className = "frame-thumb-actions";
      const duplicate = document.createElement("button");
      duplicate.className = "duplicate-frame-button";
      duplicate.type = "button";
      duplicate.dataset.duplicateFrame = frame.instanceId;
      duplicate.setAttribute("aria-label", `Duplicate frame ${index + 1}`);
      duplicate.title = "Duplicate frame";
      duplicate.textContent = "⧉";
      const remove = document.createElement("button");
      remove.className = "delete-frame-button";
      remove.type = "button";
      remove.dataset.deleteFrame = frame.instanceId;
      remove.setAttribute("aria-label", `Delete frame ${index + 1}`);
      remove.title = "Delete frame";
      remove.textContent = "×";
      actions.append(duplicate, remove);
      thumbnail.append(image, number, actions);

      const controls = document.createElement("div");
      controls.className = "frame-controls";
      const label = document.createElement("label");
      label.textContent = "Hold";
      const holdWrap = document.createElement("span");
      holdWrap.className = "frame-hold-wrap";
      const hold = document.createElement("input");
      hold.className = "frame-hold";
      hold.type = "number";
      hold.min = "1";
      hold.max = "300";
      hold.step = "1";
      hold.value = String(frame.hold);
      hold.dataset.holdFrame = frame.instanceId;
      hold.setAttribute("aria-label", `Hold ticks for frame ${index + 1}`);
      const ticks = document.createElement("i");
      ticks.textContent = frame.hold === 1 ? "tick" : "ticks";
      holdWrap.append(hold, ticks);
      label.append(holdWrap);
      const dragHandle = document.createElement("span");
      dragHandle.className = "frame-drag-handle";
      dragHandle.title = "Drag to reorder";
      dragHandle.textContent = "⠿";
      controls.append(label, dragHandle);
      card.append(thumbnail, controls);
      fragment.append(card);
    });
    elements.frameGrid.replaceChildren(fragment);
    updateFrameEditorSummary();
  }

  async function openFrameEditor() {
    if (!state.asset || state.frameEditorBusy) return;
    if (!requireCompleteMotionCrop()) return;
    if (!["gif", "webm"].includes(elements.outputFormat.value)) {
      showToast("Choose GIF or WebM before opening the frame editor.");
      return;
    }
    const estimatedFrames = Math.ceil(finalOutputDuration() * Number(elements.fpsSelect.value));
    if (estimatedFrames > 900) {
      showToast("The frame editor supports up to 900 frames. Shorten the duration or lower the FPS.");
      return;
    }
    const requestSignature = currentFrameSignature();
    state.frameEditorBusy = true;
    elements.frameEditorPanel.hidden = false;
    elements.frameGrid.replaceChildren();
    elements.frameEditorStatus.className = "frame-editor-status loading";
    elements.frameEditorStatus.textContent = `Extracting about ${Math.max(1, estimatedFrames)} local frames…`;
    elements.openFrameEditorButton.disabled = true;
    elements.openFrameEditorButton.textContent = "Building frames…";
    elements.exportFramesButton.disabled = true;
    elements.resetFramesButton.disabled = true;
    elements.clearCacheButton.disabled = true;
    elements.frameEditorPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    try {
      const data = await api("/api/frame-sequences", {
        method: "POST",
        body: JSON.stringify(sourceEditPayload())
      });
      state.frameSequence = data.sequence;
      state.frameItems = data.sequence.frames.map(createFrameItem);
      state.originalFrameItems = state.frameItems.map((frame) => ({ ...frame }));
      state.frameSignature = requestSignature;
      renderFrameGrid();
      showToast(`Loaded ${state.frameItems.length} frames into the local editor.`, "success");
    } catch (error) {
      state.frameSequence = null;
      state.frameItems = [];
      state.originalFrameItems = [];
      state.frameSignature = "";
      elements.frameEditorStatus.className = "frame-editor-status stale";
      elements.frameEditorStatus.textContent = error.message;
      showToast(error.message);
    } finally {
      state.frameEditorBusy = false;
      elements.openFrameEditorButton.disabled = false;
      elements.openFrameEditorButton.textContent = state.frameSequence ? "Rebuild frames" : "View all frames";
      elements.clearCacheButton.disabled = false;
      updateFrameEditorSummary();
    }
  }

  function resetEditedFrames() {
    if (!state.frameSequence || state.frameEditorBusy) return;
    state.frameItems = state.originalFrameItems.map((frame) => ({ ...frame }));
    renderFrameGrid();
  }

  async function exportEditedFrames() {
    if (!state.frameSequence || state.frameEditorBusy) return;
    if (state.frameSignature !== currentFrameSignature()) {
      showToast("Build the frame list again after changing crop, timing, resolution, or FPS.");
      return;
    }
    const format = elements.outputFormat.value;
    if (!["gif", "webm"].includes(format)) {
      showToast("The frame editor can compile only GIF or WebM.");
      return;
    }
    const sizeCap = selectedSizeCap();
    if (sizeCap !== null && (!Number.isInteger(sizeCap) || sizeCap < 16 || sizeCap > 1048576)) {
      showToast("Choose a file-size cap between 16 KB and 1 GB.");
      return;
    }
    const formatName = format === "gif" ? "GIF" : "WebM";
    state.frameEditorBusy = true;
    elements.clearCacheButton.disabled = true;
    elements.openFrameEditorButton.disabled = true;
    elements.exportFramesButton.disabled = true;
    elements.exportFramesButton.textContent = sizeCap ? "Compressing edited frames…" : "Compiling edited frames…";
    try {
      const payload = {
        ...frameExportSettingsPayload(),
        frames: state.frameItems.map((frame) => ({ id: frame.id, hold: frame.hold }))
      };
      const data = await api(`/api/frame-sequences/${state.frameSequence.id}/export`, {
        method: "POST",
        body: JSON.stringify(payload)
      });
      const result = data.asset;
      displayResultMedia(result);
      state.forwardAsset = result;
      state.extendedAsset = null;
      state.loopExtended = false;
      elements.extendLoopButton.hidden = false;
      elements.extendLoopButton.disabled = false;
      elements.extendLoopButton.innerHTML = "<span>↔</span> Extend into complete loop";
      state.forwardResultTitle = `Your frame-edited ${formatName} is finished.`;
      state.forwardResultMeta = `${result.width} × ${result.height} · ${result.duration.toFixed(2)}s · ${state.frameItems.length} arranged frames · ${readableBytes(result.size) || "ready to download"}${sizeCap ? ` · ${sizeCap} KB cap` : ""}`;
      elements.resultTitle.textContent = state.forwardResultTitle;
      elements.resultMeta.textContent = state.forwardResultMeta;
      elements.editor.hidden = true;
      elements.result.hidden = false;
      elements.result.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      showToast(error.message);
    } finally {
      state.frameEditorBusy = false;
      elements.clearCacheButton.disabled = false;
      elements.openFrameEditorButton.disabled = false;
      elements.openFrameEditorButton.textContent = "Rebuild frames";
      updateFrameEditorSummary();
    }
  }

  async function exportAnimation() {
    if (!state.asset) return;
    if (!requireCompleteMotionCrop()) return;
    const sizeCap = selectedSizeCap();
    if (sizeCap !== null && (!Number.isInteger(sizeCap) || sizeCap < 16 || sizeCap > 1048576)) {
      showToast("Choose a file-size cap between 16 KB and 1 GB.");
      return;
    }
    const payload = { ...sourceEditPayload(), ...frameExportSettingsPayload() };
    const formatName = { gif: "GIF", webp: "WebP", webm: "WebM" }[elements.outputFormat.value];
    elements.exportButton.disabled = true;
    elements.clearCacheButton.disabled = true;
    elements.exportButtonLabel.textContent = sizeCap ? "Compressing to fit…" : "Creating locally…";
    elements.exportButtonIcon.textContent = "◌";
    try {
      const data = await api("/api/export", { method: "POST", body: JSON.stringify(payload) });
      const result = data.asset;
      displayResultMedia(result);
      state.forwardAsset = result;
      state.extendedAsset = null;
      state.loopExtended = false;
      const extendable = ["gif", "webm"].includes(elements.outputFormat.value);
      elements.extendLoopButton.hidden = !extendable;
      elements.extendLoopButton.disabled = false;
      elements.extendLoopButton.innerHTML = "<span>↔</span> Extend into complete loop";
      state.forwardResultTitle = `Your ${formatName} is finished.`;
      state.forwardResultMeta = `${result.width} × ${result.height} · ${result.duration.toFixed(2)}s · ${readableBytes(result.size) || "ready to download"}${sizeCap ? ` · ${sizeCap} KB cap` : ""}`;
      elements.resultTitle.textContent = state.forwardResultTitle;
      elements.resultMeta.textContent = state.forwardResultMeta;
      elements.editor.hidden = true;
      elements.result.hidden = false;
      elements.result.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      showToast(error.message);
    } finally {
      elements.exportButton.disabled = false;
      elements.clearCacheButton.disabled = false;
      elements.exportButtonLabel.textContent = `Create ${formatName}`;
      elements.exportButtonIcon.textContent = "→";
    }
  }

  function displayResultMedia(result) {
    state.resultAsset = result;
    const sourceUrl = `${result.media_url}?v=${Date.now()}`;
    const isVideo = result.mime === "video/webm";
    elements.resultImage.hidden = isVideo;
    elements.resultVideo.hidden = !isVideo;
    if (isVideo) {
      elements.resultImage.removeAttribute("src");
      elements.resultVideo.src = sourceUrl;
      elements.resultVideo.play().catch(() => {});
    } else {
      elements.resultVideo.pause();
      elements.resultVideo.removeAttribute("src");
      elements.resultImage.src = sourceUrl;
    }
    const formatName = isVideo ? "WebM" : result.mime === "image/gif" ? "GIF" : "WebP";
    elements.downloadButton.href = result.download_url;
    elements.downloadLabel.textContent = `Download ${formatName}`;
  }

  async function extendCompleteLoop() {
    if (state.loopExtended && state.forwardAsset) {
      displayResultMedia(state.forwardAsset);
      state.loopExtended = false;
      elements.resultTitle.textContent = state.forwardResultTitle;
      elements.resultMeta.textContent = state.forwardResultMeta;
      elements.extendLoopButton.innerHTML = "<span>↔</span> Extend into complete loop";
      elements.extendLoopButton.disabled = false;
      return;
    }
    if (state.extendedAsset) {
      displayExtendedLoop(state.extendedAsset);
      return;
    }
    const originalAsset = state.forwardAsset || state.resultAsset;
    if (!originalAsset) return;
    elements.extendLoopButton.disabled = true;
    elements.clearCacheButton.disabled = true;
    elements.extendLoopButton.textContent = "Extending forward + reverse…";
    try {
      const data = await api("/api/extend", {
        method: "POST",
        body: JSON.stringify({ media_id: originalAsset.id })
      });
      const result = data.asset;
      state.extendedAsset = result;
      displayExtendedLoop(result);
    } catch (error) {
      state.resultAsset = originalAsset;
      elements.extendLoopButton.innerHTML = "<span>↔</span> Extend into complete loop";
      elements.extendLoopButton.disabled = false;
      elements.clearCacheButton.disabled = false;
      showToast(error.message);
    }
  }

  function displayExtendedLoop(result) {
    displayResultMedia(result);
    state.loopExtended = true;
    elements.resultTitle.textContent = "Your complete loop is finished.";
    elements.resultMeta.textContent = `${result.width} × ${result.height} · ${result.duration.toFixed(2)}s · ${readableBytes(result.size) || "ready to download"} · forward + reverse · turnaround deduplicated`;
    elements.extendLoopButton.innerHTML = "<span>↶</span> Revert to forward only";
    elements.extendLoopButton.disabled = false;
    elements.clearCacheButton.disabled = false;
  }

  async function clearLocalCache() {
    const confirmed = window.confirm(
      "Clear every imported file, preview, export, and temporary GIFmakerAthome file from this session?"
    );
    if (!confirmed) return;
    elements.clearCacheButton.disabled = true;
    elements.clearCacheButton.textContent = "Clearing…";
    elements.video.pause();
    elements.video.removeAttribute("src");
    elements.video.load();
    elements.image.removeAttribute("src");
    elements.resultImage.removeAttribute("src");
    elements.resultVideo.pause();
    elements.resultVideo.removeAttribute("src");
    elements.resultVideo.load();
    elements.frameGrid.querySelectorAll("img").forEach((image) => image.removeAttribute("src"));
    resetFrameEditor();
    try {
      await new Promise((resolve) => window.setTimeout(resolve, 120));
      const data = await api("/api/clear", { method: "POST" });
      resetToImport();
      const files = Number(data.cleared?.files || 0);
      const bytes = Number(data.cleared?.bytes || 0);
      showToast(
        files ? `Cleared ${files} local file${files === 1 ? "" : "s"} (${readableBytes(bytes)}).` : "The local cache is already empty.",
        "success"
      );
    } catch (error) {
      showToast(error.message);
    } finally {
      elements.clearCacheButton.innerHTML = "<span>⌫</span> Clear cache";
      elements.clearCacheButton.disabled = false;
    }
  }

  function stopPreviewCut() {
    elements.video.pause();
    state.previewing = false;
    elements.previewSelectionButton.textContent = "▶ Preview cut";
    restoreMotionCropEditor();
  }

  function previewCut() {
    if (!state.asset) return;
    if (state.asset.kind !== "video") {
      showToast("Animated image previews keep looping; the chosen times are applied during export.");
      return;
    }
    if (state.previewing) {
      stopPreviewCut();
      return;
    }
    const { start, end } = selectedTimes();
    state.previewing = true;
    state.discardJumped = false;
    let previewStart = state.motionCropEnabled
      ? motionCropSourceTime(state.motionCropTimings[0])
      : isDiscardMode() ? 0 : start;
    if (isDiscardMode() && previewStart >= start) {
      if (previewStart < end) previewStart = end;
      state.discardJumped = true;
    }
    elements.video.currentTime = previewStart;
    elements.previewSelectionButton.textContent = "■ Stop preview";
    updateMotionCropPreview();
    elements.video.play().catch(() => {
      stopPreviewCut();
    });
    if (!state.motionCropEnabled && isDiscardMode() && start <= minimumGap()) {
      elements.video.currentTime = end;
      state.discardJumped = true;
    }
  }

  for (const eventName of ["loadedmetadata", "seeking", "seeked", "timeupdate"]) {
    elements.video.addEventListener(eventName, () => {
      updatePreviewTimestamp();
    });
  }

  elements.video.addEventListener("timeupdate", () => {
    if (!state.previewing || !state.asset) return;
    updateMotionCropPreview();
    const { start, end } = selectedTimes();
    const lastMotionTiming = state.motionCropTimings[state.motionCropTimings.length - 1];
    const finish = state.motionCropEnabled
      ? motionCropSourceTime(lastMotionTiming)
      : isDiscardMode() ? state.asset.duration : end;
    if (elements.video.currentTime >= finish - 0.015) {
      stopPreviewCut();
      return;
    }
    if (isDiscardMode() && !state.discardJumped && elements.video.currentTime >= start) {
      state.discardJumped = true;
      elements.video.currentTime = end;
      return;
    }
  });

  elements.video.addEventListener("error", () => { void createFallbackPreview(); });
  elements.toastClose.addEventListener("click", hideToast);
  document.querySelectorAll(".source-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".source-tab").forEach((other) => {
        const active = other === tab;
        other.classList.toggle("active", active);
        other.setAttribute("aria-selected", String(active));
      });
      const linkActive = tab.dataset.tab === "link";
      $("fileTab").hidden = linkActive;
      $("linkTab").hidden = !linkActive;
      $("fileTab").classList.toggle("active", !linkActive);
      $("linkTab").classList.toggle("active", linkActive);
      if (linkActive) elements.linkInput.focus();
    });
  });

  elements.dropZone.addEventListener("click", () => elements.fileInput.click());
  elements.fileInput.addEventListener("change", () => uploadFile(elements.fileInput.files[0]));
  for (const eventName of ["dragenter", "dragover"]) {
    elements.dropZone.addEventListener(eventName, (event) => { event.preventDefault(); elements.dropZone.classList.add("dragging"); });
  }
  for (const eventName of ["dragleave", "drop"]) {
    elements.dropZone.addEventListener(eventName, (event) => { event.preventDefault(); elements.dropZone.classList.remove("dragging"); });
  }
  elements.dropZone.addEventListener("drop", (event) => uploadFile(event.dataTransfer.files[0]));
  elements.importLinkButton.addEventListener("click", importLink);
  elements.linkInput.addEventListener("keydown", (event) => { if (event.key === "Enter") importLink(); });

  window.addEventListener("pagehide", () => {
    const body = JSON.stringify({ session_id: browserSessionId, token });
    const queued = navigator.sendBeacon(
      "/api/browser-session/close",
      new Blob([body], { type: "application/json" })
    );
    if (!queued) {
      fetch("/api/browser-session/close", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-GIFmakerAthome-Token": token },
        body,
        keepalive: true
      }).catch(() => {});
    }
  });

  elements.startRange.addEventListener("input", () => setTimes(elements.startRange.value, elements.endRange.value, "start"));
  elements.endRange.addEventListener("input", () => setTimes(elements.startRange.value, elements.endRange.value, "end"));
  elements.startNumber.addEventListener("change", () => setTimes(elements.startNumber.value, elements.endRange.value, "start"));
  elements.endNumber.addEventListener("change", () => setTimes(elements.startRange.value, elements.endNumber.value, "end"));
  document.querySelectorAll('input[name="cutMode"]').forEach((input) => input.addEventListener("change", updateTimeline));
  elements.previewSelectionButton.addEventListener("click", previewCut);
  elements.openFrameEditorButton.addEventListener("click", openFrameEditor);
  elements.closeFrameEditorButton.addEventListener("click", () => { elements.frameEditorPanel.hidden = true; });
  elements.resetFramesButton.addEventListener("click", resetEditedFrames);
  elements.exportFramesButton.addEventListener("click", exportEditedFrames);

  elements.frameGrid.addEventListener("click", (event) => {
    const duplicate = event.target.closest("[data-duplicate-frame]");
    if (duplicate && !state.frameEditorBusy) {
      if (state.frameItems.length >= MAX_FRAME_EDITOR_CARDS) {
        showToast(`The frame editor supports up to ${MAX_FRAME_EDITOR_CARDS} frame cards.`);
        return;
      }
      const index = state.frameItems.findIndex(
        (frame) => frame.instanceId === duplicate.dataset.duplicateFrame
      );
      if (index < 0) return;
      state.frameItems.splice(index + 1, 0, createFrameItem(state.frameItems[index]));
      renderFrameGrid();
      return;
    }
    const button = event.target.closest("[data-delete-frame]");
    if (!button || state.frameEditorBusy) return;
    if (state.frameItems.length <= 1) {
      showToast("Keep at least one frame in the animation.");
      return;
    }
    state.frameItems = state.frameItems.filter(
      (frame) => frame.instanceId !== button.dataset.deleteFrame
    );
    renderFrameGrid();
  });

  elements.frameGrid.addEventListener("input", (event) => {
    const input = event.target.closest("[data-hold-frame]");
    if (!input || state.frameEditorBusy) return;
    const frame = state.frameItems.find((item) => item.instanceId === input.dataset.holdFrame);
    const hold = Math.max(1, Math.min(300, Math.round(Number(input.value) || 1)));
    if (!frame) return;
    frame.hold = hold;
    input.value = String(hold);
    const unit = input.parentElement.querySelector("i");
    if (unit) unit.textContent = hold === 1 ? "tick" : "ticks";
    updateFrameEditorSummary();
  });

  elements.frameGrid.addEventListener("dragstart", (event) => {
    const card = event.target.closest(".frame-card");
    if (!card || state.frameEditorBusy) { event.preventDefault(); return; }
    state.draggedFrameId = card.dataset.frameId;
    card.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", state.draggedFrameId);
  });

  elements.frameGrid.addEventListener("dragover", (event) => {
    if (!state.draggedFrameId) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    elements.frameGrid.querySelectorAll(".drag-target").forEach((card) => card.classList.remove("drag-target"));
    const target = event.target.closest(".frame-card");
    if (target && target.dataset.frameId !== state.draggedFrameId) target.classList.add("drag-target");
  });

  elements.frameGrid.addEventListener("drop", (event) => {
    if (!state.draggedFrameId) return;
    event.preventDefault();
    const target = event.target.closest(".frame-card");
    const fromIndex = state.frameItems.findIndex((frame) => frame.instanceId === state.draggedFrameId);
    if (fromIndex < 0) return;
    const [moved] = state.frameItems.splice(fromIndex, 1);
    if (!target || target.dataset.frameId === moved.instanceId) {
      state.frameItems.push(moved);
    } else {
      const rect = target.getBoundingClientRect();
      const sameRow = event.clientY >= rect.top && event.clientY <= rect.bottom;
      const after = event.clientY > rect.top + rect.height / 2 ||
        (sameRow && event.clientX > rect.left + rect.width / 2);
      const targetIndex = state.frameItems.findIndex(
        (frame) => frame.instanceId === target.dataset.frameId
      );
      state.frameItems.splice(Math.max(0, targetIndex + (after ? 1 : 0)), 0, moved);
    }
    state.draggedFrameId = null;
    renderFrameGrid();
  });

  elements.frameGrid.addEventListener("dragend", () => {
    state.draggedFrameId = null;
    elements.frameGrid.querySelectorAll(".dragging, .drag-target").forEach((card) => {
      card.classList.remove("dragging", "drag-target");
    });
  });

  document.querySelectorAll("[data-aspect]").forEach((button) => {
    button.addEventListener("click", () => applyCropAspect(button.dataset.aspect));
  });
  elements.motionCropEnabled.addEventListener("change", () => {
    setMotionCropEnabled(elements.motionCropEnabled.checked);
  });
  elements.motionCropKeyframes.addEventListener("click", (event) => {
    const button = event.target.closest("[data-motion-crop-index]");
    if (button) selectMotionCropKeyframe(Number(button.dataset.motionCropIndex));
  });
  elements.motionTimelineMarkers.addEventListener("click", (event) => {
    const marker = event.target.closest("[data-motion-crop-index]");
    if (marker) selectMotionCropKeyframe(Number(marker.dataset.motionCropIndex));
  });
  elements.motionTimelineMarkers.addEventListener("pointerdown", (event) => {
    const marker = event.target.closest("[data-motion-crop-index]");
    if (!marker || event.button !== 0) return;
    const index = Number(marker.dataset.motionCropIndex);
    if (index !== state.motionCropIndex) return;
    event.preventDefault();
    if (state.previewing) stopPreviewCut();
    state.motionTimelineDrag = { pointerId: event.pointerId, index };
    elements.motionTimelineMarkers.setPointerCapture(event.pointerId);
    setMotionCropTimingFromPointer(event);
  });
  elements.motionTimelineMarkers.addEventListener("pointermove", (event) => {
    setMotionCropTimingFromPointer(event);
  });
  elements.motionTimelineMarkers.addEventListener("pointerup", finishMotionTimelineDrag);
  elements.motionTimelineMarkers.addEventListener("pointercancel", finishMotionTimelineDrag);
  elements.addMotionCropKeyframe.addEventListener("click", addMotionCropKeyframe);
  elements.removeMotionCropKeyframe.addEventListener("click", removeMotionCropKeyframe);
  elements.motionCropTiming.addEventListener("change", () => {
    setMotionCropTiming(elements.motionCropTiming.value);
  });
  elements.cropBox.addEventListener("pointerdown", onCropPointerDown);
  elements.cropBox.addEventListener("pointermove", onCropPointerMove);
  elements.cropBox.addEventListener("pointerup", finishCropPointer);
  elements.cropBox.addEventListener("pointercancel", finishCropPointer);

  elements.outputFormat.addEventListener("change", updateFormatControls);
  elements.sizeLimitSelect.addEventListener("change", updateSizeLimitControls);
  elements.customSizeLimit.addEventListener("input", updateOutputSummary);
  elements.resolutionSelect.addEventListener("change", () => {
    if (elements.resolutionSelect.value === "512square") applyCropAspect("1");
    else syncResolutionFromCrop();
  });
  elements.dimensionLock.addEventListener("click", () => {
    state.dimensionLocked = !state.dimensionLocked;
    elements.dimensionLock.classList.toggle("active", state.dimensionLocked);
    elements.dimensionLock.setAttribute("aria-pressed", String(state.dimensionLocked));
    if (state.dimensionLocked) syncResolutionFromCrop();
  });
  elements.outputWidth.addEventListener("input", () => {
    if (elements.resolutionSelect.value !== "custom") elements.resolutionSelect.value = "custom";
    if (state.dimensionLocked && state.asset) {
      const crop = outputReferenceCropPixels();
      elements.outputHeight.value = Math.max(1, Math.round(Number(elements.outputWidth.value || 1) * crop.h / crop.w));
    }
    updateOutputSummary();
  });
  elements.outputHeight.addEventListener("input", () => {
    if (elements.resolutionSelect.value !== "custom") elements.resolutionSelect.value = "custom";
    if (state.dimensionLocked && state.asset) {
      const crop = outputReferenceCropPixels();
      elements.outputWidth.value = Math.max(1, Math.round(Number(elements.outputHeight.value || 1) * crop.w / crop.h));
    }
    updateOutputSummary();
  });
  elements.fpsSelect.addEventListener("change", updateOutputSummary);
  elements.colorsSelect.addEventListener("change", updateOutputSummary);
  elements.qualitySelect.addEventListener("change", updateOutputSummary);
  gifTechniqueInputs().forEach((input) => input.addEventListener("change", updateOutputSummary));
  elements.exportButton.addEventListener("click", exportAnimation);
  elements.extendLoopButton.addEventListener("click", extendCompleteLoop);
  elements.clearCacheButton.addEventListener("click", clearLocalCache);
  elements.replaceButton.addEventListener("click", resetToImport);
  elements.startOverButton.addEventListener("click", resetToImport);
  elements.editAgainButton.addEventListener("click", () => {
    elements.resultVideo.pause();
    elements.result.hidden = true;
    elements.editor.hidden = false;
    elements.editor.scrollIntoView({ behavior: "smooth", block: "start" });
  });
})();
