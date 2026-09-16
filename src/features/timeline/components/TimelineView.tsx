import { listen } from "@tauri-apps/api/event";
import React, { useState, useEffect, useRef, useMemo } from "react";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { MediaPool } from "./MediaPool";
import { TimelineTrack } from "./TimelineTrack";
import { ClipData, WaypointTimelineMarker } from "../../../types/index";
import { Inspector } from "./Inspector";
import { ExportModal } from "../../export/components/ExportModal";
import {
  ZoomIn,
  ZoomOut,
  Play,
  Pause,
  SkipBack,
  SkipForward,
  MousePointer2,
  Scissors,
  Sparkles,
  Magnet,
  Eye,
  EyeOff,
  Volume2,
  VolumeX,
  Lock,
  Unlock,
  Type,
  Film,
  Settings2,
  MapPin,
  Download,
  RefreshCw,
  Maximize,
  MapPinPlus,
  UnlinkIcon,
  Check,
} from "../../../components/ui/icons";
import { PreviewMonitor } from "./PreviewMonitor";
import { TransitionsPanel } from "./elements/TransitionsPanel";
import { useTimelineAudio } from "../hooks/useTimelineAudio";
import {
  WaypointMarker,
  WaypointGuideLine,
  formatMarkerTime,
} from "./elements/WaypointMarker";
import { MarkersPanel } from "./elements/MarkersPanel";

export function TimelineView() {
  const {
    timeline,
    setTimeline,
    autoLoadTimeline,
    metadata,
    waypoints,
    settings,
  } = useWorkspace();
  const { showToast } = useUI();

  const [selectedClipIds, setSelectedClipIds] = useState<string[]>([]);
  const [copiedClips, setCopiedClips] = useState<ClipData[]>([]);

  const [activeTool, setActiveTool] = useState<"pointer" | "razor" | "magic">(
    "pointer",
  );
  const [rightPanelTab, setRightPanelTab] = useState<
    "media" | "objects" | "transitions" | "inspector" | "markers" | null
  >("media");
  const [isRippleMode, setIsRippleMode] = useState(true);
  const [isExportModalOpen, setIsExportModalOpen] = useState(false);

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [isScrubbing, setIsScrubbing] = useState(false);

  // Audio Playback & Auto-Ducking synchronization hook
  const { isDuckingActive } = useTimelineAudio({
    timeline,
    currentTime,
    isPlaying,
    isScrubbing,
  });

  const timelineRef = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLDivElement>(null);
  const rulerRef = useRef<HTMLDivElement>(null);

  const [editingTrackId, setEditingTrackId] = useState<string | null>(null);

  const [marquee, setMarquee] = useState<{
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  } | null>(null);

  const [timelineHeight, setTimelineHeight] = useState(320);
  const isResizingTimeline = useRef(false);

  useEffect(() => {
    const handleGlobalMouseUp = () => {
      isResizingTimeline.current = false;
    };
    const handleGlobalMouseMove = (e: MouseEvent) => {
      if (!isResizingTimeline.current) return;
      const newHeight = window.innerHeight - e.clientY;
      setTimelineHeight(
        Math.max(150, Math.min(newHeight, window.innerHeight - 200)),
      );
    };
    window.addEventListener("mouseup", handleGlobalMouseUp);
    window.addEventListener("mousemove", handleGlobalMouseMove);
    return () => {
      window.removeEventListener("mouseup", handleGlobalMouseUp);
      window.removeEventListener("mousemove", handleGlobalMouseMove);
    };
  }, []);

  const pixelsPerSecond = 20 * timeline.zoomMultiplier;

  // ✨ SORT TRACKS BY ORDER INDEX
  const sortedTracks = useMemo(() => {
    return [...timeline.tracks].sort((a, b) => {
      const getBase = (type: string) =>
        type === "subtitle" ? 0 : type === "video" ? 100 : 200;
      const aOrder = a.orderIndex ?? getBase(a.type);
      const bOrder = b.orderIndex ?? getBase(b.type);
      return aOrder - bOrder;
    });
  }, [timeline.tracks]);

  // ✨ Calculate track bounds using the SORTED tracks
  const trackBounds = useMemo(() => {
    let y = 0;
    let currentType: string | null = null;
    return sortedTracks.map((t) => {
      if (currentType !== t.type) {
        y += 24; // 24px (h-6) spacing div for new track group (including the first one)
      }
      currentType = t.type;
      const h =
        t.type === "video" || t.name.toLowerCase().includes("video") ? 80 : 56;
      const bounds = { id: t.id, top: y, bottom: y + h };
      y += h;
      return bounds;
    });
  }, [sortedTracks]);

  useEffect(() => {
    if (!marquee) return;
    const handleMouseMove = (e: MouseEvent) => {
      if (!timelineRef.current) return;
      const rect = timelineRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left + timelineRef.current.scrollLeft;
      const y = e.clientY - rect.top + timelineRef.current.scrollTop;
      setMarquee((prev) => (prev ? { ...prev, x2: x, y2: y } : null));
    };

    const handleMouseUp = () => {
      if (marquee) {
        const mLeft = Math.min(marquee.x1, marquee.x2);
        const mRight = Math.max(marquee.x1, marquee.x2);
        const mTop = Math.min(marquee.y1, marquee.y2);
        const mBottom = Math.max(marquee.y1, marquee.y2);

        if (mRight - mLeft > 5 || mBottom - mTop > 5) {
          const selected = timeline.clips.filter((clip) => {
            const cLeft = clip.startTime * pixelsPerSecond;
            const cRight = (clip.startTime + clip.duration) * pixelsPerSecond;
            const tb = trackBounds.find((t) => t.id === clip.trackId);
            if (!tb) return false;

            return !(
              cRight < mLeft ||
              cLeft > mRight ||
              tb.bottom < mTop ||
              tb.top > mBottom
            );
          });
          if (selected.length > 0)
            setSelectedClipIds(selected.map((c) => c.id));
        }
        setMarquee(null);
      }
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [marquee, pixelsPerSecond, trackBounds, timeline.clips]);

  const handleZoom = (newZoom: number) =>
    setTimeline({ ...timeline, zoomMultiplier: newZoom });

  const handleSplitClip = (clipId: string, splitTime: number) => {
    const clip = timeline.clips.find((c) => c.id === clipId);
    const track = timeline.tracks.find((t) => t.id === clip?.trackId);
    if (
      !clip ||
      track?.isLocked ||
      splitTime <= clip.startTime ||
      splitTime >= clip.startTime + clip.duration
    )
      return;

    const clip1 = { ...clip, duration: splitTime - clip.startTime };
    const clip2 = {
      ...clip,
      id: crypto.randomUUID(),
      startTime: splitTime,
      duration: clip.duration - clip1.duration,
      sourceOffset: (clip.sourceOffset || 0) + clip1.duration,
    };
    setTimeline({
      ...timeline,
      clips: [...timeline.clips.filter((c) => c.id !== clipId), clip1, clip2],
    });
  };

  const handleSelectClip = (id: string | null, multi: boolean = false) => {
    if (!id) {
      setSelectedClipIds([]);
      return;
    }
    if (multi) {
      setSelectedClipIds((prev) =>
        prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
      );
    } else {
      setSelectedClipIds([id]);
      setRightPanelTab("inspector");
    }
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeEl = document.activeElement as HTMLElement | null;
      const activeTag = activeEl?.tagName.toLowerCase();
      if (
        activeTag === "input" ||
        activeTag === "textarea" ||
        activeEl?.isContentEditable
      )
        return;

      const isCtrl = e.ctrlKey || e.metaKey;

      switch (e.key.toLowerCase()) {
        case " ":
          e.preventDefault();
          setIsPlaying((prev) => !prev);
          break;

        case "v":
          if (isCtrl) {
            e.preventDefault();
            if (copiedClips.length === 0) return;

            const minStart = Math.min(...copiedClips.map((c) => c.startTime));
            let newTracks = [...timeline.tracks];
            let newClips = [...timeline.clips];
            const pastedClipIds: string[] = [];

            const clipsByTrack = copiedClips.reduce(
              (acc, clip) => {
                if (!acc[clip.trackId]) acc[clip.trackId] = [];
                acc[clip.trackId].push(clip);
                return acc;
              },
              {} as Record<string, typeof copiedClips>,
            );

            Object.entries(clipsByTrack).forEach(([originalTrackId, clips]) => {
              const originalTrack = timeline.tracks.find(
                (t) => t.id === originalTrackId,
              );
              if (!originalTrack) return;

              const hasCollision = clips.some((pastedClip) => {
                const newStart =
                  currentTime + (pastedClip.startTime - minStart);
                const newEnd = newStart + pastedClip.duration;

                return timeline.clips.some((existing) => {
                  if (existing.trackId !== originalTrackId) return false;
                  const existEnd = existing.startTime + existing.duration;
                  return newStart < existEnd && newEnd > existing.startTime;
                });
              });

              let targetTrackId = originalTrackId;

              if (hasCollision) {
                targetTrackId = crypto.randomUUID();
                const isVideo = originalTrack.type !== "audio";
                const prefix = isVideo ? "VIDEO" : "AUDIO";
                const existingCount = newTracks.filter((t) =>
                  t.name.toUpperCase().includes(prefix),
                ).length;

                newTracks.push({
                  id: targetTrackId,
                  name: `${prefix} ${existingCount + 1}`,
                  type: originalTrack.type,
                  orderIndex: originalTrack.orderIndex + 0.1, // Insert right below
                  isLocked: false,
                  isHidden: false,
                  isMuted: false,
                });
              }

              clips.forEach((c) => {
                const newId = crypto.randomUUID();
                pastedClipIds.push(newId);
                newClips.push({
                  ...c,
                  id: newId,
                  trackId: targetTrackId,
                  startTime: currentTime + (c.startTime - minStart),
                });
              });
            });

            setTimeline({ ...timeline, tracks: newTracks, clips: newClips });
            setSelectedClipIds(pastedClipIds);
            showToast(`Pasted ${pastedClipIds.length} clip(s)`, "success");
          } else {
            setActiveTool("pointer");
          }
          break;

        case "c":
          if (isCtrl) {
            e.preventDefault();
            const toCopy = timeline.clips.filter((c) =>
              selectedClipIds.includes(c.id),
            );
            if (toCopy.length > 0) {
              setCopiedClips(toCopy);
              showToast(`Copied ${toCopy.length} clip(s)`, "success");
            }
          } else setActiveTool("razor");
          break;

        case "x":
          if (isCtrl) {
            e.preventDefault();
            const toCopy = timeline.clips.filter((c) =>
              selectedClipIds.includes(c.id),
            );
            if (toCopy.length > 0) {
              setCopiedClips(toCopy);

              const lockedTracks = timeline.tracks
                .filter((t) => t.isLocked)
                .map((t) => t.id);
              const toDelete = selectedClipIds.filter((id) => {
                const clip = timeline.clips.find((c: any) => c.id === id);
                return clip && !lockedTracks.includes(clip.trackId);
              });

              setTimeline({
                ...timeline,
                clips: timeline.clips.filter(
                  (c: any) => !toDelete.includes(c.id),
                ),
              });
              setSelectedClipIds([]);
              showToast(`Cut ${toCopy.length} clip(s)`, "success");
            }
          }
          break;

        case "a":
          if (isCtrl) {
            e.preventDefault();
            setSelectedClipIds(timeline.clips.map((c) => c.id));
          }
          break;

        case "l":
          if (isCtrl) {
            e.preventDefault();
            if (e.shiftKey) {
              setTimeline({
                ...timeline,
                clips: timeline.clips.map((c) =>
                  selectedClipIds.includes(c.id)
                    ? { ...c, groupId: undefined }
                    : c,
                ),
              });
              showToast("Clips unlinked", "success");
            } else {
              if (selectedClipIds.length < 2) {
                showToast("Select at least 2 clips to link", "warning");
                return;
              }
              const newGroupId = crypto.randomUUID();
              setTimeline({
                ...timeline,
                clips: timeline.clips.map((c) =>
                  selectedClipIds.includes(c.id)
                    ? { ...c, groupId: newGroupId }
                    : c,
                ),
              });
              showToast("Clips linked", "success");
            }
          }
          break;

        case "s":
          if (selectedClipIds.length > 0)
            selectedClipIds.forEach((id) => handleSplitClip(id, currentTime));
          break;

        case "escape":
          e.preventDefault();
          setSelectedClipIds([]);
          break;

        case "backspace":
        case "delete":
          if (selectedClipIds.length > 0) {
            const lockedTracks = timeline.tracks
              .filter((t) => t.isLocked)
              .map((t) => t.id);
            const toDelete = selectedClipIds.filter((id) => {
              const clip = timeline.clips.find((c: any) => c.id === id);
              return clip && !lockedTracks.includes(clip.trackId);
            });
            setTimeline({
              ...timeline,
              clips: timeline.clips.filter(
                (c: any) => !toDelete.includes(c.id),
              ),
            });
            setSelectedClipIds([]);
          }
          break;

        case "home":
          e.preventDefault();
          setCurrentTime(0);
          break;
        case "end":
          e.preventDefault();
          const dur = timeline.clips.reduce(
            (max, clip) => Math.max(max, clip.startTime + clip.duration),
            0,
          );
          setCurrentTime(dur);
          break;
        case "pageup":
          e.preventDefault();
          const edgesPrev = [
            0,
            ...timeline.clips.flatMap((c) => [
              c.startTime,
              c.startTime + c.duration,
            ]),
          ];
          const prevEdge =
            Math.max(...edgesPrev.filter((t) => t < currentTime - 0.01)) || 0;
          setCurrentTime(prevEdge);
          break;
        case "pagedown":
          e.preventDefault();
          const edgesNext = [
            ...timeline.clips.flatMap((c) => [
              c.startTime,
              c.startTime + c.duration,
            ]),
          ];
          const nextEdge = Math.min(
            ...edgesNext.filter((t) => t > currentTime + 0.01),
          );
          if (nextEdge !== Infinity) setCurrentTime(nextEdge);
          break;
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isPlaying, selectedClipIds, currentTime, timeline, copiedClips]);

  useEffect(() => {
    let animationFrameId: number;
    let lastTime = performance.now();
    const playLoop = (time: number) => {
      if (isPlaying) {
        const deltaTime = (time - lastTime) / 1000;
        setCurrentTime((prevTime) => {
          const totalDur = timeline.clips.reduce(
            (max, clip) => Math.max(max, clip.startTime + clip.duration),
            0,
          );
          const nextTime = prevTime + deltaTime;
          if (nextTime >= totalDur && totalDur > 0) {
            setIsPlaying(false);
            return totalDur;
          }
          return nextTime;
        });
      }
      lastTime = time;
      if (isPlaying) animationFrameId = requestAnimationFrame(playLoop);
    };
    if (isPlaying) animationFrameId = requestAnimationFrame(playLoop);
    return () => cancelAnimationFrame(animationFrameId);
  }, [isPlaying, timeline.clips]);

  const handleScrub = (clientX: number) => {
    if (!timelineRef.current || !rulerRef.current) return;
    const rect = timelineRef.current.getBoundingClientRect();

    let currentScroll = timelineRef.current.scrollLeft;
    const scrollZone = 50;
    const maxScroll = timelineRef.current.scrollWidth - rect.width;

    if (clientX > rect.right - scrollZone && currentScroll < maxScroll) {
      currentScroll = Math.min(maxScroll, currentScroll + 30);
      timelineRef.current.scrollLeft = currentScroll;
      rulerRef.current.scrollLeft = currentScroll;
    } else if (clientX < rect.left + scrollZone && currentScroll > 0) {
      currentScroll = Math.max(0, currentScroll - 30);
      timelineRef.current.scrollLeft = currentScroll;
      rulerRef.current.scrollLeft = currentScroll;
    }

    const pixelsFromZero = clientX - rect.left + currentScroll;
    setCurrentTime(Math.max(0, pixelsFromZero / pixelsPerSecond));
  };

  useEffect(() => {
    if (!isScrubbing) return;
    const onMouseMove = (e: MouseEvent) => {
      e.preventDefault();
      handleScrub(e.clientX);
    };
    const onMouseUp = () => setIsScrubbing(false);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [isScrubbing, timeline.zoomMultiplier]);

  useEffect(() => {
    const handleRenameEvent = (e: CustomEvent<{ trackId: string }>) =>
      setEditingTrackId(e.detail.trackId);
    window.addEventListener("start-rename-track" as any, handleRenameEvent);
    return () =>
      window.removeEventListener(
        "start-rename-track" as any,
        handleRenameEvent,
      );
  }, []);

  const handleUpdateTrackName = (trackId: string, newName: string) => {
    setEditingTrackId(null);
    if (!newName.trim()) return;
    setTimeline({
      ...timeline,
      tracks: timeline.tracks.map((t) =>
        t.id === trackId ? { ...t, name: newName.trim() } : t,
      ),
    });
  };

  const handleToggleTrackProp = (
    trackId: string,
    prop: "isHidden" | "isMuted" | "isLocked",
  ) => {
    setTimeline({
      ...timeline,
      tracks: timeline.tracks.map((t) =>
        t.id === trackId ? { ...t, [prop]: !t[prop] } : t,
      ),
    });
  };

  const handleUpdateClip = (id: string, updates: any) => {
    setTimeline({
      ...timeline,
      clips: timeline.clips.map((c) =>
        c.id === id ? { ...c, ...updates } : c,
      ),
    });
  };

  const PRELOAD_SECONDS = 0.5;
  const activeClipsToRender = timeline.clips.filter((clip) => {
    const track = timeline.tracks.find((t) => t.id === clip.trackId);
    if (!track || track.isHidden) return false;

    const isTransitionSource = timeline.clips.some((nextClip) => {
      if (
        nextClip.id === clip.id ||
        nextClip.trackId !== clip.trackId ||
        !nextClip.transitionIn?.startsWith("glsl-") ||
        !nextClip.fadeIn
      ) {
        return false;
      }
      const nextEnd = nextClip.startTime + nextClip.duration;
      return (
        clip.startTime < nextClip.startTime &&
        clip.startTime + clip.duration >= nextClip.startTime &&
        currentTime >= nextClip.startTime &&
        currentTime <= Math.min(nextEnd, nextClip.startTime + nextClip.fadeIn)
      );
    });

    return (
      (currentTime >= clip.startTime - PRELOAD_SECONDS &&
        currentTime <= clip.startTime + clip.duration) ||
      isTransitionSource
    );
  });

  useEffect(() => {
    const unlisten = listen("render-complete", async (_event) => {
      if (metadata?.directory_path)
        await autoLoadTimeline(metadata.directory_path);
    });
    return () => {
      unlisten.then((f) => f());
    };
  }, [metadata]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    if (headerRef.current)
      headerRef.current.scrollTop = e.currentTarget.scrollTop;
    if (rulerRef.current)
      rulerRef.current.scrollLeft = e.currentTarget.scrollLeft;
  };

  const handleUnlink = () => {
    setTimeline({
      ...timeline,
      clips: timeline.clips.map((c) =>
        selectedClipIds.includes(c.id) ? { ...c, groupId: undefined } : c,
      ),
    });
    showToast("Clips unlinked", "success");
  };

  const handleLink = () => {
    if (selectedClipIds.length < 2) return;
    const newGroupId = crypto.randomUUID();
    setTimeline({
      ...timeline,
      clips: timeline.clips.map((c) =>
        selectedClipIds.includes(c.id) ? { ...c, groupId: newGroupId } : c,
      ),
    });
    showToast("Clips linked", "success");
  };

  useEffect(() => {
    const onLink = () => handleLink();
    const onUnlink = () => handleUnlink();

    window.addEventListener("trigger-link-clips", onLink);
    window.addEventListener("trigger-unlink-clips", onUnlink);

    return () => {
      window.removeEventListener("trigger-link-clips", onLink);
      window.removeEventListener("trigger-unlink-clips", onUnlink);
    };
  }, [timeline, selectedClipIds]);

  // Waypoint Timeline Calculation (F4.1)
  const derivedWaypointMarkers = useMemo<WaypointTimelineMarker[]>(() => {
    if (!waypoints || waypoints.length === 0) return [];

    const stepDuration =
      typeof settings?.duration_seconds === "number" &&
      settings.duration_seconds > 0
        ? settings.duration_seconds
        : 5.0;

    const videoTrackIds = new Set(
      timeline.tracks.filter((t) => t.type === "video").map((t) => t.id),
    );
    const videoClips = timeline.clips.filter((c) => {
      if (c.type && c.type !== "video") return false;
      return (
        videoTrackIds.size === 0 || (c.trackId && videoTrackIds.has(c.trackId))
      );
    });

    let runningTime = 0;

    return waypoints.map((wp, idx) => {
      let calculatedTime: number;

      if (typeof wp.timelineOffset === "number" && !isNaN(wp.timelineOffset)) {
        calculatedTime = wp.timelineOffset;
      } else {
        const rawWpName = (wp.name || "").trim().toLowerCase();
        const strippedWpName = rawWpName.replace(/[^a-z0-9]/g, "");
        const underscoreWpName = rawWpName.replace(/[\s\-]+/g, "_");

        const pad2 = String(idx + 1).padStart(2, "0");
        const pad1 = String(idx + 1);

        const matchedClip = videoClips.find((clip) => {
          const rawLabel = (clip.label || "").toLowerCase();
          const strippedLabel = rawLabel.replace(/[^a-z0-9]/g, "");
          const underscoreLabel = rawLabel.replace(/[\s\-]+/g, "_");

          if (
            strippedWpName &&
            strippedWpName !== "waypoint" &&
            (strippedLabel.includes(strippedWpName) ||
              underscoreLabel.includes(underscoreWpName))
          ) {
            return true;
          }

          return (
            rawLabel.includes(`waypoint_${pad2}`) ||
            rawLabel.includes(`waypoint_${pad1}`) ||
            rawLabel.includes(`waypoint-${pad2}`) ||
            rawLabel.includes(`waypoint-${pad1}`) ||
            rawLabel.includes(`waypoint ${pad1}`) ||
            rawLabel.includes(`wp_${pad2}`) ||
            rawLabel.includes(`wp_${pad1}`) ||
            rawLabel.includes(`wp-${pad2}`) ||
            rawLabel.includes(`wp-${pad1}`) ||
            strippedLabel.includes(`waypoint${pad2}`) ||
            strippedLabel.includes(`waypoint${pad1}`) ||
            strippedLabel.includes(`wp${pad2}`) ||
            strippedLabel.includes(`wp${pad1}`)
          );
        });

        if (matchedClip && typeof matchedClip.startTime === "number") {
          calculatedTime = matchedClip.startTime;
        } else {
          calculatedTime = runningTime;
        }
      }

      runningTime = Math.max(runningTime, calculatedTime) + stepDuration;

      return {
        id: wp.id || `waypoint-${idx + 1}`,
        name: wp.name || `Waypoint ${idx + 1}`,
        time: Math.max(0, calculatedTime),
        index: idx + 1,
        waypointId: wp.id,
        color: "#f59e0b",
      };
    });
  }, [waypoints, settings?.duration_seconds, timeline.clips, timeline.tracks]);

  const waypointMarkers = useMemo(() => {
    if (!timeline.markers) return derivedWaypointMarkers;
    const waypointIds = new Set(waypoints.map((waypoint) => waypoint.id));
    return timeline.markers
      .filter(
        (marker) => !marker.waypointId || waypointIds.has(marker.waypointId),
      )
      .sort((a, b) => a.time - b.time);
  }, [derivedWaypointMarkers, timeline.markers, waypoints]);

  const normalizeMarkers = (markers: WaypointTimelineMarker[]) =>
    [...markers]
      .sort(
        (left, right) =>
          left.time - right.time || left.id.localeCompare(right.id),
      )
      .map((marker, index) => ({ ...marker, index: index + 1 }));

  const updateMarkers = (markers: WaypointTimelineMarker[]) => {
    setTimeline({ ...timeline, markers: normalizeMarkers(markers) });
  };

  const handleAddMarker = () => {
    const existingMarkers = normalizeMarkers(
      timeline.markers || waypointMarkers,
    );
    const linkedWaypoint = waypointMarkers.find(
      (marker) =>
        marker.waypointId && Math.abs(marker.time - currentTime) < 0.15,
    );
    if (linkedWaypoint) {
      showToast(
        `${linkedWaypoint.name} already has a marker at this time.`,
        "info",
      );
      setRightPanelTab("markers");
      return;
    }
    updateMarkers([
      ...existingMarkers,
      {
        id: crypto.randomUUID(),
        name: `Marker ${existingMarkers.length + 1}`,
        time: Math.max(0, currentTime),
        index: existingMarkers.length + 1,
      },
    ]);
    setRightPanelTab("markers");
  };

  const handleUpdateMarker = (
    id: string,
    updates: Partial<WaypointTimelineMarker>,
  ) => {
    updateMarkers(
      (timeline.markers || waypointMarkers).map((marker) =>
        marker.id === id ? { ...marker, ...updates } : marker,
      ),
    );
  };

  const handleDeleteMarker = (id: string) => {
    updateMarkers(
      (timeline.markers || waypointMarkers).filter(
        (marker) => marker.id !== id,
      ),
    );
  };

  const [hoveredMarker, setHoveredMarker] =
    useState<WaypointTimelineMarker | null>(null);
  const [markerTooltipPos, setMarkerTooltipPos] = useState<{
    x: number;
    y: number;
  } | null>(null);

  const handleMarkerHover = (
    marker: WaypointTimelineMarker | null,
    rect?: DOMRect,
  ) => {
    if (marker && rect) {
      setHoveredMarker(marker);
      setMarkerTooltipPos({
        x: rect.left + rect.width / 2,
        y: rect.bottom,
      });
    } else {
      setHoveredMarker(null);
      setMarkerTooltipPos(null);
    }
  };

  const maxClipEnd = timeline.clips.reduce(
    (max, clip) => Math.max(max, clip.startTime + clip.duration),
    0,
  );
  const maxMarkerTime = waypointMarkers.reduce(
    (max, m) => Math.max(max, m.time),
    0,
  );

  const fitTimeline = () => {
    const contentEnd = Math.max(
      maxClipEnd,
      ...waypointMarkers.map((marker) => marker.time),
      1,
    );
    const availableWidth = timelineRef.current?.clientWidth || 800;
    const fittedZoom = Math.max(
      0.2,
      Math.min(5, (availableWidth * 0.9) / (contentEnd * 20)),
    );
    handleZoom(Number(fittedZoom.toFixed(1)));
  };

  const rulerDuration = Math.max(600, maxClipEnd + 120, maxMarkerTime + 120);
  const timelinePixelWidth = rulerDuration * pixelsPerSecond;

  let majorStep = 10,
    minorStep = 2;
  if (timeline.zoomMultiplier < 0.5) {
    majorStep = 30;
    minorStep = 10;
  } else if (timeline.zoomMultiplier > 2.5) {
    majorStep = 2;
    minorStep = 0.5;
  } else if (timeline.zoomMultiplier > 1.2) {
    majorStep = 5;
    minorStep = 1;
  }

  return (
    <div className="flex flex-col flex-1 h-full bg-white dark:bg-[#09090b] overflow-hidden select-none">
      <div className="flex-1 flex min-h-0 border-b border-zinc-200 dark:border-white/5">
        {/* SIDEBAR TABS BAR */}
        <div className="w-14 shrink-0 flex flex-col items-center py-4 bg-zinc-50 dark:bg-navidark-900 border-r border-zinc-200 dark:border-navidark-400 gap-4">
          <button
            onClick={() =>
              setRightPanelTab(
                rightPanelTab === "media" ? null : ("media" as any),
              )
            }
            className={`p-2 rounded-xl transition-colors ${rightPanelTab === "media" ? "bg-navi/10 text-navi" : "text-zinc-500 hover:bg-zinc-200 dark:hover:bg-white/5 dark:text-zinc-400"}`}
            title="Media Pool"
          >
            <Film className="w-5 h-5" />
          </button>
          <button
            onClick={() =>
              setRightPanelTab(
                rightPanelTab === "objects" ? null : ("objects" as any),
              )
            }
            className={`p-2 rounded-xl transition-colors ${rightPanelTab === "objects" ? "bg-navi/10 text-navi" : "text-zinc-500 hover:bg-zinc-200 dark:hover:bg-white/5 dark:text-zinc-400"}`}
            title="Add Object"
          >
            <Type className="w-5 h-5" />
          </button>
          <button
            onClick={() =>
              setRightPanelTab(
                rightPanelTab === "transitions" ? null : ("transitions" as any),
              )
            }
            className={`p-2 rounded-xl transition-colors ${rightPanelTab === "transitions" ? "bg-navi/10 text-navi" : "text-zinc-500 hover:bg-zinc-200 dark:hover:bg-white/5 dark:text-zinc-400"}`}
            title="Transitions"
          >
            <Sparkles className="w-5 h-5" />
          </button>
          <div className="w-8 h-px bg-zinc-300 dark:bg-navidark-700 my-2" />
          <button
            onClick={() =>
              setRightPanelTab(
                rightPanelTab === "inspector" ? null : "inspector",
              )
            }
            className={`p-2 rounded-xl transition-colors ${rightPanelTab === "inspector" ? "bg-navi/10 text-navi" : "text-zinc-500 hover:bg-zinc-200 dark:hover:bg-white/5 dark:text-zinc-400"}`}
            title="Inspector"
          >
            <Settings2 className="w-5 h-5" />
          </button>
        </div>

        {/* SIDEBAR PANEL CONTENT */}
        {rightPanelTab !== null && (
          <div className="w-80 bg-white dark:bg-navidark-800 border-r border-zinc-200 dark:border-navidark-400 flex flex-col shrink-0 animate-in slide-in-from-left-2 duration-200">
            <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col">
              {rightPanelTab === "media" && <MediaPool />}
              {rightPanelTab === "objects" && (
                <div className="p-4 text-center text-sm text-zinc-500">
                  <Type className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  <p>Drag and drop texts or shapes.</p>
                  <button
                    onClick={() => {
                      const popupTrack = sortedTracks.find(
                        (t) => t.type === "video" || t.type === "overlay",
                      );
                      if (!popupTrack) return;
                      const newTextClip = {
                        id: crypto.randomUUID(),
                        trackId: popupTrack.id,
                        type: "text" as any,
                        label: "Custom Text",
                        text: "Enter text here...",
                        startTime: currentTime,
                        duration: 5,
                        x: 960,
                        y: 540,
                        fontSize: 64,
                        color: "#ffffff",
                      };
                      setTimeline({
                        ...timeline,
                        clips: [...timeline.clips, newTextClip],
                      });
                      showToast("Text added to timeline", "success");
                    }}
                    className="mt-4 px-4 py-2 bg-navi text-white rounded-md w-full"
                  >
                    Add Text Layer
                  </button>
                </div>
              )}
              {rightPanelTab === "transitions" && (
                <TransitionsPanel selectedClipIds={selectedClipIds} />
              )}
              {rightPanelTab === "inspector" && (
                <div className="p-4 flex-1">
                  <Inspector
                    selectedClipIds={selectedClipIds}
                    onClearSelection={() => setSelectedClipIds([])}
                  />
                </div>
              )}
              {rightPanelTab === "markers" && (
                <MarkersPanel
                  markers={waypointMarkers}
                  currentTime={currentTime}
                  onAdd={handleAddMarker}
                  onUpdate={handleUpdateMarker}
                  onDelete={handleDeleteMarker}
                  onSeek={(time) => {
                    setCurrentTime(time);
                    setIsPlaying(false);
                  }}
                />
              )}
            </div>
          </div>
        )}

        {/* PREVIEW MONITOR */}
        <div className="flex-1 p-4 md:p-6 flex flex-col items-center justify-center bg-zinc-50/50 dark:bg-navidark-800/50 min-w-0 min-h-0 relative overflow-hidden">
          <div className="w-full max-w-5xl aspect-video bg-zinc-100 dark:bg-black border border-zinc-300 dark:border-zinc-800 ring-1 ring-black/5 dark:ring-0 relative overflow-hidden group shadow-xl">
            {activeClipsToRender.length > 0 ? (
              <PreviewMonitor
                activeClips={activeClipsToRender}
                currentTime={currentTime}
                isPlaying={isPlaying}
                selectedClipId={
                  selectedClipIds.length === 1 ? selectedClipIds[0] : null
                }
                onSelectClip={(id) => handleSelectClip(id, false)}
                onUpdateClip={handleUpdateClip}
              />
            ) : (
              <div className="flex items-center justify-center h-full"></div>
            )}
          </div>
        </div>
      </div>

      {/* ✨ RESIZER BAR */}
      <div
        className="h-1.5 cursor-row-resize bg-zinc-200 dark:bg-zinc-800 hover:bg-navi dark:hover:bg-navi transition-colors shrink-0 z-40 relative"
        onMouseDown={() => {
          isResizingTimeline.current = true;
        }}
      />

      <div
        className="shrink-0 flex flex-col bg-zinc-100 dark:bg-navidark-900 relative border-t border-zinc-300 dark:border-black shadow-[0_-4px_20px_rgba(0,0,0,0.1)] min-h-0"
        style={{ height: timelineHeight }}
      >
        <div className="h-11 bg-white dark:bg-navidark-800 border-b border-zinc-200 dark:border-navidark-400 flex items-center justify-between px-4 shrink-0 z-30">
          {/* LEFT: Tools */}
          <div className="flex items-center gap-1 bg-zinc-100 dark:bg-navidark-900 p-1 rounded-md border border-zinc-200 dark:border-navidark-700">
            <button
              onClick={() => setActiveTool("pointer")}
              className={`p-1.5 rounded transition-colors ${activeTool === "pointer" ? "bg-white dark:bg-navidark-700 text-navi shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"}`}
              title="Selection Tool (V)"
            >
              <MousePointer2 className="w-4 h-4" />
            </button>
            <button
              onClick={() => setActiveTool("razor")}
              className={`p-1.5 rounded transition-colors ${activeTool === "razor" ? "bg-white dark:bg-navidark-700 text-navi shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"}`}
              title="Razor Tool (C)"
            >
              <Scissors className="w-4 h-4" />
            </button>

            <button
              onClick={() => {
                const popupTrack = sortedTracks.find(
                  (t) => t.type === "video" || t.type === "overlay",
                );
                if (!popupTrack) return;

                const newTextClip: ClipData = {
                  id: crypto.randomUUID(),
                  trackId: popupTrack.id,
                  type: "text",
                  label: "Custom Text",
                  text: "Enter text here...",
                  startTime: currentTime,
                  duration: 5,
                  x: 960,
                  y: 540,
                  fontSize: 64,
                  color: "#ffffff",
                };
                setTimeline({
                  ...timeline,
                  clips: [...timeline.clips, newTextClip],
                });
                showToast("Text added to timeline", "success");
              }}
              className="p-1.5 rounded transition-colors text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"
              title="Add Custom Text"
            >
              <Type className="w-4 h-4" />
            </button>

            <div className="w-px h-4 bg-zinc-300 dark:bg-navidark-400 mx-1" />
            <button
              onClick={() => setIsRippleMode(!isRippleMode)}
              className={`p-1.5 rounded transition-colors ${isRippleMode ? "bg-navi text-white shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"}`}
              title="Ripple Insert Mode"
            >
              <Magnet className="w-4 h-4" />
            </button>
            <button
              onClick={handleAddMarker}
              className="p-1.5 rounded text-zinc-500 hover:text-navi"
              title="Add marker at playhead"
            >
              <MapPinPlus className="w-4 h-4" />
            </button>
            <button
              onClick={() => setRightPanelTab("markers")}
              className="p-1.5 rounded text-zinc-500 hover:text-navi"
              title="Manage timeline markers"
            >
              <MapPin className="w-4 h-4" />
            </button>
            <button
              onClick={() =>
                setSelectedClipIds(timeline.clips.map((clip) => clip.id))
              }
              className="p-1.5 rounded text-zinc-500 hover:text-navi"
              title="Select all clips (Ctrl/Cmd+A)"
            >
              <Check className="w-4 h-4" />
            </button>
            <button
              onClick={handleUnlink}
              disabled={selectedClipIds.length === 0}
              className="p-1.5 rounded text-zinc-500 hover:text-navi disabled:opacity-30"
              title="Unlink selected clips"
            >
              <UnlinkIcon className="w-4 h-4" />
            </button>
          </div>

          {/* CENTER: Playback Controls */}
          <div className="flex items-center gap-1 bg-zinc-100 dark:bg-navidark-900 p-1 rounded-md border border-zinc-200 dark:border-navidark-700">
            <button
              onClick={() => setCurrentTime(0)}
              className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors rounded hover:bg-zinc-200 dark:hover:bg-navidark-700"
              title="Home"
            >
              <SkipBack className="w-4 h-4" />
            </button>
            <button
              onClick={() => setIsPlaying(!isPlaying)}
              className="p-1.5 text-zinc-500 hover:text-navi transition-colors rounded hover:bg-zinc-200 dark:hover:bg-navidark-700"
              title="Play/Pause (Space)"
            >
              {isPlaying ? (
                <Pause className="w-4 h-4" fill="currentColor" />
              ) : (
                <Play className="w-4 h-4" fill="currentColor" />
              )}
            </button>
            <button
              onClick={() =>
                setCurrentTime(
                  timeline.clips.reduce(
                    (max, c) => Math.max(max, c.startTime + c.duration),
                    0,
                  ),
                )
              }
              className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors rounded hover:bg-zinc-200 dark:hover:bg-navidark-700"
              title="End"
            >
              <SkipForward className="w-4 h-4" />
            </button>
            <div className="w-px h-4 bg-zinc-300 dark:bg-navidark-400 mx-2" />
            <div className="text-xs font-medium tracking-wide text-zinc-600 dark:text-zinc-300 px-2 py-0.5 pointer-events-none">
              {new Date(currentTime * 1000)
                .toISOString()
                .substring(11, 23)
                .replace(".", ":")}
            </div>
          </div>

          {/* RIGHT: Zoom & Export Controls */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <ZoomOut className="w-3.5 h-3.5 text-zinc-400" />
              <input
                type="range"
                min="0.2"
                max="5"
                step="0.1"
                value={timeline.zoomMultiplier}
                onChange={(e) => handleZoom(parseFloat(e.target.value))}
                className="w-24 accent-navi cursor-ew-resize"
              />
              <ZoomIn className="w-3.5 h-3.5 text-zinc-400" />
            </div>

            <div className="w-px h-4 bg-zinc-300 dark:bg-navidark-400" />

            <button
              onClick={fitTimeline}
              className="p-1.5 text-zinc-500 hover:text-navi"
              title="Fit timeline to content"
            >
              <Maximize className="w-4 h-4" />
            </button>
            <button
              onClick={async () => {
                if (!metadata.directory_path) return;
                await autoLoadTimeline(metadata.directory_path);
                showToast("Timeline reloaded", "success");
              }}
              className="p-1.5 text-zinc-500 hover:text-navi"
              title="Reload saved timeline"
            >
              <RefreshCw className="w-4 h-4" />
            </button>

            <button
              onClick={() => setIsExportModalOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1 bg-navi hover:bg-navi-600 text-white rounded-md text-xs font-bold shadow-sm hover:shadow transition-all cursor-pointer"
              title="Export & Render Video"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Export</span>
            </button>
          </div>
        </div>

        <div className="flex-1 flex flex-row min-h-0 overflow-hidden">
          <div className="w-48 flex flex-col shrink-0 border-r border-zinc-300 dark:border-navidark-400 bg-zinc-50 dark:bg-navidark-800 z-40">
            <div className="h-8 w-full border-b border-zinc-300 dark:border-navidark-400 shrink-0 flex items-center px-3 bg-zinc-200/90 dark:bg-navidark-800/90">
              <span className="text-[9px] font-bold text-zinc-400 dark:text-zinc-500 tracking-widest">
                TRACKS
              </span>
            </div>
            <div
              ref={headerRef}
              className="flex-1 overflow-hidden"
              onWheel={(e) => {
                if (timelineRef.current) {
                  timelineRef.current.scrollTop += e.deltaY;
                }
              }}
              onContextMenu={(e) => {
                e.preventDefault();
                window.dispatchEvent(
                  new CustomEvent("open-context-menu", {
                    detail: { x: e.clientX, y: e.clientY, type: "empty-track" },
                  }),
                );
              }}
            >
              <div className="pb-32">
                {/* ✨ MAPPING OVER SORTED TRACKS */}
                {sortedTracks.map((track, idx) => {
                  const prevTrack = sortedTracks[idx - 1];
                  const isNewGroup =
                    !prevTrack || prevTrack.type !== track.type;

                  const isMainTrack =
                    track.type === "video" ||
                    track.name.toLowerCase().includes("video");
                  const isAudioTrack = track.type === "audio";
                  const trackHeight = isMainTrack ? "h-20" : "h-14";
                  return (
                    <React.Fragment key={track.id}>
                      {isNewGroup && (
                        <div className="h-6 w-full bg-zinc-200 dark:bg-navidark-900 border-b border-zinc-300 dark:border-navidark-700 flex items-center px-3 sticky top-0 z-10 shadow-sm">
                          <span className="text-[9px] font-bold text-zinc-500 uppercase tracking-widest">
                            {track.type} TRACKS
                          </span>
                        </div>
                      )}
                      <div
                        draggable
                        onDragStart={(e) => {
                          e.dataTransfer.setData(
                            "application/navivi-track",
                            track.id,
                          );
                        }}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={(e) => {
                          e.preventDefault();
                          const sourceTrackId = e.dataTransfer.getData(
                            "application/navivi-track",
                          );
                          if (!sourceTrackId || sourceTrackId === track.id)
                            return;

                          const sourceTrack = timeline.tracks.find(
                            (t) => t.id === sourceTrackId,
                          );
                          if (!sourceTrack || sourceTrack.type !== track.type)
                            return;

                          setTimeline({
                            ...timeline,
                            tracks: timeline.tracks.map((t) => {
                              if (t.id === sourceTrackId)
                                return { ...t, orderIndex: track.orderIndex };
                              if (t.id === track.id)
                                return {
                                  ...t,
                                  orderIndex: sourceTrack.orderIndex,
                                };
                              return t;
                            }),
                          });
                        }}
                        onContextMenu={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          window.dispatchEvent(
                            new CustomEvent("open-context-menu", {
                              detail: {
                                x: e.clientX,
                                y: e.clientY,
                                type: "track-header",
                                targetId: track.id,
                                data: {
                                  isLocked: track.isLocked,
                                  isHidden: track.isHidden,
                                  isMuted: track.isMuted,
                                  isAudioTrack,
                                  onToggleHide: () =>
                                    handleToggleTrackProp(track.id, "isHidden"),
                                  onToggleMute: () =>
                                    handleToggleTrackProp(track.id, "isMuted"),
                                  onToggleLock: () =>
                                    handleToggleTrackProp(track.id, "isLocked"),
                                },
                              },
                            }),
                          );
                        }}
                        onDoubleClick={() => setEditingTrackId(track.id)}
                        className={`w-full border-b border-zinc-200 dark:border-navidark-400 flex flex-col justify-center px-2.5 ${editingTrackId === track.id ? "" : "cursor-context-menu"} ${trackHeight}`}
                      >
                        <div className="flex items-center justify-between mb-1 gap-1">
                          {editingTrackId === track.id ? (
                            <input
                              type="text"
                              autoFocus
                              defaultValue={track.name}
                              onBlur={(e) =>
                                handleUpdateTrackName(track.id, e.target.value)
                              }
                              onKeyDown={(e) => {
                                if (e.key === "Enter")
                                  handleUpdateTrackName(
                                    track.id,
                                    e.currentTarget.value,
                                  );
                                if (e.key === "Escape") setEditingTrackId(null);
                              }}
                              className="w-full bg-white dark:bg-navidark-900 text-[10px] font-bold text-zinc-900 dark:text-zinc-100 px-1.5 py-1 rounded outline-none border-2 border-navi"
                            />
                          ) : (
                            <span className="text-[10px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-wider truncate flex-1">
                              {track.name}
                            </span>
                          )}

                          {/* Ducking toggle & active indicator for Audio tracks */}
                          {isAudioTrack && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                setTimeline({
                                  ...timeline,
                                  tracks: timeline.tracks.map((t) =>
                                    t.id === track.id
                                      ? {
                                          ...t,
                                          duckingEnabled: !t.duckingEnabled,
                                        }
                                      : t,
                                  ),
                                });
                              }}
                              className={`px-1 py-0.5 text-[8px] font-bold rounded tracking-tighter uppercase transition-colors shrink-0 ${
                                track.duckingEnabled
                                  ? isDuckingActive
                                    ? "bg-amber-500 text-white animate-pulse"
                                    : "bg-amber-500/20 text-amber-500 border border-amber-500/40"
                                  : "text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 opacity-60"
                              }`}
                              title={
                                track.duckingEnabled
                                  ? isDuckingActive
                                    ? "Auto-Ducking Actively Attenuating (Click to disable)"
                                    : "Auto-Ducking Armed (Click to disable)"
                                  : "Enable Auto-Ducking on this track"
                              }
                            >
                              DUCK
                            </button>
                          )}
                        </div>

                        <div className="flex items-center justify-between gap-1.5">
                          <div className="flex items-center gap-1 shrink-0">
                            {!isAudioTrack ? (
                              <button
                                onClick={() =>
                                  handleToggleTrackProp(track.id, "isHidden")
                                }
                                className={`p-1 rounded transition-colors ${track.isHidden ? "text-red-500 bg-red-50 dark:bg-red-500/10" : "text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200"}`}
                              >
                                {track.isHidden ? (
                                  <EyeOff className="w-3.5 h-3.5" />
                                ) : (
                                  <Eye className="w-3.5 h-3.5" />
                                )}
                              </button>
                            ) : (
                              <button
                                onClick={() =>
                                  handleToggleTrackProp(track.id, "isMuted")
                                }
                                className={`p-1 rounded transition-colors ${track.isMuted ? "text-red-500 bg-red-50 dark:bg-red-500/10" : "text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200"}`}
                                title={
                                  track.isMuted ? "Unmute Track" : "Mute Track"
                                }
                              >
                                {track.isMuted ? (
                                  <VolumeX className="w-3.5 h-3.5" />
                                ) : (
                                  <Volume2 className="w-3.5 h-3.5" />
                                )}
                              </button>
                            )}
                            <button
                              onClick={() =>
                                handleToggleTrackProp(track.id, "isLocked")
                              }
                              className={`p-1 rounded transition-colors ${track.isLocked ? "text-red-500 bg-red-50 dark:bg-red-500/10" : "text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200"}`}
                              title={
                                track.isLocked ? "Unlock Track" : "Lock Track"
                              }
                            >
                              {track.isLocked ? (
                                <Lock className="w-3 h-3" />
                              ) : (
                                <Unlock className="w-3 h-3" />
                              )}
                            </button>
                          </div>

                          {/* Track volume slider for Audio tracks */}
                          {isAudioTrack && (
                            <div
                              className="flex items-center gap-1 flex-1 min-w-0"
                              title={`Track Volume: ${Math.round((track.volume ?? 1.0) * 100)}%`}
                            >
                              <input
                                type="range"
                                min="0"
                                max="150"
                                step="5"
                                value={Math.round((track.volume ?? 1.0) * 100)}
                                onChange={(e) => {
                                  const newVol =
                                    parseFloat(e.target.value) / 100;
                                  setTimeline({
                                    ...timeline,
                                    tracks: timeline.tracks.map((t) =>
                                      t.id === track.id
                                        ? { ...t, volume: newVol }
                                        : t,
                                    ),
                                  });
                                }}
                                className="w-full h-1 accent-[#36604C] dark:accent-[#93C9B2] bg-zinc-200 dark:bg-zinc-700 rounded cursor-pointer"
                              />
                              <span className="text-[8px] font-mono text-zinc-400 w-5 text-right shrink-0">
                                {Math.round((track.volume ?? 1.0) * 100)}%
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    </React.Fragment>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="flex-1 flex flex-col min-w-0 relative bg-zinc-50 dark:bg-navidark-800/50">
            <div
              ref={rulerRef}
              onScroll={(e) => {
                if (timelineRef.current) {
                  timelineRef.current.scrollLeft = e.currentTarget.scrollLeft;
                }
              }}
              className="h-8 w-full border-b border-zinc-300 dark:border-navidark-400 bg-zinc-200/90 dark:bg-navidark-800/90 overflow-hidden shrink-0"
            >
              <div
                className="h-full cursor-ew-resize relative shrink-0"
                style={{ width: `${timelinePixelWidth}px` }}
                onMouseDown={(e) => {
                  if (isPlaying) setIsPlaying(false);
                  setIsScrubbing(true);
                  handleScrub(e.clientX);
                }}
              >
                {Array.from({
                  length: Math.ceil(rulerDuration / minorStep),
                }).map((_, i) => {
                  const time = i * minorStep;
                  const isMajor = time % majorStep === 0;
                  return (
                    <div
                      key={time}
                      className="absolute bottom-0"
                      style={{ left: `${time * pixelsPerSecond}px` }}
                    >
                      <div
                        className={`w-px bg-zinc-400 dark:bg-zinc-600 ${isMajor ? "h-2.5" : "h-1.5"}`}
                      />
                      {isMajor && (
                        <span className="absolute bottom-3 -translate-x-1/2 text-[9px] text-zinc-500 dark:text-zinc-400 font-semibold tracking-wider select-none pointer-events-none">
                          {Math.floor(time / 60)
                            .toString()
                            .padStart(2, "0")}
                          :
                          {Math.floor(time % 60)
                            .toString()
                            .padStart(2, "0")}
                        </span>
                      )}
                    </div>
                  );
                })}
                {/* Waypoint Timeline Ruler Markers (F4.2 & F4.3) */}
                {waypointMarkers.map((marker) => (
                  <WaypointMarker
                    key={marker.id}
                    marker={marker}
                    pixelsPerSecond={pixelsPerSecond}
                    isActive={Math.abs(currentTime - marker.time) < 0.15}
                    onSeek={(time) => {
                      if (isPlaying) setIsPlaying(false);
                      setCurrentTime(time);
                    }}
                    onHover={handleMarkerHover}
                  />
                ))}

                <div
                  className="absolute bottom-0 -translate-x-1/2 w-3 h-3 bg-navi [clip-path:polygon(50%_100%,0_0,100%_0)] z-50 pointer-events-none"
                  style={{ left: `${currentTime * pixelsPerSecond}px` }}
                />
              </div>
            </div>

            <div
              ref={timelineRef}
              onScroll={handleScroll}
              className="flex-1 overflow-auto custom-scrollbar relative"
              onMouseDown={(e) => {
                if (e.button === 2) return;
                if ((e.target as HTMLElement).closest(".react-draggable"))
                  return;
                const rect = e.currentTarget.getBoundingClientRect();
                const x = e.clientX - rect.left + e.currentTarget.scrollLeft;
                const y = e.clientY - rect.top + e.currentTarget.scrollTop;
                setMarquee({ x1: x, y1: y, x2: x, y2: y });

                if (!e.shiftKey && !e.ctrlKey && !e.metaKey) {
                  setSelectedClipIds([]);
                }
              }}
            >
              <div
                className="relative min-w-max pb-24"
                style={{ width: `${timelinePixelWidth}px` }}
              >
                <div
                  className="absolute top-0 bottom-0 w-[1.5px] bg-navi z-35 pointer-events-none shadow-[0_0_10px_var(--color-navi)]"
                  style={{ left: `${currentTime * pixelsPerSecond}px` }}
                />

                {/* Waypoint Sync Guide Lines (F4.3) */}
                {waypointMarkers.map((marker) => (
                  <WaypointGuideLine
                    key={`guide-${marker.id}`}
                    marker={marker}
                    pixelsPerSecond={pixelsPerSecond}
                  />
                ))}

                {marquee && (
                  <div
                    className="absolute bg-navi-500/20 border border-navi-500 z-50 pointer-events-none"
                    style={{
                      left: Math.min(marquee.x1, marquee.x2),
                      top: Math.min(marquee.y1, marquee.y2),
                      width: Math.abs(marquee.x2 - marquee.x1),
                      height: Math.abs(marquee.y2 - marquee.y1),
                    }}
                  />
                )}

                {/* ✨ MAPPING OVER SORTED TRACKS */}
                {sortedTracks.map((track, idx) => {
                  const prevTrack = sortedTracks[idx - 1];
                  const isNewGroup =
                    !prevTrack || prevTrack.type !== track.type;

                  return (
                    <React.Fragment key={track.id}>
                      {isNewGroup && (
                        <div className="h-6 w-full bg-zinc-100 dark:bg-navidark-900/40 border-b border-zinc-200 dark:border-navidark-700 pointer-events-none sticky left-0 z-10" />
                      )}
                      <TimelineTrack
                        track={track}
                        selectedClipIds={selectedClipIds}
                        onSelectClip={handleSelectClip}
                        activeTool={activeTool}
                        onSplit={handleSplitClip}
                        isRippleMode={isRippleMode}
                        trackWidth={timelinePixelWidth}
                        currentTime={currentTime}
                        isLocked={track.isLocked || false}
                      />
                    </React.Fragment>
                  );
                })}
              </div>
            </div>

            {/* Waypoint Marker Floating Tooltip Overlay */}
            {hoveredMarker && markerTooltipPos && (
              <div
                className="fixed z-50 pointer-events-none -translate-x-1/2 flex flex-col items-center transition-all duration-150"
                style={{
                  left: `${markerTooltipPos.x}px`,
                  top: `${markerTooltipPos.y + 4}px`,
                }}
              >
                <div className="w-0 h-0 border-l-4 border-l-transparent border-r-4 border-r-transparent border-b-[5px] border-b-zinc-900/95 dark:border-b-zinc-800/95" />
                <div className="bg-zinc-900/95 dark:bg-zinc-800/95 backdrop-blur-sm text-white text-xs rounded-md shadow-2xl border border-zinc-700/80 px-2.5 py-1.5 flex flex-col items-center gap-0.5">
                  <div className="flex items-center gap-1.5 font-bold text-amber-400">
                    <MapPin className="w-3 h-3 shrink-0" />
                    <span>
                      #{hoveredMarker.index} {hoveredMarker.name}
                    </span>
                  </div>
                  <span className="font-mono text-[10px] text-zinc-300">
                    {formatMarkerTime(hoveredMarker.time)}
                  </span>
                  <span className="text-[9px] text-zinc-400">
                    Click marker to jump playhead
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <ExportModal
        isOpen={isExportModalOpen}
        onClose={() => setIsExportModalOpen(false)}
        timeline={timeline}
        metadata={metadata}
        waypoints={waypoints}
        settings={settings}
        duration={maxClipEnd}
        onExportSuccess={() => {
          showToast("Export process started", "success");
        }}
      />
    </div>
  );
}
