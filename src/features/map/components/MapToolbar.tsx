import { useEffect, useRef } from "react";
import { MousePointer2, MapPin, Pencil } from "../../../components/ui/icons";
import { t } from "@lingui/core/macro";
import { Tip } from "../../../components/ui/Tip";

export type AddType = "normal" | "start" | "end" | "stopby";

interface MapToolbarProps {
  isAddMode: boolean;
  setIsAddMode: (v: boolean) => void;
  isDrawMode: boolean;
  setIsDrawMode: (v: boolean) => void;
  isEraserMode: boolean;
  setIsEraserMode: (v: boolean) => void;
  canErase: boolean;
  addType: AddType;
  setAddType: (v: AddType) => void;
}

export function MapToolbar({
  isAddMode,
  setIsAddMode,
  isDrawMode,
  setIsDrawMode,
  isEraserMode,
  setIsEraserMode,
  canErase,
  addType,
  setAddType,
}: MapToolbarProps) {
  const activeMode = isDrawMode ? "line" : isAddMode ? "point" : "select";

  const selectTool = (mode: "select" | "point" | "line") => {
    setIsAddMode(mode === "point");
    setIsDrawMode(mode === "line");
    if (mode !== "line") setIsEraserMode(false);
  };

  const latest = useRef({ activeMode, canErase, isEraserMode, selectTool, setIsEraserMode });
  latest.current = { activeMode, canErase, isEraserMode, selectTool, setIsEraserMode };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const { activeMode, canErase, isEraserMode, selectTool, setIsEraserMode } = latest.current;
      const activeEl = document.activeElement as HTMLElement | null;
      const activeTag = activeEl?.tagName.toLowerCase();
      if (activeTag === "input" || activeTag === "textarea" || activeEl?.isContentEditable) {
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      switch (e.key.toLowerCase()) {
        case "v":
          e.preventDefault();
          selectTool("select");
          break;
        case "p":
          e.preventDefault();
          selectTool("point");
          break;
        case "l":
          e.preventDefault();
          selectTool("line");
          break;
        case "e":
          if (activeMode === "line" && canErase) {
            e.preventDefault();
            setIsEraserMode(!isEraserMode);
          }
          break;
        case "escape":
          selectTool("select");
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const tools = [
    { id: "select" as const, icon: MousePointer2, label: t`Select`, key: "V" },
    { id: "point" as const, icon: MapPin, label: t`Add stop`, key: "P" },
    { id: "line" as const, icon: Pencil, label: t`Draw path`, key: "L" },
  ];

  const addTypes: { id: AddType; label: string }[] = [
    { id: "normal", label: t`Stop` },
    { id: "stopby", label: t`Stop-by` },
    { id: "start", label: t`Start` },
    { id: "end", label: t`End` },
  ];

  return (
    <div className="flex flex-col items-center gap-2">
      <div
        role="toolbar"
        aria-label={t`Map tools`}
        className="flex items-center gap-0.5 p-1 rounded-xl bg-white/95 dark:bg-zinc-900/95 backdrop-blur-md border border-zinc-200 dark:border-white/10 shadow-sm"
      >
        {tools.map(({ id, icon: Icon, label, key }) => {
          const active = activeMode === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => selectTool(id)}
              aria-pressed={active}
              aria-label={`${label} (${key})`}
              className={`group/tool relative flex items-center justify-center w-8 h-7 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-navi/40 ${
                active
                  ? "bg-navi text-white shadow-sm"
                  : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-white/5"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <Tip label={label} kbd={key} />
            </button>
          );
        })}
      </div>

      {isAddMode && (
        <div className="flex items-center gap-2 h-9 pl-3.5 pr-1 rounded-xl bg-white/95 dark:bg-zinc-900/95 backdrop-blur-md border border-zinc-200 dark:border-white/10 shadow-sm animate-in fade-in slide-in-from-top-1 duration-150">
          <span className="text-[12px] text-zinc-500 whitespace-nowrap">
            {t`Click the map to add:`}
          </span>
          <div className="flex items-center gap-0.5">
            {addTypes.map((type) => (
              <button
                key={type.id}
                type="button"
                onClick={() => setAddType(type.id)}
                aria-pressed={addType === type.id}
                className={`h-7 px-2.5 rounded-lg text-[12px] font-medium transition-colors ${
                  addType === type.id
                    ? "bg-navi/10 text-navi"
                    : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-white/5"
                }`}
              >
                {type.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
