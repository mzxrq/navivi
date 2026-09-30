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
  showLabel?: boolean;
}

export function ScriptInput({
  value,
  onChange,
  onGenerate,
  isGenerating,
  onCancel,
  aiEnabled = false,
  thoughtProcess = "",
  showLabel = true,
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

  const commit = () => {
    if (isGenerating || localPrompt === value) return;
    const cleaned = extractPronunciation(localPrompt);
    onChange(cleaned);
    setLocalPrompt(cleaned);
  };

  const handleSaveClick = (e: React.MouseEvent) => {
    e.preventDefault();
    commit();
  };

  return (
    <div className="space-y-1.5">
      {(showLabel || aiEnabled) && (
      <div className="flex items-center justify-between min-h-6">
        {showLabel ? (
          <label className="text-[12px] font-medium text-zinc-700 dark:text-zinc-300 flex items-center gap-1.5">
            <Mic className="w-3.5 h-3.5 text-zinc-400" /> <Trans>Script</Trans>
          </label>
        ) : (
          <span />
        )}

        <div className="flex items-center gap-2 min-w-0">
          {aiEnabled && isGenerating && (
            <div className="flex items-center gap-1.5 px-1 text-navi dark:text-navi-400 overflow-hidden whitespace-nowrap max-w-50">
              <Sparkles className="w-3.5 h-3.5 animate-pulse shrink-0" />
              <span
                className="text-[11px] animate-pulse truncate"
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
                className="shrink-0 flex items-center gap-1.5 h-6 px-2 rounded-md text-[11px] font-medium transition-colors text-red-600 dark:text-red-400 hover:bg-red-500/10"
              >
                <Square className="w-3 h-3 fill-current" />
                <Trans>cancel</Trans>
              </button>
            ) : (
              <button
                type="button"
                onClick={handleGenerateClick}
                disabled={!localPrompt.trim()}
                className="shrink-0 flex items-center gap-1.5 h-6 px-2 rounded-md text-[11px] font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed text-navi hover:bg-navi/10"
              >
                <PencilSparkles className="w-3 h-3" />
                <Trans>Auto-Write</Trans>
              </button>
            ))}
        </div>
      </div>
      )}

      <div className="relative w-full h-28 rounded-lg overflow-hidden border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-950 group focus-within:border-navi focus-within:ring-2 focus-within:ring-navi/20 transition-colors">
        <textarea
          ref={textareaRef}
          value={localPrompt}
          onChange={(e) => setLocalPrompt(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              commit();
            }
          }}
          readOnly={isGenerating}
          placeholder={t`Type a prompt or write your own script...`}
          className="w-full h-full resize-none p-2.5 pb-10 text-[13px] leading-relaxed custom-scrollbar bg-transparent text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-600 focus:outline-none read-only:opacity-80"
        />

        {localPrompt.length > 0 && (
          <span className="absolute bottom-2.5 left-2.5 text-[11px] text-zinc-400 dark:text-zinc-500 tabular-nums pointer-events-none">
            {t`${localPrompt.length} characters`}
          </span>
        )}

        {!isGenerating && (
          <div className="absolute bottom-1.5 right-1.5 flex items-center gap-1">
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={handleScanKanji}
              className="w-6 h-6 rounded-md text-zinc-500 hover:text-zinc-800 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/5 flex items-center justify-center transition-all opacity-0 group-focus-within:opacity-100"
              title={t`Scan script for all Kanji and add to Dictionary`}
              aria-label={t`Scan script for all Kanji and add to Dictionary`}
            >
              <BookOpen className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={handleSaveClick}
              onMouseDown={(e) => e.preventDefault()}
              disabled={!hasUnsavedChanges}
              title={t`Save (Ctrl+Enter)`}
              className={`flex items-center gap-1 h-6 px-2 rounded-md text-[11px] font-medium transition-colors ${
                hasUnsavedChanges
                  ? "bg-navi hover:brightness-110 text-white"
                  : "text-zinc-400 dark:text-zinc-500 cursor-default"
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
