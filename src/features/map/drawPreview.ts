import { useSyncExternalStore } from "react";
import type { Waypoint } from "../../types";

export type DrawPreview = { wpId: string; patch: Pick<Waypoint, "customRoute" | "customRouteCurve" | "drawStyle"> } | null;

// What a drawn path would look like if the anchor or handle being dragged were dropped now. Kept outside the workspace so
// a drag redraws only the preview, not the whole map or the saved project.
let current: DrawPreview = null;
let frame = 0;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

export function setDrawPreview(next: DrawPreview) {
  current = next;
  if (next === null) {
    cancelAnimationFrame(frame);
    frame = 0;
    notify();
    return;
  }
  if (!frame) {
    frame = requestAnimationFrame(() => {
      frame = 0;
      notify();
    });
  }
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

export const useDrawPreview = () => useSyncExternalStore(subscribe, () => current);
export const usePreviewedWaypointId = () => useSyncExternalStore(subscribe, () => current?.wpId ?? null);
