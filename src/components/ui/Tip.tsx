interface TipProps {
  label: string;
  kbd?: string;
  align?: "center" | "start" | "end";
}

export function Tip({ label, kbd, align = "center" }: TipProps) {
  const position =
    align === "start" ? "left-0" : align === "end" ? "right-0" : "left-1/2 -translate-x-1/2";
  return (
    <span
      aria-hidden
      className={`pointer-events-none absolute top-full ${position} mt-2 z-50 flex items-center gap-1.5 h-6 px-2 rounded-md bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 text-[11px] font-medium whitespace-nowrap shadow-md opacity-0 -translate-y-0.5 transition duration-150 group-hover/tool:opacity-100 group-hover/tool:translate-y-0 group-hover/tool:delay-300 group-focus-visible/tool:opacity-100 group-focus-visible/tool:translate-y-0`}
    >
      {label}
      {kbd && (
        <kbd className="font-sans text-[10px] px-1 rounded bg-white/15 dark:bg-black/10">{kbd}</kbd>
      )}
    </span>
  );
}
