import { ReactNode, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "./icons";

interface ComboBoxProps {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  label: string;
  // Anything typed is accepted (if `validate` allows it); otherwise only a listed option can be chosen.
  allowCustom?: boolean;
  validate?: (value: string) => boolean;
  inputMode?: "numeric" | "text";
  previewFont?: boolean;
  className?: string;
  // Heading of an option's group; options must come sorted by group. A heading is shown where it changes.
  groupOf?: (option: string) => string | undefined;
  // Something shown at the right of a group's heading (a link); clicking it closes the list.
  groupAction?: (group: string) => ReactNode;
  // Group headings always listed, in this order, even with no options under them.
  groups?: string[];
}

const field =
  "h-8 w-full min-w-0 pl-2.5 pr-8 rounded-lg bg-white dark:bg-zinc-950/40 border border-zinc-200 dark:border-white/10 text-[13px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition";

// Under the field when there is room, above it when there is more room there, never past the window edge.
function listPlacement(rect: DOMRect): React.CSSProperties {
  const below = window.innerHeight - rect.bottom - 12;
  const above = rect.top - 12;
  if (below < 180 && above > below) return { bottom: window.innerHeight - rect.top + 4, maxHeight: Math.min(224, above) };
  return { top: rect.bottom + 4, maxHeight: Math.min(224, Math.max(96, below)) };
}

// A text field with a list under it: type to filter, pick with the mouse or Up/Down and Enter.
export function ComboBox({ value, onChange, options, label, allowCustom, validate, inputMode = "text", previewFont, className = "w-48", groupOf, groupAction, groups }: ComboBoxProps) {
  const id = useId();
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [draft, setDraft] = useState(value);
  const [open, setOpen] = useState(false);
  const [filtering, setFiltering] = useState(false);
  const [active, setActive] = useState(-1);
  const [rect, setRect] = useState<DOMRect | null>(null);

  useEffect(() => {
    if (!open) setDraft(value);
  }, [value, open]);

  const shown = filtering && draft.trim() ? options.filter((o) => o.toLowerCase().includes(draft.trim().toLowerCase())) : options;

  const place = () => {
    if (wrapRef.current) setRect(wrapRef.current.getBoundingClientRect());
  };

  useLayoutEffect(() => {
    if (!open) return;
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!wrapRef.current?.contains(target) && !listRef.current?.contains(target)) finish(draft);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  });

  useEffect(() => {
    if (open && active >= 0) listRef.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [open, active, !!rect]);

  const accepts = (text: string) => (allowCustom ? text.trim() !== "" && (validate ? validate(text.trim()) : true) : options.some((o) => o.toLowerCase() === text.trim().toLowerCase()));

  // Close the list and keep the text if it is acceptable, otherwise go back to the saved value.
  const finish = (text: string) => {
    setOpen(false);
    setFiltering(false);
    setActive(-1);
    if (accepts(text)) {
      const exact = options.find((o) => o.toLowerCase() === text.trim().toLowerCase());
      const next = exact ?? text.trim();
      setDraft(next);
      if (next !== value) onChange(next);
    } else {
      setDraft(value);
    }
  };

  const choose = (option: string) => {
    setOpen(false);
    setFiltering(false);
    setActive(-1);
    setDraft(option);
    if (option !== value) onChange(option);
    inputRef.current?.focus();
  };

  const openList = () => {
    if (open) return;
    setOpen(true);
    setActive(Math.max(0, options.findIndex((o) => o === value)));
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) return openList();
      if (shown.length === 0) return;
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((a) => (a + step + shown.length) % shown.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (open && active >= 0 && shown[active]) choose(shown[active]);
      else finish(draft);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
      setFiltering(false);
      setDraft(value);
    }
  };

  return (
    <div ref={wrapRef} className={`relative ${className}`}>
      <input
        ref={inputRef}
        role="combobox"
        aria-label={label}
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-activedescendant={open && active >= 0 ? `${id}-${active}` : undefined}
        aria-autocomplete="list"
        inputMode={inputMode}
        spellCheck={false}
        value={draft}
        onFocus={(e) => {
          e.currentTarget.select();
          openList();
        }}
        onChange={(e) => {
          setDraft(e.target.value);
          setFiltering(true);
          setActive(0);
          if (!open) setOpen(true);
        }}
        onKeyDown={onKeyDown}
        onBlur={() => finish(draft)}
        className={field}
        style={previewFont ? { fontFamily: `"${draft}", sans-serif` } : undefined}
      />
      <button
        type="button"
        tabIndex={-1}
        aria-label={label}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => (open ? finish(draft) : (inputRef.current?.focus(), openList()))}
        className="absolute right-0 top-0 h-8 w-8 flex items-center justify-center text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition-colors"
      >
        <ChevronDown className={`w-3.5 h-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open &&
        rect &&
        createPortal(
          <ul
            ref={listRef}
            id={`${id}-list`}
            role="listbox"
            style={{ position: "fixed", left: rect.left, width: rect.width, zIndex: 100000, ...listPlacement(rect) }}
            className="overflow-y-auto custom-scrollbar rounded-xl border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900 shadow-xl p-1"
          >
            {(() => {
              const heading = (group: string) => (
                <li key={`group-${group}`} role="presentation" className="px-2.5 pt-2 pb-1 flex items-center gap-2 text-[11px] font-medium text-zinc-400 first:pt-1">
                  <span className="flex-1 truncate">{group}</span>
                  {groupAction && (
                    <span onMouseDown={(e) => e.preventDefault()} onClick={() => finish(draft)}>
                      {groupAction(group)}
                    </span>
                  )}
                </li>
              );
              const row = (option: string, i: number) => (
                <li
                  key={option}
                  id={`${id}-${i}`}
                  role="option"
                  aria-selected={option === value}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choose(option)}
                  onMouseEnter={() => setActive(i)}
                  style={previewFont ? { fontFamily: `"${option}", sans-serif` } : undefined}
                  className={`h-8 px-2.5 rounded-lg flex items-center gap-2 text-[13px] cursor-pointer text-zinc-800 dark:text-zinc-100 ${
                    i === active ? "bg-zinc-100 dark:bg-white/10" : ""
                  }`}
                >
                  <span className="flex-1 truncate">{option}</span>
                  {option === value && <Check className="w-3.5 h-3.5 text-navi shrink-0" />}
                </li>
              );
              const indexed = shown.map((option, i) => ({ option, i, group: groupOf?.(option) }));
              // Headings of `groups` stay even when empty (their action is still there), unless filtering.
              const order = [...(filtering ? [] : (groups ?? [])), ...indexed.map((x) => x.group)].filter(
                (g, k, all): g is string => !!g && all.indexOf(g) === k,
              );
              const ungrouped = indexed.filter((x) => !x.group);
              if (!shown.length && !order.length)
                return <li className="px-2.5 h-8 flex items-center text-[12px] text-zinc-400">{allowCustom ? "" : "—"}</li>;
              return [
                ...ungrouped.map((x) => row(x.option, x.i)),
                ...order.flatMap((g) => [heading(g), ...indexed.filter((x) => x.group === g).map((x) => row(x.option, x.i))]),
              ];
            })()}
          </ul>,
          document.body,
        )}
    </div>
  );
}
