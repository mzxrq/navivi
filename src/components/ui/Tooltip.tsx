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

  const arrowClasses = {
    top: "top-full left-1/2 -translate-x-1/2 border-t-zinc-800 dark:border-t-white",
    bottom:
      "bottom-full left-1/2 -translate-x-1/2 border-b-zinc-800 dark:border-b-white",
    left: "left-full top-1/2 -translate-y-1/2 border-l-zinc-800 dark:border-l-white",
    right:
      "right-full top-1/2 -translate-y-1/2 border-r-zinc-800 dark:border-r-white",
  };

  return (
    <div className="group relative inline-flex items-center justify-center">
      {children}
      <div
        className={`absolute z-50 invisible opacity-0 group-hover:visible group-hover:opacity-100 transition-all duration-200 pointer-events-none ${positionClasses[position]} ${className}`}
      >
        <div className="bg-zinc-800 dark:bg-white text-white dark:text-zinc-900 text-[10px] font-bold px-3 py-2 rounded-lg shadow-xl max-w-55 w-max whitespace-normal text-center leading-tight">
          {content}
        </div>
        <div
          className={`absolute w-0 h-0 border-[5px] border-transparent ${arrowClasses[position]}`}
        />
      </div>
    </div>
  );
}
