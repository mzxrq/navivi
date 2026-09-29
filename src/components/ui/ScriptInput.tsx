import { useEffect, useState, useRef } from "react";
import {
  Mic,
  Sparkles,
  Square,
  Check,
  BookOpen,
  PencilSparkles,
} from "../ui/icons";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useWorkspace } from "../../hooks/useWorkspace";

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
  const { settings, updateSettings, setIsDirty } = useWorkspace();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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

  const extractPronunciation = (text: string): string => {
    // Note: Half and full width parenthesis match
    const regex =
      /([\u4E00-\u9FAF\u3400-\u4DBF]+)[(（]([\u3040-\u309F\u30A0-\u30FF]*)[)）]/g;
    let match;
    let hasDictUpdate = false;
    const newDict = [...(settings.pronunciation_dictionary || [])];

    while ((match = regex.exec(text)) !== null) {
      const kanji = match[1];
      const kana = match[2];

      const exists = newDict.find((entry) => entry.word === kanji);
      if (exists) {
        exists.reading = kana;
      } else {
        newDict.push({ word: kanji, reading: kana });
      }
      hasDictUpdate = true;
    }

    if (hasDictUpdate) {
      updateSettings({ pronunciation_dictionary: newDict });
      setIsDirty(true);
      return text.replace(
        /([\u4E00-\u9FAF\u3400-\u4DBF]+)[(（][\u3040-\u309F\u30A0-\u30FF]*[)）]/g,
        "$1",
      );
    }
    return text;
  };

  // Extract on AI generation completion
  useEffect(() => {
    if (!isGenerating && value !== localPrompt) {
      const cleaned = extractPronunciation(value);
      if (cleaned !== value) {
        onChange(cleaned);
      }
    }
  }, [isGenerating]);

  const handleScanKanji = () => {
    const kanjiRegex = /([\u4E00-\u9FAF\u3400-\u4DBF]+)/g;
    let match;
    let hasDictUpdate = false;
    const newDict = [...(settings.pronunciation_dictionary || [])];

    while ((match = kanjiRegex.exec(localPrompt)) !== null) {
      const kanji = match[1];
      const exists = newDict.find((entry) => entry.word === kanji);
      if (!exists) {
        newDict.push({ word: kanji, reading: "" });
        hasDictUpdate = true;
      }
    }

    if (hasDictUpdate) {
      updateSettings({ pronunciation_dictionary: newDict });
      setIsDirty(true);
    }
    // Return focus to textarea
    textareaRef.current?.focus();
  };

  const handleSaveClick = (e: React.MouseEvent) => {
    e.preventDefault();
    const cleaned = extractPronunciation(localPrompt);
    onChange(cleaned);
    setLocalPrompt(cleaned);
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
              <span
                className="text-[10px] font-bold uppercase tracking-wider animate-pulse truncate"
                title={thoughtProcess}
              >
                {thoughtProcess
                  ? thoughtProcess
                      .split("\n")
                      .filter((l) => l.trim())
                      .pop()
                  : getThinkingSteps()[currentStepIndex] ||
                    getThinkingSteps()[0]}
              </span>
            </div>
          )}
          {aiEnabled &&
            (isGenerating ? (
              <button
                type="button"
                onClick={onCancel}
                className="shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-bold transition-all bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-500/20 border border-red-200 dark:border-red-500/20 shadow-sm"
              >
                <Square className="w-3 h-3 fill-current" />
                <Trans>cancel</Trans>
              </button>
            ) : (
              <button
                type="button"
                onClick={handleGenerateClick}
                disabled={!localPrompt.trim()}
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
          ref={textareaRef}
          value={localPrompt}
          onChange={(e) => setLocalPrompt(e.target.value)}
          readOnly={isGenerating}
          placeholder={t`Type a prompt or write your own script...`}
          className="w-full h-full resize-none p-3 text-xs custom-scrollbar bg-white dark:bg-navidark-800 text-zinc-900 dark:text-zinc-100 focus:outline-none readOnly:opacity-80 pb-10"
        />

        {!isGenerating && (
          <div className="absolute bottom-2 right-2 flex items-center">
            <button
              type="button"
              onClick={handleScanKanji}
              className="w-8 h-8 mr-2 rounded-full bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-300 flex items-center justify-center transition-all opacity-0 group-focus-within:opacity-100"
              title={t`Scan script for all Kanji and add to Dictionary`}
            >
              <BookOpen className="w-4 h-4" />
            </button>
            <button
              type="button"
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
