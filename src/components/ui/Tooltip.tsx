import { ReactNode } from "react";

interface TooltipProps {
  children: ReactNode;
  content: string | ReactNode;
  position?: "top" | "bottom" | "left" | "right";
  className?: string;
}

export function Tooltip({
  children,
  content,
  position = "top",
  className = "",
}: TooltipProps) {
  const positionClasses = {
    top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
    bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
    left: "right-full top-1/2 -translate-y-1/2 mr-2",
    right: "left-full top-1/2 -translate-y-1/2 ml-2",
  };

  return (
    <span className="group/tooltip relative inline-flex items-center justify-center">
      {children}
      <span
        role="tooltip"
        className={`pointer-events-none absolute z-50 w-max max-w-60 px-2 py-1.5 rounded-md bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 text-[11px] font-medium leading-snug text-left whitespace-normal shadow-md opacity-0 transition-opacity duration-150 group-hover/tooltip:opacity-100 group-hover/tooltip:delay-300 group-focus-within/tooltip:opacity-100 ${positionClasses[position]} ${className}`}
      >
        {content}
      </span>
    </span>
  );
}
