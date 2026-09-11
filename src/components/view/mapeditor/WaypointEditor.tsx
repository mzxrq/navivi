import { useState } from "react";
import {
  ChevronLeft,
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
} from "../../ui/icons";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { invoke, convertFileSrc } from "@tauri-apps/api/core";
import { ScriptInput } from "../../ui/ScriptInput";
import { open } from "@tauri-apps/plugin-dialog";
import {
  checkModelExists,
  generateWaypointScriptStream,
} from "../../../services/ollamaApi";
import { synthesizeAudio } from "../../../services/irodoriApi";
import { generateComfyUiVideo } from "../../../services/comfyUiApi";

const cameraPans = [
  { value: "none", label: "None" },
  { value: "pan-left", label: "Pan Left" },
  { value: "pan-right", label: "Pan Right" },
  { value: "pan-up", label: "Pan Up" },
  { value: "pan-down", label: "Pan Down" },
  { value: "zoom-in", label: "Zoom In" },
  { value: "zoom-out", label: "Zoom Out" },
];

const imageTransitions = [
  { value: "crossfade", label: "Crossfade" },
  { value: "dip-to-black", label: "Dip to Black" },
  { value: "dip-to-white", label: "Dip to White" },
  { value: "wipe-left", label: "Wipe Left" },
  { value: "wipe-right", label: "Wipe Right" },
  { value: "cut", label: "Hard Cut" },
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
    setActiveWaypointId,
    metadata,
    setIsDirty,
  } = useWorkspace();
  const { showToast } = useUI();

  const index = waypoints.findIndex((w) => w.id === wpId);
  const wp = index !== -1 ? waypoints[index] : undefined;
  const [showArriving, setShowArriving] = useState(!!wp?.arrivingNarration);
  const [showAttraction, setShowAttraction] = useState(
    !!(wp?.attractionNarration || wp?.narration),
  );

  if (!wp) return null;

  const isStart = index === 0;
  const isEnd = index === waypoints.length - 1 && waypoints.length > 1;

  const wpImages = wp.images || [];
  const wpImagePans = wp.imagePans || [];
  const wpImageTransitions = wp.imageTransitions || [];

  const handleImageSelect = async () => {
    if (wpImages.length >= 3) {
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
      const newImages = [...wpImages, ...pathsArray].slice(0, 3);
      const newPans = [...wpImagePans, ...pathsArray.map(() => "none")].slice(
        0,
        3,
      );
      const newTransitions = [
        ...wpImageTransitions,
        ...pathsArray.map(() => "crossfade"),
      ].slice(0, Math.max(0, newImages.length - 1));
      updateWaypoint(wp.id, {
        images: newImages,
        imagePans: newPans,
        imageTransitions: newTransitions,
      });
    }
  };

  const updateImagePan = (idx: number, pan: string) => {
    const newPans = [...wpImagePans];
    newPans[idx] = pan;
    updateWaypoint(wp.id, { imagePans: newPans });
  };

  const updateImageTransition = (idx: number, transition: string) => {
    const newTransitions = [...wpImageTransitions];
    newTransitions[idx] = transition;
    updateWaypoint(wp.id, { imageTransitions: newTransitions });
  };

  const handleRemoveImage = (idx: number) => {
    const newImages = wpImages.filter((_, i) => i !== idx);
    const newTransitions = wpImageTransitions
      .filter((_, i) => i !== idx)
      .slice(0, Math.max(0, newImages.length - 1));

    updateWaypoint(wp.id, {
      images: newImages,
      imagePans: wpImagePans.filter((_, i) => i !== idx),
      imageTransitions: newTransitions,
    });
  };

  const handleGenerateScript = async (
    type: "arriving" | "attraction",
    prompt: string,
    engine: string,
  ) => {
    const hasModel = await checkModelExists(engine);
    if (!hasModel) {
      showToast(
        `Model "${engine}" not found. Please run: ollama run ${engine}`,
        "error",
      );
      return;
    }
    updateWaypoint(wp.id, { isGeneratingScript: true });
    showToast(`Writing ${type} script for ${wp.name}...`, "info");

    try {
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
        wp.lat,
        wp.lng,
      );
      showToast(`Script finished for ${wp.name}!`, "success");
    } catch (error) {
      console.error(error);
      showToast(`Generation failed: ${error}`, "error");
    } finally {
      updateWaypoint(wp.id, { isGeneratingScript: false });
    }
  };

  const handleGenerateAudio = async () => {
    const textToSynthesize =
      wp.arrivingNarration || wp.attractionNarration || wp.narration;
    if (!textToSynthesize) {
      showToast("No narration text available to synthesize.", "error");
      return;
    }

    updateWaypoint(wp.id, { isGeneratingAudio: true });
    showToast("Generating Audio via Irodori...", "info");

    try {
      const { buffer, contentType } = await synthesizeAudio(textToSynthesize);
      const blob = new Blob([buffer], { type: contentType });
      const url = URL.createObjectURL(blob);
      if (wp.audioUrl) {
        URL.revokeObjectURL(wp.audioUrl);
      }
      updateWaypoint(wp.id, { audioUrl: url });
      showToast("Audio generated successfully!", "success");
    } catch (error) {
      console.error(error);
      showToast(`Audio generation failed: ${error}`, "error");
    } finally {
      updateWaypoint(wp.id, { isGeneratingAudio: false });
    }
  };

  const handleGenerateVideo = async () => {
    if (!wpImages || wpImages.length === 0) {
      showToast("ComfyUI Wan 2.2 requires at least one image.", "error");
      return;
    }

    updateWaypoint(wp.id, { isGeneratingVideo: true });
    showToast("Triggering ComfyUI Wan 2.2 Video Generation...", "info");

    try {
      const panValue = wpImagePans[0] || "none";
      const finalPrompt = panValue.replace("-", "");
      updateWaypoint(wp.id, { videoPrompt: finalPrompt });

      const videoPath = await generateComfyUiVideo(wpImages[0], finalPrompt);

      updateWaypoint(wp.id, { videoUrl: convertFileSrc(videoPath) });
      showToast("Video generated successfully!", "success");
    } catch (error) {
      console.error(error);
      showToast(`Video generation failed: ${error}`, "error");
    } finally {
      updateWaypoint(wp.id, { isGeneratingVideo: false });
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
    <aside className="w-85 shrink-0 bg-white dark:bg-navidark-600 border-r border-zinc-200 dark:border-white/5 flex flex-col h-full select-none z-10 relative shadow-xl transition-colors">
      {/* --- HEADER --- */}
      <div className="flex items-center gap-3 p-4 border-b border-zinc-200 dark:border-white/5 shrink-0 bg-zinc-50/50 dark:bg-navidark-700/50">
        <button
          onClick={onClose}
          className="p-1.5 -ml-1.5 rounded-lg hover:bg-zinc-200 dark:hover:bg-navidark-400 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors"
        >
          <ChevronLeft className="w-5 h-5" />
        </button>
        <div className="flex flex-col min-w-0">
          <span className="text-[10px] font-bold text-navi-600 dark:text-navi-500 uppercase tracking-wider">
            Editing Stop
          </span>
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
            {wp.name}
          </h2>
        </div>
      </div>

      {/* --- SCROLLABLE EDITOR CONTENT --- */}
      <div className="flex-1 flex flex-col min-h-0 space-y-6 overflow-y-auto custom-scrollbar p-5">
        {/* 1. Location Details */}
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-1.5">
              <MapPin className="w-3.5 h-3.5 text-zinc-400" /> Location Name
            </label>
            <input
              type="text"
              value={wp.name}
              onChange={(e) => updateWaypoint(wp.id, { name: e.target.value })}
              className="w-full bg-white dark:bg-navidark-700 border border-zinc-200 dark:border-white/10 rounded-xl px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-navi-500 dark:focus:border-navi-500/50 transition-colors shadow-sm"
            />
          </div>

          {wp.routeMode === "draw" && !isEnd && (
            <div className="flex items-center gap-2 px-3 py-2 bg-navi-50 dark:bg-navi-500/10 border border-navi-200 dark:border-navi-500/20 rounded-lg text-navi-700 dark:text-navi-400 text-[10px] font-bold uppercase tracking-wider shadow-sm">
              <Pencil className="w-4 h-4 shrink-0" />
              Draw Mode Active for Next Route
            </div>
          )}
        </div>

        {/* 2. Split Narration Scripts */}
        <div className="space-y-3">
          <div className="flex flex-col gap-1">
            <h3 className="text-xs font-bold text-zinc-800 dark:text-zinc-200 uppercase tracking-wider">
              Voiceover Scripts
            </h3>
            <p className="text-[10px] text-zinc-500 dark:text-zinc-400 leading-tight">
              Scripts are optional. Add text manually or use AI to generate
              narration for the route travel and the location itself.
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
                  updateWaypoint(wp.id, { isGeneratingScript: false });
                  invoke("cancel_python_blueprint").catch(console.error);
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
              + Add Attraction Script
            </button>
          ) : (
            <div className="space-y-1.5 bg-zinc-50 dark:bg-navidark-700/30 p-3 rounded-xl border border-zinc-200 dark:border-white/5">
              <div className="flex justify-between items-center mb-2">
                <label className="text-xs font-bold text-navi-700 dark:text-navi-400">
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
                value={wp.attractionNarration || wp.narration || ""}
                onChange={(v) =>
                  updateWaypoint(wp.id, { attractionNarration: v })
                }
                isGenerating={wp.isGeneratingScript || false}
                onCancel={() => {
                  updateWaypoint(wp.id, { isGeneratingScript: false });
                  invoke("cancel_python_blueprint").catch(console.error);
                }}
                onGenerate={(prompt, engine) =>
                  handleGenerateScript("attraction", prompt, engine)
                }
              />
            </div>
          )}
        </div>

        {/* 3. Images, Camera Pans & Transitions */}
        <div className="space-y-3 pb-8">
          <div className="flex items-center justify-between">
            <label className="text-xs font-bold text-zinc-800 dark:text-zinc-200 uppercase tracking-wider flex items-center gap-1.5">
              <ImageIcon className="w-3.5 h-3.5 text-zinc-400" /> Pop-up
              Pictures
            </label>
            <span className="text-[10px] font-medium text-zinc-500 bg-zinc-100 dark:bg-navidark-400 px-2 py-0.5 rounded-md">
              {wpImages.length} / 3
            </span>
          </div>

          <div className="flex flex-col gap-2 relative">
            {wpImages.map((img, idx) => {
              const currentPan = wpImagePans[idx] || "none";
              const currentTransition = wpImageTransitions[idx] || "crossfade";

              return (
                <div key={idx} className="flex flex-col">
                  <div className="flex flex-col bg-zinc-50 dark:bg-navidark-700/50 border border-zinc-200 dark:border-white/10 rounded-xl p-1.5 shadow-sm group">
                    <div className="relative w-full h-28 rounded-lg overflow-hidden bg-zinc-200 dark:bg-navidark-900 mb-1.5">
                      <img
                        src={convertFileSrc(img)}
                        alt="Preview"
                        className="w-full h-full object-cover"
                      />

                      <div className="absolute bottom-2 left-2 right-8 pointer-events-none">
                        <div className="bg-black/60 backdrop-blur-md text-white text-[9px] font-medium px-2 py-1 rounded-md truncate shadow-sm">
                          {img.split(/[/\\]/).pop()}
                        </div>
                      </div>

                      <button
                        onClick={() => handleRemoveImage(idx)}
                        className="absolute top-2 right-2 p-1.5 bg-black/50 hover:bg-red-500 text-white rounded-md backdrop-blur-md opacity-0 group-hover:opacity-100 transition-all shadow-md"
                        title="Remove Image"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>

                    <div className="flex items-center gap-2 px-1">
                      <span className="text-[9px] font-bold text-zinc-500 uppercase tracking-wider shrink-0">
                        Cam Pan:
                      </span>
                      <select
                        value={currentPan}
                        onChange={(e) => updateImagePan(idx, e.target.value)}
                        className="w-full bg-white dark:bg-navidark-900 border border-zinc-200 dark:border-white/5 text-zinc-700 dark:text-zinc-300 text-[10px] font-medium rounded-md px-2 py-1 focus:outline-none focus:border-navi-500 transition-colors cursor-pointer"
                      >
                        {cameraPans.map((pan) => (
                          <option key={pan.value} value={pan.value}>
                            {pan.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {idx < wpImages.length - 1 && (
                    <div className="flex justify-center py-2 relative z-10">
                      <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-px bg-zinc-200 dark:bg-white/10 -z-10" />

                      <div className="bg-white dark:bg-navidark-600 border border-zinc-200 dark:border-white/10 rounded-full shadow-sm flex items-center pr-1 hover:border-navi-300 transition-colors">
                        <div className="pl-3 pr-2 py-1 text-[9px] text-zinc-400 font-bold uppercase tracking-wider border-r border-zinc-100 dark:border-white/5">
                          Transition
                        </div>
                        <select
                          value={currentTransition}
                          onChange={(e) =>
                            updateImageTransition(idx, e.target.value)
                          }
                          className="bg-transparent text-[10px] font-bold text-navi-600 dark:text-navi-400 py-1 pl-2 pr-6 focus:outline-none cursor-pointer appearance-none"
                          style={{
                            backgroundImage: `url("data:image/svg+xml;charset=US-ASCII,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%2212%22%20height%3D%2212%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20stroke%3D%22%23296cf2%22%20stroke-width%3D%222%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%3E%3Cpolyline%20points%3D%226%209%2012%2015%2018%209%22%3E%3C%2Fpolyline%3E%3C%2Fsvg%3E")`,
                            backgroundRepeat: "no-repeat",
                            backgroundPosition: "right 4px center",
                          }}
                        >
                          {imageTransitions.map((t) => (
                            <option key={t.value} value={t.value}>
                              {t.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}

            {wpImages.length < 3 && (
              <button
                onClick={handleImageSelect}
                className="w-full bg-zinc-50 dark:bg-navidark-700/50 hover:bg-navi-50 dark:hover:bg-navi-500/10 border border-zinc-300 dark:border-white/10 hover:border-navi-500/50 border-dashed rounded-xl py-3 text-xs font-medium text-zinc-500 hover:text-navi-600 dark:hover:text-navi-400 transition-all flex items-center justify-center gap-2 mt-2"
              >
                + Add Image
              </button>
            )}

            {wpImages.length > 0 && (
              <div className="flex flex-col gap-1.5 mt-3">
                <label className="text-[10px] font-bold text-zinc-800 dark:text-zinc-200 uppercase tracking-wider">
                  Visual Layout
                </label>
                <div className="flex p-1 bg-zinc-100 dark:bg-navidark-900 rounded-lg border border-zinc-200/50 dark:border-white/5 shadow-inner">
                  <button
                    onClick={() =>
                      updateWaypoint(wp.id, { imageDisplay: "pip" })
                    }
                    className={`flex-1 py-1.5 text-xs font-bold rounded-md transition-all duration-200 ${
                      wp.imageDisplay !== "fullscreen"
                        ? "bg-white dark:bg-navidark-500 shadow-sm text-navi-600 dark:text-navi-400"
                        : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-200/50 dark:hover:bg-white/5"
                    }`}
                  >
                    Map Pop-up
                  </button>
                  <button
                    onClick={() =>
                      updateWaypoint(wp.id, { imageDisplay: "fullscreen" })
                    }
                    className={`flex-1 py-1.5 text-xs font-bold rounded-md transition-all duration-200 ${
                      wp.imageDisplay === "fullscreen"
                        ? "bg-white dark:bg-navidark-500 shadow-sm text-navi-600 dark:text-navi-400"
                        : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-200/50 dark:hover:bg-white/5"
                    }`}
                  >
                    Fullscreen
                  </button>
                </div>
                <p className="text-[9px] text-zinc-500 dark:text-zinc-400 leading-tight px-1 mt-1">
                  {wp.imageDisplay !== "fullscreen"
                    ? "Displays as a pop-up above the map marker. Transitions to the generated AI video will be applied in the Timeline."
                    : "Displays the image fullscreen over the map. Transitions to the generated AI video will be applied in the Timeline."}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* 4. Media Generation (Audio & Video) */}
        <div className="space-y-3 pb-4">
          <div className="flex items-center justify-between">
            <label className="text-xs font-bold text-zinc-800 dark:text-zinc-200 uppercase tracking-wider">
              AI Generation
            </label>
          </div>

          <div className="flex flex-col gap-2">
            <button
              onClick={handleGenerateAudio}
              disabled={
                wp.isGeneratingAudio ||
                (!wp.arrivingNarration &&
                  !wp.attractionNarration &&
                  !wp.narration)
              }
              className="w-full bg-indigo-50 dark:bg-indigo-500/10 hover:bg-indigo-100 dark:hover:bg-indigo-500/20 border border-indigo-200 dark:border-indigo-500/30 text-indigo-700 dark:text-indigo-400 py-2 rounded-xl text-xs font-bold transition-all flex items-center justify-center gap-2 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {wp.isGeneratingAudio
                ? "Generating Audio..."
                : "Generate Audio (Irodori)"}
            </button>

            {wp.audioUrl && (
              <audio controls src={wp.audioUrl} className="w-full h-8 mt-1" />
            )}

            <button
              onClick={handleGenerateVideo}
              disabled={
                wp.isGeneratingVideo || !wpImages || wpImages.length === 0
              }
              className="w-full bg-fuchsia-50 dark:bg-fuchsia-500/10 hover:bg-fuchsia-100 dark:hover:bg-fuchsia-500/20 border border-fuchsia-200 dark:border-fuchsia-500/30 text-fuchsia-700 dark:text-fuchsia-400 py-2 rounded-xl text-xs font-bold transition-all flex items-center justify-center gap-2 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {wp.isGeneratingVideo
                ? "Generating Video..."
                : "Generate Video (ComfyUI Wan)"}
            </button>

            {wp.videoPrompt && (
              <div className="mt-2 p-2 bg-zinc-50 dark:bg-navidark-700/50 border border-zinc-200 dark:border-white/10 rounded-lg">
                <label className="text-[10px] font-bold text-zinc-500 uppercase">
                  Generated Video Prompt
                </label>
                <p className="text-xs text-zinc-700 dark:text-zinc-300 mt-1 whitespace-pre-wrap">
                  {wp.videoPrompt}
                </p>
              </div>
            )}

            {wp.videoUrl && (
              <div className="mt-2">
                {wp.videoUrl.startsWith("http") ? (
                  <video
                    src={wp.videoUrl}
                    controls
                    className="w-full rounded-lg shadow-sm border border-zinc-200 dark:border-white/10"
                  />
                ) : (
                  <div className="p-2 bg-green-50 dark:bg-green-500/10 border border-green-200 dark:border-green-500/30 rounded-lg">
                    <p className="text-xs text-green-700 dark:text-green-400 font-medium">
                      Video Task ID: {wp.videoUrl} (Processing)
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* --- ✨ REDESIGNED SETTINGS & DANGER ZONE --- */}
      <div className="flex flex-col p-4 border-t border-zinc-200 dark:border-white/5 shrink-0 bg-zinc-50/80 dark:bg-navidark-700/80 gap-3">
        {/* Type Configuration Buttons */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider px-1">
            Waypoint Properties
          </label>
          <div className="grid grid-cols-2 gap-2">
            {!isStart && (
              <button
                onClick={() => handleSetWaypointType("start")}
                className="flex items-center justify-center gap-1.5 py-1.5 rounded-lg border border-emerald-200 dark:border-emerald-500/20 bg-emerald-50 dark:bg-emerald-500/5 text-emerald-600 dark:text-emerald-400 text-[10px] font-bold hover:bg-emerald-100 dark:hover:bg-emerald-500/10 transition-colors"
              >
                <MapPinned className="w-3.5 h-3.5" /> Set Start
              </button>
            )}
            {!isEnd && (
              <button
                onClick={() => handleSetWaypointType("end")}
                className="flex items-center justify-center gap-1.5 py-1.5 rounded-lg border border-red-200 dark:border-red-500/20 bg-red-50 dark:bg-red-500/5 text-red-600 dark:text-red-400 text-[10px] font-bold hover:bg-red-100 dark:hover:bg-red-500/10 transition-colors"
              >
                <CornerDownLeft className="w-3.5 h-3.5" /> Set End
              </button>
            )}
            {wp.isStopBy ? (
              <button
                onClick={() => handleSetWaypointType("normal")}
                className="col-span-2 flex items-center justify-center gap-1.5 py-1.5 rounded-lg border border-blue-200 dark:border-blue-500/20 bg-blue-50 dark:bg-blue-500/5 text-blue-600 dark:text-blue-400 text-[10px] font-bold hover:bg-blue-100 dark:hover:bg-blue-500/10 transition-colors"
              >
                <MapPinPlus className="w-3.5 h-3.5" /> Revert to Normal Stop
              </button>
            ) : (
              <button
                onClick={() => handleSetWaypointType("stopby")}
                className="flex items-center justify-center gap-1.5 py-1.5 rounded-lg border border-amber-200 dark:border-amber-500/20 bg-amber-50 dark:bg-amber-500/5 text-amber-600 dark:text-amber-500 text-[10px] font-bold hover:bg-amber-100 dark:hover:bg-amber-500/10 transition-colors"
              >
                <MapPin className="w-3.5 h-3.5" /> Set Stop-By
              </button>
            )}
          </div>
        </div>

        {/* Connect to Route Toggle (Only visible if Stop-By) */}
        {wp.isStopBy && (
          <button
            onClick={() => {
              updateWaypoint(wp.id, { connectToRoute: !wp.connectToRoute });
              if (setIsDirty) setIsDirty(true);
            }}
            className={`flex justify-center items-center gap-2 w-full py-2 rounded-lg border text-xs font-bold transition-all shadow-sm ${
              wp.connectToRoute
                ? "border-amber-200 dark:border-amber-500/30 bg-amber-100/50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 hover:bg-amber-100 dark:hover:bg-amber-500/20"
                : "border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-500/20"
            }`}
          >
            {wp.connectToRoute ? (
              <UnlinkIcon className="w-4 h-4" />
            ) : (
              <LinkIcon className="w-4 h-4" />
            )}
            {wp.connectToRoute ? "Disconnect from Route" : "Connect to Route"}
          </button>
        )}

        <div className="w-full h-px bg-zinc-200 dark:bg-white/10 my-1" />

        <button
          onClick={() => {
            if (confirm(`Remove ${wp.name}?`)) {
              setWaypoints(waypoints.filter((w) => w.id !== wp.id));
              setActiveWaypointId(null);
              onClose();
            }
          }}
          className="w-full py-2 rounded-xl border border-zinc-200 dark:border-white/10 bg-white dark:bg-navidark-600 text-red-600 dark:text-red-400 text-xs font-bold hover:bg-red-50 dark:hover:bg-red-500/10 transition-colors flex justify-center items-center gap-2 shadow-sm"
        >
          <Trash2 className="w-4 h-4" /> Remove Waypoint
        </button>
      </div>
    </aside>
  );
}
