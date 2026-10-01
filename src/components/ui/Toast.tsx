import { useState, useEffect, useRef } from "react";
import { t } from "@lingui/core/macro";
import { CheckCircle2, AlertCircle, Info, AlertTriangle, X } from "../ui/icons";
import { useUI } from "../../hooks/useUI";

const toneStyles = {
  success: { icon: CheckCircle2, color: "text-emerald-500" },
  error: { icon: AlertCircle, color: "text-red-500" },
  warning: { icon: AlertTriangle, color: "text-amber-500" },
  info: { icon: Info, color: "text-navi" },
} as const;

const DURATION_MS = { error: 7000, default: 3700 };

function ToastItem({
  toast,
  hideToast,
}: {
  toast: any;
  hideToast: (id: string) => void;
}) {
  const [isExiting, setIsExiting] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tone =
    toneStyles[toast.type as keyof typeof toneStyles] ?? toneStyles.info;
  const Icon = tone.icon;

  const triggerExit = () => {
    setIsExiting(true);
    setTimeout(() => hideToast(toast.id), 200);
  };

  const startTimer = () => {
    stopTimer();
    timer.current = setTimeout(
      triggerExit,
      toast.type === "error" ? DURATION_MS.error : DURATION_MS.default,
    );
  };
  const stopTimer = () => {
    if (timer.current) clearTimeout(timer.current);
  };

  useEffect(() => {
    startTimer();
    return stopTimer;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      role={toast.type === "error" ? "alert" : "status"}
      onMouseEnter={stopTimer}
      onMouseLeave={startTimer}
      className={`flex items-start gap-2.5 w-80 max-w-[calc(100vw-1.5rem)] pl-3 pr-1.5 py-2.5 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-lg pointer-events-auto select-none ${
        isExiting
          ? "animate-out fade-out slide-out-to-right-4 duration-200"
          : "animate-in fade-in slide-in-from-bottom-2 duration-200"
      }`}
    >
      <Icon className={`w-4 h-4 mt-px shrink-0 ${tone.color}`} />
      <p className="flex-1 min-w-0 text-[13px] leading-snug text-zinc-800 dark:text-zinc-200 wrap-break-word select-text">
        {toast.message}
      </p>
      <button
        type="button"
        onClick={triggerExit}
        aria-label={t`Dismiss`}
        title={t`Dismiss`}
        className="flex items-center justify-center w-6 h-6 -my-0.5 rounded-md shrink-0 text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/5 transition-colors"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

export function Toast() {
  const { activeToasts, hideToast } = useUI();
  if (!activeToasts || activeToasts.length === 0) return null;

  return (
    <div className="fixed bottom-9 right-3 z-999 flex flex-col items-end gap-2 pointer-events-none">
      {activeToasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} hideToast={hideToast} />
      ))}
    </div>
  );
}
