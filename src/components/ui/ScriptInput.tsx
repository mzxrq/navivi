import { useEffect, useState } from "react";
import {
  Mic,
  Sparkles,
  Square,
  Check,
  PencilSparkles // ✨ NEW: Using the matching icon from OverviewPanel
} from "../ui/icons";

const thinkingSteps = [
  "Detecting context...",
  "Searching for location facts...",
  "Cross-checking building data...",
  "Drafting narration...",
  "Polishing voiceover tone...",
];

interface ScriptInputProps {
  value: string;
  onChange: (v: string) => void;
  onGenerate: (prompt: string, engine: string, language: string) => void;
  isGenerating: boolean;
  onCancel?: () => void;
}

export function ScriptInput({
  value,
  onChange,
  onGenerate,
  isGenerating,
  onCancel,
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
        prev < thinkingSteps.length - 1 ? prev + 1 : prev,
      );
    }, 1800);
    return () => clearInterval(interval);
  }, [isGenerating]);

  const hasUnsavedChanges = localPrompt !== value;

  const handleGenerateClick = () => {
    if (!localPrompt.trim()) return;
    // ✨ FIXED: Force gemma2 just like OverviewPanel
    onGenerate(localPrompt, "gemma2", language); 
  };

  const handleSaveClick = () => {
    onChange(localPrompt);
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-1.5">
          <Mic className="w-3.5 h-3.5 text-zinc-400" /> AI Script
        </label>

        <div className="flex items-center gap-2">
          {/* Toggle between Auto-Write and Cancel */}
          {isGenerating ? (
            <button
              onClick={onCancel}
              className="shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-bold transition-all bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-500/20 border border-red-200 dark:border-red-500/20 shadow-sm"
            >
              <Square className="w-3 h-3 fill-current" />
              Cancel
            </button>
          ) : (
            <button
              onClick={handleGenerateClick}
              disabled={!localPrompt.trim()}
              // ✨ FIXED: Match OverviewPanel styling exactly
              className="shrink-0 flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed bg-navi-50 dark:bg-navi-500/10 text-navi-700 dark:text-navi-300 hover:bg-navi-100 dark:hover:bg-navi-500/20 border border-navi-200 dark:border-navi-500/20 shadow-sm"
            >
              <PencilSparkles className="w-3 h-3" />
              Auto-Write
            </button>
          )}
        </div>
      </div>

      <div className="relative w-full h-28 rounded-lg overflow-hidden shadow-inner border border-zinc-200 dark:border-navidark-300 group focus-within:border-navi-400 dark:focus-within:border-navi-500/50 transition-colors">
        <textarea
          value={localPrompt}
          onChange={(e) => setLocalPrompt(e.target.value)}
          disabled={isGenerating}
          placeholder="Type a prompt or write your own script..."
          className="w-full h-full resize-none p-3 text-xs custom-scrollbar bg-white dark:bg-navidark-800 text-zinc-900 dark:text-zinc-100 focus:outline-none disabled:opacity-50 pb-10"
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
              {hasUnsavedChanges ? "Save" : "Saved"}
            </button>
          </div>
        )}

        {isGenerating && (
          <div className="absolute inset-0 bg-white/70 dark:bg-navidark-900/70 backdrop-blur-[2px] flex flex-col items-center justify-center z-10">
            <div className="flex flex-col items-center gap-2">
              <Sparkles className="w-5 h-5 text-navi-400 animate-bounce" />
              <div className="text-[10px] font-bold text-navi-600 dark:text-navi-300 tracking-wide uppercase">
                AI is writing...
              </div>
              <div className="text-[9px] font-medium text-zinc-500 dark:text-zinc-400 animate-fade-in text-center mb-1">
                {thinkingSteps[currentStepIndex]}
              </div>
              <div className="w-20 h-1 bg-navi-100 dark:bg-navi-900/50 rounded-full overflow-hidden">
                <div className="h-full bg-navi-500 rounded-full w-full animate-[pulse_1s_ease-in-out_infinite]"></div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}