import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useEffect, useRef, useState } from "react";
import {
  Check,
  ChevronDown,
  Edit2,
  GripVertical,
  ImageIcon,
  Mic,
  Pencil,
  Route,
  X,
} from "../../../components/ui/icons";
import { useUI } from "../../../hooks/useUI";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { Waypoint } from "../../../types/index";
import { openContextMenu } from "../../../components/ui/menuItems";
import {
  legColorable,
  useLegActions,
  useModeOptions,
  useStopMenus,
  VIA_MODES,
} from "../hooks/useStopMenus";
import { LegColorButton } from "./LegColorButton";
import { stopLabel } from "../../../utils/stopLabel";

interface WaypointItemProps {
  wp: Waypoint;
  index: number;
  isListEditMode: boolean;
  isFirst: boolean;
  isLast: boolean;
  onEdit: () => void;
  onDelete: () => void;
}

export function WaypointItem({
  wp,
  index,
  isListEditMode,
  isFirst,
  isLast,
  onEdit,
  onDelete,
}: WaypointItemProps) {
  const { activeWaypointId, setActiveWaypointId, updateWaypoint, waypoints } =
    useWorkspace();
  const { isRendering } = useUI();
  const itemRef = useRef<HTMLDivElement>(null);
  const modeMenuRef = useRef<HTMLDivElement>(null);
  const [isModeMenuOpen, setIsModeMenuOpen] = useState(false);
  const [isViaActive, setIsViaActive] = useState(false);
  const modeOptions = useModeOptions();
  const { startDrawing: startDrawingLeg, setLegMode } = useLegActions();
  const { stopMenu, legMenu } = useStopMenus();

  useEffect(() => {
    const handleEnter = (e: any) => setIsViaActive(e.detail.wpId === wp.id);
    const handleExit = () => setIsViaActive(false);
    window.addEventListener("enter-via-mode", handleEnter);
    window.addEventListener("exit-via-mode", handleExit);
    return () => {
      window.removeEventListener("enter-via-mode", handleEnter);
      window.removeEventListener("exit-via-mode", handleExit);
    };
  }, [wp.id]);

  const isActive = activeWaypointId === wp.id;

  useEffect(() => {
    if (isActive && itemRef.current) {
      itemRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [isActive]);

  useEffect(() => {
    if (!isModeMenuOpen) return;
    const close = (e: MouseEvent) => {
      if (!modeMenuRef.current?.contains(e.target as Node))
        setIsModeMenuOpen(false);
    };
    const closeOnEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setIsModeMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    window.addEventListener("keydown", closeOnEsc, true);
    return () => {
      document.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", closeOnEsc, true);
    };
  }, [isModeMenuOpen]);

  const handleSelect = () => {
    setActiveWaypointId(wp.id);
    onEdit();
  };

  const startDrawing = () => startDrawingLeg(wp.id);

  const selectMode = (mode: Waypoint["routeMode"]) => {
    setIsModeMenuOpen(false);
    if (mode) setLegMode(wp, mode);
  };

  const isStart = index === 0;
  const isEnd = index === waypoints.length - 1 && waypoints.length > 1;
  const displayLabel = stopLabel(waypoints, index);

  const imageCount = wp.images?.length ?? 0;
  const script = wp.arrivingNarration || wp.attractionNarration || "";
  const mode =
    modeOptions.find((m) => m.id === (wp.routeMode || "driving")) ??
    modeOptions[1];
  const ModeIcon = mode.icon;
  const viaCount = wp.viaPoints?.length ?? 0;
  const canAdjust = VIA_MODES.includes(wp.routeMode);
  const isEndpoint = isStart || isEnd;

  return (
    <div
      ref={itemRef}
      onContextMenu={(e) => {
        if (isListEditMode) {
          e.preventDefault();
          return;
        }
        openContextMenu(e, stopMenu(wp.id));
      }}
      className="relative"
    >
      {!isListEditMode && (
        <>
          {!isFirst && (
            <span className="absolute left-4.75 top-0 h-4 w-px bg-zinc-200 dark:bg-zinc-800" />
          )}
          {!isLast && (
            <span className="absolute left-4.75 top-4 bottom-0 w-px bg-zinc-200 dark:bg-zinc-800" />
          )}
        </>
      )}

      <div
        onClick={() => !isListEditMode && handleSelect()}
        className={`group relative flex items-start gap-2.5 rounded-lg pl-1.5 pr-1.5 py-1.5 transition-colors ${
          isListEditMode ? "cursor-default" : "cursor-pointer"
        } ${
          isActive
            ? "bg-navi/8 dark:bg-navi/12"
            : "hover:bg-zinc-100/80 dark:hover:bg-white/4"
        }`}
      >
        <div className="w-7 h-5 flex items-center justify-center shrink-0">
          {isListEditMode ? (
            <button
              type="button"
              disabled={isRendering}
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              title={t`Remove stop`}
              aria-label={t`Remove stop`}
              className="w-5 h-5 rounded-full bg-red-500/10 text-red-500 hover:bg-red-500 hover:text-white flex items-center justify-center transition-colors animate-in zoom-in-75 duration-150"
            >
              <X className="w-3 h-3" />
            </button>
          ) : (
            <span
              className={`relative z-10 flex items-center justify-center rounded-full font-semibold tabular-nums transition-colors ${
                wp.isStopBy
                  ? "w-4 h-4 text-[8px] border border-dashed border-zinc-400 dark:border-zinc-600 bg-white dark:bg-zinc-950 text-zinc-500"
                  : isActive
                    ? "w-5 h-5 text-[10px] bg-navi text-white ring-3 ring-navi/20"
                    : isEndpoint
                      ? "w-5 h-5 text-[10px] bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                      : "w-5 h-5 text-[10px] border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 text-zinc-700 dark:text-zinc-300"
              }`}
            >
              {displayLabel}
            </span>
          )}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 min-h-5">
            <span
              className={`text-[13px] leading-5 truncate ${
                wp.isStopBy
                  ? "text-zinc-500 dark:text-zinc-400"
                  : "font-medium text-zinc-900 dark:text-zinc-100"
              }`}
              title={wp.name}
            >
              {wp.name}
            </span>
            {wp.isStopBy && (
              <span className="text-[10px] px-1 rounded bg-zinc-100 dark:bg-white/5 text-zinc-500 shrink-0">
                <Trans>Stop-by</Trans>
              </span>
            )}
          </div>

          {(imageCount > 0 || script) && (
            <div className="flex items-center gap-2 mt-0.5 text-[11px] text-zinc-500 min-w-0">
              {imageCount > 0 && (
                <span
                  className="flex items-center gap-1 shrink-0"
                  title={t`${imageCount} photos`}
                >
                  <ImageIcon className="w-3 h-3" />
                  {imageCount}
                </span>
              )}
              {script && (
                <span
                  className="flex items-center gap-1 min-w-0"
                  title={script}
                >
                  <Mic className="w-3 h-3 shrink-0" />
                  <span className="truncate">{script}</span>
                </span>
              )}
            </div>
          )}
        </div>

        {!isListEditMode && (
          <div className="flex items-center shrink-0 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                handleSelect();
              }}
              title={t`Edit Stop`}
              aria-label={t`Edit Stop`}
              className="p-1 rounded-md text-zinc-400 hover:text-zinc-900 hover:bg-zinc-200/70 dark:hover:text-zinc-100 dark:hover:bg-white/10 transition-colors"
            >
              <Edit2 className="w-3.5 h-3.5" />
            </button>
            <span
              aria-hidden
              className="p-1 text-zinc-300 dark:text-zinc-600 cursor-grab active:cursor-grabbing"
            >
              <GripVertical className="w-3.5 h-3.5" />
            </span>
          </div>
        )}
      </div>

      {!isLast && !isListEditMode && !(wp.isStopBy && !wp.connectToRoute) && (
        <div
          onContextMenu={(e) => openContextMenu(e, legMenu(wp))}
          className="relative flex items-center gap-2.5 pl-1.5 pr-1.5 py-1"
        >
          <div className="w-7 flex items-center justify-center shrink-0">
            <span className="relative z-10 w-5 h-5 rounded-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 flex items-center justify-center text-zinc-500">
              <ModeIcon className="w-3 h-3" />
            </span>
          </div>

          <div className="flex items-center gap-1 min-w-0 flex-wrap">
            <div ref={modeMenuRef} className="relative">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setIsModeMenuOpen(!isModeMenuOpen);
                }}
                aria-haspopup="menu"
                aria-expanded={isModeMenuOpen}
                title={t`Travel mode to the next stop`}
                className={`flex items-center gap-1 h-6 pl-1.5 pr-1 rounded-md text-[11px] font-medium transition-colors ${
                  isModeMenuOpen
                    ? "bg-zinc-200/80 text-zinc-900 dark:bg-white/10 dark:text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100 dark:hover:text-zinc-100 dark:hover:bg-white/5"
                }`}
              >
                {mode.label}
                <ChevronDown className="w-3 h-3 opacity-60" />
              </button>

              {isModeMenuOpen && (
                <div
                  role="menu"
                  className="absolute left-0 top-full mt-1 z-50 w-36 p-1 rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-lg animate-in fade-in zoom-in-95 duration-100"
                >
                  {modeOptions.map((option) => {
                    const Icon = option.icon;
                    const selected = option.id === mode.id;
                    return (
                      <button
                        key={option.id}
                        type="button"
                        role="menuitemradio"
                        aria-checked={selected}
                        onClick={(e) => {
                          e.stopPropagation();
                          selectMode(option.id);
                        }}
                        className={`w-full flex items-center gap-2 h-7 px-2 rounded-md text-[12px] transition-colors ${
                          selected
                            ? "text-zinc-900 dark:text-zinc-100 font-medium"
                            : "text-zinc-600 dark:text-zinc-400"
                        } hover:bg-zinc-100 dark:hover:bg-white/5`}
                      >
                        <Icon className="w-3.5 h-3.5" />
                        <span className="flex-1 text-left">{option.label}</span>
                        {selected && (
                          <Check className="w-3.5 h-3.5 text-navi" />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {legColorable(wp) && <LegColorButton wp={wp} />}

            {wp.routeMode === "draw" && (
              <>
                <span
                  className="text-zinc-300 dark:text-zinc-700 text-[11px]"
                  aria-hidden
                >
                  ·
                </span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    startDrawing();
                  }}
                  title={t`Edit the drawn path on the map`}
                  className="flex items-center gap-1 h-6 px-1.5 rounded-md text-[11px] font-medium text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100 dark:hover:text-zinc-100 dark:hover:bg-white/5 transition-colors"
                >
                  <Pencil className="w-3 h-3" />
                  <Trans>Edit path</Trans>
                  {(wp.customRoute?.length ?? 0) > 0 && (
                    <span className="text-zinc-400 tabular-nums">
                      {wp.customRoute!.length}
                    </span>
                  )}
                </button>
              </>
            )}

            {canAdjust && (
              <>
                <span
                  className="text-zinc-300 dark:text-zinc-700 text-[11px]"
                  aria-hidden
                >
                  ·
                </span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    window.dispatchEvent(
                      isViaActive
                        ? new CustomEvent("exit-via-mode")
                        : new CustomEvent("enter-via-mode", {
                            detail: { wpId: wp.id },
                          }),
                    );
                  }}
                  aria-pressed={isViaActive}
                  title={t`Adjust Route (Add via points to nudge)`}
                  className={`flex items-center gap-1 h-6 px-1.5 rounded-md text-[11px] font-medium transition-colors ${
                    isViaActive
                      ? "bg-navi text-white"
                      : "text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100 dark:hover:text-zinc-100 dark:hover:bg-white/5"
                  }`}
                >
                  <Route className="w-3 h-3" />
                  {isViaActive ? (
                    <Trans>Done adjusting</Trans>
                  ) : (
                    <Trans>Adjust</Trans>
                  )}
                </button>
                {viaCount > 0 && (
                  <span
                    title={t`Right-click the leg to clear via points`}
                    className="flex items-center h-5 px-1.5 rounded-md bg-zinc-100 dark:bg-white/5 text-[10px] text-zinc-600 dark:text-zinc-400 tabular-nums"
                  >
                    <Trans>{viaCount} via</Trans>
                  </span>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
