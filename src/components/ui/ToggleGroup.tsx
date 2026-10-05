import type { ReactNode } from "react";

export interface Toggle {
  id: string;
  label: string;
  icon: ReactNode;
  pressed: boolean;
  onToggle: () => void;
}

// Independent on/off buttons (bold, italic, underline) in one rounded group; each is a square icon with a tooltip.
export function ToggleGroup({ items, className = "" }: { items: Toggle[]; className?: string }) {
  return (
    <div role="group" className={`inline-flex shrink-0 p-0.5 gap-0.5 rounded-lg bg-zinc-100 dark:bg-white/5 ${className}`}>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          title={item.label}
          aria-label={item.label}
          aria-pressed={item.pressed}
          onClick={item.onToggle}
          className={`h-7 w-8 rounded-md flex items-center justify-center transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-navi ${
            item.pressed
              ? "bg-white dark:bg-zinc-800 text-navi shadow-sm"
              : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-100"
          }`}
        >
          {item.icon}
        </button>
      ))}
    </div>
  );
}
