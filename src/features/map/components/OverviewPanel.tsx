import { useState, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  Sparkles,
  PencilSparkles,
  Square,
  ChevronUp,
  ChevronDown,
  X,
} from "../../../components/ui/icons";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import {
  generateOverviewScriptStream,
  checkModelExists,
} from "../../../services/ollamaApi";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

export function OverviewPanel() {
  const { waypoints, metadata, updateMetadata, setIsDirty, settings } =
    useWorkspace();
  const { showToast } = useUI();

  const [showOverview, setShowOverview] = useState(
    !!metadata.overview_narration || !!metadata.theme,
  );
  const [isGeneratingOverview, setIsGeneratingOverview] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  const handleGenerateOverview = async () => {
    const waypointNames = waypoints
      .map((wp) => wp.name)
      .filter((name) => name && name !== "Locating...");

    if (waypointNames.length === 0) {
      return showToast(t`Please add some waypoints!`, "info");
    }

    let engine = settings.ai_model || "schroneko/gemma-2-2b-jpn-it";
    const hasModel = await checkModelExists(engine);
    if (!hasModel) {
      return showToast(
        t`Model "${engine}" not found. Please install it from the Settings.`,
        "error",
      );
    }

    setIsGeneratingOverview(true);
    showToast(t`Generating with ${engine}...`, "info");

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      await generateOverviewScriptStream(
        waypointNames,
        engine,
        metadata.theme || "",
        (chunk) => {
          updateMetadata({ overview_narration: chunk });
        },
        controller.signal
      );
      setIsDirty(true);
      showToast(t`Overview script compiled!`, "success");
    } catch (error: any) {
      if (error?.name === "AbortError") {
        showToast(t`Overview generation canceled.`, "info");
        return;
      }
      const errorDetail =
        error?.message ||
        (typeof error === "string" ? error : JSON.stringify(error));
      showToast(t`Overview generation failed: ${errorDetail}`, "error");
    } finally {
      setIsGeneratingOverview(false);
      abortControllerRef.current = null;
    }
  };

  const handleCancel = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsGeneratingOverview(false);
    invoke("cancel_python_blueprint").catch(console.error);
    showToast(t`Overview generation canceled.`, "info");
  };

  if (!showOverview) {
    const hasData = !!metadata.overview_narration || !!metadata.theme;
    return (
      <button
        onClick={() => setShowOverview(true)}
        className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl border border-dashed border-zinc-300 dark:border-white/10 text-xs font-semibold text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-black/5 dark:hover:bg-white/5 transition-colors shrink-0"
      >
        <span>
          {hasData ? t`Course Concept & Intro` : t`+ Add Course Theme & Intro`}
        </span>
        {hasData && <ChevronDown className="w-3.5 h-3.5" />}
      </button>
    );
  }

  return (
    <div className="space-y-3 bg-zinc-50/50 dark:bg-navidark-800/50 p-3 rounded-xl border border-zinc-200/80 dark:border-navidark-700 shrink-0">
      <div className="flex justify-between items-center">
        <label className="text-[11px] font-bold text-zinc-800 dark:text-zinc-200 tracking-wide uppercase flex items-center gap-1.5">
          <PencilSparkles className="w-3.5 h-3.5 text-navi" />
          <Trans>Course Concept & Intro</Trans>
        </label>
        <button
          onClick={() => setShowOverview(false)}
          title="Collapse"
          className="p-1 rounded-md text-zinc-400 hover:text-zinc-600 hover:bg-zinc-200 dark:hover:text-zinc-200 dark:hover:bg-navidark-700 transition-colors"
        >
          <ChevronUp className="w-3.5 h-3.5" />
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
          placeholder={t`Course Theme`}
          className="w-full bg-white dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-700 rounded-lg px-2.5 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-navi dark:focus:border-navi focus:ring-1 focus:ring-navi/30 shadow-sm transition-all"
        />
      </div>

      <div className="relative w-full h-28 rounded-lg overflow-hidden shadow-sm border border-zinc-200 dark:border-navidark-700 focus-within:border-navi dark:focus-within:border-navi focus-within:ring-1 focus-within:ring-navi/30 transition-all">
        <textarea
          value={metadata.overview_narration || ""}
          onChange={(e) => {
            updateMetadata({ overview_narration: e.target.value });
            setIsDirty(true);
          }}
          disabled={isGeneratingOverview}
          placeholder={t`Opening Narration...`}
          className="w-full h-full resize-none p-3 pb-10 text-xs custom-scrollbar bg-white dark:bg-navidark-900 text-zinc-900 dark:text-zinc-100 focus:outline-none disabled:opacity-50 leading-relaxed"
        />

        <div className="absolute bottom-2 right-2 flex items-center gap-2 z-20">
          {isGeneratingOverview ? (
            <button
              onClick={handleCancel}
              className="shrink-0 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] font-bold transition-all bg-red-500/10 text-red-600 dark:text-red-400 hover:bg-red-500/20 shadow-sm"
            >
              <Square className="w-3 h-3 fill-current" /> <Trans>Cancel</Trans>
            </button>
          ) : (
            <button
              onClick={handleGenerateOverview}
              disabled={isGeneratingOverview || waypoints.length === 0}
              className="shrink-0 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed bg-navi hover:bg-navi-600 text-white shadow-md shadow-navi/20"
            >
              <Sparkles className="w-3 h-3" /> <Trans>Auto-Write</Trans>
            </button>
          )}
        </div>

        {isGeneratingOverview && (
          <div className="absolute inset-0 bg-white/80 dark:bg-navidark-900/80 backdrop-blur-[2px] flex flex-col items-center justify-center z-10 animate-in fade-in">
            <div className="flex flex-col items-center gap-3">
              <Sparkles className="w-6 h-6 text-navi animate-bounce" />
              <div className="text-[10px] font-bold text-navi tracking-wider uppercase">
                <Trans>Synthesizing...</Trans>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
