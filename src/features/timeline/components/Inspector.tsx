import { InspectorAudioPanel } from "./elements/inspector/InspectorAudioPanel";
import { InspectorTextPanel } from "./elements/inspector/InspectorTextPanel";
import { InspectorTransitionsPanel } from "./elements/inspector/InspectorTransitionsPanel";
import { InspectorColorPanel } from "./elements/inspector/InspectorColorPanel";
import { InspectorTransformPanel } from "./elements/inspector/InspectorTransformPanel";
import { useWorkspace } from "../../../hooks/useWorkspace";
import {
  Trash2,
  Type,
  Settings2,
  CopyPlus,
} from "../../../components/ui/icons";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

interface InspectorProps {
  selectedClipIds: string[];
  onClearSelection: () => void;
}

export function Inspector({
  selectedClipIds,
  onClearSelection,
}: InspectorProps) {
  const { timeline, setTimeline } = useWorkspace();

  if (selectedClipIds.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-zinc-400 p-6 text-center">
        <Settings2 className="w-8 h-8 mb-3 opacity-20" />
        <p className="text-xs">
          <Trans>Select a clip on the timeline to edit its properties</Trans>
        </p>
      </div>
    );
  }

  if (selectedClipIds.length > 1) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-zinc-400 p-6 text-center animate-in fade-in zoom-in-95">
        <CopyPlus className="w-8 h-8 mb-3 text-navi-500/50" />
        <p className="text-sm font-bold text-zinc-800 dark:text-zinc-200">
          <Trans>{selectedClipIds.length} Clips Selected</Trans>
        </p>
        <p className="text-[10px] mt-2 leading-relaxed">
          <Trans>
            You can drag these clips together on the timeline, copy/paste them,
            or press Delete to remove them
          </Trans>
        </p>
        <button
          onClick={() => {
            setTimeline({
              ...timeline,
              clips: timeline.clips.filter(
                (c) => !selectedClipIds.includes(c.id),
              ),
            });
            onClearSelection();
          }}
          className="mt-6 px-4 py-2 bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 text-xs font-bold rounded-lg hover:bg-red-100 transition-colors flex items-center gap-2"
        >
          <Trash2 className="w-3.5 h-3.5" /> <Trans>Delete Selected</Trans>
        </button>
      </div>
    );
  }

  const selectedClip = timeline.clips.find((c) => c.id === selectedClipIds[0]);
  if (!selectedClip) return null;

  const updateClip = (updates: Partial<typeof selectedClip>) => {
    setTimeline({
      ...timeline,
      clips: timeline.clips.map((c) =>
        c.id === selectedClip.id ? { ...c, ...updates } : c,
      ),
    });
  };

  const isAudioClip = selectedClip.type === "audio";
  const isTextOrSubtitle =
    selectedClip.type === "text" || selectedClip.type === "subtitle";

  const updateTextStyle = (props: Partial<typeof selectedClip>) => {
    updateClip({
      ...props,
      style: {
        ...(selectedClip.style || {}),
        ...props,
      },
    });
  };

  return (
    <div className="flex-1 flex flex-col gap-4 animate-in fade-in duration-200">
      <div className="flex items-center justify-between pb-3 border-b border-zinc-200 dark:border-navidark-400">
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${
              isAudioClip
                ? "bg-[#93C9B2]"
                : isTextOrSubtitle
                  ? "bg-amber-400"
                  : "bg-navi-500"
            }`}
          />
          <h4 className="text-sm font-bold text-zinc-800 dark:text-zinc-100 truncate w-40">
            {selectedClip.label}
          </h4>
        </div>
        <button
          onClick={() => {
            setTimeline({
              ...timeline,
              clips: timeline.clips.filter((c) => c.id !== selectedClip.id),
            });
            onClearSelection();
          }}
          className="p-1.5 text-zinc-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-md transition-colors"
          title={t`Delete Clip`}
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      <div className="space-y-4">
        {/* Label Edit */}
        <div className="space-y-1.5">
          <label className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
            <Type className="w-3 h-3" /> <Trans>Clip Label</Trans>
          </label>
          <input
            type="text"
            value={selectedClip.label}
            onChange={(e) => updateClip({ label: e.target.value })}
            className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 focus:outline-none focus:border-navi"
          />
        </div>

        {isAudioClip && (
          <InspectorAudioPanel
            selectedClip={selectedClip}
            updateClip={updateClip}
          />
        )}

        {isTextOrSubtitle && (
          <InspectorTextPanel
            selectedClip={selectedClip}
            updateClip={updateClip}
            updateTextStyle={updateTextStyle}
          />
        )}

        {!isAudioClip && !isTextOrSubtitle && (
          <InspectorTransitionsPanel
            selectedClip={selectedClip}
            updateClip={updateClip}
            timeline={timeline}
            setTimeline={setTimeline}
          />
        )}

        {(selectedClip.type === "video" || selectedClip.type === "image") && (
          <InspectorColorPanel
            selectedClip={selectedClip}
            updateClip={updateClip}
          />
        )}

        {!isAudioClip && (
          <InspectorTransformPanel
            selectedClip={selectedClip}
            updateClip={updateClip}
          />
        )}
      </div>
    </div>
  );
}
