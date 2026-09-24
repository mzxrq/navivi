import { useState } from "react";
import { MapPinPlus, Trash2 } from "../../../../components/ui/icons";
import { WaypointTimelineMarker } from "../../../../types";
import { formatMarkerTime } from "./WaypointMarker";
import { t } from "@lingui/core/macro";


interface MarkersPanelProps {
  markers: WaypointTimelineMarker[];
  currentTime: number;
  onAdd: () => void;
  onUpdate: (id: string, updates: Partial<WaypointTimelineMarker>) => void;
  onDelete: (id: string) => void;
  onSeek: (time: number) => void;
}

export function MarkersPanel({
  markers,
  currentTime,
  onAdd,
  onUpdate,
  onDelete,
  onSeek,
}: MarkersPanelProps) {
  const [editingId, setEditingId] = useState<string | null>(null);

  return (
    <div className="flex h-full flex-col bg-white dark:bg-navidark-900">
      <div className="flex items-center justify-between border-b border-zinc-200 p-3 dark:border-navidark-700">
        <div>
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
            Timeline markers
          </h3>
          <p className="text-[10px] text-zinc-500">
            Waypoint-linked and custom markers
          </p>
        </div>
        <button
          type="button"
          onClick={onAdd}
          className="flex items-center gap-1 rounded bg-navi px-2 py-1 text-[10px] font-bold text-white"
          title={`Add marker at ${formatMarkerTime(currentTime)}`}
        >
          <MapPinPlus className="h-3.5 w-3.5" /> Add
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {markers.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center p-6 text-center text-xs text-zinc-400">
            <MapPinPlus className="mb-2 h-7 w-7 opacity-40" />
            <p>No timeline markers yet.</p>
            <p className="mt-1 text-[10px]">
              Add one at the current playhead position.
            </p>
          </div>
        ) : (
          <div className="space-y-1">
            {markers.map((marker) => {
              const isEditing = editingId === marker.id;
              return (
                <div
                  key={marker.id}
                  className="flex items-center gap-2 rounded border border-zinc-200 p-2 dark:border-navidark-700"
                >
                  <button
                    type="button"
                    onClick={() => onSeek(marker.time)}
                    className="min-w-0 flex-1 text-left"
                    title="Seek to marker"
                  >
                    {isEditing ? (
                      <input
                        autoFocus
                        value={marker.name}
                        onChange={(event) =>
                          onUpdate(marker.id, { name: event.target.value })
                        }
                        onBlur={() => setEditingId(null)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === "Escape")
                            setEditingId(null);
                        }}
                        onClick={(event) => event.stopPropagation()}
                        className="w-full rounded border border-navi bg-transparent px-1 text-xs outline-none"
                      />
                    ) : (
                      <span className="block truncate text-xs font-semibold text-zinc-800 dark:text-zinc-100">
                        #{marker.index} {marker.name}
                      </span>
                    )}
                    <span className="font-mono text-[10px] text-zinc-400">
                      {formatMarkerTime(marker.time)}
                      {marker.waypointId ? " · waypoint" : ""}
                    </span>
                  </button>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={marker.time}
                    onChange={(event) =>
                      onUpdate(marker.id, {
                        time: Math.max(0, Number(event.target.value) || 0),
                      })
                    }
                    className="w-16 rounded border border-zinc-200 bg-transparent px-1 py-0.5 text-[10px] font-mono dark:border-navidark-600"
                    title="Marker time in seconds"
                  />
                  <button
                    type="button"
                    onClick={() => setEditingId(marker.id)}
                    className="text-[10px] text-zinc-400 hover:text-navi"
                    title="Rename marker"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(marker.id)}
                    className="text-zinc-400 hover:text-red-500"
                    title="Delete marker"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
