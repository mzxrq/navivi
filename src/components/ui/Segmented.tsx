import { ReactNode } from "react";

interface SegmentedProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  options: { id: T; label: string; icon?: ReactNode }[];
}

export function Segmented<T extends string>({ value, onChange, options }: SegmentedProps<T>) {
  return (
    <div className="flex p-0.5 rounded-lg bg-zinc-100 dark:bg-white/5">
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          aria-pressed={value === option.id}
          onClick={() => onChange(option.id)}
          className={`flex-1 flex items-center justify-center gap-1.5 h-8 rounded-md text-[13px] font-medium transition-colors ${
            value === option.id
              ? "bg-white dark:bg-zinc-800 text-navi shadow-sm"
              : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
          }`}
        >
          {option.icon}
          {option.label}
        </button>
      ))}
    </div>
  );
}
