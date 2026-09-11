import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Sparkles, PencilSparkles, Square, X } from "../../ui/icons";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { generateOverviewScriptStream, checkModelExists } from "../../../services/ollamaApi";

export function OverviewPanel() {
  const { waypoints, metadata, updateMetadata, setIsDirty } = useWorkspace();
  const { showToast } = useUI();

  const [showOverview, setShowOverview] = useState(!!metadata.overview_narration || !!metadata.theme);
  const [isGeneratingOverview, setIsGeneratingOverview] = useState(false);

  const handleGenerateOverview = async () => {
    const waypointNames = waypoints
      .map((wp) => wp.name)
      .filter((name) => name && name !== "Locating...");
      
    if (waypointNames.length === 0) {
      return showToast("Please add some waypoints!", "info");
    }

    // Try Qwen2.5 first if they have it, otherwise fallback to Gemma2
    let engine = "gemma2";
    const hasQwen = await checkModelExists("qwen2.5");
    if (hasQwen) engine = "qwen2.5";
    else {
      const hasGemma = await checkModelExists("gemma2");
      if (!hasGemma) return showToast(`Model "gemma2" or "qwen2.5" not found. Please install one via Ollama!`, "error");
    }
      
    setIsGeneratingOverview(true);
    showToast(`Synthesizing with ${engine}...`, "info");

    try {
      // ✨ Pass the theme to the API!
      await generateOverviewScriptStream(waypointNames, engine, metadata.theme || "", (chunk) => {
        updateMetadata({ overview_narration: chunk });
      });
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

  if (!showOverview) {
    return (
      <button
        onClick={() => setShowOverview(true)}
        className="w-full text-left px-3 py-2.5 rounded-xl border border-dashed border-zinc-300 dark:border-navidark-400 text-xs font-semibold text-zinc-500 hover:text-navi-600 dark:hover:text-navi-400 hover:bg-navi-50 dark:hover:bg-navi-900/20 transition-colors shrink-0"
      >
        + Add Course Theme & Intro
      </button>
    );
  }

  return (
    <div className="space-y-3 bg-zinc-50 dark:bg-navidark-700/30 p-3 rounded-xl border border-zinc-200 dark:border-navidark-400 shrink-0">
      
      <div className="flex justify-between items-center">
        <label className="text-xs font-bold text-navi-700 dark:text-navi-400">
          Course Concept & Intro
        </label>
        <button onClick={() => setShowOverview(false)} className="text-zinc-400 hover:text-red-500 transition-colors">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* ✨ NEW: Theme Input */}
      <div className="space-y-1.5">
        <input
          type="text"
          value={metadata.theme || ""}
          onChange={(e) => {
            updateMetadata({ theme: e.target.value });
            setIsDirty(true);
          }}
          placeholder="Course Theme (e.g., 葛城修験と友ヶ島廃墟巡り)"
          className="w-full bg-white dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-300 rounded-lg px-2.5 py-1.5 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-navi-400 shadow-sm"
        />
      </div>

      <div className="flex items-center justify-between mt-2">
        <p className="text-[10px] text-zinc-500 dark:text-navidark-150 leading-tight pr-4">
          AI will use the theme above to write a perfect Japanese intro.
        </p>
        {isGeneratingOverview ? (
          <button
            onClick={handleCancel}
            className="shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-bold transition-all bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 hover:bg-red-100 border border-red-200 shadow-sm"
          >
            <Square className="w-3 h-3 fill-current" /> Cancel
          </button>
        ) : (
          <button
            onClick={handleGenerateOverview}
            disabled={isGeneratingOverview || waypoints.length === 0}
            className="shrink-0 flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed bg-navi-50 dark:bg-navi-500/10 text-navi-700 dark:text-navi-300 hover:bg-navi-100 border border-navi-200 shadow-sm"
          >
            <PencilSparkles className="w-3 h-3" /> Auto-Write
          </button>
        )}
      </div>

      <div className="relative w-full h-24 rounded-lg overflow-hidden shadow-inner border border-zinc-200 dark:border-navidark-300 group focus-within:border-navi-400 transition-colors">
        <textarea
          value={metadata.overview_narration || ""}
          onChange={(e) => {
            updateMetadata({ overview_narration: e.target.value });
            setIsDirty(true);
          }}
          disabled={isGeneratingOverview}
          placeholder="オープニングナレーション..."
          className="w-full h-full resize-none p-3 text-xs custom-scrollbar bg-white dark:bg-navidark-800 text-zinc-900 dark:text-zinc-100 focus:outline-none disabled:opacity-50"
        />

        {isGeneratingOverview && (
          <div className="absolute inset-0 bg-white/70 dark:bg-navidark-900/70 backdrop-blur-[2px] flex flex-col items-center justify-center z-10">
            <div className="flex flex-col items-center gap-2">
              <Sparkles className="w-5 h-5 text-navi-400 animate-bounce" />
              <div className="text-[10px] font-bold text-navi-600 dark:text-navi-300 tracking-wide uppercase">
                AI is writing...
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}