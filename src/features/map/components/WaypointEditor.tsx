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

  const wpIndex = waypoints.findIndex((w) => w.id === wpId);
  const wp = wpIndex !== -1 ? waypoints[wpIndex] : null;

  const [showArriving, setShowArriving] = useState(
    () => !!wp?.arrivingNarration,
  );
  const [showAttraction, setShowAttraction] = useState(
    () => !!wp?.attractionNarration,
  );
  const [isEditingName, setIsEditingName] = useState(false);
  const [activeTab, setActiveTab] = useState<"scripts" | "images">("scripts");
  const [isCollapsed, setIsCollapsed] = useState(false);

  // Auto-expand if the user clicks a new waypoint
  useEffect(() => {
    setIsCollapsed(false);
  }, [wpId]);

  if (!wp) return null;

  const wpImages = wp.images || [];
  const imagePans = wp.imagePans || [];
  const imageTransitionsState = wp.imageTransitions || [];
  const isStart = wpIndex === 0;
  const isEnd = wpIndex === waypoints.length - 1 && waypoints.length > 1;

  const handleImageSelect = async () => {
    try {
      const selected = await open({
        multiple: true,
        filters: [
          {
            name: "Images",
            extensions: ["png", "jpg", "jpeg", "webp"],
          },
        ],
      });
      if (selected && Array.isArray(selected)) {
        updateWaypoint(wp.id, {
          images: [...wpImages, ...selected].slice(0, 3),
        });
        if (setIsDirty) setIsDirty(true);
      }
    } catch (err) {
      console.error(err);
      showToast("Failed to select images", "error");
    }
  };

  const removeImage = (idx: number) => {
    const newImgs = [...wpImages];
    newImgs.splice(idx, 1);

    const newPans = [...imagePans];
    newPans.splice(idx, 1);

    const newTrans = [...imageTransitionsState];
    newTrans.splice(idx, 1);

    updateWaypoint(wp.id, {
      images: newImgs,
      imagePans: newPans,
      imageTransitions: newTrans,
    });
    if (setIsDirty) setIsDirty(true);
  };

  const updateImagePan = (idx: number, val: string) => {
    const newPans = [...imagePans];
    newPans[idx] = val;
    updateWaypoint(wp.id, { imagePans: newPans });
    if (setIsDirty) setIsDirty(true);
  };

  const handleGenerateScript = async (
    type: "arriving" | "attraction",
    prompt: string,
    engine: string,
  ) => {
    if (type === "arriving" && !showArriving) setShowArriving(true);
    if (type === "attraction" && !showAttraction) setShowAttraction(true);

    try {
      updateWaypoint(wp.id, { isGeneratingScript: true });

      const hasEngine = await checkModelExists(engine);
      if (!hasEngine) {
        showToast(
          `Model "${engine}" not found. Please install it in Ollama.`,
          "error",
        );
        updateWaypoint(wp.id, { isGeneratingScript: false });
        return;
      }

      await generateWaypointScriptStream(
        wp.name,
        prompt,
        engine,
        metadata.theme || "",
        (chunk) => {
          if (type === "arriving") {
            updateWaypoint(wp.id, { arrivingNarration: chunk });
          } else {
            updateWaypoint(wp.id, { attractionNarration: chunk });
          }
        },
      );
      showToast(`Generated ${type} script!`, "success");
    } catch (error) {
      showToast(`Script generation failed: ${error}`, "error");
    } finally {
      updateWaypoint(wp.id, { isGeneratingScript: false });
    }
  };

  const handleSetWaypointType = (
    type: "start" | "end" | "stopby" | "normal",
  ) => {
    const newWaypoints = [...waypoints];
    const currentIndex = newWaypoints.findIndex((w) => w.id === wp.id);
    if (currentIndex === -1) return;

    if (type === "start") {
      newWaypoints.splice(currentIndex, 1);
      newWaypoints.unshift({
        ...wp,
        isStopBy: false,
        connectToRoute: undefined,
      });
    } else if (type === "end") {
      newWaypoints.splice(currentIndex, 1);
      newWaypoints.push({ ...wp, isStopBy: false, connectToRoute: undefined });
    } else if (type === "stopby") {
      newWaypoints[currentIndex] = {
        ...wp,
        isStopBy: true,
        connectToRoute: false,
      };
    } else if (type === "normal") {
      newWaypoints[currentIndex] = {
        ...wp,
        isStopBy: false,
        connectToRoute: undefined,
      };
    }

    setWaypoints(newWaypoints);
    if (setIsDirty) setIsDirty(true);
  };

  return (
    <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-50 pointer-events-none w-full px-4 flex flex-col items-center">
      <div
        className={`flex flex-col bg-white/95 dark:bg-navidark-800/95 backdrop-blur-xl rounded-2xl shadow-[0_-10px_60px_-15px_rgba(0,0,0,0.5)] border border-zinc-200/50 dark:border-white/10 select-none transition-all duration-400 ease-[cubic-bezier(0.16,1,0.3,1)] pointer-events-auto ${
          isCollapsed ? "w-[300px] h-[56px]" : "w-full max-w-5xl h-[420px] max-h-[45vh]"
        } overflow-hidden`}
      >
        {/* --- HEADER --- */}
        <div 
          className="cursor-pointer flex items-center justify-between gap-3 p-3 px-5 border-b border-zinc-200/50 dark:border-white/5 shrink-0 hover:bg-zinc-50/50 dark:hover:bg-white/5 transition-colors"
          onClick={() => setIsCollapsed(!isCollapsed)}
        >
          <div className="flex flex-col min-w-0 pointer-events-none">
            <span className="text-[9px] font-bold text-navi dark:text-navi-400 uppercase tracking-[0.2em] opacity-80 mb-0.5">
              Editing Waypoint
            </span>
            <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 truncate flex items-center gap-2">
              <MapPin className="w-3.5 h-3.5 text-navi" /> {wp.name}
            </h2>
          </div>

          <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setIsCollapsed(!isCollapsed);
              }}
              title="Toggle Editor Size"
              className="p-1.5 rounded-lg hover:bg-zinc-200 dark:hover:bg-navidark-400 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors"
            >
              {isCollapsed ? (
                <ChevronUp className="w-5 h-5" />
              ) : (
                <ChevronDown className="w-5 h-5" />
              )}
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onClose();
              }}
              title="Close Editor"
              className="p-1.5 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/30 text-zinc-500 hover:text-red-600 dark:hover:text-red-400 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {!isCollapsed && (
          <div className="flex-1 flex flex-row min-w-0 h-full overflow-hidden items-stretch">
            {/* --- LEFT COLUMN: METADATA & ACTIONS --- */}
            <div className="w-1/3 min-w-[240px] max-w-[320px] shrink-0 border-r border-zinc-200 dark:border-white/10 p-5 flex flex-col gap-6 overflow-y-auto scrollbar-none bg-zinc-50/30 dark:bg-navidark-800/30">
              {/* Waypoint Name */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-1.5">
                  <MapPin className="w-3.5 h-3.5 text-zinc-400" /> Location Name
                </label>
                {isEditingName ? (
                  <input
                    type="text"
                    autoFocus
                    value={wp.name}
                    onBlur={() => setIsEditingName(false)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") setIsEditingName(false);
                    }}
                    onChange={(e) =>
                      updateWaypoint(wp.id, { name: e.target.value })
                    }
                    className="w-full bg-white dark:bg-navidark-700 border border-zinc-200 dark:border-white/10 rounded-xl px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-navi-500 dark:focus:border-navi-500/50 transition-colors shadow-sm"
                  />
                ) : (
                  <button
                    onClick={() => setIsEditingName(true)}
                    className="w-full text-left bg-white dark:bg-navidark-700 border border-zinc-200 dark:border-white/10 rounded-xl px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 hover:border-navi-300 transition-colors shadow-sm truncate"
                  >
                    {wp.name}
                  </button>
                )}
              </div>

              {/* Custom Marker */}
              <div className="flex items-center gap-3">
                {wp.customMarker ? (
                  <div className="relative w-12 h-12 rounded-lg border border-zinc-200 dark:border-white/10 flex items-center justify-center bg-zinc-50 dark:bg-navidark-700/50 group shrink-0">
                    <img
                      src={convertFileSrc(wp.customMarker)}
                      alt="Custom Marker"
                      className="w-8 h-8 object-contain"
                    />
                    <button
                      onClick={() =>
                        updateWaypoint(wp.id, { customMarker: undefined })
                      }
                      className="absolute -top-2 -right-2 p-1 bg-red-500 text-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity shadow-md"
                      title="Remove Marker"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ) : (
                  <div className="w-12 h-12 rounded-lg border border-dashed border-zinc-300 dark:border-white/20 flex items-center justify-center bg-zinc-50 dark:bg-navidark-700/30 shrink-0">
                    <MapPin className="w-5 h-5 text-zinc-300 dark:text-zinc-600" />
                  </div>
                )}

                <div className="flex flex-col flex-1 gap-1.5">
                  <h3 className="text-xs font-bold text-zinc-800 dark:text-zinc-200">
                    Custom Marker
                  </h3>
                  <button
                    onClick={async () => {
                      const selected = await open({
                        multiple: false,
                        filters: [
                          {
                            name: "Images",
                            extensions: ["svg", "png", "jpg", "jpeg"],
                          },
                        ],
                      });
                      if (selected && typeof selected === "string") {
                        updateWaypoint(wp.id, { customMarker: selected });
                      }
                    }}
                    className="w-full flex items-center text-xs text-zinc-500 dark:text-zinc-400 bg-white dark:bg-navidark-700 border border-zinc-200 dark:border-white/10 rounded-lg overflow-hidden hover:bg-zinc-50 dark:hover:bg-navidark-600 transition-colors shadow-sm"
                  >
                    <div className="bg-zinc-100 dark:bg-navidark-600 text-zinc-700 dark:text-zinc-300 font-semibold px-3 py-1.5 border-r border-zinc-200 dark:border-white/10 shrink-0">
                      {wp.customMarker ? "Change file" : "Choose file"}
                    </div>
                    <div className="px-3 py-1.5 truncate">
                      {wp.customMarker
                        ? wp.customMarker.split(/[/\\]/).pop()
                        : "No file chosen"}
                    </div>
                  </button>
                </div>
              </div>

              {/* Waypoint Actions */}
              <div className="space-y-3 pt-4 border-t border-zinc-200 dark:border-white/10">
                <h3 className="text-xs font-bold text-zinc-800 dark:text-zinc-200 flex items-center gap-1.5">
                  Actions
                  <button
                    type="button"
                    className="btn text-zinc-600 dark:text-zinc-400"
                    data-toggle="tooltip"
                    title="Change Waypoint Type"
                  >
                    <Info className="w-3.5 h-3.5" />
                  </button>
                </h3>

                <div className="grid grid-rows-1 gap-2">
                  {!isStart ? (
                    <button
                      onClick={() => handleSetWaypointType("start")}
                      title="Set Start"
                      className="flex flex-col items-center justify-center gap-1 py-2 rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-navidark-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-navidark-500 transition-colors shadow-sm"
                    >
                      <MapPinned className="w-4 h-4 text-zinc-400" />
                      <span className="text-[10px] font-semibold">Start</span>
                    </button>
                  ) : (
                    <button
                      onClick={() => handleSetWaypointType("start")}
                      title="Set Start"
                      className="flex flex-col disable items-center justify-center gap-1 py-2 rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-navidark-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-navidark-500 transition-colors shadow-sm"
                    >
                      <MapPinned className="w-4 h-4 text-zinc-400" />
                      <span className="text-[10px] font-semibold">Start</span>
                    </button>
                  )}
                  {!isEnd && (
                    <button
                      onClick={() => handleSetWaypointType("end")}
                      title="Set End"
                      className="flex flex-col items-center justify-center gap-1 py-2 rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-navidark-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-navidark-500 transition-colors shadow-sm"
                    >
                      <CornerDownLeft className="w-4 h-4 text-zinc-400" />
                      <span className="text-[10px] font-semibold">End</span>
                    </button>
                  )}
                  {wp.isStopBy ? (
                    <button
                      onClick={() => handleSetWaypointType("normal")}
                      title="Revert to Normal Stop"
                      className="flex flex-col items-center justify-center gap-1 py-2 rounded-lg border border-zinc-200 dark:border-white/10 bg-navi-50 dark:bg-navi-500/10 text-navi-700 dark:text-navi-400 hover:bg-navi-100 dark:hover:bg-navi-500/20 transition-colors shadow-sm"
                    >
                      <MapPinPlus className="w-4 h-4" />
                      <span className="text-[10px] font-semibold">Revert</span>
                    </button>
                  ) : (
                    <button
                      onClick={() => handleSetWaypointType("stopby")}
                      title="Set Stop-By"
                      className="flex flex-col items-center justify-center gap-1 py-2 rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-navidark-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-navidark-500 transition-colors shadow-sm"
                    >
                      <MapPin className="w-4 h-4 text-zinc-400" />
                      <span className="text-[10px] font-semibold">Stop-By</span>
                    </button>
                  )}

                  {wp.isStopBy && (
                    <button
                      onClick={() => {
                        updateWaypoint(wp.id, {
                          connectToRoute: !wp.connectToRoute,
                        });
                        if (setIsDirty) setIsDirty(true);
                      }}
                      title={wp.connectToRoute ? "Disconnect" : "Connect"}
                      className="flex flex-col items-center justify-center gap-1 py-2 rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-navidark-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-navidark-500 transition-colors shadow-sm"
                    >
                      {wp.connectToRoute ? (
                        <UnlinkIcon className="w-4 h-4 text-zinc-400" />
                      ) : (
                        <LinkIcon className="w-4 h-4 text-zinc-400" />
                      )}
                      <span className="text-[10px] font-semibold">
                        {wp.connectToRoute ? "Unlink" : "Link"}
                      </span>
                    </button>
                  )}

                  <button
                    onClick={() => {
                      if (confirm(`Remove ${wp.name}?`)) {
                        setWaypoints(waypoints.filter((w) => w.id !== wp.id));
                        setActiveWaypointId(null);
                        onClose();
                      }
                    }}
                    title="Remove Stop"
                    className="flex flex-col items-center justify-center gap-1 py-2 rounded-lg border border-transparent text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 transition-colors col-span-full mt-2"
                  >
                    <Trash2 className="w-4 h-4" />
                    <span className="text-[10px] font-semibold">Remove</span>
                  </button>
                </div>
              </div>
            </div>

            {/* --- RIGHT COLUMN: TABS --- */}
            <div className="flex-1 flex flex-col min-w-0 h-full">
              {/* Tabs Header */}
              <div className="flex items-center px-4 pt-3 gap-2 border-b border-zinc-200 dark:border-white/10">
                <button
                  onClick={() => setActiveTab("scripts")}
                  className={`px-4 py-2 text-xs font-bold transition-all border-b-2 ${
                    activeTab === "scripts"
                      ? "border-navi text-navi dark:text-navi-400"
                      : "border-transparent text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <Mic className="w-3.5 h-3.5" />
                    Voiceover Scripts
                  </div>
                </button>
                <button
                  onClick={() => setActiveTab("images")}
                  className={`px-4 py-2 text-xs font-bold transition-all border-b-2 ${
                    activeTab === "images"
                      ? "border-emerald-500 text-emerald-600 dark:text-emerald-400"
                      : "border-transparent text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <ImageIcon className="w-3.5 h-3.5" />
                    Pop-up Images
                  </div>
                </button>
              </div>

              {/* Tab Content */}
              <div className="flex-1 overflow-y-auto custom-scrollbar p-5">
                {activeTab === "scripts" && (
                  <div className="space-y-6 max-w-2xl">
                    <div className="flex flex-col gap-1 mb-2">
                      <h3 className="text-xs font-bold text-zinc-800 dark:text-zinc-200 uppercase tracking-wider">
                        Voiceover Scripts
                      </h3>
                      <p className="text-[10px] text-zinc-500 dark:text-zinc-400 leading-tight">
                        Scripts are optional. Add text manually or use AI to
                        generate narration for the route travel and the location
                        itself.
                      </p>
                    </div>

                    {/* Arriving Script */}
                    {!showArriving ? (
                      <button
                        onClick={() => setShowArriving(true)}
                        className="w-full text-left px-3 py-2.5 rounded-xl border border-dashed border-zinc-300 dark:border-navidark-300 text-xs font-semibold text-zinc-500 hover:text-navi-600 dark:hover:text-navi-400 hover:bg-navi-50 dark:hover:bg-navi-900/20 transition-colors"
                      >
                        + Add Arriving Narration Script
                      </button>
                    ) : (
                      <div className="space-y-1.5 bg-zinc-50 dark:bg-navidark-700/30 p-3 rounded-xl border border-zinc-200 dark:border-white/5">
                        <div className="flex justify-between items-center mb-2">
                          <label className="text-xs font-bold text-navi-700 dark:text-navi-400">
                            Arriving Script
                          </label>
                          <button
                            onClick={() => setShowArriving(false)}
                            className="text-zinc-400 hover:text-red-500"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                        <ScriptInput
                          value={wp.arrivingNarration || ""}
                          onChange={(v) =>
                            updateWaypoint(wp.id, { arrivingNarration: v })
                          }
                          isGenerating={wp.isGeneratingScript || false}
                          onCancel={() => {
                            updateWaypoint(wp.id, {
                              isGeneratingScript: false,
                            });
                            invoke("cancel_python_blueprint").catch(
                              console.error,
                            );
                          }}
                          onGenerate={(prompt, engine) =>
                            handleGenerateScript("arriving", prompt, engine)
                          }
                        />
                      </div>
                    )}

                    {/* Attraction Script */}
                    {!showAttraction ? (
                      <button
                        onClick={() => setShowAttraction(true)}
                        className="w-full text-left px-3 py-2.5 rounded-xl border border-dashed border-zinc-300 dark:border-navidark-300 text-xs font-semibold text-zinc-500 hover:text-navi-600 dark:hover:text-navi-400 hover:bg-navi-50 dark:hover:bg-navi-900/20 transition-colors"
                      >
                        + Add Attraction Narration Script
                      </button>
                    ) : (
                      <div className="space-y-1.5 bg-zinc-50 dark:bg-navidark-700/30 p-3 rounded-xl border border-zinc-200 dark:border-white/5">
                        <div className="flex justify-between items-center mb-2">
                          <label className="text-xs font-bold text-emerald-700 dark:text-emerald-500">
                            Attraction Script
                          </label>
                          <button
                            onClick={() => setShowAttraction(false)}
                            className="text-zinc-400 hover:text-red-500"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                        <ScriptInput
                          value={wp.attractionNarration || ""}
                          onChange={(v) =>
                            updateWaypoint(wp.id, { attractionNarration: v })
                          }
                          isGenerating={wp.isGeneratingScript || false}
                          onCancel={() => {
                            updateWaypoint(wp.id, {
                              isGeneratingScript: false,
                            });
                            invoke("cancel_python_blueprint").catch(
                              console.error,
                            );
                          }}
                          onGenerate={(prompt, engine) =>
                            handleGenerateScript("attraction", prompt, engine)
                          }
                        />
                      </div>
                    )}
                  </div>
                )}

                {activeTab === "images" && (
                  <div className="space-y-4 max-w-3xl">
                    <div className="flex flex-col gap-1">
                      <h3 className="text-xs font-bold text-zinc-800 dark:text-zinc-200 uppercase tracking-wider">
                        Pop-up Images ({wpImages.length}/3)
                      </h3>
                      <p className="text-[10px] text-zinc-500 dark:text-zinc-400 leading-tight">
                        Add up to 3 images that will pop up during the narration
                        at this stop.
                      </p>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                      {wpImages.map((img, idx) => {
                        const currentPan = imagePans[idx] || "none";

                        return (
                          <div
                            key={`${img}-${idx}`}
                            className="flex flex-col bg-zinc-50 dark:bg-navidark-700/30 rounded-xl p-3 border border-zinc-200 dark:border-white/5"
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
                                  onChange={(e) =>
                                    updateImagePan(idx, e.target.value)
                                  }
                                  className="w-full bg-white dark:bg-navidark-800 border border-zinc-200 dark:border-white/10 text-zinc-700 dark:text-zinc-300 text-xs font-medium rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-navi-500 transition-colors cursor-pointer"
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
                          className="h-full min-h-50 bg-zinc-50 dark:bg-navidark-700/50 hover:bg-navi-50 dark:hover:bg-navi-500/10 border border-zinc-300 dark:border-white/10 hover:border-navi-500/50 border-dashed rounded-xl py-3 flex flex-col items-center justify-center gap-3 text-zinc-500 hover:text-navi-600 dark:hover:text-navi-400 transition-all"
                        >
                          <ImageIcon className="w-8 h-8 opacity-50" />
                          <span className="text-xs font-medium">
                            + Add Image
                          </span>
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
