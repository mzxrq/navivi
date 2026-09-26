import { useState, useRef, useEffect } from "react";
import { useWorkspace } from "../../../../hooks/useWorkspace";
import { useUI } from "../../../../hooks/useUI";
import {
  Sparkles,
  Search,
  Play,
  Film,
  Check,
  Clock,
  Lightbulb,
} from "../../../../components/ui/icons";
import { t } from "@lingui/core/macro"; import { Trans } from "@lingui/react/macro";

export interface TransitionItem {
  shader: string;
  name: string;
  category: "Dissolve" | "Wipe & Slide" | "Warp & Distortion" | "Stylized";
  description: string;
  colorFrom: string;
  colorTo: string;
}

export const getTransitionLibrary = (): TransitionItem[] => [
  {
    shader: "glsl-crossfade",
    name: t`Crossfade`,
    category: "Dissolve",
    description: t`Smooth linear dissolve blending outgoing and incoming clips`,
    colorFrom: "#3B82F6",
    colorTo: "#EC4899",
  },
  {
    shader: "glsl-wipe",
    name: t`Wipe`,
    category: "Wipe & Slide",
    description: t`Linear directional wipe from left to right`,
    colorFrom: "#10B981",
    colorTo: "#6366F1",
  },
  {
    shader: "glsl-slide",
    name: t`Slide`,
    category: "Wipe & Slide",
    description: t`Push transition smoothly sliding incoming clip from left`,
    colorFrom: "#F59E0B",
    colorTo: "#8B5CF6",
  },
  {
    shader: "glsl-dissolve",
    name: t`Dissolve`,
    category: "Dissolve",
    description: t`Dithering noise pixel dissolve between scenes`,
    colorFrom: "#06B6D4",
    colorTo: "#F43F5E",
  },
  {
    shader: "glsl-dreamy",
    name: t`Dreamy`,
    category: "Warp & Distortion",
    description: t`Ethereal sinusoidal wave distortion and color blend`,
    colorFrom: "#8B5CF6",
    colorTo: "#F59E0B",
  },
  {
    shader: "glsl-directionalwarp",
    name: t`Directional Warp`,
    category: "Warp & Distortion",
    description: t`Angular diagonal stretch and perspective displacement`,
    colorFrom: "#EC4899",
    colorTo: "#3B82F6",
  },
  {
    shader: "glsl-pixelize",
    name: t`Pixelize`,
    category: "Stylized",
    description: t`Progressive mosaic pixel grid reveal`,
    colorFrom: "#14B8A6",
    colorTo: "#F97316",
  },
  {
    shader: "glsl-multiply_blend",
    name: t`Multiply Blend`,
    category: "Stylized",
    description: t`Luminance photographic multiply overlay`,
    colorFrom: "#6366F1",
    colorTo: "#E11D48",
  },
  {
    shader: "glsl-crosswarp",
    name: t`Cross Warp`,
    category: "Warp & Distortion",
    description: t`Double-sided horizontal perspective warp effect`,
    colorFrom: "#3B82F6",
    colorTo: "#10B981",
  },
  {
    shader: "glsl-burn",
    name: t`Burn`,
    category: "Stylized",
    description: t`High-exposure film burn and fiery glow reveal`,
    colorFrom: "#EF4444",
    colorTo: "#F59E0B",
  },
];

const CATEGORIES = ["All", "Dissolve", "Wipe & Slide", "Warp & Distortion", "Stylized"] as const;

interface TransitionsPanelProps {
  selectedClipIds?: string[];
}

export function TransitionsPanel({ selectedClipIds = [] }: TransitionsPanelProps) {
  const { timeline, setTimeline } = useWorkspace();
  const { showToast } = useUI();
  const [searchQuery, setSearchQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>("All");
  const [previewShader, setPreviewShader] = useState<string | null>(null);
  const [selectedDuration, setSelectedDuration] = useState<number>(1.0);
  const [appliedShader, setAppliedShader] = useState<string | null>(null);

  const filteredTransitions = getTransitionLibrary().filter((item) => {
    const matchesCategory =
      activeCategory === "All" || item.category === activeCategory;
    const matchesSearch =
      item.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.description.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  const handleApplyToSelected = (item: TransitionItem) => {
    if (!selectedClipIds || selectedClipIds.length === 0) {
      showToast(
        t`Select a clip on the timeline or drag this transition onto a cut`,
        "info",
      );
      return;
    }

    let updatedClips = [...timeline.clips];
    let newTransitions = [...(timeline.transitions || [])];

    selectedClipIds.forEach((selectedId) => {
      const targetClip = updatedClips.find((c) => c.id === selectedId);
      if (!targetClip) return;

      const candidateClips = updatedClips
        .filter(
          (c) =>
            c.trackId === targetClip.trackId &&
            c.id !== targetClip.id &&
            c.startTime < targetClip.startTime,
        )
        .sort(
          (a, b) =>
            b.startTime + b.duration - (a.startTime + a.duration),
        );

      const precedingClip = candidateClips[0] || null;

      if (precedingClip) {
        updatedClips = updatedClips.map((c) => {
          if (c.id === targetClip.id) {
            return {
              ...c,
              transitionIn: item.shader,
              fadeIn: selectedDuration,
              prevClip: precedingClip,
            };
          }
          if (c.id === precedingClip.id) {
            return {
              ...c,
              transitionOut: item.shader,
              fadeOut: selectedDuration,
            };
          }
          return c;
        });

        const cutTime = precedingClip.startTime + precedingClip.duration;
        newTransitions = newTransitions.filter(
          (t) =>
            !(
              t.fromClipId === precedingClip.id &&
              t.toClipId === targetClip.id
            ),
        );
        newTransitions.push({
          id: crypto.randomUUID(),
          trackId: targetClip.trackId,
          fromClipId: precedingClip.id,
          toClipId: targetClip.id,
          type: item.shader,
          duration: selectedDuration,
          startTime: cutTime - selectedDuration / 2,
        });
      } else {
        updatedClips = updatedClips.map((c) => {
          if (c.id === targetClip.id) {
            return {
              ...c,
              transitionIn: item.shader,
              fadeIn: selectedDuration,
              prevClip: undefined,
            };
          }
          return c;
        });
      }
    });

    setTimeline({
      ...timeline,
      clips: updatedClips,
      transitions: newTransitions,
    });

    setAppliedShader(item.shader);
    setTimeout(() => setAppliedShader(null), 1800);
    showToast(t`Applied ${item.name} transition to selected clip`, "success");
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-navidark-900 overflow-hidden select-none text-xs">
      {/* Header with Title & Quick info */}
      <div className="p-3 border-b border-zinc-200 dark:border-navidark-700 space-y-2.5 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-md bg-navi-50 dark:bg-navi-900/40 text-navi">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-bold text-zinc-900 dark:text-zinc-100 text-sm leading-tight">
                <Trans>Transitions</Trans>
              </h3>
              <p className="text-[10px] text-zinc-500 dark:text-zinc-400">
                <Trans>Drag to cuts on timeline or click to apply</Trans>
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1 bg-zinc-100 dark:bg-navidark-800 px-2 py-1 rounded border border-zinc-200 dark:border-navidark-700">
            <Clock className="w-3 h-3 text-zinc-400" />
            <select
              value={selectedDuration}
              onChange={(e) => setSelectedDuration(parseFloat(e.target.value))}
              className="bg-transparent text-[11px] font-mono text-zinc-800 dark:text-zinc-200 outline-none cursor-pointer"
              title="Default transition duration"
            >
              <option value={0.5}>0.5s</option>
              <option value={1.0}>1.0s</option>
              <option value={1.5}>1.5s</option>
              <option value={2.0}>2.0s</option>
            </select>
          </div>
        </div>

        {/* Search Bar */}
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            type="text"
            placeholder={t`Search transitions...`}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-700 rounded-md text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 outline-none focus:border-navi transition-colors"
          />
        </div>

        {/* Category Pill Filters */}
        <div className="flex items-center gap-1 overflow-x-auto custom-scrollbar pb-0.5">
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              className={`px-2.5 py-1 rounded-full text-[10px] font-medium whitespace-nowrap transition-colors ${
                activeCategory === cat
                  ? "bg-navi text-white shadow-sm"
                  : "bg-zinc-100 dark:bg-navidark-800 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-navidark-700"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Grid of Transition Cards */}
      <div className="flex-1 p-3 overflow-y-auto custom-scrollbar space-y-2.5 min-h-0">
        {filteredTransitions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-zinc-400 text-center space-y-2">
            <Film className="w-8 h-8 opacity-30" />
            <p className="text-xs"><Trans>No transitions found for "{searchQuery}"</Trans></p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-2.5">
            {filteredTransitions.map((item) => {
              const isHovered = previewShader === item.shader;
              const isJustApplied = appliedShader === item.shader;

              return (
                <div
                  key={item.shader}
                  draggable={true}
                  onDragStart={(e) => {
                    const dragPayload = JSON.stringify({
                      type: "transition",
                      shader: item.shader,
                      name: item.name,
                      duration: selectedDuration,
                    });
                    e.dataTransfer.setData("text", dragPayload);
                    e.dataTransfer.effectAllowed = "copyMove";
                  }}
                  onMouseEnter={() => setPreviewShader(item.shader)}
                  onMouseLeave={() => setPreviewShader(null)}
                  className={`group relative p-2.5 rounded-lg border transition-all cursor-grab active:cursor-grabbing ${
                    isHovered
                      ? "border-navi/60 bg-navi-50/20 dark:bg-navi-900/20 shadow-sm"
                      : "border-zinc-200 dark:border-navidark-700 hover:border-zinc-300 dark:hover:border-navidark-600 bg-zinc-50/50 dark:bg-navidark-800/60"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    {/* Animated Thumbnail / Preview canvas */}
                    <div className="w-16 h-12 rounded-md overflow-hidden shrink-0 relative shadow-inner bg-zinc-800 border border-black/10">
                      <TransitionThumbnail
                        item={item}
                        isHovered={isHovered}
                      />
                      <div className="absolute inset-0 bg-black/10 group-hover:bg-transparent transition-colors pointer-events-none" />
                      {isHovered && (
                        <div className="absolute bottom-1 right-1 px-1 py-0.2 bg-black/70 backdrop-blur-xs text-[8px] font-mono text-white rounded">
                          <Trans>Preview</Trans>
                        </div>
                      )}
                    </div>

                    {/* Metadata & Controls */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-1 mb-0.5">
                        <h4 className="font-semibold text-zinc-900 dark:text-zinc-100 truncate text-xs group-hover:text-navi transition-colors">
                          {item.name}
                        </h4>
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-200/60 dark:bg-navidark-700 text-zinc-600 dark:text-zinc-400 shrink-0">
                          {item.category}
                        </span>
                      </div>
                      <p className="text-[10px] text-zinc-500 dark:text-zinc-400 line-clamp-1 leading-relaxed">
                        {item.description}
                      </p>

                      {/* Quick Apply / Status Bar */}
                      <div className="mt-1.5 flex items-center justify-between text-[10px]">
                        <span className="text-zinc-400 text-[9px] flex items-center gap-1 font-mono">
                          <Clock className="w-2.5 h-2.5" />
                          {selectedDuration.toFixed(1)}s
                        </span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleApplyToSelected(item);
                          }}
                          className={`px-2 py-0.5 rounded font-medium transition-all flex items-center gap-1 ${
                            isJustApplied
                              ? "bg-navi-500 text-white"
                              : selectedClipIds.length > 0
                              ? "bg-navi text-white hover:bg-navi-600 active:scale-95"
                              : "bg-zinc-200 dark:bg-navidark-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-300 dark:hover:bg-navidark-600"
                          }`}
                          title={
                            selectedClipIds.length > 0
                              ? t`Apply to selected clip`
                              : t`Select clip or drag to cut`
                          }
                        >
                          {isJustApplied ? (
                            <>
                              <Check className="w-3 h-3" /> <Trans>Applied</Trans>
                            </>
                          ) : (
                            <>
                              <Play className="w-2.5 h-2.5" /> <Trans>Apply</Trans>
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer Instructions */}
      <div className="p-2.5 border-t border-zinc-200 dark:border-navidark-700 bg-zinc-50 dark:bg-navidark-800 text-[10px] text-zinc-500 dark:text-zinc-400 flex items-center justify-between shrink-0">
        <span><Lightbulb className="w-3.5 h-3.5" /><Trans>Drag card between 2 clips on timeline</Trans></span>
        <span className="font-mono">{filteredTransitions.length} <Trans>presets</Trans></span>
      </div>
    </div>
  );
}

function TransitionThumbnail({
  item,
  isHovered,
}: {
  item: TransitionItem;
  isHovered: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animFrameRef = useRef<number | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let progress = isHovered ? 0 : 0.5;
    let forward = true;
    let lastTime = performance.now();

    const render = (time: number) => {
      const dt = (time - lastTime) / 1000;
      lastTime = time;

      if (isHovered) {
        // Ping-pong progress between 0 and 1
        const speed = 0.8;
        if (forward) {
          progress += dt * speed;
          if (progress >= 1.0) {
            progress = 1.0;
            forward = false;
          }
        } else {
          progress -= dt * speed;
          if (progress <= 0.0) {
            progress = 0.0;
            forward = true;
          }
        }
      } else {
        progress = 0.5;
      }

      const w = canvas.width;
      const h = canvas.height;

      // Draw "From" background (Clip A)
      const gradA = ctx.createLinearGradient(0, 0, w, h);
      gradA.addColorStop(0, item.colorFrom);
      gradA.addColorStop(1, "#18181B");
      ctx.fillStyle = gradA;
      ctx.fillRect(0, 0, w, h);

      // Label A
      ctx.fillStyle = "rgba(255, 255, 255, 0.4)";
      ctx.font = "bold 9px sans-serif";
      ctx.fillText("A", 6, 12);

      // Transition simulation on canvas
      ctx.save();
      if (item.shader === "glsl-crossfade") {
        ctx.globalAlpha = progress;
        const gradB = ctx.createLinearGradient(0, 0, w, h);
        gradB.addColorStop(0, item.colorTo);
        gradB.addColorStop(1, "#27272A");
        ctx.fillStyle = gradB;
        ctx.fillRect(0, 0, w, h);
      } else if (item.shader === "glsl-wipe") {
        ctx.beginPath();
        ctx.rect(0, 0, w * progress, h);
        ctx.clip();
        const gradB = ctx.createLinearGradient(0, 0, w, h);
        gradB.addColorStop(0, item.colorTo);
        gradB.addColorStop(1, "#27272A");
        ctx.fillStyle = gradB;
        ctx.fillRect(0, 0, w, h);
      } else if (item.shader === "glsl-slide") {
        const slideOffset = (1 - progress) * w;
        ctx.save();
        ctx.translate(-slideOffset, 0);
        const gradB = ctx.createLinearGradient(0, 0, w, h);
        gradB.addColorStop(0, item.colorTo);
        gradB.addColorStop(1, "#27272A");
        ctx.fillStyle = gradB;
        ctx.fillRect(0, 0, w, h);
        ctx.restore();
      } else if (item.shader === "glsl-dissolve" || item.shader === "glsl-pixelize") {
        ctx.globalAlpha = progress;
        const gradB = ctx.createLinearGradient(0, 0, w, h);
        gradB.addColorStop(0, item.colorTo);
        gradB.addColorStop(1, "#27272A");
        ctx.fillStyle = gradB;
        ctx.fillRect(0, 0, w, h);

        // Add dither blocks
        ctx.fillStyle = item.colorFrom;
        const blockSize = item.shader === "glsl-pixelize" ? 6 : 3;
        for (let x = 0; x < w; x += blockSize) {
          for (let y = 0; y < h; y += blockSize) {
            if (Math.sin(x * 12.9898 + y * 78.233) > progress * 2 - 1) {
              ctx.fillRect(x, y, blockSize, blockSize);
            }
          }
        }
      } else {
        // Stylized/Dreamy/Burn/Multiply
        ctx.globalAlpha = progress;
        const gradB = ctx.createLinearGradient(0, 0, w, h);
        gradB.addColorStop(0, item.colorTo);
        gradB.addColorStop(1, "#3F3F46");
        ctx.fillStyle = gradB;
        ctx.fillRect(0, 0, w, h);
      }
      ctx.restore();

      // Label B
      ctx.fillStyle = "rgba(255, 255, 255, 0.7)";
      ctx.font = "bold 9px sans-serif";
      ctx.fillText("B", w - 12, h - 5);

      if (isHovered) {
        animFrameRef.current = requestAnimationFrame(render);
      }
    };

    render(performance.now());

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [isHovered, item]);

  return (
    <canvas
      ref={canvasRef}
      width={64}
      height={48}
      className="w-full h-full object-cover block"
    />
  );
}
