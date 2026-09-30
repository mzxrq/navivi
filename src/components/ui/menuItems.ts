import type { ComponentType } from "react";

/** One row in a context menu. */
export interface MenuItem {
  type?: "item";
  label: string;
  icon?: ComponentType<{ className?: string }>;
  onSelect?: () => void;
  disabled?: boolean;
  /** Red, for destructive actions. */
  danger?: boolean;
  /** Shows a check mark (radio/toggle state). */
  checked?: boolean;
  /** Shortcut hint on the right, e.g. "Ctrl+C". */
  kbd?: string;
  submenu?: MenuEntry[];
}

export type MenuEntry =
  | MenuItem
  | { type: "separator" }
  /** Small grey heading, e.g. the name of the stop the menu is for. */
  | { type: "label"; label: string };

export const separator: MenuEntry = { type: "separator" };

/**
 * Opens the global context menu (see ContextMenu.tsx) at the pointer.
 * Call it from an onContextMenu handler; it stops the event so parents and the
 * text-field fallback don't open a menu of their own.
 */
export function openContextMenu(
  event: { clientX: number; clientY: number; preventDefault?: () => void; stopPropagation?: () => void },
  items: (MenuEntry | false | null | undefined)[],
) {
  event.preventDefault?.();
  event.stopPropagation?.();
  window.dispatchEvent(
    new CustomEvent("open-context-menu", {
      detail: {
        x: event.clientX,
        y: event.clientY,
        type: "items",
        items: tidy(items.filter(Boolean) as MenuEntry[]),
      },
    }),
  );
}

/** Drops leading/trailing/doubled separators left behind by conditional items. */
export function tidy(entries: MenuEntry[]): MenuEntry[] {
  const out: MenuEntry[] = [];
  for (const entry of entries) {
    if (entry.type === "separator" && (out.length === 0 || out[out.length - 1].type === "separator")) {
      continue;
    }
    out.push(entry);
  }
  while (out.length && out[out.length - 1].type === "separator") out.pop();
  return out;
}
