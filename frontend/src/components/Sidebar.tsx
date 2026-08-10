import { invoke } from "@tauri-apps/api/core";
import { useState, useEffect, useRef } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import {
  MapPin,
  Layers,
  ChevronRight,
  X,
  Edit2,
  ChevronLeft,
  Image as ImageIcon,
  Mic,
  Trash2,
} from "lucide-react";
import { useWorkspace } from "../hooks/useWorkspace";

export function Sidebar() {
  const {
    projectName,
    setProjectName,
    routeFile,
    waypoints,
    setWaypoints,
    updateWaypoint,
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
    if (
      !confirm(
        "Ready to render? This will generate the configuration for the backend.",
      )
    )
      return;
    const jobConfig = {
      project_name: projectName,
      source_files: { gps_route: routeFile },
      waypoints: waypoints.map((wp) => ({
        lat: wp.lat,
        lng: wp.lng,
        label: wp.name,
        freeze_seconds: 3.0,
        popup_image: wp.image,
        narration: wp.narration,
      })),
    };
    
    try {
      const response = await invoke('trigger_render_pipeline', {
        payload: JSON.stringify(jobConfig, null, 2)
      });
      alert(response);
    } catch (error) {
      alert('Error from Rust: ${error}');
    }
  };

  const handleImageSelect = async (id: string) => {
    const selectedPath = await open({
      multiple: false,
      filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg"] }],
    });
    if (typeof selectedPath === "string")
      updateWaypoint(id, { image: selectedPath });
  };

  if (editingId) {
    const wp = waypoints.find((w) => w.id === editingId);
    if (!wp) return null;

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
                <ImageIcon className="w-3.5 h-3.5" /> Pop-up Picture
              </label>
              <button
                onClick={() => handleImageSelect(wp.id)}
                className="w-full bg-zinc-50 dark:bg-zinc-900/50 hover:bg-zinc-100 dark:hover:bg-zinc-800/80 border border-zinc-300 dark:border-white/10 border-dashed rounded-xl px-3 py-3 text-xs font-medium text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 transition-all flex items-center justify-center gap-2 truncate"
              >
                {wp.image ? (
                  <span className="truncate max-w-[200px]" title={wp.image}>
                    Selected: {wp.image.split("\\").pop()}
                  </span>
                ) : (
                  "Click to browse local files..."
                )}
              </button>
            </div>
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
      <div className="shrink-0 flex items-center gap-3.5">
        <div className="w-10 h-10 rounded-xl bg-zinc-100 dark:bg-zinc-900 flex items-center justify-center border border-zinc-200 dark:border-white/5 shadow-sm transition-colors">
          <MapPin className="w-5 h-5 text-zinc-700 dark:text-zinc-300" />
        </div>
        <div>
          <div className="flex flex-col flex-1">
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              className="bg-transparent border-b border-transparent focus:border-zinc-400 dark:focus:border-zinc-500 hover:border-zinc-300 dark:hover:border-zinc-700 outline-none text-base font-semibold text-zinc-900 dark:text-zinc-200 tracking-tight transition-all w-full px-1 -ml-1 rounded-sm"
              placeholder="Project Name"
            />
            <p className="text-[10px] text-zinc-500 font-medium tracking-widest uppercase px-1 -ml-1 mt-0.5">
              Workspace Settings
            </p>
          </div>
        </div>
      </div>

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
                        {wp.image && (
                          <ImageIcon className="w-3 h-3 text-zinc-400 dark:text-zinc-500" />
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
                        onClick={() => setEditingId(wp.id)}
                        className="p-1.5 hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-500 dark:text-zinc-500 hover:text-zinc-900 dark:hover:text-white rounded-md transition-all"
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

      <div className="shrink-0 pt-2">
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
