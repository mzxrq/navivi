import { useState, useEffect } from "react";
import {
  ChevronLeft,
  ChevronUp,
  ChevronDown,
  ImageIcon,
  X,
  Trash2,
  MapPin,
  Pencil,
  MapPinned,
  MapPinPlus,
  LinkIcon,
  UnlinkIcon,
  CornerDownLeft,
  Mic,
  Info,
  Check,
} from "../../../components/ui/icons";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { invoke, convertFileSrc } from "@tauri-apps/api/core";
import { ScriptInput } from "../../../components/ui/ScriptInput";
import { open } from "@tauri-apps/plugin-dialog";
import {
  checkModelExists,
  generateWaypointScriptStream,
} from "../../../services/ollamaApi";

const cameraPans = [
  { value: "none", label: "None" },
  { value: "pan-left", label: "Pan Left" },
  { value: "pan-right", label: "Pan Right" },
  { value: "pan-up", label: "Pan Up" },
  { value: "pan-down", label: "Pan Down" },
  { value: "zoom-in", label: "Zoom In" },
  { value: "zoom-out", label: "Zoom Out" },
];

export function WaypointEditor({
  wpId,
  onClose,
}: {
  wpId: string;
  onClose: () => void;
}) {
  const {
    waypoints,
    setWaypoints,
    updateWaypoint,
    setIsDirty,
    setActiveWaypointId,
    metadata,
  } = useWorkspace();
  const { showToast } = useUI();

  const wp = waypoints.find((w) => w.id === wpId);
  const wpIndex = waypoints.findIndex((w) => w.id === wpId);

  const [showArriving, setShowArriving] = useState(
    !!(wp?.arrivingNarration && wp.arrivingNarration.length > 0)
  );
  const [showAttraction, setShowAttraction] = useState(
    !!(wp?.attractionNarration && wp.attractionNarration.length > 0)
  );
  const [activeTab, setActiveTab] = useState<"scripts" | "images">("scripts");
  const [isCollapsed, setIsCollapsed] = useState(false);

  // Auto-expand if the user clicks a new waypoint
  useEffect(() => {
    setIsCollapsed(false);
  }, [wpId]);

  if (!wp) return null;

  const wpImages = wp.images || [];
  const imagePans = wp.imagePans || [];

  const removeWaypoint = (id: string) => {
    setWaypoints(waypoints.filter((w) => w.id !== id));
    setIsDirty(true);
    setActiveWaypointId(null);
  };

  const handleImageSelect = async () => {
    try {
      const selected = await open({
        multiple: true,
        filters: [{ name: "Images", extensions: ["svg", "png", "jpg", "jpeg"] }],
      });
      if (selected && Array.isArray(selected)) {
        const currentImages = wp.images || [];
        const currentPans = wp.imagePans || [];
        const newImages = [...currentImages, ...selected].slice(0, 3);
        const newPans = [
          ...currentPans,
          ...selected.map(() => "none"),
        ].slice(0, 3);
        updateWaypoint(wp.id, { images: newImages, imagePans: newPans });
      } else if (selected && typeof selected === "string") {
        const currentImages = wp.images || [];
        const currentPans = wp.imagePans || [];
        if (currentImages.length < 3) {
          updateWaypoint(wp.id, {
            images: [...currentImages, selected],
            imagePans: [...currentPans, "none"],
          });
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  const removeImage = (idx: number) => {
    const currentImages = [...(wp.images || [])];
    const currentPans = [...(wp.imagePans || [])];
    currentImages.splice(idx, 1);
    currentPans.splice(idx, 1);
    updateWaypoint(wp.id, { images: currentImages, imagePans: currentPans });
  };

  const updateImagePan = (idx: number, pan: string) => {
    const currentPans = [...(wp.imagePans || [])];
    currentPans[idx] = pan;
    updateWaypoint(wp.id, { imagePans: currentPans });
  };

  const handleGenerateScript = async (
    type: "arriving" | "attraction",
    prompt: string,
    engine: string
  ) => {
    if (engine === "ollama") {
      const hasModel = await checkModelExists("llama3.1");
      if (!hasModel) {
        showToast("Ollama is not running or llama3.1 is missing.", "error");
        return;
      }
    }

    try {
      updateWaypoint(wp.id, { isGeneratingScript: true });

      if (type === "arriving") {
        updateWaypoint(wp.id, { arrivingNarration: "" });
      } else {
        updateWaypoint(wp.id, { attractionNarration: "" });
      }

      await generateWaypointScriptStream(
        wp.name,
        prompt,
        engine,
        metadata.theme || "",
        (chunk) => {
          setWaypoints((prev) =>
            prev.map((w) => {
              if (w.id !== wp.id) return w;
              if (type === "arriving") {
                return {
                  ...w,
                  arrivingNarration: (w.arrivingNarration || "") + chunk,
                };
              } else {
                return {
                  ...w,
                  attractionNarration: (w.attractionNarration || "") + chunk,
                };
              }
            })
          );
        },
        wp.lat,
        wp.lng
      );
    } catch (err: any) {
      console.error("Script generation failed:", err);
      showToast(err.message || "Failed to generate script", "error");
    } finally {
      updateWaypoint(wp.id, { isGeneratingScript: false });
    }
  };

  // Node vs Stop-by vs Start vs Dest logic
  const isStart = wpIndex === 0;
  const isDest = wpIndex === waypoints.length - 1;
  const isStopBy = wp.isStopBy; // undefined or true = stop-by, false = node

  return (
    <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-50 pointer-events-none w-full px-4 flex flex-col items-center">
      <div
        className={`flex flex-col bg-white/95 dark:bg-navidark-800/95 backdrop-blur-xl rounded-3xl shadow-[0_-10px_60px_-15px_rgba(0,0,0,0.5)] border-2 border-zinc-900 dark:border-white/20 select-none transition-all duration-400 ease-[cubic-bezier(0.16,1,0.3,1)] pointer-events-auto ${
          isCollapsed ? "w-[300px] h-[56px]" : "w-full max-w-6xl h-[520px] max-h-[50vh]"
        } overflow-hidden`}
      >
        {isCollapsed ? (
          <div 
            className="cursor-pointer flex items-center justify-between gap-3 p-3 px-5 h-full w-full hover:bg-zinc-50 dark:hover:bg-navidark-700 transition-colors"
            onClick={() => setIsCollapsed(false)}
          >
            <div className="flex flex-col min-w-0 pointer-events-none">
              <span className="text-[9px] font-bold text-navi dark:text-navi-400 uppercase tracking-[0.2em] opacity-80 mb-0.5">
                Editing Waypoint
              </span>
              <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 truncate flex items-center gap-2">
                <MapPin className="w-3.5 h-3.5 text-navi" /> {wp.name}
              </h2>
            </div>
            <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
              <button
                onClick={() => setIsCollapsed(false)}
                className="p-1.5 rounded-lg hover:bg-zinc-200 dark:hover:bg-navidark-400 text-zinc-600 dark:text-zinc-300 transition-colors"
              >
                <ChevronUp className="w-5 h-5 stroke-[2.5]" />
              </button>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/30 text-zinc-600 hover:text-red-600 dark:hover:text-red-400 transition-colors"
              >
                <X className="w-5 h-5 stroke-[2.5]" />
              </button>
            </div>
          </div>
        ) : (
          <div className="flex-1 flex flex-row min-w-0 h-full overflow-hidden items-stretch text-zinc-900 dark:text-zinc-100">
            {/* --- LEFT COLUMN --- */}
            <div className="w-[35%] min-w-[320px] max-w-[420px] shrink-0 border-r-2 border-zinc-900 dark:border-white/20 flex flex-col overflow-y-auto scrollbar-none">
              
              {/* TOP: Location Name */}
              <div className="p-6 pb-5 flex flex-col gap-1">
                <input
                  type="text"
                  value={wp.name}
                  onChange={(e) => updateWaypoint(wp.id, { name: e.target.value })}
                  className="w-full bg-transparent border-b-4 border-zinc-900 dark:border-white text-3xl font-black focus:outline-none focus:border-navi pb-1 truncate"
                  placeholder="Location Name"
                />
                <span className="text-[11px] font-medium text-zinc-600 dark:text-zinc-400 pl-1 mt-1">
                  Get name from coordinate
                </span>

                <div className="mt-6 flex flex-col gap-4">
                  {/* Skip Asset Generation Toggle */}
                  <label className="flex items-start gap-3 cursor-pointer group">
                    <div className="relative inline-flex items-center mt-0.5">
                      <input 
                        type="checkbox" 
                        className="sr-only peer" 
                        checked={wp.skipAssetGeneration || false}
                        onChange={(e) => updateWaypoint(wp.id, { skipAssetGeneration: e.target.checked })}
                      />
                      <div className="w-10 h-6 bg-zinc-200 peer-focus:outline-none rounded-full peer dark:bg-navidark-600 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-zinc-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-navi-500 border-2 border-zinc-900 dark:border-white/50"></div>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="text-xs font-bold">Will be generated in asset</span>
                      <span className="text-[9px] font-medium text-red-500 leading-tight">
                        // will be skipped (only used when forcing path into another way but not wanting to visit anything on this point)
                      </span>
                    </div>
                  </label>

                  {/* Pause At Waypoint Toggle */}
                  <label className="flex items-center gap-3 cursor-pointer group">
                    <div className="relative inline-flex items-center">
                      <input 
                        type="checkbox" 
                        className="sr-only peer" 
                        checked={wp.pauseAtWaypoint || false}
                        onChange={(e) => updateWaypoint(wp.id, { pauseAtWaypoint: e.target.checked })}
                      />
                      <div className="w-10 h-6 bg-zinc-200 peer-focus:outline-none rounded-full peer dark:bg-navidark-600 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-zinc-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-navi-500 border-2 border-zinc-900 dark:border-white/50"></div>
                    </div>
                    <span className="text-xs font-bold text-zinc-400 dark:text-zinc-500">i dont know what to put here</span>
                  </label>
                </div>
              </div>

              {/* DIVIDER */}
              <div className="border-t-2 border-zinc-900 dark:border-white/20" />

              {/* BOTTOM: Action */}
              <div className="p-6 pt-5 flex flex-col gap-5 flex-1">
                <h3 className="text-base font-black uppercase">Action</h3>

                {/* Custom Marker */}
                <div className="flex items-center gap-4">
                  <div className="w-14 h-14 border-2 border-zinc-900 dark:border-white/50 rounded-lg flex items-center justify-center shrink-0 bg-zinc-50 dark:bg-navidark-700/50 relative overflow-hidden group">
                    {wp.customMarker ? (
                      <>
                        <img src={convertFileSrc(wp.customMarker)} alt="Marker" className="w-10 h-10 object-contain" />
                        <button 
                          onClick={() => updateWaypoint(wp.id, { customMarker: undefined })}
                          className="absolute inset-0 bg-black/60 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                          <Trash2 className="w-5 h-5 text-white" />
                        </button>
                      </>
                    ) : (
                      <MapPin className="w-6 h-6 text-zinc-300 dark:text-zinc-600" />
                    )}
                  </div>
                  <div className="flex flex-col gap-2">
                    <span className="text-sm font-bold">Custom Marker</span>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={async () => {
                          const selected = await open({
                            multiple: false,
                            filters: [{ name: "Images", extensions: ["svg", "png", "jpg", "jpeg"] }],
                          });
                          if (selected && typeof selected === "string") {
                            updateWaypoint(wp.id, { customMarker: selected });
                          }
                        }}
                        className="bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 px-3 py-1 rounded-full text-xs font-bold hover:bg-zinc-700 dark:hover:bg-zinc-200 transition-colors"
                      >
                        Select
                      </button>
                      <span className="text-xs font-medium text-zinc-500">
                        {wp.customMarker ? wp.customMarker.split(/[\/]/).pop() : "No file chosen"}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Waypoint Settings */}
                <div className="flex flex-col gap-3 mt-1">
                  <h3 className="text-[13px] font-bold flex items-center gap-1.5">
                    Waypoint settings <Info className="w-3.5 h-3.5 text-zinc-500" />
                  </h3>
                  <div className="flex items-center gap-2 flex-wrap">
                    <button 
                      onClick={() => updateWaypoint(wp.id, { isStopBy: false })}
                      className={`border-2 border-zinc-900 dark:border-white/50 rounded-xl px-3 py-2 text-[11px] font-bold transition-colors ${!isStopBy && !isStart && !isDest ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900' : 'hover:bg-zinc-100 dark:hover:bg-navidark-700'}`}
                    >
                      Node
                    </button>
                    <button 
                      onClick={() => updateWaypoint(wp.id, { isStopBy: true })}
                      className={`border-2 border-zinc-900 dark:border-white/50 rounded-xl px-3 py-2 text-[11px] font-bold transition-colors ${isStopBy && !isStart && !isDest ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900' : 'hover:bg-zinc-100 dark:hover:bg-navidark-700'}`}
                    >
                      Stop-by
                    </button>
                    <div className="h-6 w-[2px] bg-zinc-300 dark:bg-white/10 mx-1" />
                    <button 
                      disabled
                      className={`border-2 border-zinc-900/30 dark:border-white/20 rounded-xl px-3 py-2 text-[11px] font-bold transition-colors ${isStart ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 border-zinc-900 dark:border-white' : 'opacity-50'}`}
                    >
                      Start
                    </button>
                    <button 
                      disabled
                      className={`border-2 border-zinc-900/30 dark:border-white/20 rounded-xl px-3 py-2 text-[11px] font-bold transition-colors ${isDest ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 border-zinc-900 dark:border-white' : 'opacity-50'}`}
                    >
                      Dest
                    </button>
                    
                    <button 
                      onClick={() => removeWaypoint(wp.id)}
                      className="ml-auto border-2 border-red-500 text-red-600 dark:text-red-400 rounded-xl px-3 py-2 text-[11px] font-bold hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                    >
                      Delete
                    </button>
                  </div>
                </div>

              </div>
            </div>

            {/* --- RIGHT COLUMN --- */}
            <div className="flex-1 flex flex-col min-w-0 bg-white dark:bg-navidark-800">
              
              {/* Tabs & Window Controls */}
              <div className="flex border-b-2 border-zinc-900 dark:border-white/20 h-[56px] shrink-0">
                <button
                  onClick={() => setActiveTab("scripts")}
                  className={`px-6 flex items-center justify-center font-black text-sm border-r-2 border-zinc-900 dark:border-white/20 transition-colors ${
                    activeTab === "scripts"
                      ? "bg-zinc-200 dark:bg-zinc-700 text-zinc-900 dark:text-white"
                      : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-navidark-700"
                  }`}
                >
                  Narration Script
                </button>
                <button
                  onClick={() => setActiveTab("images")}
                  className={`px-6 flex items-center justify-center font-black text-sm border-r-2 border-zinc-900 dark:border-white/20 transition-colors ${
                    activeTab === "images"
                      ? "bg-zinc-200 dark:bg-zinc-700 text-zinc-900 dark:text-white"
                      : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-navidark-700"
                  }`}
                >
                  Image
                </button>

                <div className="ml-auto flex items-center px-4 gap-3 border-l-2 border-zinc-900 dark:border-white/20">
                  <button
                    onClick={() => setIsCollapsed(true)}
                    title="Collapse"
                    className="p-1 rounded hover:bg-zinc-200 dark:hover:bg-navidark-600 transition-colors"
                  >
                    <ChevronDown className="w-6 h-6 stroke-[3] text-zinc-700 dark:text-zinc-300" />
                  </button>
                  <button
                    onClick={onClose}
                    title="Close"
                    className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors group"
                  >
                    <X className="w-6 h-6 stroke-[3] text-zinc-700 dark:text-zinc-300 group-hover:text-red-500" />
                  </button>
                </div>
              </div>

              {/* Tab Content */}
              <div className="flex-1 overflow-y-auto custom-scrollbar p-6">
                
                {activeTab === "scripts" && (
                  <div className="space-y-6 max-w-3xl">
                    {/* Arriving Script */}
                    <div className="flex flex-col gap-3">
                      <button 
                        onClick={() => setShowArriving(!showArriving)}
                        className="flex items-center gap-2 group"
                      >
                        <Mic className="w-5 h-5 text-zinc-700 dark:text-zinc-300" />
                        <h3 className="text-sm font-bold">Arriving Script</h3>
                        {showArriving ? (
                          <ChevronUp className="w-5 h-5 ml-2 text-zinc-400 group-hover:text-zinc-700" />
                        ) : (
                          <ChevronDown className="w-5 h-5 ml-2 text-zinc-400 group-hover:text-zinc-700" />
                        )}
                      </button>
                      
                      {showArriving && (
                        <div className="pl-7">
                          <ScriptInput
                            value={wp.arrivingNarration || ""}
                            onChange={(v) => updateWaypoint(wp.id, { arrivingNarration: v })}
                            isGenerating={wp.isGeneratingScript || false}
                            onCancel={() => {
                              updateWaypoint(wp.id, { isGeneratingScript: false });
                              invoke("cancel_python_blueprint").catch(console.error);
                            }}
                            onGenerate={(prompt, engine) => handleGenerateScript("arriving", prompt, engine)}
                          />
                        </div>
                      )}
                    </div>

                    <div className="border-t border-zinc-200 dark:border-white/10" />

                    {/* Attraction Script */}
                    <div className="flex flex-col gap-3">
                      <button 
                        onClick={() => setShowAttraction(!showAttraction)}
                        className="flex items-center gap-2 group"
                      >
                        <Mic className="w-5 h-5 text-zinc-700 dark:text-zinc-300" />
                        <h3 className="text-sm font-bold">Attraction Script</h3>
                        {showAttraction ? (
                          <ChevronUp className="w-5 h-5 ml-2 text-zinc-400 group-hover:text-zinc-700" />
                        ) : (
                          <ChevronDown className="w-5 h-5 ml-2 text-zinc-400 group-hover:text-zinc-700" />
                        )}
                      </button>

                      {showAttraction && (
                        <div className="pl-7">
                          <ScriptInput
                            value={wp.attractionNarration || ""}
                            onChange={(v) => updateWaypoint(wp.id, { attractionNarration: v })}
                            isGenerating={wp.isGeneratingScript || false}
                            onCancel={() => {
                              updateWaypoint(wp.id, { isGeneratingScript: false });
                              invoke("cancel_python_blueprint").catch(console.error);
                            }}
                            onGenerate={(prompt, engine) => handleGenerateScript("attraction", prompt, engine)}
                          />
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {activeTab === "images" && (
                  <div className="space-y-5 max-w-3xl pl-2">
                    <div className="flex flex-col gap-1">
                      <h3 className="text-xs font-bold text-zinc-800 dark:text-zinc-200 uppercase tracking-wider">
                        Pop-up Images ({wpImages.length}/3)
                      </h3>
                      <p className="text-[11px] font-medium text-zinc-500 dark:text-zinc-400 leading-tight">
                        Add up to 3 images that will pop up during the narration at this stop.
                      </p>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                      {wpImages.map((img, idx) => {
                        const currentPan = imagePans[idx] || "none";

                        return (
                          <div
                            key={`${img}-${idx}`}
                            className="flex flex-col bg-zinc-50 dark:bg-navidark-700/30 rounded-xl p-3 border-2 border-zinc-900/10 dark:border-white/10"
                          >
                            <div className="relative group w-full aspect-video rounded-lg overflow-hidden bg-black/5 dark:bg-white/5 shadow-inner mb-3">
                              <img
                                src={convertFileSrc(img)}
                                alt={`Waypoint ${idx}`}
                                className="w-full h-full object-cover"
                              />
                              <button
                                onClick={() => removeImage(idx)}
                                className="absolute top-2 right-2 p-1.5 bg-red-500/90 text-white rounded-md opacity-0 group-hover:opacity-100 transition-opacity shadow-md hover:bg-red-500 backdrop-blur-sm"
                                title="Remove Image"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>

                            <div className="space-y-3">
                              <div className="flex flex-col gap-1.5">
                                <label className="text-[10px] font-bold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">
                                  Camera Motion
                                </label>
                                <select
                                  value={currentPan}
                                  onChange={(e) => updateImagePan(idx, e.target.value)}
                                  className="w-full bg-white dark:bg-navidark-800 border-2 border-zinc-900/20 dark:border-white/20 text-zinc-700 dark:text-zinc-300 text-xs font-bold rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-navi-500 transition-colors cursor-pointer"
                                >
                                  {cameraPans.map((pan) => (
                                    <option key={pan.value} value={pan.value}>
                                      {pan.label}
                                    </option>
                                  ))}
                                </select>
                              </div>
                            </div>
                          </div>
                        );
                      })}

                      {wpImages.length < 3 && (
                        <button
                          onClick={handleImageSelect}
                          className="h-full min-h-32 bg-zinc-50 dark:bg-navidark-700/50 hover:bg-zinc-100 dark:hover:bg-navidark-600 border-2 border-zinc-300 dark:border-white/20 hover:border-zinc-500 dark:hover:border-white/50 border-dashed rounded-xl py-3 flex flex-col items-center justify-center gap-3 text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200 transition-all group"
                        >
                          <ImageIcon className="w-8 h-8 opacity-50 group-hover:opacity-100 transition-opacity" />
                          <span className="text-xs font-bold">+ Add Image</span>
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>

            </div>
          </div>
        )}
      </div>
    </div>
  );
}
