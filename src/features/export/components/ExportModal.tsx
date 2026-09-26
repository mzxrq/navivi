import { useState, useMemo, useEffect } from "react";
import { createPortal } from "react-dom";
import { invoke } from "@tauri-apps/api/core";
import {
  X,
  Monitor,
  Smartphone,
  Film,
  Download,
  FileCode,
  Loader2,
  CheckCircle,
  Sliders,
  Clock,
  HardDrive,
  Layers,
  Volume2,
} from "lucide-react";
import {
  AspectRatioType,
  TimelineData,
  ProjectMetadata,
  ProjectSettings,
  Waypoint,
  RenderSettings,
} from "../../../types/index";
import {
  saveTimelineManifest,
  compileTimelineManifest,
} from "../../../services/fileSystem";
import { useUI } from "../../../hooks/useUI";
import { t } from "@lingui/core/macro"; import { Trans } from "@lingui/react/macro";

export interface ExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  timeline: TimelineData;
  metadata?: ProjectMetadata;
  waypoints?: Waypoint[];
  settings?: ProjectSettings;
  duration?: number;
  onExportSuccess?: () => void;
}

type ResolutionTier = "4k" | "1080p" | "720p";
type BitratePresetTier = "high" | "standard" | "draft";

interface ResolutionOption {
  id: ResolutionTier;
  label: string;
  tag: string;
  landscape: { width: number; height: number };
  portrait: { width: number; height: number };
}

const RESOLUTION_OPTIONS: ResolutionOption[] = [
  {
    id: "4k",
    label: "4K",
    tag: "UHD",
    landscape: { width: 3840, height: 2160 },
    portrait: { width: 2160, height: 3840 },
  },
  {
    id: "1080p",
    label: "1080p",
    tag: "FHD",
    landscape: { width: 1920, height: 1080 },
    portrait: { width: 1080, height: 1920 },
  },
  {
    id: "720p",
    label: "720p",
    tag: "HD",
    landscape: { width: 1280, height: 720 },
    portrait: { width: 720, height: 1280 },
  },
];

interface BitratePreset {
  id: BitratePresetTier;
  label: string;
  description: string;
  rates: {
    "4k": number; // Kbps
    "1080p": number; // Kbps
    "720p": number; // Kbps
  };
}

const getBitratePresets = (): BitratePreset[] => [
  {
    id: "high",
    label: t`High Quality`,
    description:
      t`Maximum quality for archival and master presentation (50 Mbps 4K / 20 Mbps 1080p)`,
    rates: {
      "4k": 50000,
      "1080p": 20000,
      "720p": 10000,
    },
  },
  {
    id: "standard",
    label: t`Balanced / Standard`,
    description:
      t`Optimal balance between quality and file size for web & YouTube (25 Mbps 4K / 10 Mbps 1080p)`,
    rates: {
      "4k": 25000,
      "1080p": 10000,
      "720p": 5000,
    },
  },
  {
    id: "draft",
    label: t`Fast`,
    description:
      t`Fastest export with compact file size for quick previews (12 Mbps 4K / 5 Mbps 1080p)`,
    rates: {
      "4k": 12000,
      "1080p": 5000,
      "720p": 2500,
    },
  },
];

interface FramerateOption {
  fps: number;
  label: string;
  description: string;
}

const getFramerateOptions = (): FramerateOption[] => [
  { fps: 60, label: "60 fps", description: t`Smooth / Action` },
  { fps: 30, label: "30 fps", description: t`Standard Web Video` },
  { fps: 24, label: "24 fps", description: t`Cinematic` },
];

export function ExportModal({
  isOpen,
  onClose,
  timeline,
  metadata,
  waypoints,
  settings,
  duration,
  onExportSuccess,
}: ExportModalProps) {
  const { showToast } = useUI();

  const initialAspectRatio: AspectRatioType = "16:9";

  const initialResolution: ResolutionTier = "1080p";

  const initialFps = settings?.fps === 60 ? 60 : settings?.fps === 24 ? 24 : 30;

  const [aspectRatio, setAspectRatio] =
    useState<AspectRatioType>(initialAspectRatio);
  const [resolutionTier, setResolutionTier] =
    useState<ResolutionTier>(initialResolution);
  const [fps, setFps] = useState<number>(initialFps);
  const [bitrateTier, setBitrateTier] = useState<BitratePresetTier>("standard");
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [exportStep, setExportStep] = useState<string>("");

  // Sync settings if modal opens afresh
  useEffect(() => {
    if (isOpen) {
      setAspectRatio("16:9");
      setResolutionTier("1080p");

      if (settings?.fps && [24, 30, 60].includes(settings.fps)) {
        setFps(settings.fps);
      }
    }
  }, [isOpen, settings]);

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen && !isExporting) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, isExporting, onClose]);

  // Resolved dimensions
  const activeResolutionOption = useMemo(
    () =>
      RESOLUTION_OPTIONS.find((r) => r.id === resolutionTier) ||
      RESOLUTION_OPTIONS[1],
    [resolutionTier],
  );

  const activeDimensions = useMemo(() => {
    return aspectRatio === "16:9"
      ? activeResolutionOption.landscape
      : activeResolutionOption.portrait;
  }, [aspectRatio, activeResolutionOption]);

  const activeBitratePreset = useMemo(
    () =>
      getBitratePresets().find((b) => b.id === bitrateTier) || getBitratePresets()[1],
    [bitrateTier],
  );

  const activeBitrateKbps = activeBitratePreset.rates[resolutionTier];

  // Total timeline duration
  const totalDuration = useMemo(() => {
    if (typeof duration === "number" && duration > 0) return duration;
    return timeline.clips.reduce(
      (max, clip) => Math.max(max, clip.startTime + clip.duration),
      0,
    );
  }, [duration, timeline.clips]);

  // Estimated output file size
  // Formula: estimatedMb = (totalDuration * (bitrateKbps / 8)) / 1024
  const estimatedMb = useMemo(() => {
    return (totalDuration * (activeBitrateKbps / 8)) / 1024;
  }, [totalDuration, activeBitrateKbps]);

  const formattedEstimatedSize = useMemo(() => {
    if (estimatedMb >= 1024) {
      return `${(estimatedMb / 1024).toFixed(2)} GB`;
    }
    return `${Math.max(0.1, estimatedMb).toFixed(1)} MB`;
  }, [estimatedMb]);

  const markers = useMemo(() => {
    if (timeline.markers) return timeline.markers;
    if (!waypoints || waypoints.length === 0) return [];
    let runningTime = 0;
    return waypoints.map((wp, idx) => {
      const legDuration = 5;
      const time =
        wp.timelineOffset !== undefined ? wp.timelineOffset : runningTime;
      runningTime = Math.max(runningTime, time + legDuration);
      return {
        id: wp.id,
        name: wp.name || t`Waypoint ${idx + 1}`,
        time,
        index: idx + 1,
        waypointId: wp.id,
      };
    });
  }, [timeline.markers, waypoints]);

  // Audio mix status
  const audioMixSummary = useMemo(() => {
    const audioTracks = timeline.tracks.filter((t) => t.type === "audio");
    const audioClips = timeline.clips.filter((c) => c.type === "audio");
    const hasDucking =
      audioTracks.some((t) => t.duckingEnabled) ||
      timeline.clips.some((c) => c.ducking);

    return {
      trackCount: audioTracks.length,
      clipCount: audioClips.length,
      hasDucking,
      statusText: hasDucking
        ? t`Auto-Ducking Active`
        : t`Standard Multi-Track Mix`,
    };
  }, [timeline.tracks, timeline.clips]);

  // Output filename preview
  const projectName = metadata?.project_name || t`Navivi_Project`;
  const safeProjectName = projectName.replace(/[^a-zA-Z0-9_-]/g, "_");
  const outputFilename = `${safeProjectName}_${aspectRatio === "9:16" ? "Shorts_9x16" : "Desktop_16x9"}_${resolutionTier}_${fps}fps.mp4`;

  // Render settings object conforming to interface
  const renderSettings: RenderSettings = useMemo(
    () => ({
      aspectRatio,
      resolution: activeDimensions,
      fps,
      bitrateKbps: activeBitrateKbps,
      qualityId: resolutionTier,
      skipRichMedia: settings?.skip_rich_media ?? false,
    }),
    [
      aspectRatio,
      activeDimensions,
      fps,
      activeBitrateKbps,
      resolutionTier,
      settings?.skip_rich_media,
    ],
  );

  // Format time (MM:SS)
  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  // Action: Export Video (Compile & Tauri Invoke)
  const handleExportVideo = async () => {
    const projectDir = metadata?.directory_path;
    if (!projectDir) {
      showToast(
        t`No project directory found. Save your project first.`,
        "error",
      );
      return;
    }

    setIsExporting(true);
    setExportStep(t`Compiling timeline manifest...`);

    try {
      const saved = await saveTimelineManifest(
        projectDir,
        metadata?.project_name || t`Project`,
        timeline,
        renderSettings,
        markers,
      );

      if (!saved) {
        throw new Error(t`Failed to write timeline.json manifest`);
      }

      setExportStep(t`Launching video rendering engine...`);

      // Invoke Tauri export command
      await invoke("export_video", { projectDir });
      showToast(t`Export process initiated successfully!`, "success");
      onExportSuccess?.();
      onClose();
    } catch (err: any) {
      console.error("Export video failed:", err);
      showToast(t`Export failed: ${err?.message || err}`, "error");
    } finally {
      setIsExporting(false);
      setExportStep("");
    }
  };

  const handleExportJsonOnly = async () => {
    try {
      const payload = compileTimelineManifest(
        metadata?.project_name || t`Project`,
        timeline,
        renderSettings,
        markers,
        metadata?.directory_path,
      );

      const jsonString = JSON.stringify(payload, null, 2);

      if (metadata?.directory_path) {
        await saveTimelineManifest(
          metadata.directory_path,
          metadata.project_name || "Project",
          timeline,
          renderSettings,
          markers,
        );
      }

      const blob = new Blob([jsonString], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${safeProjectName}_timeline_manifest.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      showToast(t`Timeline JSON manifest exported successfully!`, "success");
    } catch (err: any) {
      console.error("Failed to export JSON manifest:", err);
      showToast(t`Failed to export JSON: ${err?.message || err}`, "error");
    }
  };

  if (!isOpen) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-99999 flex items-center justify-center bg-black/75 backdrop-blur-md p-4 animate-in fade-in duration-200"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isExporting) {
          onClose();
        }
      }}
    >
      <div className="w-full max-w-2xl max-h-[92vh] flex flex-col bg-zinc-900 border border-zinc-800 rounded-2xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200 text-zinc-100">
        {/* Header */}
        <div className="px-6 py-4 border-b border-zinc-800 bg-zinc-900/90 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-navi/15 text-navi rounded-xl border border-navi/20">
              <Film className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white tracking-wide">
                <Trans>Export & Render Video</Trans>
              </h2>
              <p className="text-xs text-zinc-400">
                <Trans>Configure aspect ratio, quality profiles, and compile timeline manifest</Trans>
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isExporting}
            className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors disabled:opacity-40"
            title={t`Close`}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto custom-scrollbar flex-1 space-y-6 text-sm">
          {/* 1. ASPECT RATIO SELECTOR */}
          <div>
            <div className="flex items-center justify-between mb-2.5">
              <label className="text-xs font-bold uppercase tracking-wider text-zinc-300 flex items-center gap-1.5">
                <Sliders className="w-3.5 h-3.5 text-navi" />
                <span><Trans>Aspect Ratio & Platform Target</Trans></span>
              </label>
              {/* Live aspect ratio badge */}
              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-navi/20 text-navi border border-navi/30 animate-pulse">
                {aspectRatio === "16:9"
                  ? t`16:9 Landscape`
                  : t`9:16 Vertical`}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3">
              {/* 16:9 Landscape Card */}
              <button
                type="button"
                onClick={() => setAspectRatio("16:9")}
                className={`flex flex-col items-start p-4 rounded-xl border transition-all text-left group ${
                  aspectRatio === "16:9"
                    ? "bg-navi/10 border-navi text-white shadow-md ring-1 ring-navi/50"
                    : "bg-zinc-800/60 border-zinc-700/60 text-zinc-300 hover:bg-zinc-800 hover:border-zinc-600"
                }`}
              >
                <div className="flex items-center justify-between w-full mb-2">
                  <div className="p-2 rounded-lg bg-zinc-800 text-navi group-hover:text-navi-400 border border-zinc-700">
                    <Monitor className="w-5 h-5" />
                  </div>
                  <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700">
                    16:9
                  </span>
                </div>
                <div className="font-bold text-sm text-white">
                  <Trans>Desktop & YouTube</Trans>
                </div>
                <div className="text-xs text-zinc-400 mt-0.5">
                  <Trans>Standard widescreen (1920ÁE080)</Trans>
                </div>
              </button>

              {/* 9:16 Portrait Card */}
              <button
                type="button"
                onClick={() => setAspectRatio("9:16")}
                className={`flex flex-col items-start p-4 rounded-xl border transition-all text-left group ${
                  aspectRatio === "9:16"
                    ? "bg-navi/10 border-navi text-white shadow-md ring-1 ring-navi/50"
                    : "bg-zinc-800/60 border-zinc-700/60 text-zinc-300 hover:bg-zinc-800 hover:border-zinc-600"
                }`}
              >
                <div className="flex items-center justify-between w-full mb-2">
                  <div className="p-2 rounded-lg bg-zinc-800 text-navi group-hover:text-navi-400 border border-zinc-700">
                    <Smartphone className="w-5 h-5" />
                  </div>
                  <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700">
                    9:16
                  </span>
                </div>
                <div className="font-bold text-sm text-white">
                  <Trans>Shorts, Reels & TikTok</Trans>
                </div>
                <div className="text-xs text-zinc-400 mt-0.5">
                  <Trans>Vertical portrait format (1080ÁE920)</Trans>
                </div>
              </button>
            </div>
          </div>

          {/* 2. QUALITY PROFILE SELECTOR */}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-zinc-300 mb-2.5">
              <Trans>Resolution & Quality Profile</Trans>
            </label>
            <div className="grid grid-cols-3 gap-2.5">
              {RESOLUTION_OPTIONS.map((opt) => {
                const dims =
                  aspectRatio === "16:9" ? opt.landscape : opt.portrait;
                const isSelected = resolutionTier === opt.id;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setResolutionTier(opt.id)}
                    className={`flex flex-col items-center justify-center p-3 rounded-xl border transition-all text-center ${
                      isSelected
                        ? "bg-navi/15 border-navi text-white shadow-md ring-1 ring-navi/50"
                        : "bg-zinc-800/60 border-zinc-700/60 text-zinc-300 hover:bg-zinc-800 hover:border-zinc-600"
                    }`}
                  >
                    <span className="text-xs font-mono font-bold text-navi mb-1">
                      {opt.tag}
                    </span>
                    <span className="text-sm font-bold text-white">
                      {opt.label}
                    </span>
                    <span className="text-[11px] font-mono text-zinc-400 mt-1">
                      {dims.width} ÁE{dims.height}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* 3. FRAMERATE & BITRATE PRESETS */}
          <div className="grid grid-cols-2 gap-4">
            {/* Framerate */}
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-zinc-300 mb-2">
                <Trans>Framerate (FPS)</Trans>
              </label>
              <div className="space-y-2">
                {getFramerateOptions().map((f) => {
                  const isSelected = fps === f.fps;
                  return (
                    <button
                      key={f.fps}
                      type="button"
                      onClick={() => setFps(f.fps)}
                      className={`w-full flex items-center justify-between px-3 py-2 rounded-lg border text-xs transition-all ${
                        isSelected
                          ? "bg-navi/15 border-navi text-white ring-1 ring-navi/50 font-semibold"
                          : "bg-zinc-800/50 border-zinc-700/60 text-zinc-300 hover:bg-zinc-800"
                      }`}
                    >
                      <span>{f.label}</span>
                      <span className="text-[10px] text-zinc-400">
                        {f.description}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Bitrate Preset */}
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-zinc-300 mb-2">
                <Trans>Bitrate Preset</Trans>
              </label>
              <div className="space-y-2">
                {getBitratePresets().map((b) => {
                  const isSelected = bitrateTier === b.id;
                  const rateKbps = b.rates[resolutionTier];
                  const rateMbps = (rateKbps / 1000).toFixed(0);
                  return (
                    <button
                      key={b.id}
                      type="button"
                      onClick={() => setBitrateTier(b.id)}
                      className={`w-full flex items-center justify-between px-3 py-2 rounded-lg border text-xs transition-all ${
                        isSelected
                          ? "bg-navi/15 border-navi text-white ring-1 ring-navi/50 font-semibold"
                          : "bg-zinc-800/50 border-zinc-700/60 text-zinc-300 hover:bg-zinc-800"
                      }`}
                    >
                      <div className="text-left">
                        <div>{b.label}</div>
                      </div>
                      <span className="font-mono text-navi text-[11px] font-bold">
                        {rateMbps} Mbps
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* 4. SUMMARY & ESTIMATED OUTPUT CARD */}
          <div className="bg-zinc-950/70 border border-zinc-800 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2">
              <div className="flex items-center gap-2 text-xs font-bold text-zinc-300 uppercase tracking-wide">
                <HardDrive className="w-3.5 h-3.5 text-navi" />
                <span><Trans>Export Summary</Trans></span>
              </div>
              <div className="flex items-center gap-1 text-xs text-navi font-bold">
                <CheckCircle className="w-3.5 h-3.5" />
                <span><Trans>Ready to Compile</Trans></span>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
              <div className="bg-zinc-900/80 p-2.5 rounded-lg border border-zinc-800/60">
                <span className="text-[10px] text-zinc-400 mb-0.5 flex items-center gap-1">
                  <Clock className="w-3 h-3 text-zinc-400" />
                  <Trans>Timeline Duration</Trans>
                </span>
                <span className="font-mono font-bold text-white text-sm">
                  {formatTime(totalDuration)}
                </span>
              </div>

              <div className="bg-zinc-900/80 p-2.5 rounded-lg border border-zinc-800/60">
                <span className="text-[10px] text-zinc-400 mb-0.5 flex items-center gap-1">
                  <Layers className="w-3 h-3 text-zinc-400" />
                  <Trans>Target Canvas</Trans>
                </span>
                <span className="font-mono font-bold text-white text-sm">
                  {activeDimensions.width}×{activeDimensions.height}
                </span>
              </div>

              <div className="bg-zinc-900/80 p-2.5 rounded-lg border border-zinc-800/60">
                <span className="text-[10px] text-zinc-400 mb-0.5 flex items-center gap-1">
                  <Volume2 className="w-3 h-3 text-zinc-400" />
                  <Trans>Audio Mix</Trans>
                </span>
                <span
                  className="font-semibold text-zinc-200 text-xs truncate block"
                  title={audioMixSummary.statusText}
                >
                  {audioMixSummary.statusText}
                </span>
              </div>

              <div className="bg-zinc-900/80 p-2.5 rounded-lg border border-zinc-800/60">
                <span className="text-[10px] text-zinc-400 mb-0.5 flex items-center gap-1">
                  <HardDrive className="w-3 h-3 text-zinc-400" />
                  <Trans>Est. File Size</Trans>
                </span>
                <span className="font-mono font-bold text-emerald-400 text-sm">
                  ~{formattedEstimatedSize}
                </span>
              </div>
            </div>

            {/* Output filename preview */}
            <div className="text-[11px] text-zinc-400 flex items-center gap-2 pt-1 font-mono break-all bg-zinc-900/50 px-3 py-1.5 rounded-md border border-zinc-800/50">
              <span className="text-zinc-400 shrink-0 font-sans font-semibold">
                <Trans>Output File:</Trans>
              </span>
              <span className="text-zinc-200 truncate">{outputFilename}</span>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="px-6 py-4 border-t border-zinc-800 bg-zinc-900/90 flex flex-col sm:flex-row items-center justify-between shrink-0 gap-3">
          {/* JSON Manifest button */}
          <button
            type="button"
            onClick={handleExportJsonOnly}
            disabled={isExporting}
            className="w-full sm:w-auto px-4 py-2 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-200 text-xs font-semibold rounded-xl transition-colors flex items-center justify-center gap-2 disabled:opacity-40"
            title="Download compiled timeline manifest JSON without starting video render"
          >
            <FileCode className="w-4 h-4 text-navi" />
            <span><Trans>Export JSON Manifest Only</Trans></span>
          </button>

          <div className="flex items-center gap-2.5 w-full sm:w-auto justify-end">
            <button
              type="button"
              onClick={onClose}
              disabled={isExporting}
              className="px-4 py-2 text-xs font-semibold text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-xl transition-colors disabled:opacity-40"
            >
              <Trans>Cancel</Trans>
            </button>

            <button
              type="button"
              onClick={handleExportVideo}
              disabled={isExporting}
              className="w-full sm:w-auto px-5 py-2.5 bg-navi hover:bg-navi-600 text-white text-xs font-bold rounded-xl shadow-lg shadow-navi/25 hover:shadow-navi/40 transition-all flex items-center justify-center gap-2 disabled:opacity-60 cursor-pointer"
            >
              {isExporting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin text-white" />
                  <span>{exportStep || t`Exporting...`}</span>
                </>
              ) : (
                <>
                  <Download className="w-4 h-4" />
                  <span><Trans>Export Video</Trans></span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
