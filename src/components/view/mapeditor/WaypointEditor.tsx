import {
  ChevronLeft,
  ImageIcon,
  X,
  Trash2,
  MapPin,
  Settings2,
} from "../../ui/icons";
import { ScrubInput } from "../../ui/ScrubInput";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { invoke } from "@tauri-apps/api/core";
import { ScriptInput } from "../../ui/ScriptInput";
import { open } from "@tauri-apps/plugin-dialog";

export function WaypointEditor({
  wpId,
  onClose,
}: {
  wpId: string;
  onClose: () => void;
}) {
  const { waypoints, setWaypoints, updateWaypoint, settings, setActiveWaypointId } = useWorkspace();
  const { showToast } = useUI();

  const wp = waypoints.find((w) => w.id === wpId);
  if (!wp) return null;

  const wpImages = wp.images || [];
  const wpImagePans = wp.imagePans || [];

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
      updateWaypoint(wp.id, { images: newImages, imagePans: newPans });
    }
  };

  const updateImagePan = (idx: number, pan: string) => {
    const newPans = [...wpImagePans];
    newPans[idx] = pan;
    updateWaypoint(wp.id, { imagePans: newPans });
  };

  const handleRemoveImage = (idx: number) => {
    updateWaypoint(wp.id, {
      images: wpImages.filter((_, i) => i !== idx),
      imagePans: wpImagePans.filter((_, i) => i !== idx),
    });
  };

  return (
    <aside className="w-85 shrink-0 bg-white dark:bg-zinc-950 border-r border-zinc-200 dark:border-white/10 flex flex-col h-full select-none z-10 relative shadow-xl transition-colors">
      {/* --- HEADER --- */}
      <div className="flex items-center gap-3 p-4 border-b border-zinc-200 dark:border-white/10 shrink-0">
        <button
          onClick={onClose}
          className="p-1.5 -ml-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors"
        >
          <ChevronLeft className="w-5 h-5" />
        </button>
        <div className="flex flex-col min-w-0">
          <span className="text-[10px] font-bold text-emerald-600 dark:text-emerald-500 uppercase tracking-wider">
            Editing Stop
          </span>
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
            {wp.name}
          </h2>
        </div>
      </div>

      {/* --- SCROLLABLE EDITOR CONTENT --- */}
      <div className="flex-1 flex flex-col min-h-0 space-y-6 overflow-y-auto custom-scrollbar p-5">
        {/* Location Name */}
        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-1.5">
            <MapPin className="w-3.5 h-3.5 text-zinc-400" /> Location Name
          </label>
          <input
            type="text"
            value={wp.name}
            onChange={(e) => updateWaypoint(wp.id, { name: e.target.value })}
            className="w-full bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-white/10 rounded-xl px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-emerald-500 dark:focus:border-emerald-500/50 transition-colors shadow-sm"
          />
        </div>

        {/* 2. AI Script Component */}
        <ScriptInput
          value={wp.narration || ""}
          onChange={(v) => updateWaypoint(wp.id, { narration: v })}
          isGenerating={wp.isGeneratingScript || false}
          onCancel={() => {
            updateWaypoint(wp.id, { isGeneratingScript: false });
            invoke("cancel_python_blueprint").catch(console.error);
            showToast(`Canceled script generation for ${wp.name}`, "info");
          }}
          onGenerate={async (prompt, engine) => {
            updateWaypoint(wp.id, { isGeneratingScript: true });
            showToast(`Started writing script for ${wp.name}...`, "info");

            try {
              const payload = JSON.stringify({
                prompt: prompt,
                lat: wp.lat,
                lng: wp.lng,
                locationName: wp.name,
                engine: engine
              });

              const pythonResponse = await invoke<string>("run_python_blueprint", {
                action: "generate_script",
                payload: payload,
              });

              const parsed = JSON.parse(pythonResponse);
              if (parsed.success) {
                updateWaypoint(wp.id, { narration: parsed.script, isGeneratingScript: false });
                showToast(`Script finished for ${wp.name}!`, "success");
              } else {
                console.error(parsed.error);
                throw new Error(parsed.error);
              }
            } catch (error) {
              updateWaypoint(wp.id, { isGeneratingScript: false });
              console.log("Error: ", error);
              showToast(`Generation failed for ${wp.name}: ${error}`, "error");
            }
          }}
        />

        {/* Images */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-1.5">
              <ImageIcon className="w-3.5 h-3.5 text-zinc-400" /> Pop-up Pictures
            </label>
            <span className="text-[10px] font-medium text-zinc-400 bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 rounded-md">
              {wpImages.length} / 3
            </span>
          </div>

          <div className="flex flex-col gap-2">
            {wpImages.map((img, idx) => {
              const currentPan = wpImagePans[idx] || "none";
              return (
                <div
                  key={idx}
                  className="flex flex-col bg-zinc-50 dark:bg-zinc-900/80 border border-zinc-200 dark:border-white/10 rounded-lg p-2 group hover:border-zinc-300 dark:hover:border-white/20 transition-colors gap-2 shadow-sm"
                >
                  <div className="flex items-center justify-between border-b border-zinc-200/50 dark:border-white/5 pb-2">
                    <span
                      className="text-xs font-medium text-zinc-700 dark:text-zinc-300 truncate mr-2"
                      title={img}
                    >
                      {img.split(/[/\\]/).pop()}
                    </span>
                    <button
                      onClick={() => handleRemoveImage(idx)}
                      className="p-1 text-zinc-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-md transition-colors shrink-0"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  <ScrubInput
                    label="Camera Pan"
                    value={currentPan}
                    onChange={(v) => updateImagePan(idx, v)}
                    options={["left", "none", "right"]}
                  />
                </div>
              );
            })}

            {wpImages.length < 3 && (
              <button
                onClick={handleImageSelect}
                className="w-full bg-zinc-50 dark:bg-zinc-900/50 hover:bg-emerald-50 dark:hover:bg-emerald-500/10 border border-zinc-300 dark:border-white/10 hover:border-emerald-500/50 border-dashed rounded-xl py-3 text-xs font-medium text-zinc-500 hover:text-emerald-600 dark:hover:text-emerald-400 transition-all flex items-center justify-center gap-2 mt-1"
              >
                + Add Image
              </button>
            )}

            {wpImages.length > 0 && (
              <div className="flex p-0.5 mt-2 bg-zinc-100 dark:bg-zinc-900 rounded-lg border border-zinc-200/50 dark:border-white/5">
                <button
                  onClick={() => updateWaypoint(wp.id, { imageDisplay: "pip" })}
                  className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all duration-200 ${wp.imageDisplay !== "fullscreen" ? "bg-white dark:bg-zinc-800 shadow-sm text-emerald-600 dark:text-emerald-400" : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-200/50 dark:hover:bg-white/5"}`}
                >
                  PIP Overlay
                </button>
                <button
                  onClick={() =>
                    updateWaypoint(wp.id, { imageDisplay: "fullscreen" })
                  }
                  className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all duration-200 ${wp.imageDisplay === "fullscreen" ? "bg-white dark:bg-zinc-800 shadow-sm text-emerald-600 dark:text-emerald-400" : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-200/50 dark:hover:bg-white/5"}`}
                >
                  Fullscreen
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Timing & FPS Override */}
        <div className="bg-zinc-50 dark:bg-zinc-900/40 border border-zinc-200 dark:border-white/10 rounded-xl p-4 space-y-3 mt-2">
          <h4 className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-1.5">
            <Settings2 className="w-3.5 h-3.5" /> Timing & Video
          </h4>
          <div className="space-y-3">
            <ScrubInput
              label="Hold Duration"
              value={wp.duration || settings.duration_seconds}
              onChange={(v) => updateWaypoint(wp.id, { duration: v })}
              min={1}
              max={8}
              step={1}
              suffix="s"
            />
            <ScrubInput
              label="Frame Rate"
              value={wp.fps || settings.fps}
              onChange={(v) => updateWaypoint(wp.id, { fps: v })}
              min={24}
              max={60}
              step={1}
              options={["24", "30", "60"]}
              suffix=" FPS"
            />
          </div>
        </div>
      </div>

      {/* --- FOOTER / DANGER ZONE --- */}
      <div className="p-4 border-t border-zinc-200 dark:border-white/10 shrink-0 bg-zinc-50/50 dark:bg-zinc-900/20">
        <button
          onClick={() => {
            if (confirm(`Remove ${wp.name}?`)) {
              setWaypoints(waypoints.filter((w) => w.id !== wp.id));
              setActiveWaypointId(null);
              onClose();
            }
          }}
          className="w-full py-2.5 rounded-xl border border-red-200 dark:border-red-500/20 bg-white dark:bg-zinc-950 text-red-600 dark:text-red-400 text-xs font-bold hover:bg-red-50 dark:hover:bg-red-500/10 transition-colors flex justify-center items-center gap-2 shadow-sm"
        >
          <Trash2 className="w-4 h-4" /> Remove Waypoint
        </button>
      </div>
    </aside>
  );
}