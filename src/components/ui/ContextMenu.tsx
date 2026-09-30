import { t } from "@lingui/core/macro";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useWorkspace } from "../../hooks/useWorkspace";
import {
  Check,
  ChevronRight,
  ClipboardPaste,
  Copy,
  CopyPlus,
  Edit3,
  Eye,
  EyeOff,
  Film,
  Folder,
  FolderOpen,
  LinkIcon,
  Lock,
  Plus,
  Scissors,
  Settings2,
  Trash2,
  UnlinkIcon,
  Unlock,
  Volume2,
  VolumeX,
} from "../ui/icons";
import { MenuEntry, MenuItem, separator, tidy } from "./menuItems";

export interface ContextMenuState {
  x: number;
  y: number;
  type:
    | "items"
    | "track-header"
    | "timeline-clip"
    | "empty-track"
    | "project-card"
    | "mediapool-item";
  targetId?: string;
  data?: any;
  items?: MenuEntry[];
}

const PANEL_ATTR = "data-context-menu";

export function ContextMenu() {
  const [menu, setMenu] = useState<ContextMenuState | null>(null);
  const { timeline, setTimeline } = useWorkspace();
  const openedThisEventRef = useRef(false);

  useEffect(() => {
    const close = () => setMenu(null);

    const handleOpenMenu = (e: CustomEvent<ContextMenuState>) => {
      openedThisEventRef.current = true;
      setTimeout(() => (openedThisEventRef.current = false), 0);
      setMenu({ ...e.detail });
    };

    const handleNativeContextMenu = (e: MouseEvent) => {
      e.preventDefault();
      if (openedThisEventRef.current) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest(`[${PANEL_ATTR}]`)) return;
      const items = textMenuFor(target);
      setMenu(items ? { x: e.clientX, y: e.clientY, type: "items", items } : null);
    };

    const handleMouseDown = (e: MouseEvent) => {
      if (!(e.target as Element).closest?.(`[${PANEL_ATTR}]`)) close();
    };
    const handleScroll = (e: Event) => {
      if (!(e.target as Element)?.closest?.(`[${PANEL_ATTR}]`)) close();
    };

    window.addEventListener("contextmenu", handleNativeContextMenu);
    window.addEventListener("open-context-menu" as any, handleOpenMenu);
    window.addEventListener("mousedown", handleMouseDown);
    window.addEventListener("close-context-menus", close);
    window.addEventListener("resize", close);
    window.addEventListener("blur", close);
    window.addEventListener("scroll", handleScroll, { capture: true });

    return () => {
      window.removeEventListener("contextmenu", handleNativeContextMenu);
      window.removeEventListener("open-context-menu" as any, handleOpenMenu);
      window.removeEventListener("mousedown", handleMouseDown);
      window.removeEventListener("close-context-menus", close);
      window.removeEventListener("resize", close);
      window.removeEventListener("blur", close);
      window.removeEventListener("scroll", handleScroll, { capture: true });
    };
  }, []);

  useEffect(() => {
    if (!menu) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if ((document.activeElement as Element | null)?.closest?.(`[${PANEL_ATTR}]`)) return;
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopImmediatePropagation();
        setMenu(null);
      } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        e.stopImmediatePropagation();
        const panels = document.querySelectorAll<HTMLElement>(`[${PANEL_ATTR}]`);
        const items = panels[panels.length - 1]?.querySelectorAll<HTMLElement>(
          ":scope > [role^='menuitem']:not([disabled])",
        );
        items?.[e.key === "ArrowDown" ? 0 : items.length - 1]?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [menu]);

  if (!menu) return null;

  const close = () => setMenu(null);
  const items = tidy(menu.items ?? legacyItems(menu, timeline, setTimeline));
  if (items.length === 0) return null;

  return (
    <MenuPanel
      key={`${menu.x}-${menu.y}`}
      entries={items}
      anchor={{ x: menu.x, y: menu.y }}
      onClose={close}
      autoFocus
    />
  );
}


type Anchor = { x: number; y: number } | { rect: DOMRect };

function MenuPanel({
  entries,
  anchor,
  onClose,
  onBack,
  autoFocus,
}: {
  entries: MenuEntry[];
  anchor: Anchor;
  onClose: () => void;
  onBack?: () => void;
  autoFocus?: boolean;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const [openSub, setOpenSub] = useState<{ index: number; rect: DOMRect; focus: boolean } | null>(
    null,
  );
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useLayoutEffect(() => {
    const el = panelRef.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const margin = 8;
    let left: number;
    let top: number;
    if ("rect" in anchor) {
      left = anchor.rect.right + 2;
      if (left + width > vw - margin) left = anchor.rect.left - width - 2;
      top = anchor.rect.top - 5;
    } else {
      left = anchor.x;
      top = anchor.y;
      if (left + width > vw - margin) left = anchor.x - width;
      if (top + height > vh - margin) top = anchor.y - height;
    }
    left = Math.max(margin, Math.min(left, vw - width - margin));
    top = Math.max(margin, Math.min(top, vh - height - margin));
    setPos({ left, top });
  }, [anchor]);

  useEffect(() => {
    if (!autoFocus || !pos) return;
    panelRef.current?.focus({ preventScroll: true });
  }, [autoFocus, pos]);

  useEffect(() => () => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
  }, []);

  const itemButtons = () =>
    Array.from(
      panelRef.current?.querySelectorAll<HTMLButtonElement>(":scope > [role^='menuitem']:not([disabled])") ?? [],
    );

  const moveFocus = (delta: number | "first" | "last") => {
    const buttons = itemButtons();
    if (!buttons.length) return;
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
    let next: number;
    if (delta === "first") next = 0;
    else if (delta === "last") next = buttons.length - 1;
    else next = current === -1 ? (delta > 0 ? 0 : buttons.length - 1) : (current + delta + buttons.length) % buttons.length;
    buttons[next].focus();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const stop = () => {
      e.preventDefault();
      e.stopPropagation();
    };
    switch (e.key) {
      case "ArrowDown":
        stop();
        moveFocus(1);
        break;
      case "ArrowUp":
        stop();
        moveFocus(-1);
        break;
      case "Home":
        stop();
        moveFocus("first");
        break;
      case "End":
        stop();
        moveFocus("last");
        break;
      case "ArrowRight": {
        const el = document.activeElement as HTMLElement | null;
        const index = Number(el?.dataset.index);
        const entry = entries[index] as MenuItem | undefined;
        if (el && entry?.submenu) {
          stop();
          setOpenSub({ index, rect: el.getBoundingClientRect(), focus: true });
        }
        break;
      }
      case "ArrowLeft":
        if (onBack) {
          stop();
          onBack();
        }
        break;
      case "Escape":
        stop();
        (onBack ?? onClose)();
        break;
      case "Tab":
        stop();
        break;
    }
  };

  const activate = (entry: MenuItem, index: number, el: HTMLElement) => {
    if (entry.disabled) return;
    if (entry.submenu) {
      setOpenSub({ index, rect: el.getBoundingClientRect(), focus: true });
      return;
    }
    onClose();
    entry.onSelect?.();
  };

  const subEntry = openSub ? (entries[openSub.index] as MenuItem) : null;

  return createPortal(
    <>
      <div
        ref={panelRef}
        {...{ [PANEL_ATTR]: "" }}
        role="menu"
        tabIndex={-1}
        onKeyDown={onKeyDown}
        onMouseDown={(e) => e.preventDefault()}
        onContextMenu={(e) => e.preventDefault()}
        style={pos ? { left: pos.left, top: pos.top } : { left: -9999, top: -9999 }}
        className={`fixed z-100000 min-w-52 max-w-80 max-h-[calc(100vh-1rem)] overflow-y-auto p-1 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-lg outline-none select-none ${
          pos ? "transition-none animate-in fade-in zoom-in-95 duration-100" : "invisible"
        }`}
      >
        {entries.map((entry, index) => {
          if (entry.type === "separator") {
            return <div key={index} role="separator" className="h-px my-1 mx-1.5 bg-zinc-100 dark:bg-white/5" />;
          }
          if (entry.type === "label") {
            return (
              <div
                key={index}
                className="px-2.5 pt-1.5 pb-1 text-[11px] font-medium text-zinc-400 dark:text-zinc-500 truncate"
                title={entry.label}
              >
                {entry.label}
              </div>
            );
          }
          const Icon = entry.icon;
          const isSubOpen = openSub?.index === index;
          return (
            <button
              key={index}
              type="button"
              data-index={index}
              role={entry.checked !== undefined ? "menuitemcheckbox" : "menuitem"}
              aria-checked={entry.checked}
              aria-haspopup={entry.submenu ? "menu" : undefined}
              aria-expanded={entry.submenu ? isSubOpen : undefined}
              disabled={entry.disabled}
              onClick={(e) => activate(entry, index, e.currentTarget)}
              onMouseEnter={(e) => {
                const el = e.currentTarget;
                el.focus({ preventScroll: true });
                if (hoverTimer.current) clearTimeout(hoverTimer.current);
                if (entry.submenu && !entry.disabled) {
                  hoverTimer.current = setTimeout(
                    () => setOpenSub({ index, rect: el.getBoundingClientRect(), focus: false }),
                    120,
                  );
                } else if (openSub) {
                  hoverTimer.current = setTimeout(() => setOpenSub(null), 150);
                }
              }}
              className={`group w-full flex items-center gap-2.5 h-8 px-2.5 rounded-lg text-[13px] text-left outline-none transition-colors disabled:opacity-40 disabled:pointer-events-none ${
                entry.danger
                  ? "text-red-600 dark:text-red-400 focus:bg-red-500/10"
                  : `text-zinc-700 dark:text-zinc-200 focus:bg-zinc-100 dark:focus:bg-white/5 ${isSubOpen ? "bg-zinc-100 dark:bg-white/5" : ""}`
              }`}
            >
              <span className="w-4 h-4 shrink-0 flex items-center justify-center">
                {entry.checked ? (
                  <Check className="w-3.5 h-3.5 text-navi" />
                ) : Icon ? (
                  <Icon
                    className={`w-3.5 h-3.5 ${entry.danger ? "" : "text-zinc-400 dark:text-zinc-500 group-focus:text-zinc-600 dark:group-focus:text-zinc-300"}`}
                  />
                ) : null}
              </span>
              <span className={`flex-1 truncate ${entry.checked ? "font-medium" : ""}`}>{entry.label}</span>
              {entry.kbd && (
                <span className="ml-4 text-[11px] text-zinc-400 dark:text-zinc-500">{entry.kbd}</span>
              )}
              {entry.submenu && <ChevronRight className="w-3.5 h-3.5 -mr-1 text-zinc-400" />}
            </button>
          );
        })}
      </div>

      {openSub && subEntry?.submenu && (
        <MenuPanel
          key={openSub.index}
          entries={tidy(subEntry.submenu)}
          anchor={{ rect: openSub.rect }}
          onClose={onClose}
          autoFocus={openSub.focus}
          onBack={() => {
            const index = openSub.index;
            setOpenSub(null);
            panelRef.current
              ?.querySelector<HTMLButtonElement>(`[data-index='${index}']`)
              ?.focus();
          }}
        />
      )}
    </>,
    document.body,
  );
}


function textMenuFor(target: HTMLElement | null): MenuEntry[] | null {
  const field = target?.closest<HTMLElement>("input, textarea, [contenteditable='true'], [contenteditable='']");
  const input = field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement ? field : null;
  const textInputTypes = ["text", "search", "url", "email", "tel", "password", "number", ""];
  if (input instanceof HTMLInputElement && !textInputTypes.includes(input.type)) return null;

  if (field) {
    const editable = input ? !input.readOnly && !input.disabled : true;
    const isPassword = input?.type === "password";
    let hasSelection = true;
    try {
      hasSelection = input
        ? input.selectionStart !== input.selectionEnd
        : !window.getSelection()?.isCollapsed;
    } catch {
    }
    const run = (command: string) => {
      field.focus();
      document.execCommand(command);
    };
    return [
      {
        label: t`Cut`,
        icon: Scissors,
        kbd: "Ctrl+X",
        disabled: !editable || !hasSelection || isPassword,
        onSelect: () => run("cut"),
      },
      {
        label: t`Copy`,
        icon: Copy,
        kbd: "Ctrl+C",
        disabled: !hasSelection || isPassword,
        onSelect: () => run("copy"),
      },
      {
        label: t`Paste`,
        icon: ClipboardPaste,
        kbd: "Ctrl+V",
        disabled: !editable,
        onSelect: async () => {
          try {
            const text = await navigator.clipboard.readText();
            field.focus();
            document.execCommand("insertText", false, text);
          } catch (err) {
            console.warn("Clipboard read failed:", err);
          }
        },
      },
      separator,
      {
        label: t`Select all`,
        kbd: "Ctrl+A",
        onSelect: () => {
          field.focus();
          if (input) input.select();
          else document.execCommand("selectAll");
        },
      },
    ];
  }

  const selection = window.getSelection();
  if (selection && !selection.isCollapsed && selection.toString().trim()) {
    const text = selection.toString();
    return [
      {
        label: t`Copy`,
        icon: Copy,
        kbd: "Ctrl+C",
        onSelect: () => void navigator.clipboard.writeText(text),
      },
    ];
  }
  return null;
}


function legacyItems(
  menu: ContextMenuState,
  timeline: ReturnType<typeof useWorkspace>["timeline"],
  setTimeline: ReturnType<typeof useWorkspace>["setTimeline"],
): MenuEntry[] {
  const data = menu.data ?? {};
  const call = (fn?: () => void) => () => fn?.();

  const addTrack = (type: "video" | "audio" | "subtitle") => {
    const existingTracksOfType = timeline.tracks.filter((track) => track.type === type);
    const trackCount = existingTracksOfType.length + 1;
    const newOrderIndex =
      existingTracksOfType.length > 0
        ? Math.max(...existingTracksOfType.map((track) => track.orderIndex)) + 1
        : type === "subtitle"
          ? 0
          : type === "video"
            ? 100
            : 200;
    const trackPrefix = type === "video" ? "VISUAL" : type.toUpperCase();

    setTimeline({
      ...timeline,
      tracks: [
        ...timeline.tracks,
        {
          id: crypto.randomUUID(),
          name: `${trackPrefix} ${trackCount}`,
          type,
          orderIndex: newOrderIndex,
          isHidden: false,
          isMuted: false,
          isLocked: false,
        },
      ],
    });
  };

  const deleteTrack = (trackId?: string) => {
    if (!trackId) return;
    const trackToDelete = timeline.tracks.find((track) => track.id === trackId);
    if (trackToDelete?.type === "video") {
      const visualTracks = timeline.tracks.filter((track) => track.type === "video");
      if (visualTracks.length <= 1) return;
    }
    setTimeline({
      ...timeline,
      tracks: timeline.tracks.filter((track) => track.id !== trackId),
      clips: timeline.clips.filter((clip) => clip.trackId !== trackId),
    });
  };

  const addTrackItems: MenuEntry[] = [
    { label: t`add-subtitle-track`, icon: Plus, onSelect: () => addTrack("subtitle") },
    { label: t`add-visual-track`, icon: Plus, onSelect: () => addTrack("video") },
    { label: t`add-audio-track`, icon: Plus, onSelect: () => addTrack("audio") },
  ];

  switch (menu.type) {
    case "track-header":
      return [
        {
          label: t`Rename track`,
          icon: Edit3,
          onSelect: () =>
            window.dispatchEvent(
              new CustomEvent("start-rename-track", { detail: { trackId: menu.targetId } }),
            ),
        },
        separator,
        data.isAudioTrack
          ? {
              label: data.isMuted ? t`unmute-track` : t`mute-track`,
              icon: data.isMuted ? Volume2 : VolumeX,
              onSelect: call(data.onToggleMute),
            }
          : {
              label: data.isHidden ? t`Show Track` : t`Hide Track`,
              icon: data.isHidden ? Eye : EyeOff,
              onSelect: call(data.onToggleHide),
            },
        {
          label: data.isLocked ? t`unlock-track` : t`lock-track`,
          icon: data.isLocked ? Unlock : Lock,
          onSelect: call(data.onToggleLock),
        },
        separator,
        ...addTrackItems,
        separator,
        { label: t`delete-track`, icon: Trash2, danger: true, onSelect: () => deleteTrack(menu.targetId) },
      ];

    case "timeline-clip":
      return [
        {
          label: t`duplicate-clip`,
          icon: CopyPlus,
          onSelect: () => {
            const targetClip = timeline.clips.find((clip) => clip.id === menu.targetId);
            if (!targetClip) return;
            setTimeline({
              ...timeline,
              clips: [
                ...timeline.clips,
                {
                  ...targetClip,
                  id: crypto.randomUUID(),
                  startTime: targetClip.startTime + targetClip.duration,
                },
              ],
            });
          },
        },
        separator,
        {
          label: t`link-clips`,
          icon: LinkIcon,
          onSelect: () => window.dispatchEvent(new CustomEvent("trigger-link-clips")),
        },
        {
          label: t`unlink-clips`,
          icon: UnlinkIcon,
          onSelect: () => window.dispatchEvent(new CustomEvent("trigger-unlink-clips")),
        },
        separator,
        {
          label: t`delete-clip`,
          icon: Trash2,
          danger: true,
          onSelect: () =>
            setTimeline({
              ...timeline,
              clips: timeline.clips.filter((clip) => clip.id !== menu.targetId),
            }),
        },
      ];

    case "empty-track":
      return [
        ...addTrackItems,
        separator,
        menu.targetId
          ? {
              label: t`delete-empty-track`,
              icon: Trash2,
              danger: true,
              onSelect: () => deleteTrack(menu.targetId),
            }
          : separator,
      ];

    case "project-card":
      return [
        { label: t`open-project`, icon: FolderOpen, onSelect: call(data.onOpen) },
        separator,
        { label: t`rename`, icon: Edit3, onSelect: call(data.onRename) },
        { label: t`duplicate`, icon: Copy, onSelect: call(data.onDuplicate) },
        { label: t`Quick Render`, icon: Film, onSelect: call(data.onQuickRender) },
        { label: t`Reveal in File Explorer`, icon: Folder, onSelect: call(data.onReveal) },
        separator,
        { label: t`remove-from-list`, icon: Trash2, danger: true, onSelect: call(data.onRemove) },
      ];

    case "mediapool-item":
      return [
        { label: t`duplicate`, icon: Copy, onSelect: call(data.onDuplicate) },
        { label: t`Quick Render`, icon: Film, onSelect: call(data.onQuickRender) },
        { label: t`Reveal in File Explorer`, icon: Folder, onSelect: call(data.onReveal) },
        { label: t`properties`, icon: Settings2, onSelect: call(data.onProperties) },
        separator,
        {
          label: t`remove-from-media-pool`,
          icon: Trash2,
          danger: true,
          onSelect: call(data.onRemove),
        },
      ];

    default:
      return [];
  }
}
