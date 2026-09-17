import { useState, useEffect } from "react";
import {
  ChevronUp,
  ChevronDown,
  ImageIcon,
  X,
  Trash2,
  MapPin,
  MapPinned,
  Mic,
  Info,
  Navigation,
  PlayCircle,
  CheckCircle2,
  LinkIcon,
  UnlinkIcon,
} from "../../../components/ui/icons";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { invoke, convertFileSrc } from "@tauri-apps/api/core";
import { Tooltip } from "../../../components/ui/Tooltip";
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
    if (type === "arriving" && !showArriving) setShowArriving(true);
    if (type === "attraction" && !showAttraction) setShowAttraction(true);

    try {
      updateWaypoint(wp.id, { isGeneratingScript: true });

      const hasEngine = await checkModelExists(engine);
      if (!hasEngine) {
        showToast(
          `Model "${engine}" not found. Please install it in Ollama.`,
          "error"
        );
        updateWaypoint(wp.id, { isGeneratingScript: false });
        return;
      }

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

  const isStart = wpIndex === 0;
  const isDest = wpIndex === waypoints.length - 1;
  const isStopBy = wp.isStopBy; 

  return (
    <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-50 pointer-events-none w-full px-4 flex flex-col items-center">
      <div
        className={`flex flex-col bg-white/95 dark:bg-navidark-800/95 backdrop-blur-xl rounded-2xl shadow-[0_-10px_60px_-15px_rgba(0,0,0,0.4)] border border-zinc-200/50 dark:border-white/10 select-none transition-all duration-400 ease-[cubic-bezier(0.16,1,0.3,1)] pointer-events-auto ${
          isCollapsed ? "w-[300px] h-[52px]" : "w-full max-w-5xl h-[460px] max-h-[50vh]"
        } overflow-hidden`}
      >
        {isCollapsed ? (
          <div 
            className="cursor-pointer flex items-center justify-between gap-3 p-2.5 px-5 h-full w-full hover:bg-zinc-50 dark:hover:bg-navidark-700 transition-colors"
            onClick={() => setIsCollapsed(false)}
          >
            <div className="flex flex-col min-w-0 pointer-events-none">
              <span className="text-[10px] font-bold text-navi dark:text-navi-400 uppercase tracking-widest opacity-80 mb-0.5">
                Editing Waypoint
              </span>
              <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 truncate flex items-center gap-2">
                <MapPin className="w-3.5 h-3.5 text-navi" /> {wp.name}
              </h2>
            </div>
            <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
              <button
                onClick={() => setIsCollapsed(false)}
                className="p-1.5 rounded-lg hover:bg-zinc-200 dark:hover:bg-navidark-400 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors"
              >
                <ChevronUp className="w-5 h-5" />
              </button>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/30 text-zinc-500 hover:text-red-600 dark:hover:text-red-400 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>
        ) : (
          <div className="flex-1 flex flex-row min-w-0 h-full overflow-hidden items-stretch text-zinc-900 dark:text-zinc-100">
            {/* --- LEFT COLUMN --- */}
            <div className="w-1/3 min-w-[280px] max-w-[360px] shrink-0 border-r border-zinc-200/50 dark:border-white/10 flex flex-col overflow-y-auto scrollbar-none bg-zinc-50/30 dark:bg-navidark-800/30">
              
              {/* TOP: Location Name & Toggles */}
              <div className="p-5 pb-5 flex flex-col gap-1">
                <input
                  type="text"
                  value={wp.name}
                  onChange={(e) => updateWaypoint(wp.id, { name: e.target.value })}
                  className="w-full bg-transparent border-b border-zinc-300 dark:border-white/20 text-2xl font-bold focus:outline-none focus:border-navi pb-1 truncate transition-colors"
                  placeholder="Location Name"
                />
                <span className="text-[10px] font-medium text-zinc-500 dark:text-zinc-400 pl-1 mt-1">
                  Get name from coordinate
                </span>

                <div className="mt-5 flex flex-col gap-4 pl-1">
                  {/* Skip Asset Generation Toggle */}
                  <div className="flex items-center gap-3">
                    <label className={`flex items-center gap-3 group ${isStart || isDest ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}>
                      <div className="relative inline-flex items-center">
                        <input 
                          type="checkbox" 
                          className="sr-only peer" 
                          checked={wp.skipAssetGeneration || false}
                          disabled={isStart || isDest}
                          onChange={(e) => updateWaypoint(wp.id, { skipAssetGeneration: e.target.checked })}
                        />
                        <div className="w-9 h-5 bg-zinc-200 peer-focus:outline-none rounded-full peer dark:bg-navidark-600 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-zinc-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all dark:border-gray-600 peer-checked:bg-navi-500 border border-zinc-300 dark:border-white/20 peer-disabled:cursor-not-allowed"></div>
                      </div>
                      <span className="text-[11px] font-bold text-zinc-700 dark:text-zinc-200">Skip in Video Export</span>
                    </label>
                    <Tooltip content="Skips this location during video generation (useful for shaping the route without visiting)." position="top">
                      <Info className="w-3.5 h-3.5 text-zinc-400 hover:text-navi transition-colors cursor-help" />
                    </Tooltip>
                  </div>

                  {/* Pause At Waypoint Toggle */}
                  <div className="flex items-center gap-3">
                    <label className="flex items-center gap-3 cursor-pointer group">
                      <div className="relative inline-flex items-center">
                        <input 
                          type="checkbox" 
                          className="sr-only peer" 
                          checked={wp.pauseAtWaypoint !== undefined ? wp.pauseAtWaypoint : (waypoints[wpIndex + 1]?.isStopBy === true)}
                          onChange={(e) => updateWaypoint(wp.id, { pauseAtWaypoint: e.target.checked })}
                        />
                        <div className="w-9 h-5 bg-zinc-200 peer-focus:outline-none rounded-full peer dark:bg-navidark-600 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-zinc-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all dark:border-gray-600 peer-checked:bg-navi-500 border border-zinc-300 dark:border-white/20"></div>
                      </div>
                      <span className="text-[11px] font-bold text-zinc-700 dark:text-zinc-200">Pause at Location</span>
                    </label>
                    <Tooltip content="Adds a brief pause in the generated video at this waypoint before continuing the journey." position="top">
                      <Info className="w-3.5 h-3.5 text-zinc-400 hover:text-navi transition-colors cursor-help" />
                    </Tooltip>
                  </div>
                </div>
              </div>

              {/* DIVIDER */}
              <div className="border-t border-zinc-200/50 dark:border-white/10 mx-5" />

              {/* BOTTOM: Action */}
              <div className="p-5 pt-4 flex flex-col gap-4 flex-1">
                <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-800 dark:text-zinc-200">Action</h3>

                {/* Custom Marker */}
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 border border-dashed border-zinc-300 dark:border-white/20 rounded-lg flex items-center justify-center shrink-0 bg-white dark:bg-navidark-700/50 relative overflow-hidden group shadow-sm">
                    {wp.customMarker ? (
                      <>
                        <img src={convertFileSrc(wp.customMarker)} alt="Marker" className="w-8 h-8 object-contain" />
                        <button 
                          onClick={() => updateWaypoint(wp.id, { customMarker: undefined })}
                          className="absolute inset-0 bg-black/50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                          <Trash2 className="w-4 h-4 text-white" />
                        </button>
                      </>
                    ) : (
                      <MapPin className="w-5 h-5 text-zinc-300 dark:text-zinc-600" />
                    )}
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <span className="text-[11px] font-bold text-zinc-700 dark:text-zinc-300">Custom Marker</span>
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
                        className="bg-navi-500 hover:bg-navi-600 text-white px-2.5 py-1 rounded-md text-[10px] font-bold shadow-sm transition-colors"
                      >
                        Select
                      </button>
                      <span className="text-[10px] font-medium text-zinc-500 truncate max-w-[100px]" title={wp.customMarker || ""}>
                        {wp.customMarker ? wp.customMarker.split(/[\\/]/).pop() : "No file chosen"}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Waypoint Settings (Grid of buttons with icons) */}
                <div className="flex flex-col gap-2.5 mt-2">
                  <h3 className="text-[11px] font-bold flex items-center gap-1.5 text-zinc-700 dark:text-zinc-300">
                    Waypoint settings <Info className="w-3.5 h-3.5 text-zinc-400" />
                  </h3>
                  
                  <div className={`grid gap-2 ${isStopBy && !isStart && !isDest ? 'grid-cols-6' : 'grid-cols-5'}`}>
                    <button 
                      onClick={() => updateWaypoint(wp.id, { isStopBy: false })}
                      className={`flex flex-col items-center justify-center gap-1.5 p-2 rounded-xl border transition-all shadow-sm ${!isStopBy && !isStart && !isDest ? 'bg-navi-50 dark:bg-navi-900/30 border-navi text-navi-700 dark:text-navi-400' : 'bg-white dark:bg-navidark-700 border-zinc-200 dark:border-white/10 hover:border-navi-300 text-zinc-600 dark:text-zinc-300'}`}
                    >
                      <Navigation className="w-4 h-4" />
                      <span className="text-[9px] font-bold max-[1414px]:hidden">Node</span>
                    </button>
                    
                    <button 
                      onClick={() => updateWaypoint(wp.id, { isStopBy: true })}
                      className={`flex flex-col items-center justify-center gap-1.5 p-2 rounded-xl border transition-all shadow-sm ${isStopBy && !isStart && !isDest ? 'bg-navi-50 dark:bg-navi-900/30 border-navi text-navi-700 dark:text-navi-400' : 'bg-white dark:bg-navidark-700 border-zinc-200 dark:border-white/10 hover:border-navi-300 text-zinc-600 dark:text-zinc-300'}`}
                    >
                      <MapPinned className="w-4 h-4" />
                      <span className="text-[9px] font-bold max-[1414px]:hidden">Stop-by</span>
                    </button>
                    
                    {isStopBy && !isStart && !isDest && (
                      <button 
                        onClick={() => updateWaypoint(wp.id, { connectToRoute: wp.connectToRoute === false ? true : false })}
                        className={`flex flex-col items-center justify-center gap-1.5 p-2 rounded-xl border transition-all shadow-sm ${wp.connectToRoute !== false ? 'bg-emerald-50 dark:bg-emerald-900/30 border-emerald-500 text-emerald-700 dark:text-emerald-400' : 'bg-zinc-100 dark:bg-navidark-600 border-zinc-300 dark:border-white/20 text-zinc-600 dark:text-zinc-400'}`}
                        title={wp.connectToRoute !== false ? "Connected to route" : "Disconnected from route"}
                      >
                        {wp.connectToRoute !== false ? <LinkIcon className="w-4 h-4" /> : <UnlinkIcon className="w-4 h-4" />}
                        <span className="text-[9px] font-bold max-[1414px]:hidden">{wp.connectToRoute !== false ? "Linked" : "Unlinked"}</span>
                      </button>
                    )}

                    <button 
                      disabled
                      className={`flex flex-col items-center justify-center gap-1.5 p-2 rounded-xl border transition-all shadow-sm ${isStart ? 'bg-emerald-50 dark:bg-emerald-900/30 border-emerald-500 text-emerald-700 dark:text-emerald-400' : 'bg-white dark:bg-navidark-700 border-zinc-200 dark:border-white/10 opacity-50'}`}
                    >
                      <PlayCircle className="w-4 h-4" />
                      <span className="text-[9px] font-bold max-[1414px]:hidden">Start</span>
                    </button>

                    <button 
                      disabled
                      className={`flex flex-col items-center justify-center gap-1.5 p-2 rounded-xl border transition-all shadow-sm ${isDest ? 'bg-indigo-50 dark:bg-indigo-900/30 border-indigo-500 text-indigo-700 dark:text-indigo-400' : 'bg-white dark:bg-navidark-700 border-zinc-200 dark:border-white/10 opacity-50'}`}
                    >
                      <CheckCircle2 className="w-4 h-4" />
                      <span className="text-[9px] font-bold max-[1414px]:hidden">Dest</span>
                    </button>

                    <button 
                      onClick={() => removeWaypoint(wp.id)}
                      className="flex flex-col items-center justify-center gap-1.5 p-2 rounded-xl border border-zinc-200 dark:border-white/10 bg-white dark:bg-navidark-700 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 hover:border-red-200 transition-all shadow-sm"
                    >
                      <Trash2 className="w-4 h-4" />
                      <span className="text-[9px] font-bold max-[1414px]:hidden">Delete</span>
                    </button>
                  </div>
                </div>

              </div>
            </div>

            {/* --- RIGHT COLUMN --- */}
            <div className="flex-1 flex flex-col min-w-0 bg-white dark:bg-navidark-800">
              
              {/* Tabs & Window Controls */}
              <div className="flex border-b border-zinc-200/50 dark:border-white/10 h-[56px] shrink-0 bg-zinc-50/50 dark:bg-navidark-800">
                <button
                  onClick={() => setActiveTab("scripts")}
                  className={`px-6 flex items-center justify-center font-bold text-xs transition-colors ${
                    activeTab === "scripts"
                      ? "bg-white dark:bg-navidark-700 text-navi-600 dark:text-navi-400 border-r border-zinc-200/50 dark:border-white/10 shadow-[2px_0_5px_-2px_rgba(0,0,0,0.05)] relative z-10"
                      : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 border-r border-zinc-200/50 dark:border-white/10"
                  }`}
                >
                  Narration Script
                </button>
                <button
                  onClick={() => setActiveTab("images")}
                  className={`px-6 flex items-center justify-center font-bold text-xs transition-colors ${
                    activeTab === "images"
                      ? "bg-white dark:bg-navidark-700 text-navi-600 dark:text-navi-400 border-r border-zinc-200/50 dark:border-white/10 shadow-[2px_0_5px_-2px_rgba(0,0,0,0.05)] relative z-10"
                      : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 border-r border-zinc-200/50 dark:border-white/10"
                  }`}
                >
                  Image
                </button>

                <div className="ml-auto flex items-center px-4 gap-1">
                  <button
                    onClick={() => setIsCollapsed(true)}
                    title="Collapse"
                    className="p-1.5 rounded-lg hover:bg-zinc-200 dark:hover:bg-navidark-600 transition-colors"
                  >
                    <ChevronDown className="w-5 h-5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100" />
                  </button>
                  <button
                    onClick={onClose}
                    title="Close"
                    className="p-1.5 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors group"
                  >
                    <X className="w-5 h-5 text-zinc-500 group-hover:text-red-500" />
                  </button>
                </div>
              </div>

              {/* Tab Content */}
              <div className="flex-1 overflow-y-auto custom-scrollbar p-6 bg-white dark:bg-navidark-800">
                
                {activeTab === "scripts" && (
                  <div className="space-y-6 max-w-3xl">
                    {/* Arriving Script */}
                    <div className="flex flex-col gap-3">
                      <button 
                        onClick={() => setShowArriving(!showArriving)}
                        className="flex items-center gap-2 group w-max"
                      >
                        <Mic className="w-4 h-4 text-zinc-500 dark:text-zinc-400 group-hover:text-navi transition-colors" />
                        <h3 className="text-sm font-bold text-zinc-800 dark:text-zinc-200">Arriving Script</h3>
                        {showArriving ? (
                          <ChevronUp className="w-4 h-4 ml-1 text-zinc-400 group-hover:text-zinc-700 transition-colors" />
                        ) : (
                          <ChevronDown className="w-4 h-4 ml-1 text-zinc-400 group-hover:text-zinc-700 transition-colors" />
                        )}
                      </button>
                      
                      {showArriving && (
                        <div className="pl-6">
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

                    <div className="border-t border-zinc-200/50 dark:border-white/5" />

                    {!(isStopBy && wp.connectToRoute === false) && (
                      <>
                        {/* Attraction Script */}
                        <div className="flex flex-col gap-3">
                          <button 
                            onClick={() => setShowAttraction(!showAttraction)}
                            className="flex items-center gap-2 group w-max"
                          >
                            <Mic className="w-4 h-4 text-zinc-500 dark:text-zinc-400 group-hover:text-emerald-500 transition-colors" />
                            <h3 className="text-sm font-bold text-zinc-800 dark:text-zinc-200">Attraction Script</h3>
                            {showAttraction ? (
                              <ChevronUp className="w-4 h-4 ml-1 text-zinc-400 group-hover:text-zinc-700 transition-colors" />
                            ) : (
                              <ChevronDown className="w-4 h-4 ml-1 text-zinc-400 group-hover:text-zinc-700 transition-colors" />
                            )}
                          </button>

                          {showAttraction && (
                            <div className="pl-6">
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
                      </>
                    )}
                  </div>
                )}

                {activeTab === "images" && (
                  <div className="space-y-5 max-w-3xl">
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
                            className="flex flex-col bg-zinc-50 dark:bg-navidark-700/30 rounded-xl p-3 border border-zinc-200 dark:border-white/10 shadow-sm"
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
                                  className="w-full bg-white dark:bg-navidark-800 border border-zinc-200 dark:border-white/10 text-zinc-700 dark:text-zinc-300 text-xs font-bold rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-navi-500 transition-colors cursor-pointer shadow-sm"
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
                          className="h-full min-h-32 bg-zinc-50 dark:bg-navidark-700/50 hover:bg-zinc-100 dark:hover:bg-navidark-600 border border-zinc-300 dark:border-white/20 hover:border-zinc-400 dark:hover:border-white/40 border-dashed rounded-xl py-3 flex flex-col items-center justify-center gap-3 text-zinc-400 hover:text-zinc-600 dark:text-zinc-500 dark:hover:text-zinc-300 transition-all group shadow-sm"
                        >
                          <ImageIcon className="w-8 h-8 opacity-60 group-hover:opacity-100 transition-opacity" />
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
