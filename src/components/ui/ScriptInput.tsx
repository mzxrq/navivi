import { useEffect, useState } from "react";
import { Mic, Sparkles, Settings2, Loader } from "lucide-react";

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
  onGenerate: (prompt: string, engine: string) => void;
  isGenerating: boolean;
}

export function ScriptInput({ value, onChange, onGenerate, isGenerating }: ScriptInputProps) {
  const [engine, setEngine] = useState("ollama"); 
  const [localPrompt, setLocalPrompt] = useState(value);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);

  useEffect(() => {
    if (!isGenerating) {
      setCurrentStepIndex(0);
      return;
    }
    const interval = setInterval(() => {
      setCurrentStepIndex((prev) => (prev < thinkingSteps.length - 1 ? prev + 1 : prev));
    }, 1800);
    return () => clearInterval(interval);
  }, [isGenerating]);

  const displayValue = isGenerating ? localPrompt : value;

  const handleGenerateClick = () => {
    if (!displayValue.trim()) return;
    onGenerate(displayValue, engine);
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-1.5">
          <Mic className="w-3.5 h-3.5 text-zinc-400" /> AI Script
        </label>
        
        <div className="flex items-center gap-2">
          <div className="relative flex items-center">
            <Settings2 className="w-3 h-3 text-zinc-400 absolute left-1.5 pointer-events-none" />
            <select 
              value={engine} 
              onChange={(e) => setEngine(e.target.value)}
              disabled={isGenerating}
              className="pl-5 pr-1 py-1 text-[10px] bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 rounded-md outline-none cursor-pointer disabled:opacity-50"
            >
              <option value="ollama">Ollama</option>
              <option value="gemini">Gemini</option>
              <option value="groq">Groq</option>
            </select>
          </div>

          <button 
            onClick={handleGenerateClick} 
            disabled={isGenerating || !displayValue.trim()} 
            className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed bg-green-50 dark:bg-green-500/10 text-green-600 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-500/20 border border-green-200 dark:border-green-500/20 shadow-sm"
          >
            <Sparkles className={`w-3 h-3 ${isGenerating ? 'animate-pulse' : ''}`} /> 
            {isGenerating ? 'Thinking...' : 'Magic Write'}
          </button>
        </div>
      </div>
      
      <div className="relative w-full h-28 rounded-xl overflow-hidden shadow-sm border border-zinc-200 dark:border-white/10 group focus-within:border-green-500 dark:focus-within:border-green-500/50 transition-colors">
        <textarea
          value={displayValue}
          onChange={(e) => {
             setLocalPrompt(e.target.value);
             onChange(e.target.value);
          }}
          disabled={isGenerating}
          placeholder="Type a prompt (e.g., 'Tell me about the history') and click Magic Write..."
          className="w-full h-full resize-none p-3 text-sm focus:outline-none custom-scrollbar bg-zinc-50 dark:bg-zinc-900/50 text-zinc-900 dark:text-zinc-100"
        />

        {isGenerating && (
          <div className="absolute inset-0 bg-white/80 dark:bg-zinc-950/80 backdrop-blur-sm flex flex-col items-center justify-center z-10 px-4">
            <div className="flex flex-col items-center gap-2.5 text-center">
              <div className="relative flex items-center justify-center">
				        <Loader className="w-6 h-6 animate-pulse text-green-300 dark:text-green-400" />
                <div className="absolute w-8 h-8 rounded-full bg-emerald-600/20 animate-pulse" />
              </div>

              <div className="space-y-0.5">
                <div className="text-xs font-bold text-green-600 dark:text-green-400 tracking-wide uppercase">
                  Thinking
                </div>
                <div className="text-[11px] font-medium text-zinc-600 dark:text-zinc-300 animate-fade-in transition-all">
                  {thinkingSteps[currentStepIndex]}
                </div>
              </div>

              {/* Progress bar matching step index */}
              <div className="w-32 h-1.5 bg-green-100 dark:bg-green-950 rounded-full overflow-hidden p-0.5">
                <div 
                  className="h-full bg-green-500 rounded-full transition-all duration-500 ease-out"
                  style={{ width: `${((currentStepIndex + 1) / thinkingSteps.length) * 100}%` }}
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}