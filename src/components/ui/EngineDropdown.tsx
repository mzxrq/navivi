import { useState, useRef, useEffect } from "react";
import { ChevronDown, Check, ToolCase } from "./icons";

interface EngineDropdownProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

const llmEngines = [
  { id: "ollama", label: "Ollama", badge: "Local" },
  { id: "gemini", label: "Gemini", badge: "Cloud" },
  { id: "groq", label: "Groq", badge: "Fast" },
];

export function EngineDropdown({ value, onChange, disabled }: EngineDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const selectedEngine = llmEngines.find((e) => e.id === value) || llmEngines[0];

  // Close popup when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className="relative inline-block text-left" ref={containerRef}>
      {/* Trigger Button */}
      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-semibold transition-all duration-150 border select-none ${
          isOpen
            ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-900 dark:text-white border-navi-500/50 ring-2 ring-navi-500/20"
            : "bg-zinc-100/80 dark:bg-zinc-900/80 hover:bg-zinc-200/80 dark:hover:bg-zinc-800/80 text-zinc-700 dark:text-zinc-300 border-zinc-200/80 dark:border-white/10"
        } ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
      >
        <ToolCase className="w-3 h-3 text-navi shrink-0" />
        <span>{selectedEngine.label}</span>
        <ChevronDown
          className={`w-3 h-3 text-navidark-200 dark:text-navidark-100 transition-transform duration-200 ${
            isOpen ? "rotate-180" : ""
          }`}
        />
      </button>

      {/* Floating Glassmorphic Menu */}
      {isOpen && (
        <div className="absolute left-0 mt-1.5 w-36 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200/80 dark:border-white/10 rounded-xl shadow-xl py-1 z-50 animate-in fade-in zoom-in-95 duration-100 overflow-hidden">
          <div className="px-2 py-1 text-[9px] font-bold text-navidark-150 dark:text-navidark-100 uppercase tracking-wider">
            Engine
          </div>
          {llmEngines.map((engine) => {
            const isSelected = engine.id === value;
            return (
              <button
                key={engine.id}
                onClick={() => {
                  onChange(engine.id);
                  setIsOpen(false);
                }}
                className={`w-full flex items-center justify-between px-2.5 py-1.5 text-[11px] font-medium transition-colors text-left ${
                  isSelected
                    ? "bg-navi-800/10 text-navi-600 dark:text-navi-400 font-semibold"
                    : "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-white/5"
                }`}
              >
                <div className="flex items-center gap-1.5">
                  {isSelected ? (
                    <Check className="w-3 h-3 text-navi-500 shrink-0" />
                  ) : (
                    <span className="w-3" />
                  )}
                  <span>{engine.label}</span>
                </div>
                <span className="text-[8px] px-1 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-500 font-mono">
                  {engine.badge}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}