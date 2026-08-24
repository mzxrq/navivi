import { useState, useEffect, useRef } from "react";
import { Info } from "lucide-react";

interface ScrubInputProps {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  suffix?: string;
  tooltip?: string;
}

export function ScrubInput({ 
  label, value, onChange, min, max, step = 1, suffix = "", tooltip = "" 
}: ScrubInputProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(value.toString());
  
  const startX = useRef(0);
  const startVal = useRef(value);
  const hasDragged = useRef(false);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging) return;
      hasDragged.current = true; // Mark that we actually moved the mouse
      const delta = (e.clientX - startX.current) * (step * 0.5);
      let newVal = startVal.current + delta;
      newVal = Math.max(min, Math.min(max, newVal));
      
      const decimals = step.toString().includes('.') ? step.toString().split('.')[1].length : 0;
      onChange(Number(newVal.toFixed(decimals)));
    };
    
    const handleMouseUp = () => {
      if (isDragging && !hasDragged.current) {
        // If they clicked but didn't drag, switch to typing mode
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
  }, [isDragging, max, min, onChange, step, value]);

  const handleEditSubmit = () => {
    setIsEditing(false);
    let parsed = parseFloat(editValue);
    if (!isNaN(parsed)) {
      parsed = Math.max(min, Math.min(max, parsed));
      onChange(parsed);
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
        className="w-20 bg-zinc-100 dark:bg-zinc-900/80 border border-zinc-200 dark:border-white/5 hover:border-emerald-500/50 dark:hover:border-emerald-500/50 rounded-md px-2 py-1 flex justify-center items-center transition-colors"
        style={{ cursor: isEditing ? 'text' : 'ew-resize' }}
        onMouseDown={(e) => {
          if (isEditing) return;
          setIsDragging(true);
          hasDragged.current = false;
          startX.current = e.clientX;
          startVal.current = value;
        }}
      >
        {isEditing ? (
          <input
            type="number"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={handleEditSubmit}
            onKeyDown={(e) => e.key === 'Enter' && handleEditSubmit()}
            className="w-full bg-transparent outline-none text-center text-xs font-mono font-bold text-emerald-600 dark:text-emerald-400 no-spinners"
            autoFocus
          />
        ) : (
          <span className="text-xs font-mono font-bold text-emerald-600 dark:text-emerald-400 pointer-events-none select-none">
            {value}{suffix}
          </span>
        )}
      </div>
    </div>
  );
}