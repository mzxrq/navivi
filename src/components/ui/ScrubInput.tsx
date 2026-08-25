import { useState, useEffect, useRef } from "react";
import { Info } from "lucide-react";

interface ScrubInputProps {
  label: string;
  value: number | string;
  onChange: (v: any) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
  tooltip?: string;
  options?: string[]; // Passing this converts it into a Categorical Dropdown Scrub!
}

export function ScrubInput({ 
  label, value, onChange, min = 0, max = 100, step = 1, suffix = "", tooltip = "", options 
}: ScrubInputProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(value.toString());
  
  const startX = useRef(0);
  const startVal = useRef<number | string>(value);
  const hasDragged = useRef(false);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging) return;
      hasDragged.current = true; 

      if (options) {
        // --- CATEGORICAL SCRUB MODE ---
        const sensitivity = 30; // Pixels to drag before changing the option
        const delta = e.clientX - startX.current;
        const offset = Math.floor(delta / sensitivity);
        const initialIndex = Math.max(0, options.indexOf(String(startVal.current)));
        
        let newIndex = initialIndex + offset;
        newIndex = Math.max(0, Math.min(options.length - 1, newIndex)); // Clamp to array bounds
        
        if (options[newIndex] !== value) {
          onChange(options[newIndex]);
        }
      } else {
        // --- NUMBER SCRUB MODE ---
        const delta = (e.clientX - startX.current) * (step * 0.5);
        let newVal = (startVal.current as number) + delta;
        newVal = Math.max(min, Math.min(max, newVal));
        
        const decimals = step.toString().includes('.') ? step.toString().split('.')[1].length : 0;
        onChange(Number(newVal.toFixed(decimals)));
      }
    };
    
    const handleMouseUp = () => {
      if (isDragging && !hasDragged.current) {
        setIsEditing(true);
        setEditValue(value.toString());
      }
      setIsDragging(false);
    };

    if (isDragging) {
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
    }
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, max, min, onChange, step, value, options]);

  const handleEditSubmit = () => {
    setIsEditing(false);
    if (!options) {
      let parsed = parseFloat(editValue);
      if (!isNaN(parsed)) {
        parsed = Math.max(min, Math.min(max, parsed));
        onChange(parsed);
      }
    }
  };

  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-1.5 group relative">
        <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">{label}</label>
        {tooltip && (
          <div className="relative">
            <Info className="w-3 h-3 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 cursor-help" />
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-48 p-2 bg-zinc-800 dark:bg-zinc-100 text-white dark:text-zinc-900 text-[10px] font-medium rounded-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all shadow-xl z-50 pointer-events-none">
              {tooltip}
              <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 border-4 border-transparent border-t-zinc-800 dark:border-t-zinc-100" />
            </div>
          </div>
        )}
      </div>
      
      <div 
        className="w-20 bg-zinc-100 dark:bg-zinc-900/80 border border-zinc-200 dark:border-white/5 hover:border-zinc-500/50 dark:hover:border-zinc-500/50 rounded-md px-2 py-1 flex justify-center items-center transition-colors relative"
        style={{ cursor: isEditing ? (options ? 'pointer' : 'text') : 'ew-resize' }}
        onMouseDown={(e) => {
          if (isEditing) return;
          setIsDragging(true);
          hasDragged.current = false;
          startX.current = e.clientX;
          startVal.current = value;
        }}
      >
        {isEditing ? (
          options ? (
            <select
              value={editValue}
              onChange={(e) => {
                setEditValue(e.target.value);
                onChange(e.target.value);
                setIsEditing(false);
              }}
              onBlur={() => setIsEditing(false)}
              className="w-full bg-transparent outline-none text-center text-xs font-mono font-bold text-zinc-600 dark:text-zinc-400 appearance-none cursor-pointer uppercase tracking-wider"
              autoFocus
            >
              {options.map(opt => (
                <option key={opt} value={opt} className="bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100">
                  {opt}
                </option>
              ))}
            </select>
          ) : (
            <input
              type="number"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onBlur={handleEditSubmit}
              onKeyDown={(e) => e.key === 'Enter' && handleEditSubmit()}
              className="w-full bg-transparent outline-none text-center text-xs font-mono font-bold text-zinc-600 dark:text-zinc-400 no-spinners"
              autoFocus
            />
          )
        ) : (
          <span className="text-xs font-mono font-bold text-zinc-600 dark:text-zinc-400 pointer-events-none select-none uppercase tracking-wider">
            {value}{suffix}
          </span>
        )}
      </div>
    </div>
  );
}