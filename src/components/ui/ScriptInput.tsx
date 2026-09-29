import { useEffect, useState } from "react";
import { Mic, Sparkles, Square, Check, PencilSparkles } from "../ui/icons";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

const getThinkingSteps = () => [
  t`Detecting context...`,
  t`Searching...`,
  t`Cross-checking building data...`,
  t`Drafting narration...`,
  t`Polishing voiceover tone...`,
];

interface ScriptInputProps {
  value: string;
  onChange: (v: string) => void;
  onGenerate: (prompt: string, engine: string, language: string) => void;
  isGenerating: boolean;
  onCancel?: () => void;
  aiEnabled?: boolean;
  thoughtProcess?: string;
}

export function ScriptInput({
  value,
  onChange,
  onGenerate,
  isGenerating,
  onCancel,
  aiEnabled = false,
  thoughtProcess = "",
}: ScriptInputProps) {
  const [localPrompt, setLocalPrompt] = useState(value);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const language = "English";

  // Sync internal state when prop changes externally (e.g. generation finishes)
  useEffect(() => {
    setLocalPrompt(value);
  }, [value]);

  useEffect(() => {
    if (!isGenerating) {
      setCurrentStepIndex(0);
      return;
    }
    const interval = setInterval(() => {
      setCurrentStepIndex((prev) =>
        prev < getThinkingSteps().length - 1 ? prev + 1 : prev,
      );
    }, 1800);
    return () => clearInterval(interval);
  }, [isGenerating]);

  const hasUnsavedChanges = localPrompt !== value;

  const handleGenerateClick = () => {
    if (!localPrompt.trim()) return;
    onGenerate(localPrompt, "gemma2", language);
  };

  const handleSaveClick = () => {
    onChange(localPrompt);
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-1.5">
          <Mic className="w-3.5 h-3.5 text-zinc-400" /> <Trans>Script</Trans>
        </label>

        <div className="flex items-center gap-2">
          {aiEnabled && isGenerating && (
            <div className="flex items-center gap-1.5 px-2 text-navi-500 dark:text-navi-400 animate-fade-in overflow-hidden whitespace-nowrap max-w-[200px]">
              <Sparkles className="w-3.5 h-3.5 animate-pulse shrink-0" />
              <span className="text-[10px] font-bold uppercase tracking-wider animate-pulse truncate" title={thoughtProcess}>
                {thoughtProcess ? thoughtProcess.split("\n").filter(l => l.trim()).pop() : (getThinkingSteps()[currentStepIndex] || getThinkingSteps()[0])}
              </span>
            </div>
          )}
          {/* Toggle between Auto-Write and Cancel — only when AI features enabled */}
          {aiEnabled &&
            (isGenerating ? (
              <button
                onClick={onCancel}
                className="shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-bold transition-all bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-500/20 border border-red-200 dark:border-red-500/20 shadow-sm"
              >
                <Square className="w-3 h-3 fill-current" />
                <Trans>cancel</Trans>
              </button>
            ) : (
              <button
                onClick={handleGenerateClick}
                disabled={!localPrompt.trim()}
                // ✨ FIXED: Match OverviewPanel styling exactly
                className="shrink-0 flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed bg-navi-50 dark:bg-navi-500/10 text-navi-700 dark:text-navi-300 hover:bg-navi-100 dark:hover:bg-navi-500/20 border border-navi-200 dark:border-navi-500/20 shadow-sm"
              >
                <PencilSparkles className="w-3 h-3" />
                <Trans>Auto-Write</Trans>
              </button>
            ))}
        </div>
      </div>

      <div className="relative w-full h-28 rounded-lg overflow-hidden shadow-inner border border-zinc-200 dark:border-navidark-300 group focus-within:border-navi-400 dark:focus-within:border-navi-500/50 transition-colors">
        <textarea
          value={localPrompt}
          onChange={(e) => setLocalPrompt(e.target.value)}
          readOnly={isGenerating}
          placeholder={t`Type a prompt or write your own script...`}
          className="w-full h-full resize-none p-3 text-xs custom-scrollbar bg-white dark:bg-navidark-800 text-zinc-900 dark:text-zinc-100 focus:outline-none readOnly:opacity-80 pb-10"
        />

        {!isGenerating && (
          <div className="absolute bottom-2 right-2">
            <button
              onClick={handleSaveClick}
              disabled={!hasUnsavedChanges}
              className={`flex items-center gap-1 px-3 py-1 rounded-md text-[10px] font-bold transition-all shadow-sm ${
                hasUnsavedChanges
                  ? "bg-navi hover:bg-navi-600 text-white"
                  : "bg-zinc-100 dark:bg-navidark-500 text-zinc-400 dark:text-zinc-500 cursor-default"
              }`}
            >
              <Check className="w-3 h-3" />
              {hasUnsavedChanges ? t`Save` : t`Saved`}
            </button>
          </div>
        )}


      </div>
    </div>
  );
}
