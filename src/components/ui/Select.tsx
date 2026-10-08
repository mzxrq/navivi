import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "./icons";
import { listPlacement } from "./ComboBox";

export interface SelectOption<T extends string> {
  value: T;
  label: string;
}

// A closed list of choices with the app's own look (the browser's <select> opens a Windows-style menu).
// Up/Down move, Enter or Space picks, Escape closes; typing a letter jumps to the first label that starts with it.
export function Select<T extends string>({
  value,
  onChange,
  options,
  label,
  className = "w-full",
  disabled,
  placeholder,
}: {
  value: T;
  onChange: (value: T) => void;
  options: SelectOption<T>[];
  label: string;
  className?: string;
  disabled?: boolean;
  placeholder?: string;
}) {
  const id = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const shown = options.find((o) => o.value === value);

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => buttonRef.current && setRect(buttonRef.current.getBoundingClientRect());
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
      if (!buttonRef.current?.contains(target) && !listRef.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  useEffect(() => {
    if (open) listRef.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [open, active, !!rect]);

  const openList = () => {
    setActive(Math.max(0, options.findIndex((o) => o.value === value)));
    setOpen(true);
  };

  const choose = (next: T) => {
    setOpen(false);
    if (next !== value) onChange(next);
    buttonRef.current?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) return openList();
      setActive((a) => (a + (e.key === "ArrowDown" ? 1 : -1) + options.length) % options.length);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (!open) openList();
      else choose(options[active].value);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
    } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
      const at = options.findIndex((o) => o.label.toLowerCase().startsWith(e.key.toLowerCase()));
      if (at >= 0) {
        if (!open) openList();
        setActive(at);
      }
    }
  };

  return (
    <div className={className}>
      <button
        ref={buttonRef}
        type="button"
        role="combobox"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? `${id}-list` : undefined}
        onClick={() => (open ? setOpen(false) : openList())}
        onKeyDown={onKeyDown}
        disabled={disabled || options.length === 0}
        className="h-8 w-full min-w-0 pl-2.5 pr-2 rounded-lg flex items-center gap-2 text-left bg-white dark:bg-zinc-950/40 border border-zinc-200 dark:border-white/10 text-[12px] text-zinc-900 dark:text-zinc-100 hover:border-zinc-300 dark:hover:border-white/20 outline-none focus-visible:border-navi focus-visible:ring-2 focus-visible:ring-navi/20 transition disabled:opacity-50 disabled:pointer-events-none"
      >
        <span className={`flex-1 truncate ${shown || value ? "" : "text-zinc-400"}`}>{shown?.label ?? (value || placeholder)}</span>
        <ChevronDown className={`w-3.5 h-3.5 shrink-0 text-zinc-400 transition-transform ${open ? "rotate-180" : ""}`} />
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
            {options.map((option, i) => (
              <li
                key={option.value}
                role="option"
                aria-selected={option.value === value}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(option.value)}
                onMouseEnter={() => setActive(i)}
                className={`h-8 px-2.5 rounded-lg flex items-center gap-2 text-[12px] cursor-pointer text-zinc-800 dark:text-zinc-100 ${
                  i === active ? "bg-zinc-100 dark:bg-white/10" : ""
                }`}
              >
                <span className="flex-1 truncate">{option.label}</span>
                {option.value === value && <Check className="w-3.5 h-3.5 text-navi shrink-0" />}
              </li>
            ))}
          </ul>,
          document.body,
        )}
    </div>
  );
}
