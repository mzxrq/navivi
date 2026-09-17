import { Scissors, Box } from "lucide-react";
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
  onSimplifyRoute: () => void;
  onBufferRoute: () => void;
  onShowInfo: () => void;
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
  onSimplifyRoute,
  onBufferRoute,
  onShowInfo,
}: MapToolbarProps) {
  const activeMode = isDrawMode ? "line" : isAddMode ? "point" : "select";
  const isContextOpen = activeMode === "line" && !!activeWp;

  return (
    <div className="flex max-[1159px]:flex-col min-[1160px]:flex-row gap-2 transition-all">
      {/* PRIMARY TOOLS */}
      <div className="flex max-[1159px]:flex-col min-[1160px]:flex-row items-center bg-white dark:bg-zinc-900 rounded-full max-[1159px]:rounded-3xl shadow-md p-1 transition-all">
        <button
          onClick={() => {
            setIsDrawMode(false);
            setIsAddMode(false);
          }}
          title="Select (V)"
          className={`p-2 rounded-4xl transition-colors ${activeMode === "select" ? "bg-navi/10 text-navi" : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}
        >
          <MousePointer2 className="w-4 h-4" />
        </button>
        <button
          onClick={() => {
            setIsAddMode(true);
            setIsDrawMode(false);
          }}
          title="Add Waypoint (P)"
          className={`p-2 rounded-4xl transition-colors ${activeMode === "point" ? "bg-navi/10 text-navi" : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}
        >
          <MapPin className="w-4 h-4" />
        </button>
        <button
          onClick={() => {
            setIsDrawMode(true);
            setIsAddMode(false);
          }}
          title="Draw Custom Route (L)"
          className={`p-2 rounded-4xl transition-colors ${activeMode === "line" ? "bg-navi/10 text-navi" : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}
        >
          <Pencil className="w-4 h-4" />
        </button>
      </div>

      {/* CONTEXTUAL TOOLS */}
      <div
        className={`flex max-[1159px]:flex-col min-[1160px]:flex-row items-center bg-white dark:bg-zinc-900 rounded-full max-[1159px]:rounded-3xl shadow-md dark:border-zinc-800 p-1 transition-all duration-300 overflow-hidden ${isContextOpen ? "max-[1159px]:max-h-[500px] min-[1160px]:max-w-[500px] opacity-100 translate-x-0 translate-y-0" : "max-[1159px]:max-h-0 min-[1160px]:max-w-0 opacity-0 max-[1159px]:-translate-y-4 min-[1160px]:-translate-x-4 border-none shadow-none p-0!"}`}
      >
        <button
          onClick={() => setIsEraserMode(!isEraserMode)}
          title="Eraser"
          tabIndex={isContextOpen ? 0 : -1}
          className={`p-2 rounded-4xl transition-colors ${isEraserMode ? "text-red-500 bg-red-50 dark:bg-red-500/10" : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}
        >
          <Eraser className="w-4 h-4" />
        </button>

        <button
          onClick={onToggleSpline}
          title="Toggle Smooth Spline"
          tabIndex={isContextOpen ? 0 : -1}
          className={`p-2 rounded-4xl transition-colors ${activeWp?.drawStyle === "spline" ? "text-amber-500 bg-amber-50 dark:bg-amber-500/10" : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}
        >
          <SplinePointer className="w-4 h-4" />
        </button>

        <button
          onClick={onZoomTo}
          title="Zoom to Fit Route"
          tabIndex={isContextOpen ? 0 : -1}
          className="p-2 rounded-4xl transition-colors text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
        >
          <ZoomIn className="w-4 h-4" />
        </button>

        <div className="w-px h-5 bg-zinc-200 dark:bg-zinc-800 mx-1" />

        <button
          onClick={onSimplifyRoute}
          title="Simplify Route (Reduce Points)"
          tabIndex={isContextOpen ? 0 : -1}
          className="p-2 rounded-4xl transition-colors text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
        >
          <Scissors className="w-4 h-4" />
        </button>
        <button
          onClick={onBufferRoute}
          title="Buffer Route"
          tabIndex={isContextOpen ? 0 : -1}
          className="p-2 rounded-4xl transition-colors text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
        >
          <Box className="w-4 h-4" />
        </button>
        <button
          onClick={onShowInfo}
          title="Geometry Information"
          tabIndex={isContextOpen ? 0 : -1}
          className="p-2 rounded-4xl transition-colors text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
        >
          <Info className="w-4 h-4" />
        </button>

        <div className="w-px h-5 bg-zinc-200 dark:bg-zinc-800 mx-1" />

        <button
          onClick={onClearRoute}
          title="Clear Route"
          tabIndex={isContextOpen ? 0 : -1}
          className="p-2 rounded-4xl transition-colors text-zinc-500 hover:text-red-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
