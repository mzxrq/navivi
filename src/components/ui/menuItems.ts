import type { ComponentType } from "react";

export interface MenuItem {
  type?: "item";
  label: string;
  icon?: ComponentType<{ className?: string }>;
  onSelect?: () => void;
  disabled?: boolean;
  danger?: boolean;
  checked?: boolean;
  kbd?: string;
  submenu?: MenuEntry[];
}

export type MenuEntry =
  | MenuItem
  | { type: "separator" }
  | { type: "label"; label: string };

export const separator: MenuEntry = { type: "separator" };

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
