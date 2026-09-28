import { t } from "@lingui/core/macro"; import { Trans } from "@lingui/react/macro";
import { Sparkles } from "../../../../../components/ui/icons";

interface InspectorTransitionsPanelProps {
  selectedClip: any;
  updateClip: (updates: any) => void;
  timeline: any;
  setTimeline: (timeline: any) => void;
}

export function InspectorTransitionsPanel({
  selectedClip,
  updateClip,
  timeline,
  setTimeline,
}: InspectorTransitionsPanelProps) {
  return (
    <div className="space-y-3 pt-3 border-t border-zinc-200 dark:border-navidark-400">
      <h5 className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
        <Sparkles className="w-3 h-3" /> <Trans>Transitions</Trans>
      </h5>
      <div className="space-y-2">
        <div>
          <label className="text-[10px] text-zinc-400 block mb-1">
            <Trans>In-Transition</Trans>
          </label>
          <select
            value={selectedClip.transitionIn || "none"}
            onChange={(e) => {
              const val =
                e.target.value === "none" ? undefined : e.target.value;
              if (val) {
                const duration = selectedClip.fadeIn || 1.0;
                const precedingClip = timeline.clips
                  .filter(
                    (c: any) =>
                      c.trackId === selectedClip.trackId &&
                      c.id !== selectedClip.id &&
                      c.startTime < selectedClip.startTime,
                  )
                  .sort(
                    (a: any, b: any) =>
                      b.startTime + b.duration - (a.startTime + a.duration),
                  )[0];

                const updatedClips = timeline.clips.map((c: any) => {
                  if (c.id === selectedClip.id) {
                    return {
                      ...c,
                      transitionIn: val,
                      fadeIn: duration,
                      prevClip: precedingClip || undefined,
                    };
                  }
                  if (precedingClip && c.id === precedingClip.id) {
                    return {
                      ...c,
                      transitionOut: val,
                      fadeOut: duration,
                    };
                  }
                  return c;
                });

                const filteredTransitions = (timeline.transitions || []).filter(
                  (t: any) =>
                    !precedingClip ||
                    !(
                      t.fromClipId === precedingClip.id &&
                      t.toClipId === selectedClip.id
                    ),
                );

                const newTransitions = precedingClip
                  ? [
                      ...filteredTransitions,
                      {
                        id: crypto.randomUUID(),
                        trackId: selectedClip.trackId,
                        fromClipId: precedingClip.id,
                        toClipId: selectedClip.id,
                        type: val,
                        duration: duration,
                        startTime:
                          precedingClip.startTime +
                          precedingClip.duration -
                          duration / 2,
                      },
                    ]
                  : filteredTransitions;

                setTimeline({
                  ...timeline,
                  clips: updatedClips,
                  transitions: newTransitions,
                });
              } else {
                updateClip({
                  transitionIn: undefined,
                  fadeIn: undefined,
                  prevClip: undefined,
                });
              }
            }}
            className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 cursor-pointer"
          >
            <option value="none"><Trans>None</Trans></option>
            <option value="glsl-crossfade"><Trans>Crossfade</Trans></option>
            <option value="glsl-wipe"><Trans>Wipe</Trans></option>
            <option value="glsl-slide"><Trans>Slide</Trans></option>
            <option value="glsl-dissolve"><Trans>Dissolve</Trans></option>
            <option value="glsl-dreamy"><Trans>Dreamy</Trans></option>
            <option value="glsl-directionalwarp">
              <Trans>Directional Warp</Trans>
            </option>
            <option value="glsl-pixelize"><Trans>Pixelize</Trans></option>
            <option value="glsl-multiply_blend"><Trans>Multiply Blend</Trans></option>
            <option value="glsl-crosswarp"><Trans>Cross Warp</Trans></option>
            <option value="glsl-burn"><Trans>Burn</Trans></option>
            <option value="crossfade"><Trans>Opacity Fade</Trans></option>
            <option value="fade-black"><Trans>Fade to Black</Trans></option>
          </select>
        </div>
        <div>
          <label className="text-[10px] text-zinc-400 block mb-1">
            <Trans>Out-Transition</Trans>
          </label>
          <select
            value={selectedClip.transitionOut || "none"}
            onChange={(e) => {
              const val =
                e.target.value === "none" ? undefined : e.target.value;
              if (val) {
                const duration = selectedClip.fadeOut || 1.0;
                const nextClip = timeline.clips
                  .filter(
                    (c: any) =>
                      c.trackId === selectedClip.trackId &&
                      c.id !== selectedClip.id &&
                      c.startTime > selectedClip.startTime,
                  )
                  .sort((a: any, b: any) => a.startTime - b.startTime)[0];

                const updatedClips = timeline.clips.map((c: any) => {
                  if (c.id === selectedClip.id) {
                    return {
                      ...c,
                      transitionOut: val,
                      fadeOut: duration,
                    };
                  }
                  if (nextClip && c.id === nextClip.id) {
                    return {
                      ...c,
                      transitionIn: val,
                      fadeIn: duration,
                      prevClip: selectedClip,
                    };
                  }
                  return c;
                });

                const filteredTransitions = (timeline.transitions || []).filter(
                  (t: any) =>
                    !nextClip ||
                    !(
                      t.fromClipId === selectedClip.id &&
                      t.toClipId === nextClip.id
                    ),
                );

                const newTransitions = nextClip
                  ? [
                      ...filteredTransitions,
                      {
                        id: crypto.randomUUID(),
                        trackId: selectedClip.trackId,
                        fromClipId: selectedClip.id,
                        toClipId: nextClip.id,
                        type: val,
                        duration: duration,
                        startTime:
                          selectedClip.startTime +
                          selectedClip.duration -
                          duration / 2,
                      },
                    ]
                  : filteredTransitions;

                setTimeline({
                  ...timeline,
                  clips: updatedClips,
                  transitions: newTransitions,
                });
              } else {
                updateClip({ transitionOut: undefined, fadeOut: undefined });
              }
            }}
            className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 cursor-pointer"
          >
            <option value="none"><Trans>None</Trans></option>
            <option value="glsl-crossfade"><Trans>Crossfade</Trans></option>
            <option value="glsl-wipe"><Trans>Wipe</Trans></option>
            <option value="glsl-slide"><Trans>Slide</Trans></option>
            <option value="glsl-dissolve"><Trans>Dissolve</Trans></option>
            <option value="glsl-dreamy"><Trans>Dreamy</Trans></option>
            <option value="glsl-directionalwarp">
              <Trans>Directional Warp</Trans>
            </option>
            <option value="glsl-pixelize"><Trans>Pixelize</Trans></option>
            <option value="glsl-multiply_blend"><Trans>Multiply Blend</Trans></option>
            <option value="glsl-crosswarp"><Trans>Cross Warp</Trans></option>
            <option value="glsl-burn"><Trans>Burn</Trans></option>
            <option value="crossfade"><Trans>Opacity Fade</Trans></option>
            <option value="fade-black"><Trans>Fade to Black</Trans></option>
          </select>
        </div>
      </div>
    </div>
  );
}
