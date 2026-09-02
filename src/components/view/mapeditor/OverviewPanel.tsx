import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  MapIcon,
  FileVideo,
  Sparkles,
  PencilSparkles,
  Square,
} from "../../ui/icons";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { EngineDropdown } from "../../ui/EngineDropdown";
import { generateOverviewScript } from "../../../services/ollamaApi";
// Import your EngineSelect component if you used Option 1 from earlier!

export function OverviewPanel() {
  const { waypoints, metadata, updateMetadata, settings, setIsDirty } =
    useWorkspace();
  const { showToast } = useUI();

  const [isGeneratingOverview, setIsGeneratingOverview] = useState(false);
  const [overviewEngine, setOverviewEngine] = useState("ollama");

  // Calculations
  const totalDuration = waypoints.reduce(
    (acc, wp) => acc + (wp.duration || settings?.duration_seconds || 3),
    0,
  );
  const estimatedTime = totalDuration.toFixed(1);

  const handleGenerateOverview = async () => {
    const waypointNames = waypoints
      .map((wp) => wp.name)
      .filter((name) => name && name !== "Locating...");
    if (waypointNames.length === 0)
      return showToast("Please add some waypoints!", "info");
    setIsGeneratingOverview(true);
    showToast("Synthesizing route overview...", "info");

    try {
      const script = await generateOverviewScript(
        waypointNames,
        overviewEngine,
      );
      updateMetadata({ overview_narration: script });
      setIsDirty(true);
      showToast("Overview script compiled!", "success");
    } catch (error) {
      showToast(`Overview generation failed: ${error}`, "error");
    } finally {
      setIsGeneratingOverview(false);
    }
  };

  const handleCancel = () => {
    setIsGeneratingOverview(false);
    invoke("cancel_python_blueprint").catch(console.error);
    showToast("Overview generation canceled.", "info");
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-[12px] font-medium text-zinc-400">
          <span className="flex items-center gap-1 text-navi-600 dark:text-navi">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              className="lucide lucide-sparkles-icon lucide-sparkles"
            >
              <path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z" />
              <path d="M20 2v4" />
              <path d="M22 4h-4" />
              <circle cx="4" cy="20" r="2" />
            </svg>
            <p className="text-zinc-400 text-[10px]">Overview Narration</p>
          </span>
        </div>
        <div className="space-y-1.5">
          <div className="flex justify-between">
            <div className="flex items-center gap-2">
              <EngineDropdown
                value={overviewEngine || "ollama"}
                onChange={(val) => setOverviewEngine(val)}
                disabled={isGeneratingOverview}
              />

              {isGeneratingOverview ? (
                <button
                  onClick={handleCancel}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-bold transition-all bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-500/20 border border-red-200 dark:border-red-500/20 shadow-sm"
                >
                  <Square className="w-3 h-3 fill-current" />
                  Cancel
                </button>
              ) : (
                <button
                  onClick={handleGenerateOverview}
                  disabled={isGeneratingOverview || waypoints.length === 0}
                  className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed bg-navi-800/40 dark:bg-navi-500/10 text-navi-900 dark:text-navi-200 hover:text-navi-100 hover:bg-navi dark:hover:bg-navi-200/20 dark:hover:text-navi-400 border border-navi-600 dark:border-navi-200/20 shadow-sm"
                >
                  <PencilSparkles
                    className={`w-3 h-3 ${isGeneratingOverview ? "animate-pulse" : ""}`}
                  />
                  Write
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 3. Textarea with Glass Overlay */}
      {/* Textarea Container with Glass Loading Overlay */}
      <div className="relative w-full h-24 rounded-xl overflow-hidden shadow-sm border border-zinc-200 dark:border-white/10 group focus-within:border-zinc-200 dark:focus-within:border-zinc-200/50 transition-colors">
        <textarea
          value={metadata.overview_narration || ""}
          onChange={(e) =>
            updateMetadata({ overview_narration: e.target.value })
          }
          disabled={isGeneratingOverview}
          placeholder="e.g., Welcome to our road trip! Today we'll explore..."
          className="w-full h-full resize-none p-3 text-xs custom-scrollbar bg-zinc-50 dark:bg-zinc-900/50 text-zinc-900 dark:text-zinc-100 focus:outline-none"
        />

        {/* Background Processing Indicator */}
        {isGeneratingOverview && (
          <div className="absolute inset-0 bg-white/70 dark:bg-zinc-950/70 backdrop-blur-[2px] flex flex-col items-center justify-center z-10">
            <div className="flex flex-col items-center gap-2">
              <Sparkles className="w-5 h-5 text-zinc-200 animate-bounce" />
              <div className="text-[10px] font-bold text-fuchsia-400 dark:text-purple-300 tracking-wide uppercase">
                Gemma is summarizing route...
              </div>
              <div className="w-20 h-1 bg-emerald-100 dark:bg-purple-900/50 rounded-full overflow-hidden">
                <div className="h-full bg-zinc-200 rounded-full w-full animate-[pulse_1s_ease-in-out_infinite]"></div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
