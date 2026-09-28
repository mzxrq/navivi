import { useState } from "react";
import { Rnd } from "react-rnd";
import { ChevronDown, ChevronUp, Trash2 } from "../../../components/ui/icons";
import { Waypoint } from "../../../types";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

interface UnifiedLayersPanelProps {
  activeWp: Waypoint;
  nextWp: Waypoint;
  waypoints: Waypoint[];
  updateWaypoint: (id: string, data: Partial<Waypoint>) => void;
  setIsDirty: (dirty: boolean) => void;
}

export function UnifiedLayersPanel({
  activeWp,
  nextWp,
  waypoints,
  updateWaypoint,
  setIsDirty,
}: UnifiedLayersPanelProps) {
  const [isDrawStatusCollapsed, setIsDrawStatusCollapsed] = useState(false);

  return (
    <Rnd
      key="anchors-layer-panel"
      default={{
        x:
          window.innerWidth < 1160 ? 80 : Math.max(10, window.innerWidth - 660),
        y: window.innerWidth < 1160 ? 56 : 80,
        width: 320,
        height: "auto",
      }}
      enableResizing={false}
      minWidth={250}
      bounds="parent"
      dragHandleClassName="anchors-drag-handle"
      style={{ zIndex: 300 }}
    >
      <div className="w-full bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200 dark:border-zinc-700 rounded-xl shadow-2xl flex flex-col overflow-hidden pointer-events-auto transition-all duration-300 ease-in-out">
        <div className="anchors-drag-handle px-3 py-2 bg-zinc-100/50 dark:bg-zinc-800/50 border-b border-zinc-200 dark:border-zinc-700 flex justify-between items-center cursor-move group">
          <div className="flex items-center gap-2 overflow-hidden pr-2">
            <span
              className="text-xs font-bold text-zinc-700 dark:text-zinc-300 truncate max-w-24"
              title={activeWp.name}
            >
              {activeWp.name}
            </span>
            <span className="text-xs opacity-50 font-black shrink-0">ↁE</span>
            <span
              className="text-xs font-bold text-zinc-700 dark:text-zinc-300 truncate max-w-24"
              title={nextWp.name}
            >
              {nextWp.name}
            </span>
            <span className="text-[10px] font-bold text-zinc-500 bg-black/5 dark:bg-white/10 px-1.5 py-0.5 rounded shrink-0">
              {activeWp.customRoute?.length || 0}
            </span>

            <div className="w-px h-4 bg-black/10 dark:bg-white/20 ml-1 shrink-0" />
            <div className="relative group/copy">
              <button
                className="px-2 py-1 bg-black/5 hover:bg-black/10 dark:bg-white/10 dark:hover:bg-white/20 rounded text-[10px] font-bold uppercase tracking-wider transition-colors flex items-center gap-1 shrink-0"
                title={t`Copy a trail from another waypoint`}
              >
                <Trans>Copy</Trans>
              </button>
              <div className="absolute left-0 top-full mt-2 w-48 bg-white dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-xl shadow-xl py-1.5 z-50 opacity-0 invisible group-hover/copy:opacity-100 group-hover/copy:visible transition-all">
                <div className="px-3 py-1.5 text-[10px] font-bold text-zinc-500 uppercase tracking-wider border-b border-zinc-100 dark:border-white/5 mb-1">
                  <Trans>Select Layer to Copy</Trans>
                </div>
                <div className="max-h-40 overflow-y-auto custom-scrollbar">
                  {waypoints.filter(
                    (w) =>
                      w.id !== activeWp.id &&
                      w.customRoute &&
                      w.customRoute.length > 0,
                  ).length === 0 ? (
                    <div className="px-4 py-2 text-xs text-zinc-500 italic">
                      <Trans>No drawn trails found</Trans>
                    </div>
                  ) : (
                    waypoints
                      .filter(
                        (w) =>
                          w.id !== activeWp.id &&
                          w.customRoute &&
                          w.customRoute.length > 0,
                      )
                      .map((w) => (
                        <button
                          key={w.id}
                          onClick={() => {
                            if (w.customRoute) {
                              updateWaypoint(activeWp.id, {
                                customRoute: [...w.customRoute],
                                routeMode: "draw",
                              });
                              setIsDirty(true);
                            }
                          }}
                          className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 truncate"
                        >
                          {w.name || t`Waypoint`}
                        </button>
                      ))
                  )}
                </div>
              </div>
            </div>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              setIsDrawStatusCollapsed(!isDrawStatusCollapsed);
            }}
            className="p-1 hover:bg-black/10 dark:hover:bg-white/10 rounded text-zinc-500 shrink-0"
            title={isDrawStatusCollapsed ? t`Collapse` : t`Expand`}
          >
            {isDrawStatusCollapsed ? (
              <ChevronDown className="w-4 h-4" />
            ) : (
              <ChevronUp className="w-4 h-4" />
            )}
          </button>
        </div>

        {!isDrawStatusCollapsed && (
          <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col p-1 max-h-100">
            {!activeWp.customRoute || activeWp.customRoute.length === 0 ? (
              <div className="px-4 py-3 text-xs text-zinc-500 italic text-center">
                <Trans>No anchors drawn yet</Trans>
              </div>
            ) : (
              activeWp.customRoute.map((anchor, idx) => (
                <div
                  key={`anchor-mgr-${idx}`}
                  className="flex items-center justify-between p-1 hover:bg-zinc-100 dark:hover:bg-zinc-700 rounded group/anchor"
                >
                  <div className="flex items-center gap-2">
                    <div className="w-5 h-5 rounded-full bg-amber-500/20 text-amber-600 dark:text-amber-400 flex items-center justify-center text-[10px] font-black shrink-0">
                      {idx + 1}
                    </div>
                    <span className="text-xs text-zinc-700 dark:text-zinc-300 font-mono truncate">
                      {anchor[0].toFixed(5)}, {anchor[1].toFixed(5)}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover/anchor:opacity-100 transition-opacity">
                    <button
                      disabled={idx === 0}
                      onClick={() => {
                        const newRoute = [...activeWp.customRoute!];
                        [newRoute[idx - 1], newRoute[idx]] = [
                          newRoute[idx],
                          newRoute[idx - 1],
                        ];
                        updateWaypoint(activeWp.id, {
                          customRoute: newRoute,
                        });
                        setIsDirty(true);
                      }}
                      className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-600 rounded text-zinc-500 disabled:opacity-30"
                      title={t`Move Up`}
                    >
                      <ChevronUp className="w-3.5 h-3.5" />
                    </button>
                    <button
                      disabled={idx === (activeWp.customRoute?.length ?? 0) - 1}
                      onClick={() => {
                        const newRoute = [...activeWp.customRoute!];
                        [newRoute[idx + 1], newRoute[idx]] = [
                          newRoute[idx],
                          newRoute[idx + 1],
                        ];
                        updateWaypoint(activeWp.id, {
                          customRoute: newRoute,
                        });
                        setIsDirty(true);
                      }}
                      className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-600 rounded text-zinc-500 disabled:opacity-30"
                      title={t`Move Down`}
                    >
                      <ChevronDown className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => {
                        const newRoute = [...activeWp.customRoute!];
                        newRoute.splice(idx, 1);
                        updateWaypoint(activeWp.id, {
                          customRoute: newRoute,
                        });
                        setIsDirty(true);
                      }}
                      className="p-1 hover:bg-red-100 dark:hover:bg-red-500/20 hover:text-red-500 rounded text-zinc-500"
                      title={t`Delete Anchor`}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </Rnd>
  );
}
