import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Folder, Play, Plus, Trash2, Volume2, VolumeX } from "../../../components/ui/icons";
import { openContextMenu, separator } from "../../../components/ui/menuItems";
import { Switch } from "../../../components/ui/Switch";
import { useWorkspace } from "../../../hooks/useWorkspace";
import type { Waypoint } from "../../../types";

export const MAX_VIDEOS = 3;
export const VIDEO_EXTENSIONS = ["mp4", "mov", "m4v", "mkv", "webm"];

const fileName = (p: string) => p.split(/\\|\//).pop() || p;

export function WaypointVideos({ wp }: { wp: Waypoint }) {
  const { updateWaypoint } = useWorkspace();
  const videos = wp.videos ?? [];
  const sound = wp.videoSound ?? [];

  const add = async () => {
    const selected = await open({
      multiple: true,
      filters: [{ name: t`Videos`, extensions: VIDEO_EXTENSIONS }],
    });
    const picked = Array.isArray(selected) ? selected : selected ? [selected] : [];
    if (!picked.length) return;
    const next = [...videos, ...picked].slice(0, MAX_VIDEOS);
    updateWaypoint(wp.id, { videos: next, videoSound: next.map((_, i) => sound[i] ?? false) });
  };

  const remove = (idx: number) =>
    updateWaypoint(wp.id, {
      videos: videos.filter((_, i) => i !== idx),
      videoSound: videos.map((_, i) => sound[i] ?? false).filter((_, i) => i !== idx),
    });

  const setSound = (idx: number, on: boolean) =>
    updateWaypoint(wp.id, { videoSound: videos.map((_, i) => (i === idx ? on : (sound[i] ?? false))) });

  return (
    <div>
      <p className="text-[11px] text-zinc-500 mb-3 max-w-xl leading-relaxed">
        <Trans>
          Use your own footage for this stop. It plays in place of the animated photo clip and is fitted to the narration. Its sound is off
          unless you turn it on.
        </Trans>
      </p>
      <div className="flex flex-wrap gap-3">
        {videos.map((video, idx) => {
          const keep = sound[idx] ?? false;
          return (
            <div
              key={`${video}-${idx}`}
              onContextMenu={(e) =>
                openContextMenu(e, [
                  { type: "label", label: fileName(video) },
                  { label: t`Reveal in File Explorer`, icon: Folder, onSelect: () => void invoke("open_in_explorer", { path: video }).catch(console.error) },
                  separator,
                  { label: t`Remove video`, icon: Trash2, danger: true, onSelect: () => remove(idx) },
                ])
              }
              className="group w-48 rounded-lg border border-zinc-200 dark:border-white/10 overflow-hidden bg-white dark:bg-zinc-950"
            >
              <div className="relative aspect-4/3 bg-zinc-900">
                <video src={`${convertFileSrc(video)}#t=0.1`} preload="metadata" muted playsInline className="w-full h-full object-cover" />
                <span className="absolute inset-0 flex items-center justify-center pointer-events-none">
                  <span className="w-8 h-8 rounded-full bg-black/55 text-white flex items-center justify-center">
                    <Play className="w-3.5 h-3.5 ml-0.5" />
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => remove(idx)}
                  title={t`Remove video`}
                  aria-label={t`Remove video`}
                  className="absolute top-1.5 right-1.5 p-1 rounded-md bg-black/55 text-white opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-red-500 transition"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
              <div className="p-2 space-y-2">
                <p className="text-[11px] text-zinc-600 dark:text-zinc-400 truncate" title={video}>
                  {fileName(video)}
                </p>
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-[11px] text-zinc-500">
                    {keep ? <Volume2 className="w-3 h-3" /> : <VolumeX className="w-3 h-3" />}
                    <Trans>Keep its sound</Trans>
                  </span>
                  <Switch checked={keep} onChange={(v) => setSound(idx, v)} label={t`Keep the sound of this video`} />
                </div>
              </div>
            </div>
          );
        })}

        {videos.length < MAX_VIDEOS && (
          <button
            type="button"
            onClick={add}
            className="w-48 aspect-4/3 rounded-lg border border-dashed border-zinc-300 dark:border-white/15 flex flex-col items-center justify-center gap-1.5 text-zinc-500 hover:text-zinc-800 hover:border-zinc-400 hover:bg-zinc-50 dark:hover:text-zinc-200 dark:hover:border-white/25 dark:hover:bg-white/2 transition-colors"
          >
            <span className="w-8 h-8 rounded-full bg-zinc-100 dark:bg-white/5 flex items-center justify-center">
              <Plus className="w-4 h-4" />
            </span>
            <span className="text-[12px] font-medium">
              <Trans>Add video</Trans>
            </span>
          </button>
        )}
      </div>
    </div>
  );
}
