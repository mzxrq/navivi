import { invoke } from "@tauri-apps/api/core";
import { useState, useEffect, useRef } from "react";
import { open, save } from "@tauri-apps/plugin-dialog";
import { MapPin, Layers, ChevronLeft, ChevronRight, ChevronUp, ChevronDown, X, Edit2, Image as ImageIcon, Mic, Trash2, Info, } from "lucide-react";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { ScrubInput } from "../../ui/ScrubInput";

export function Sidebar() {
  const { showToast } = useUI();
  const {
    waypoints,
    setWaypoints,
    updateWaypoint,
    settings,
    metadata,
    updateMetadata,
    saveProject,
  } = useWorkspace();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [isListEditMode, setIsListEditMode] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        sidebarRef.current &&
        !sidebarRef.current.contains(event.target as Node)
      ) {
        setIsListEditMode(false);
        setShowClearConfirm(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleRenderVideo = async () => {
    if (waypoints.length === 0) {
      showToast("Cannot render: Please add at least one waypoint.", "error");
      return;
    }
    const invalidWps = waypoints.filter(
      (wp) => !wp.narration.trim() || !wp.images || wp.images.length === 0,
    );

    if (invalidWps.length > 0) {
      const names = invalidWps.map((w) => w.name).join(", ");
      showToast(
        `Validation Failed: Missing image or script in [${names}]`,
        "error",
      );
      return;
    }

    //////////////////////////////////////////////////////

    if (
      !confirm(
        "Ready to render? This will generate the configuration for the backend.",
      )
    )
      return;
    await saveProject();

    try {
      const configPath = `${metadata.directory_path}/job_config.json`;
      const response = await invoke("trigger_render_pipeline", {
        payload: JSON.stringify({ config_path: configPath }),
      });
      alert(response);
    } catch (error) {
      alert(`Error from Rust: ${error}`);
    }
  };

  const handleImageSelect = async (
    id: string,
    currentImages: string[] = [],
  ) => {
    if (currentImages.length >= 3) {
      showToast("Maximum of 3 images allowed per waypoint.", "error");
      return;
    }

    const selectedPaths = await open({
      multiple: true,
      filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg"] }],
    });

    if (selectedPaths) {
      const pathsArray = Array.isArray(selectedPaths)
        ? selectedPaths
        : [selectedPaths];
      const newImages = [...currentImages, ...pathsArray].slice(0, 3);
      updateWaypoint(id, { images: newImages });
    }
  };

  const moveWaypointUp = (index: number) => {
    if (index === 0) return;
    const newWaypoints = [...waypoints];
    [newWaypoints[index - 1], newWaypoints[index]] = [
      newWaypoints[index],
      newWaypoints[index - 1],
    ];
    setWaypoints(newWaypoints);
  };

  const moveWaypointDown = (index: number) => {
    if (index === waypoints.length - 1) return;
    const newWaypoints = [...waypoints];
    [newWaypoints[index + 1], newWaypoints[index]] = [
      newWaypoints[index],
      newWaypoints[index + 1],
    ];
    setWaypoints(newWaypoints);
  };

  if (editingId) {
    const wp = waypoints.find((w) => w.id === editingId);
    if (!wp) return null;
    const wpImages = wp.images || [];

    return (
      <aside className="w-[340px] bg-white dark:bg-zinc-950 border-r border-zinc-200 dark:border-white/[0.08] flex flex-col p-6 h-full select-none z-10 relative shadow-xl transition-colors gap-6">
        <div className="flex-1 flex flex-col min-h-0 space-y-6">
          <button
            onClick={() => setEditingId(null)}
            className="flex items-center gap-2 text-xs font-semibold text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300 transition-colors w-fit"
          >
            <ChevronLeft className="w-4 h-4" /> Back to List
          </button>

          <div className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest px-1">
                Location Name
              </label>
              <input
                type="text"
                value={wp.name}
                onChange={(e) =>
                  updateWaypoint(wp.id, { name: e.target.value })
                }
                className="w-full bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-white/10 rounded-xl px-3 py-2 text-sm text-zinc-900 dark:text-zinc-200 outline-none focus:border-zinc-400 dark:focus:border-zinc-500 transition-colors"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest px-1 flex items-center gap-1.5">
                <Mic className="w-3.5 h-3.5" /> AI Script
              </label>
              <textarea
                value={wp.narration}
                onChange={(e) =>
                  updateWaypoint(wp.id, { narration: e.target.value })
                }
                placeholder="Type what the AI voice should say here..."
                className="w-full bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-white/10 rounded-xl px-3 py-2 text-sm text-zinc-900 dark:text-zinc-200 outline-none focus:border-zinc-400 dark:focus:border-zinc-500 transition-colors resize-none h-24 custom-scrollbar"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest px-1 flex items-center gap-1.5">
                <ImageIcon className="w-3.5 h-3.5" /> Pop-up Pictures (
                {wpImages.length}/3)
              </label>

              <div className="flex flex-col gap-2">
                {wpImages.map((img, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-white/10 rounded-lg px-3 py-2 text-xs text-zinc-600 dark:text-zinc-400"
                  >
                    <span className="truncate max-w-[200px]" title={img}>
                      {img.split(/[/\\]/).pop()}
                    </span>
                    <button
                      onClick={() => {
                        const newImages = wpImages.filter((_, i) => i !== idx);
                        updateWaypoint(wp.id, { images: newImages });
                      }}
                      className="text-red-500 hover:text-red-600 transition-colors"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}

                {wpImages.length < 3 && (
                  <button
                    onClick={() => handleImageSelect(wp.id, wpImages)}
                    className="w-full bg-zinc-50 dark:bg-zinc-900/50 hover:bg-zinc-100 dark:hover:bg-zinc-800/80 border border-zinc-300 dark:border-white/10 border-dashed rounded-xl px-3 py-3 text-xs font-medium text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 transition-all flex items-center justify-center gap-2"
                  >
                    Click to add images...
                  </button>
                )}

                {/* NEW: PIP vs Fullscreen Toggle */}
                {wpImages.length > 0 && (
                  <div className="flex gap-2 mt-1">
                    <button
                      onClick={() =>
                        updateWaypoint(wp.id, { imageDisplay: "pip" })
                      }
                      className={`flex-1 py-1.5 text-[10px] font-bold uppercase tracking-wider rounded-md transition-all ${wp.imageDisplay !== "fullscreen" ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20" : "bg-zinc-100 dark:bg-zinc-800/50 text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"}`}
                    >
                      PIP Overlay
                    </button>
                    <button
                      onClick={() =>
                        updateWaypoint(wp.id, { imageDisplay: "fullscreen" })
                      }
                      className={`flex-1 py-1.5 text-[10px] font-bold uppercase tracking-wider rounded-md transition-all ${wp.imageDisplay === "fullscreen" ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20" : "bg-zinc-100 dark:bg-zinc-800/50 text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"}`}
                    >
                      Fullscreen
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Timing & Frame Rate Overrides */}
            <div className="space-y-3 pt-2 border-t border-zinc-200 dark:border-white/10">
              <h4 className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">
                Timing & FPS Override
              </h4>
              
              <div className="space-y-2">
                <ScrubInput 
                  label="Hold Duration"
                  value={wp.duration || settings.duration_seconds}
                  onChange={(v) => updateWaypoint(wp.id, { duration: v })}
                  min={1} max={15} step={0.5} suffix="s"
                  tooltip="How long the video pauses on this waypoint while the AI narration plays."
                />
                
                <ScrubInput 
                  label="Frame Rate"
                  value={wp.fps || settings.fps}
                  onChange={(v) => updateWaypoint(wp.id, { fps: v })}
                  min={1} max={60} step={1} suffix=" FPS"
                  tooltip="Overrides the global frame rate for this specific location."
                />
              </div>
            </div>

        <div className="shrink-0">
          <button
            onClick={() => {
              if (confirm(`Remove ${wp.name}?`)) {
                setWaypoints(waypoints.filter((w) => w.id !== wp.id));
                setEditingId(null);
              }
            }}
            className="w-full py-2.5 rounded-xl border border-transparent text-zinc-500 dark:text-zinc-500 text-xs font-semibold hover:border-red-500/20 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/5 transition-all flex justify-center items-center gap-2"
          >
            <Trash2 className="w-4 h-4" /> Remove Waypoint
          </button>
        </div>
      </aside>
    );
  }

  return (
    <aside
      ref={sidebarRef}
      className="w-[340px] bg-white dark:bg-zinc-950 border-r border-zinc-200 dark:border-white/[0.08] flex flex-col p-6 h-full select-none z-10 relative shadow-xl transition-colors gap-6"
    >
      <div className="flex-1 flex flex-col min-h-0 space-y-3">
        <div className="flex justify-between items-center px-1 shrink-0">
          <h2 className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-2">
            <Layers className="w-3.5 h-3.5" /> Waypoints ({waypoints.length})
          </h2>
          {waypoints.length > 0 && (
            <button
              onClick={() => {
                setIsListEditMode(!isListEditMode);
                setShowClearConfirm(false);
              }}
              className={`text-[10px] font-semibold transition-colors px-2 py-0.5 rounded-md ${isListEditMode ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-200" : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300"}`}
            >
              {isListEditMode ? "Done" : "Edit"}
            </button>
          )}
        </div>

        {waypoints.length === 0 ? (
          <div className="group rounded-2xl border border-dashed border-zinc-300 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/20 p-8 text-center shrink-0 transition-colors">
            <p className="text-sm font-medium text-zinc-500">
              Click the map to drop markers
            </p>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar space-y-2">
            {isListEditMode && (
              <div className="relative mb-3 shrink-0">
                {!showClearConfirm ? (
                  <button
                    onClick={() => setShowClearConfirm(true)}
                    className="w-full py-2.5 rounded-xl border border-red-200 dark:border-red-500/20 bg-red-50 dark:bg-red-500/5 text-red-600 dark:text-red-400 text-xs font-bold hover:bg-red-100 dark:hover:bg-red-500/10 transition-colors flex items-center justify-center gap-2"
                  >
                    <Trash2 className="w-3.5 h-3.5" /> Clear All
                  </button>
                ) : (
                  <div className="w-full py-2 px-3 rounded-xl border border-red-300 dark:border-red-500/40 bg-white dark:bg-zinc-900 shadow-sm flex items-center justify-between animate-in fade-in zoom-in-95 duration-200">
                    <span className="text-[11px] font-semibold text-zinc-800 dark:text-zinc-300">
                      Are you sure?
                    </span>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setShowClearConfirm(false)}
                        className="text-[10px] font-medium text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300 px-2 py-1"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => {
                          setWaypoints([]);
                          setIsListEditMode(false);
                          setShowClearConfirm(false);
                        }}
                        className="text-[10px] font-bold text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-500/10 px-2.5 py-1 rounded-md hover:bg-red-100 dark:hover:bg-red-500/20 transition-colors"
                      >
                        Confirm
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {waypoints.map((wp, i) => (
              <div key={wp.id} className="flex items-center gap-2 group">
                {isListEditMode && (
                  <button
                    onClick={() =>
                      setWaypoints(waypoints.filter((w) => w.id !== wp.id))
                    }
                    className="shrink-0 p-1.5 text-red-500 dark:text-red-400/70 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-lg transition-all animate-in slide-in-from-left-2"
                  >
                    <X className="w-4 h-4" />
                  </button>
                )}

                <div className="flex-1 flex items-center justify-between bg-zinc-50 dark:bg-zinc-900/30 border border-zinc-200 dark:border-white/5 p-2.5 rounded-xl hover:bg-zinc-100 dark:hover:bg-zinc-900/80 transition-colors overflow-hidden shadow-sm dark:shadow-none">
                  <div className="flex items-center gap-2.5 overflow-hidden">
                    <div className="w-6 h-6 rounded-md bg-zinc-200 dark:bg-zinc-800/50 text-zinc-600 dark:text-zinc-500 flex items-center justify-center text-xs font-bold shrink-0 transition-colors">
                      {i + 1}
                    </div>
                    <div className="flex flex-col overflow-hidden">
                      <span
                        className="text-xs font-medium text-zinc-800 dark:text-zinc-300 truncate"
                        title={wp.name}
                      >
                        {wp.name}
                      </span>
                      <div className="flex gap-1.5 mt-0.5">
                        {wp.images && wp.images.length > 0 && (
                          <div className="flex items-center gap-1 text-zinc-400 dark:text-zinc-500">
                            <ImageIcon className="w-3 h-3" />
                            <span className="text-[9px] font-bold">
                              {wp.images.length}
                            </span>
                          </div>
                        )}
                        {wp.narration && (
                          <Mic className="w-3 h-3 text-zinc-400 dark:text-zinc-500" />
                        )}
                      </div>
                    </div>
                  </div>

                  {!isListEditMode && (
                    <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition-all shrink-0">
                      <button
                        onClick={() => moveWaypointUp(i)}
                        disabled={i === 0}
                        className="p-1.5 hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-500 disabled:opacity-30 disabled:cursor-not-allowed"
                      >
                        <ChevronUp className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => moveWaypointDown(i)}
                        disabled={i === waypoints.length - 1}
                        className="p-1.5 hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-500 disabled:opacity-30 disabled:cursor-not-allowed"
                      >
                        <ChevronDown className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => setEditingId(wp.id)}
                        className="p-1.5 hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-500"
                      >
                        <Edit2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="shrink-0 pt-2 flex flex-col gap-2">
        <button
          onClick={handleRenderVideo}
          className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl bg-zinc-900 dark:bg-zinc-900 hover:bg-zinc-800 text-zinc-100 dark:text-zinc-400 dark:hover:text-zinc-200 border border-transparent dark:border-white/5 dark:hover:border-white/10 font-medium text-sm transition-all disabled:opacity-40 disabled:pointer-events-none shadow-md dark:shadow-none"
          disabled={waypoints.length === 0 || isListEditMode}
        >
          Render Video
          <ChevronRight className="w-4 h-4 opacity-50" />
        </button>
      </div>
    </aside>
  );
}
