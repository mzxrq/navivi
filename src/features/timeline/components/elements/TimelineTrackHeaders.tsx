import React from "react";
import { Eye, EyeOff, Volume2, VolumeX, Lock, Unlock } from "lucide-react";
import { TimelineData } from "../../../../types/index";

interface TimelineTrackHeadersProps {
  headerRef: React.RefObject<HTMLDivElement | null>;
  timelineRef: React.RefObject<HTMLDivElement | null>;
  sortedTracks: any[];
  timeline: TimelineData;
  setTimeline: (data: TimelineData) => void;
  editingTrackId: string | null;
  setEditingTrackId: (id: string | null) => void;
  handleUpdateTrackName: (id: string, name: string) => void;
  handleToggleTrackProp: (id: string, prop: "isHidden" | "isMuted" | "isLocked") => void;
  isDuckingActive: boolean;
}

export function TimelineTrackHeaders({
  headerRef,
  timelineRef,
  sortedTracks,
  timeline,
  setTimeline,
  editingTrackId,
  setEditingTrackId,
  handleUpdateTrackName,
  handleToggleTrackProp,
  isDuckingActive,
}: TimelineTrackHeadersProps) {
  return (
    <div className="w-48 flex flex-col shrink-0 border-r border-zinc-300 dark:border-navidark-400 bg-zinc-50 dark:bg-navidark-800 z-40">
      <div className="h-8 w-full border-b border-zinc-300 dark:border-navidark-400 shrink-0 flex items-center px-3 bg-zinc-200/90 dark:bg-navidark-800/90">
        <span className="text-[9px] font-bold text-zinc-400 dark:text-zinc-500 tracking-widest">
          TRACKS
        </span>
      </div>
      <div
        ref={headerRef}
        className="flex-1 overflow-hidden"
        onWheel={(e) => {
          if (timelineRef.current) {
            timelineRef.current.scrollTop += e.deltaY;
          }
        }}
        onContextMenu={(e) => {
          e.preventDefault();
          window.dispatchEvent(
            new CustomEvent("open-context-menu", {
              detail: { x: e.clientX, y: e.clientY, type: "empty-track" },
            }),
          );
        }}
      >
        <div className="pb-32">
          {/* ✨ MAPPING OVER SORTED TRACKS */}
          {sortedTracks.map((track, idx) => {
            const prevTrack = sortedTracks[idx - 1];
            const isNewGroup =
              !prevTrack || prevTrack.type !== track.type;

            const isMainTrack =
              track.type === "video" ||
              track.name.toLowerCase().includes("video");
            const isAudioTrack = track.type === "audio";
            const trackHeight = isMainTrack ? "h-20" : "h-14";
            return (
              <React.Fragment key={track.id}>
                {isNewGroup && (
                  <div className="h-6 w-full bg-zinc-200 dark:bg-navidark-900 border-b border-zinc-300 dark:border-navidark-700 flex items-center px-3 sticky top-0 z-10 shadow-sm">
                    <span className="text-[9px] font-bold text-zinc-500 uppercase tracking-widest">
                      {track.type} TRACKS
                    </span>
                  </div>
                )}
                <div
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData(
                      "application/navivi-track",
                      track.id,
                    );
                  }}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    const sourceTrackId = e.dataTransfer.getData(
                      "application/navivi-track",
                    );
                    if (!sourceTrackId || sourceTrackId === track.id)
                      return;

                    const sourceTrack = timeline.tracks.find(
                      (t) => t.id === sourceTrackId,
                    );
                    if (!sourceTrack || sourceTrack.type !== track.type)
                      return;

                    setTimeline({
                      ...timeline,
                      tracks: timeline.tracks.map((t) => {
                        if (t.id === sourceTrackId)
                          return { ...t, orderIndex: track.orderIndex };
                        if (t.id === track.id)
                          return {
                            ...t,
                            orderIndex: sourceTrack.orderIndex,
                          };
                        return t;
                      }),
                    });
                  }}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    window.dispatchEvent(
                      new CustomEvent("open-context-menu", {
                        detail: {
                          x: e.clientX,
                          y: e.clientY,
                          type: "track-header",
                          targetId: track.id,
                          data: {
                            isLocked: track.isLocked,
                            isHidden: track.isHidden,
                            isMuted: track.isMuted,
                            isAudioTrack,
                            onToggleHide: () =>
                              handleToggleTrackProp(track.id, "isHidden"),
                            onToggleMute: () =>
                              handleToggleTrackProp(track.id, "isMuted"),
                            onToggleLock: () =>
                              handleToggleTrackProp(track.id, "isLocked"),
                          },
                        },
                      }),
                    );
                  }}
                  onDoubleClick={() => setEditingTrackId(track.id)}
                  className={`w-full border-b border-zinc-200 dark:border-navidark-400 flex flex-col justify-center px-2.5 ${editingTrackId === track.id ? "" : "cursor-context-menu"} ${trackHeight}`}
                >
                  <div className="flex items-center justify-between mb-1 gap-1">
                    {editingTrackId === track.id ? (
                      <input
                        type="text"
                        autoFocus
                        defaultValue={track.name}
                        onBlur={(e) =>
                          handleUpdateTrackName(track.id, e.target.value)
                        }
                        onKeyDown={(e) => {
                          if (e.key === "Enter")
                            handleUpdateTrackName(
                              track.id,
                              e.currentTarget.value,
                            );
                          if (e.key === "Escape") setEditingTrackId(null);
                        }}
                        className="w-full bg-white dark:bg-navidark-900 text-[10px] font-bold text-zinc-900 dark:text-zinc-100 px-1.5 py-1 rounded outline-none border-2 border-navi"
                      />
                    ) : (
                      <span className="text-[10px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-wider truncate flex-1">
                        {track.name}
                      </span>
                    )}

                    {/* Ducking toggle & active indicator for Audio tracks */}
                    {isAudioTrack && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setTimeline({
                            ...timeline,
                            tracks: timeline.tracks.map((t) =>
                              t.id === track.id
                                ? {
                                    ...t,
                                    duckingEnabled: !t.duckingEnabled,
                                  }
                                : t,
                            ),
                          });
                        }}
                        className={`px-1 py-0.5 text-[8px] font-bold rounded tracking-tighter uppercase transition-colors shrink-0 ${
                          track.duckingEnabled
                            ? isDuckingActive
                              ? "bg-amber-500 text-white animate-pulse"
                              : "bg-amber-500/20 text-amber-500 border border-amber-500/40"
                            : "text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 opacity-60"
                        }`}
                        title={
                          track.duckingEnabled
                            ? isDuckingActive
                              ? "Auto-Ducking Actively Attenuating (Click to disable)"
                              : "Auto-Ducking Armed (Click to disable)"
                            : "Enable Auto-Ducking on this track"
                        }
                      >
                        DUCK
                      </button>
                    )}
                  </div>

                  <div className="flex items-center justify-between gap-1.5">
                    <div className="flex items-center gap-1 shrink-0">
                      {!isAudioTrack ? (
                        <button
                          onClick={() =>
                            handleToggleTrackProp(track.id, "isHidden")
                          }
                          className={`p-1 rounded transition-colors ${track.isHidden ? "text-red-500 bg-red-50 dark:bg-red-500/10" : "text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200"}`}
                        >
                          {track.isHidden ? (
                            <EyeOff className="w-3.5 h-3.5" />
                          ) : (
                            <Eye className="w-3.5 h-3.5" />
                          )}
                        </button>
                      ) : (
                        <button
                          onClick={() =>
                            handleToggleTrackProp(track.id, "isMuted")
                          }
                          className={`p-1 rounded transition-colors ${track.isMuted ? "text-red-500 bg-red-50 dark:bg-red-500/10" : "text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200"}`}
                          title={
                            track.isMuted ? "Unmute Track" : "Mute Track"
                          }
                        >
                          {track.isMuted ? (
                            <VolumeX className="w-3.5 h-3.5" />
                          ) : (
                            <Volume2 className="w-3.5 h-3.5" />
                          )}
                        </button>
                      )}
                      <button
                        onClick={() =>
                          handleToggleTrackProp(track.id, "isLocked")
                        }
                        className={`p-1 rounded transition-colors ${track.isLocked ? "text-red-500 bg-red-50 dark:bg-red-500/10" : "text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200"}`}
                        title={
                          track.isLocked ? "Unlock Track" : "Lock Track"
                        }
                      >
                        {track.isLocked ? (
                          <Lock className="w-3 h-3" />
                        ) : (
                          <Unlock className="w-3 h-3" />
                        )}
                      </button>
                    </div>

                    {/* Track volume slider for Audio tracks */}
                    {isAudioTrack && (
                      <div
                        className="flex items-center gap-1 flex-1 min-w-0"
                        title={`Track Volume: ${Math.round((track.volume ?? 1.0) * 100)}%`}
                      >
                        <input
                          type="range"
                          min="0"
                          max="150"
                          step="5"
                          value={Math.round((track.volume ?? 1.0) * 100)}
                          onChange={(e) => {
                            const newVol =
                              parseFloat(e.target.value) / 100;
                            setTimeline({
                              ...timeline,
                              tracks: timeline.tracks.map((t) =>
                                t.id === track.id
                                  ? { ...t, volume: newVol }
                                  : t,
                              ),
                            });
                          }}
                          className="w-full h-1 accent-[#36604C] dark:accent-[#93C9B2] bg-zinc-200 dark:bg-zinc-700 rounded cursor-pointer"
                        />
                        <span className="text-[8px] font-mono text-zinc-400 w-5 text-right shrink-0">
                          {Math.round((track.volume ?? 1.0) * 100)}%
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </div>

  );
}
