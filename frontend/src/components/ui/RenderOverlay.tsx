import { useUI } from "../../hooks/useUI";
import { Loader2 } from "lucide-react";

export function RenderOverlay() {
  const { isRendering, renderLogs } = useUI();
  if (!isRendering) return null;

  return (
    <div className="absolute inset-0 z-[100] bg-zinc-950/80 backdrop-blur-md flex flex-col items-center justify-center text-white transition-all animate-in fade-in">
      <Loader2 className="w-16 h-16 animate-spin text-emerald-500 mb-6" />
      <h2 className="text-3xl font-bold tracking-tight mb-2">
        Rendering Video
      </h2>
      <p className="text-zinc-400 font-mono text-sm max-w-lg text-center px-4">
        {renderLogs || "Rendering.."}
      </p>
    </div>
  );
}
