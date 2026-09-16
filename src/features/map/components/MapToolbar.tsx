import {
  MousePointer2,
  MapPin,
  Pencil,
  SplinePointer,
  Eraser,
  ZoomIn,
  Info,
  Ruler,
  Trash2,
  Undo,
} from "../../../components/ui/icons";

interface MapToolbarProps {
  isAddMode: boolean;
  setIsAddMode: (v: boolean) => void;
  isDrawMode: boolean;
  setIsDrawMode: (v: boolean) => void;
  isEraserMode: boolean;
  setIsEraserMode: (v: boolean) => void;
  activeWp: any;
  onToggleSpline: () => void;
  onZoomTo: () => void;
  onClearRoute: () => void;
}

export function MapToolbar({
  isAddMode,
  setIsAddMode,
  isDrawMode,
  setIsDrawMode,
  isEraserMode,
  setIsEraserMode,
  activeWp,
  onToggleSpline,
  onZoomTo,
  onClearRoute,
}: MapToolbarProps) {
  // A pseudo-mode to determine which primary tool is active
  const activeMode = isDrawMode ? "line" : isAddMode ? "point" : "select";

  return (
    <div className="flex items-center gap-2 shadow-sm">
      {/* PRIMARY TOOLS */}
      <div className="flex items-center bg-white dark:bg-zinc-900 rounded-lg shadow-md border border-zinc-200 dark:border-zinc-800 p-1">
        <button
          onClick={() => {
            setIsDrawMode(false);
            setIsAddMode(false);
          }}
          title="Select (V)"
          className={`p-2 rounded-md transition-colors ${activeMode === "select" ? "bg-navi/10 text-navi" : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}
        >
          <MousePointer2 className="w-4 h-4" />
        </button>
        <button
          onClick={() => {
            setIsAddMode(true);
            setIsDrawMode(false);
          }}
          title="Add Waypoint (P)"
          className={`p-2 rounded-md transition-colors ${activeMode === "point" ? "bg-navi/10 text-navi" : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}
        >
          <MapPin className="w-4 h-4" />
        </button>
        <button
          onClick={() => {
            setIsDrawMode(true);
            setIsAddMode(false);
          }}
          title="Draw Custom Route (L)"
          className={`p-2 rounded-md transition-colors ${activeMode === "line" ? "bg-navi/10 text-navi" : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}
        >
          <Pencil className="w-4 h-4" />
        </button>
      </div>

      {/* CONTEXTUAL TOOLS */}
      <div
        className={`flex items-center bg-white dark:bg-zinc-900 rounded-lg shadow-md border border-zinc-200 dark:border-zinc-800 p-1 transition-all duration-300 overflow-hidden ${activeMode === "line" && activeWp ? "max-w-[500px] opacity-100 translate-x-0" : "max-w-0 opacity-0 -translate-x-4 border-none shadow-none !p-0"}`}
      >
        <span className="text-[10px] font-bold tracking-wider text-zinc-400 uppercase px-2 whitespace-nowrap">
          LINE TOOLS
        </span>
        <div className="w-px h-5 bg-zinc-200 dark:bg-zinc-800 mx-1" />

        <button
          onClick={() => setIsEraserMode(!isEraserMode)}
          title="Eraser"
          className={`p-2 rounded-md transition-colors ${isEraserMode ? "text-red-500 bg-red-50 dark:bg-red-500/10" : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}
        >
          <Eraser className="w-4 h-4" />
        </button>

        <button
          onClick={onToggleSpline}
          title="Toggle Smooth Spline"
          className={`p-2 rounded-md transition-colors ${activeWp?.drawStyle === "spline" ? "text-amber-500 bg-amber-50 dark:bg-amber-500/10" : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}
        >
          <SplinePointer className="w-4 h-4" />
        </button>

        <button
          onClick={onZoomTo}
          title="Zoom to Fit Route"
          className="p-2 rounded-md transition-colors text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
        >
          <ZoomIn className="w-4 h-4" />
        </button>

        <button
          onClick={onClearRoute}
          title="Clear Route"
          className="p-2 rounded-md transition-colors text-zinc-500 hover:text-red-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
