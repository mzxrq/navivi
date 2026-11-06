import { Draggable, Droppable } from "@hello-pangea/dnd";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { GitBranch, MapPinPlus, Trash2 } from "../../../components/ui/icons";
import { Switch } from "../../../components/ui/Switch";
import { Tip } from "../../../components/ui/Tip";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { inSubCourse, mainStops, removeSubCourse, resolveAnchor, setEndsAtDestination, subEnd, SUB_COURSE_COLOR } from "../../../utils/courses";
import { WaypointItem } from "./WaypointItem";

export const SUB_LIST = "sub-course-list";

/** The sub course under the main route: where it branches off, its own stops (droppable SUB_LIST), and whether it
 *  ends at the main destination. Started from a stop's menu ("Start a sub course here"). */
export function SubCourseSection({ isListEditMode }: { isListEditMode: boolean }) {
  const { waypoints, setWaypoints, settings, updateSettings, addToSub, setAddToSub, setActiveWaypointId } = useWorkspace();
  const sub = waypoints.filter(inSubCourse);
  if (sub.length === 0) return null;

  const end = subEnd(waypoints);
  const [first, last] = [sub[0], end ? sub[sub.length - 1] : undefined];
  const middle = sub.filter((w) => w !== first && w !== last);
  const main = mainStops(waypoints);
  const branch = main.find((w) => w.id === first.branchOf);
  const dest = main[main.length - 1];
  const anchorRow = (wp: typeof first, isFirst: boolean, isLast: boolean) => (
    <WaypointItem
      wp={resolveAnchor(wp, waypoints)}
      index={waypoints.indexOf(wp)}
      isListEditMode={false}
      isFirst={isFirst}
      isLast={isLast}
      onEdit={() => setActiveWaypointId(wp.branchOf ?? null)}
      onDelete={() => undefined}
    />
  );

  return (
    <div className="mt-4">
      <div className="-mx-1 px-1 py-2 flex items-center gap-2">
        <GitBranch className="w-3.5 h-3.5 shrink-0" style={{ color: SUB_COURSE_COLOR }} />
        <input
          value={settings.sub_course_name ?? ""}
          onChange={(e) => updateSettings({ sub_course_name: e.target.value })}
          placeholder={t`Sub course`}
          aria-label={t`Sub course name`}
          className="flex-1 min-w-0 h-6 px-1.5 -ml-1.5 rounded-md bg-transparent text-[12px] font-semibold text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-500 hover:bg-zinc-200/60 dark:hover:bg-white/5 focus:bg-white dark:focus:bg-zinc-900 focus:outline-none focus:ring-1 focus:ring-navi/40"
        />
        <button
          type="button"
          onClick={() => setAddToSub(!addToSub)}
          aria-pressed={addToSub}
          aria-label={t`Add stops to the sub course`}
          className={`group/tool relative h-6 w-6 rounded-md flex items-center justify-center transition-colors ${
            addToSub ? "bg-navi/10 text-navi" : "text-zinc-500 hover:text-zinc-900 hover:bg-zinc-200/60 dark:hover:text-zinc-100 dark:hover:bg-white/5"
          }`}
        >
          <MapPinPlus className="w-3.5 h-3.5" />
          <Tip label={addToSub ? t`New stops go to the sub course` : t`Add stops to the sub course`} />
        </button>
        <button
          type="button"
          onClick={() => (setWaypoints((prev) => removeSubCourse(prev)), setAddToSub(false))}
          aria-label={t`Remove sub course`}
          className="group/tool relative h-6 w-6 rounded-md flex items-center justify-center text-zinc-500 hover:text-red-500 hover:bg-red-500/10 transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" />
          <Tip label={t`Remove sub course`} />
        </button>
      </div>
      <p className="px-1 pb-1 text-[11px] text-zinc-500">
        <Trans>From {branch?.name ?? "?"}</Trans>
      </p>

      {anchorRow(first, true, middle.length === 0 && !last)}
      <Droppable droppableId={SUB_LIST}>
        {(provided) => (
          <div className="flex flex-col" {...provided.droppableProps} ref={provided.innerRef}>
            {middle.map((wp, i) => (
              <Draggable key={wp.id} draggableId={wp.id} index={i} isDragDisabled={isListEditMode}>
                {(drag, snapshot) => (
                  <div
                    ref={drag.innerRef}
                    {...drag.draggableProps}
                    {...drag.dragHandleProps}
                    className={`rounded-lg ${snapshot.isDragging ? "z-50 bg-white dark:bg-zinc-900 shadow-lg ring-1 ring-black/5 dark:ring-white/10" : ""}`}
                    style={drag.draggableProps.style}
                  >
                    <WaypointItem
                      wp={wp}
                      index={waypoints.indexOf(wp)}
                      isListEditMode={isListEditMode}
                      isFirst={false}
                      isLast={i === middle.length - 1 && !last}
                      onEdit={() => setActiveWaypointId(wp.id)}
                      onDelete={() => setWaypoints((prev) => prev.filter((w) => w.id !== wp.id))}
                    />
                  </div>
                )}
              </Draggable>
            ))}
            {provided.placeholder}
          </div>
        )}
      </Droppable>
      {last && anchorRow(last, false, true)}
      {middle.length === 0 && (
        <p className="px-1 py-2 text-[11px] text-zinc-500">
          <Trans>Turn on the pin button above and click the map to add the sub course's stops.</Trans>
        </p>
      )}

      <label className="mt-2 px-1 flex items-center gap-2 text-[12px] text-zinc-700 dark:text-zinc-300">
        <span className="flex-1">
          <Trans>Ends at {dest?.name ?? "?"}</Trans>
        </span>
        <Switch checked={!!end} label={t`End at the main destination`} onChange={(on) => setWaypoints((prev) => setEndsAtDestination(prev, on))} />
      </label>
    </div>
  );
}

/** The sub course after a drag inside SUB_LIST: its middle stops reordered, the anchors kept at the ends. */
export function reorderSub<T extends { id: string; course?: "sub"; branchOf?: string; lat: number; lng: number }>(all: T[], from: number, to: number): T[] {
  const sub = all.filter(inSubCourse);
  const end = subEnd(all) ? sub[sub.length - 1] : undefined;
  const middle = sub.filter((w) => w !== sub[0] && w !== end);
  const [moved] = middle.splice(from, 1);
  middle.splice(to, 0, moved);
  return [...mainStops(all), sub[0], ...middle, ...(end ? [end] : [])];
}
