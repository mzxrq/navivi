import { ReactNode } from "react";

interface SegmentedProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  options: { id: T; label: string; icon?: ReactNode }[];
  // Smaller buttons for side panels; with `iconOnly` the label is only the tooltip and the accessible name.
  compact?: boolean;
  iconOnly?: boolean;
  className?: string;
}

export function Segmented<T extends string>({ value, onChange, options, compact, iconOnly, className = "" }: SegmentedProps<T>) {
  return (
    <div role="group" className={`flex p-0.5 rounded-lg bg-zinc-100 dark:bg-white/5 ${className}`}>
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          title={iconOnly ? option.label : undefined}
          aria-label={iconOnly ? option.label : undefined}
          aria-pressed={value === option.id}
          onClick={() => onChange(option.id)}
          className={`flex-1 flex items-center justify-center gap-1.5 rounded-md font-medium whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-navi ${
            compact ? "h-7 text-[12px]" : "h-8 text-[13px]"
          } ${iconOnly ? "min-w-0" : compact ? "px-2.5" : "px-3"} ${
            value === option.id
              ? "bg-white dark:bg-zinc-800 text-navi shadow-sm"
              : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
          }`}
        >
          {option.icon}
          {!iconOnly && <span>{option.label}</span>}
        </button>
      ))}
    </div>
  );
}
