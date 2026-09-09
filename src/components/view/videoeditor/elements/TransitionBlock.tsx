import { TimelineTransition } from "../../../../types";
import { useWorkspace } from "../../../../hooks/useWorkspace";
import { Trash2 } from "../../../ui/icons";

interface TransitionBlockProps {
  transition: TimelineTransition;
  pixelsPerSecond: number;
}

export function TransitionBlock({ transition, pixelsPerSecond }: TransitionBlockProps) {
  const { timeline, setTimeline } = useWorkspace();

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    setTimeline({
      ...timeline,
      transitions: timeline.transitions.filter(t => t.id !== transition.id)
    });
  };

  const xPos = transition.startTime * pixelsPerSecond;
  const width = transition.duration * pixelsPerSecond;

  const label = transition.type.replace("glsl-", "").toUpperCase();

  return (
    <div
      className="absolute top-1 bottom-1 bg-yellow-500/80 border border-yellow-300 rounded shadow-md z-40 flex items-center justify-center group overflow-hidden"
      style={{ left: xPos, width: width }}
    >
      <span className="text-[8px] font-black text-yellow-950 tracking-widest truncate px-1">
        {label}
      </span>
      
      <button 
        onClick={handleDelete}
        className="absolute right-0 top-0 bottom-0 bg-red-500 w-4 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
      >
        <Trash2 className="w-2.5 h-2.5 text-white" />
      </button>
    </div>
  );
}