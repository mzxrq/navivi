import { ReactNode, useEffect } from "react";
import { createPortal } from "react-dom";

interface DialogProps {
  title: ReactNode;
  subtitle?: ReactNode;
  children?: ReactNode;
  footer: ReactNode;
  onClose: () => void;
  width?: string;
}

export function Dialog({ title, subtitle, children, footer, onClose, width = "w-96" }: DialogProps) {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return createPortal(
    <div
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-x-0 top-10 bottom-0 z-99999 flex items-center justify-center p-4 bg-zinc-950/30 backdrop-blur-[2px] animate-in fade-in duration-150"
    >
      <div
        role="dialog"
        aria-modal="true"
        className={`${width} max-w-full max-h-full flex flex-col rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-2xl overflow-hidden animate-in zoom-in-95 duration-150`}
      >
        <div className="px-5 pt-5 pb-1">
          <h3 className="text-[14px] font-semibold text-zinc-900 dark:text-zinc-100">{title}</h3>
          {subtitle && (
            <p className="mt-0.5 text-[12px] text-zinc-500 dark:text-zinc-400 truncate">{subtitle}</p>
          )}
        </div>
        {children && <div className="px-5 pt-3 pb-1 overflow-y-auto">{children}</div>}
        <div className="flex items-center justify-end gap-2 px-5 pt-4 pb-5">{footer}</div>
      </div>
    </div>,
    document.body,
  );
}

export const dialogButton = {
  secondary:
    "h-8 px-3.5 rounded-lg text-[13px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors",
  primary:
    "h-8 px-3.5 rounded-lg text-[13px] font-semibold text-white bg-navi hover:brightness-110 transition disabled:opacity-40 disabled:pointer-events-none",
  danger:
    "h-8 px-3.5 rounded-lg text-[13px] font-semibold text-white bg-red-500 hover:bg-red-600 transition-colors",
};

export const dialogInput =
  "h-9 w-full px-3 rounded-lg bg-white dark:bg-zinc-950/40 border border-zinc-200 dark:border-white/10 text-[13px] text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition";
