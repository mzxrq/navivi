import { useEffect, useRef, useState } from "react";
import { DragDropContext, Droppable, Draggable, DropResult } from "@hello-pangea/dnd";
import {
  Check,
  ChevronDown,
  Eraser,
  GripVertical,
  List,
  Maximize,
  MoreVertical,
  Pencil,
  SplinePointer,
  Trash2,
  X,
} from "../../../components/ui/icons";
import { Waypoint } from "../../../types";
import { parseCoordinates } from "../../../utils/coordinates";
import { curvesOf, isAllSmooth, moveAnchor, pathOf, removeAnchors, reorderAnchors, setAllCurves, toggleAnchorCurve } from "../../../utils/drawnPath";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

interface DrawBarProps {
  waypoints: Waypoint[];
  activeWp: Waypoint | null;
  nextWp: Waypoint | null;
  isEraserMode: boolean;
  setIsEraserMode: (v: boolean) => void;
  onPickLeg: (wpId: string) => void;
  onFit: () => void;
  onDone: () => void;
  updateWaypoint: (id: string, data: Partial<Waypoint>) => void;
  setIsDirty: (dirty: boolean) => void;
}

function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
      }
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [open, close]);
  return ref;
}

const menuClass =
  "absolute top-full mt-1 z-50 p-1 rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-lg animate-in fade-in zoom-in-95 duration-100";
const menuItemClass =
  "w-full flex items-center gap-2 h-7 px-2 rounded-md text-[12px] text-left text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors";
const iconButtonClass = (active = false) =>
  `flex items-center gap-1.5 h-7 px-2 rounded-lg text-[12px] font-medium transition-colors ${
    active
      ? "bg-navi text-white shadow-sm"
      : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-white/5"
  }`;

export function DrawBar({
  waypoints,
  activeWp,
  nextWp,
  isEraserMode,
  setIsEraserMode,
  onPickLeg,
  onFit,
  onDone,
  updateWaypoint,
  setIsDirty,
}: DrawBarProps) {
  const [isLegMenuOpen, setIsLegMenuOpen] = useState(false);
  const [isMoreOpen, setIsMoreOpen] = useState(false);
  const [showPoints, setShowPoints] = useState(false);
  const [selectedAnchorIdx, setSelectedAnchorIdx] = useState<number | null>(null);
  const [marked, setMarked] = useState<Set<number>>(new Set());
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [draftBad, setDraftBad] = useState(false);
  const lastMarked = useRef<number | null>(null);
  const legMenuRef = useDismiss(isLegMenuOpen, () => setIsLegMenuOpen(false));
  const moreRef = useDismiss(isMoreOpen, () => setIsMoreOpen(false));

  useEffect(() => {
    const sync = ((e: CustomEvent) => setSelectedAnchorIdx(e.detail.index)) as EventListener;
    window.addEventListener("select-anchor", sync);
    return () => window.removeEventListener("select-anchor", sync);
  }, []);

  const selectAnchor = (index: number | null) => {
    setSelectedAnchorIdx(index);
    window.dispatchEvent(new CustomEvent("select-anchor", { detail: { index } }));
  };

  const legs = waypoints.slice(0, -1).map((wp, i) => ({ wp, next: waypoints[i + 1] }));
  const hasLeg = !!activeWp && !!nextWp;
  const points = activeWp?.customRoute ?? [];
  const copySources = waypoints.filter(
    (w) => w.id !== activeWp?.id && (w.customRoute?.length ?? 0) > 0,
  );

  const curves = activeWp ? curvesOf(activeWp) : [];
  const patchPath = (patch: Partial<Waypoint>) => {
    if (!activeWp) return;
    updateWaypoint(activeWp.id, patch);
    setIsDirty(true);
  };

  const clearMarked = () => {
    setMarked(new Set());
    lastMarked.current = null;
  };

  // Ctrl/Cmd-click toggles one point, Shift-click marks the range from the last one clicked.
  const markPoint = (idx: number, e: React.MouseEvent) => {
    const next = new Set(marked);
    if (e.shiftKey && lastMarked.current !== null) {
      const [from, to] = [Math.min(lastMarked.current, idx), Math.max(lastMarked.current, idx)];
      for (let i = from; i <= to; i++) next.add(i);
    } else {
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      lastMarked.current = idx;
    }
    setMarked(next);
  };

  const removeMarked = () => {
    if (marked.size === 0) return;
    patchPath(removeAnchors(activeWp!, marked));
    selectAnchor(null);
    clearMarked();
  };
  const removeMarkedRef = useRef(removeMarked);
  removeMarkedRef.current = removeMarked;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      if (e.key === "Delete" || e.key === "Backspace") removeMarkedRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(clearMarked, [activeWp?.id, points.length]);
  useEffect(() => setEditingIdx(null), [activeWp?.id, points.length]);

  const startEdit = (idx: number) => {
    setDraft(`${points[idx][0].toFixed(5)}, ${points[idx][1].toFixed(5)}`);
    setDraftBad(false);
    setEditingIdx(idx);
  };

  // An unchanged or invalid entry leaves the point alone; Enter on an invalid one keeps the box open and red.
  const editingRef = useRef<number | null>(null);
  editingRef.current = editingIdx;
  const commitEdit = (idx: number, leaving = false) => {
    if (editingRef.current !== idx) return;
    const parsed = parseCoordinates(draft);
    if (!parsed) return leaving ? setEditingIdx(null) : setDraftBad(true);
    editingRef.current = null;
    setEditingIdx(null);
    if (parsed[0] === points[idx][0] && parsed[1] === points[idx][1]) return;
    patchPath(moveAnchor(activeWp!, idx, parsed));
  };

  const handlePointDragEnd = (result: DropResult) => {
    if (!result.destination || result.source.index === result.destination.index) return;
    patchPath(reorderAnchors(activeWp!, result.source.index, result.destination.index));
  };

  const legLabel = hasLeg ? `${activeWp!.name} → ${nextWp!.name}` : t`Choose a leg`;

  return (
    <div className="select-none w-[min(40rem,calc(100vw-2rem))] max-w-full rounded-xl bg-white/95 dark:bg-zinc-900/95 backdrop-blur-md border border-zinc-200 dark:border-white/10 shadow-sm animate-in fade-in slide-in-from-top-1 duration-150">
      <div className="flex flex-wrap items-center gap-1 p-1">
        <div ref={legMenuRef} className="relative min-w-0 flex-1 basis-44">
          <button
            type="button"
            onClick={() => setIsLegMenuOpen(!isLegMenuOpen)}
            aria-haspopup="menu"
            aria-expanded={isLegMenuOpen}
            title={legLabel}
            className={`w-full flex items-center gap-2 h-7 px-2 rounded-lg text-[12px] transition-colors hover:bg-zinc-100 dark:hover:bg-white/5 ${
              hasLeg ? "text-zinc-900 dark:text-zinc-100 font-medium" : "text-navi font-medium"
            }`}
          >
            <Pencil className="w-3.5 h-3.5 text-navi shrink-0" />
            <span className="truncate">{legLabel}</span>
            <ChevronDown className="w-3 h-3 opacity-60 shrink-0 ml-auto" />
          </button>
          {isLegMenuOpen && (
            <div role="menu" className={`${menuClass} left-0 w-72 max-h-72 overflow-y-auto custom-scrollbar`}>
              {legs.length === 0 ? (
                <p className="px-2 py-2 text-[12px] text-zinc-500">
                  <Trans>Add at least two stops to draw a path between them.</Trans>
                </p>
              ) : (
                legs.map(({ wp, next }) => (
                  <button
                    key={wp.id}
                    type="button"
                    role="menuitemradio"
                    aria-checked={wp.id === activeWp?.id}
                    onClick={() => {
                      onPickLeg(wp.id);
                      setIsLegMenuOpen(false);
                    }}
                    className={menuItemClass}
                  >
                    <span className="flex-1 min-w-0 truncate">
                      {wp.name} <span className="text-zinc-400">→</span> {next.name}
                    </span>
                    {wp.routeMode === "draw" && (
                      <span className="text-[10px] text-zinc-400 shrink-0">
                        <Trans>drawn</Trans>
                      </span>
                    )}
                    {wp.id === activeWp?.id && <Check className="w-3.5 h-3.5 text-navi shrink-0" />}
                  </button>
                ))
              )}
            </div>
          )}
        </div>

        {hasLeg && (
          <>
            <div className="flex items-center rounded-lg bg-zinc-100 dark:bg-white/5 p-0.5">
              <button
                type="button"
                onClick={() => setIsEraserMode(false)}
                aria-pressed={!isEraserMode}
                title={t`Add points`}
                className={`flex items-center gap-1 h-6 px-2 rounded-md text-[12px] font-medium transition-colors ${
                  !isEraserMode
                    ? "bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-sm"
                    : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                }`}
              >
                <Pencil className="w-3 h-3" />
                <span className="max-[1159px]:hidden">
                  <Trans>Add</Trans>
                </span>
              </button>
              <button
                type="button"
                onClick={() => setIsEraserMode(true)}
                aria-pressed={isEraserMode}
                title={t`Erase points (E)`}
                className={`flex items-center gap-1 h-6 px-2 rounded-md text-[12px] font-medium transition-colors ${
                  isEraserMode
                    ? "bg-white dark:bg-zinc-800 text-red-500 shadow-sm"
                    : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                }`}
              >
                <Eraser className="w-3 h-3" />
                <span className="max-[1159px]:hidden">
                  <Trans>Erase</Trans>
                </span>
              </button>
            </div>

            <button
              type="button"
              onClick={() => patchPath(setAllCurves(activeWp!, !isAllSmooth(curves)))}
              aria-pressed={isAllSmooth(curves)}
              title={t`Make every point smooth, or every point a corner`}
              className={iconButtonClass(isAllSmooth(curves))}
            >
              <SplinePointer className="w-3.5 h-3.5" />
              <span className="max-[1159px]:hidden">
                <Trans>Smooth all</Trans>
              </span>
            </button>

            <button
              type="button"
              onClick={() => setShowPoints(!showPoints)}
              aria-pressed={showPoints}
              title={t`Show the list of points`}
              className={iconButtonClass(showPoints)}
            >
              <List className="w-3.5 h-3.5" />
              <span className="tabular-nums">{points.length}</span>
            </button>

            <button
              type="button"
              onClick={onFit}
              disabled={points.length === 0}
              title={t`Zoom to path`}
              aria-label={t`Zoom to path`}
              className={`${iconButtonClass()} disabled:opacity-40`}
            >
              <Maximize className="w-3.5 h-3.5" />
            </button>

            <div ref={moreRef} className="relative">
              <button
                type="button"
                onClick={() => setIsMoreOpen(!isMoreOpen)}
                aria-haspopup="menu"
                aria-expanded={isMoreOpen}
                title={t`More`}
                aria-label={t`More`}
                className={iconButtonClass(isMoreOpen)}
              >
                <MoreVertical className="w-3.5 h-3.5" />
              </button>
              {isMoreOpen && (
                <div role="menu" className={`${menuClass} right-0 w-60`}>
                  <p className="px-2 pt-1 pb-1 text-[11px] font-medium text-zinc-500">
                    <Trans>Copy path from</Trans>
                  </p>
                  {copySources.length === 0 ? (
                    <p className="px-2 pb-1.5 text-[12px] text-zinc-400">
                      <Trans>No other drawn paths yet</Trans>
                    </p>
                  ) : (
                    <div className="max-h-40 overflow-y-auto custom-scrollbar">
                      {copySources.map((w) => (
                        <button
                          key={w.id}
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            updateWaypoint(activeWp!.id, {
                              ...pathOf(w),
                              routeMode: "draw",
                            });
                            setIsDirty(true);
                            setIsMoreOpen(false);
                          }}
                          className={menuItemClass}
                        >
                          <span className="flex-1 truncate">{w.name || t`Waypoint`}</span>
                          <span className="text-[10px] text-zinc-400 tabular-nums">
                            {w.customRoute!.length}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="my-1 h-px bg-zinc-100 dark:bg-white/5" />
                  <button
                    type="button"
                    role="menuitem"
                    disabled={points.length === 0}
                    onClick={() => {
                      patchPath({ customRoute: [], customRouteCurve: undefined, drawStyle: undefined });
                      selectAnchor(null);
                      setIsMoreOpen(false);
                    }}
                    className={`${menuItemClass} text-red-500! disabled:opacity-40`}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <Trans>Clear path</Trans>
                  </button>
                </div>
              )}
            </div>
          </>
        )}

        <button
          type="button"
          onClick={onDone}
          className="h-7 px-3 rounded-lg text-[12px] font-semibold bg-navi text-white hover:brightness-110 transition"
        >
          <Trans>Done</Trans>
        </button>
      </div>

      <p className="px-3 pb-2 -mt-0.5 text-[11px] text-zinc-500">
        {!hasLeg ? (
          <Trans>Pick the leg you want to draw, or select a stop in the list.</Trans>
        ) : isEraserMode ? (
          <Trans>Click a point to remove it.</Trans>
        ) : selectedAnchorIdx !== null ? (
          <Trans>New points go after point {selectedAnchorIdx + 1}. Click it again to add at the end.</Trans>
        ) : (
          <Trans>Click the map to add points. Drag a point to move it; click one to insert after it; double-click one to smooth it.</Trans>
        )}
      </p>

      {hasLeg && showPoints && (
        <div className="border-t border-zinc-100 dark:border-white/5 max-h-60 overflow-y-auto custom-scrollbar p-1">
          {points.length === 0 ? (
            <p className="px-2 py-3 text-[12px] text-zinc-500 text-center">
              <Trans>No points yet</Trans>
            </p>
          ) : (
            <>
            {marked.size > 0 && (
              <div className="flex items-center gap-2 h-7 px-2 mb-1 rounded-md bg-navi/10 text-[11px] text-navi">
                <span className="flex-1 font-medium">{t`${marked.size} selected`}</span>
                <button type="button" onClick={removeMarked} className="flex items-center gap-1 px-1.5 h-5 rounded hover:bg-red-500/10 hover:text-red-500">
                  <Trash2 className="w-3 h-3" />
                  <Trans>Delete</Trans>
                </button>
                <button type="button" onClick={clearMarked} className="px-1.5 h-5 rounded hover:bg-navi/10">
                  <Trans>Clear</Trans>
                </button>
              </div>
            )}
            <DragDropContext onDragEnd={handlePointDragEnd}>
              <Droppable droppableId="draw-points">
                {(provided) => (
                  <div ref={provided.innerRef} {...provided.droppableProps}>
                    {points.map((point, idx) => (
                      <Draggable
                        key={`point-${idx}-${point[0]}-${point[1]}`}
                        draggableId={`point-${idx}`}
                        index={idx}
                      >
                        {(provided, snapshot) => (
                          <div
                            ref={provided.innerRef}
                            {...provided.draggableProps}
                            onClick={(e) => {
                              if (e.ctrlKey || e.metaKey || e.shiftKey) return markPoint(idx, e);
                              clearMarked();
                              selectAnchor(selectedAnchorIdx === idx ? null : idx);
                            }}
                            className={`group flex items-center gap-2 h-7 px-1 rounded-md cursor-pointer transition-colors ${
                              snapshot.isDragging
                                ? "bg-white dark:bg-zinc-800 shadow-md"
                                : marked.has(idx)
                                  ? "bg-navi/20 ring-1 ring-navi/40"
                                  : selectedAnchorIdx === idx
                                  ? "bg-navi/10"
                                  : "hover:bg-zinc-100 dark:hover:bg-white/5"
                            }`}
                          >
                            <span
                              {...provided.dragHandleProps}
                              className="text-zinc-300 dark:text-zinc-600 hover:text-zinc-500 cursor-grab"
                            >
                              <GripVertical className="w-3.5 h-3.5" />
                            </span>
                            <span className="w-5 text-[11px] font-semibold text-amber-600 dark:text-amber-400 tabular-nums">
                              {idx + 1}
                            </span>
                            {editingIdx === idx ? (
                              <input
                                autoFocus
                                value={draft}
                                onChange={(e) => {
                                  setDraft(e.target.value);
                                  setDraftBad(false);
                                }}
                                onClick={(e) => e.stopPropagation()}
                                onFocus={(e) => e.currentTarget.select()}
                                onBlur={() => commitEdit(idx, true)}
                                onKeyDown={(e) => {
                                  e.stopPropagation();
                                  if (e.key === "Enter") commitEdit(idx);
                                  else if (e.key === "Escape") setEditingIdx(null);
                                }}
                                placeholder="34.2908, 135.1508"
                                aria-label={t`Coordinates of point ${idx + 1}`}
                                aria-invalid={draftBad}
                                className={`flex-1 min-w-0 h-5 px-1 rounded border bg-white dark:bg-zinc-800 text-[11px] tabular-nums outline-none ${
                                  draftBad ? "border-red-500" : "border-navi"
                                }`}
                              />
                            ) : (
                              <span
                                onDoubleClick={() => startEdit(idx)}
                                title={t`Double-click to type coordinates`}
                                className="flex-1 text-[11px] tabular-nums tracking-tight text-zinc-600 dark:text-zinc-400 truncate"
                              >
                                {point[0].toFixed(5)}, {point[1].toFixed(5)}
                              </span>
                            )}
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                patchPath(toggleAnchorCurve(activeWp!, idx));
                              }}
                              title={curves[idx] ? t`Smooth point: click for a corner` : t`Corner point: click to smooth`}
                              aria-label={curves[idx] ? t`Make this a corner` : t`Make this smooth`}
                              aria-pressed={!!curves[idx]}
                              className={`p-1 rounded transition ${curves[idx] ? "text-navi" : "text-zinc-400 opacity-0 group-hover:opacity-100 hover:text-navi"}`}
                            >
                              <SplinePointer className="w-3 h-3" />
                            </button>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                if (marked.has(idx) && marked.size > 1) return removeMarked();
                                patchPath(removeAnchors(activeWp!, new Set([idx])));
                              }}
                              title={t`Delete Anchor`}
                              aria-label={t`Delete Anchor`}
                              className="p-1 rounded text-zinc-400 opacity-0 group-hover:opacity-100 hover:text-red-500 hover:bg-red-500/10 transition"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </div>
                        )}
                      </Draggable>
                    ))}
                    {provided.placeholder}
                  </div>
                )}
              </Droppable>
            </DragDropContext>
            </>
          )}
        </div>
      )}
    </div>
  );
}
