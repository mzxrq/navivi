import { CheckCircle2, AlertCircle, Info, AlertTriangle } from "../ui/icons";
import { useUI } from "../../hooks/useUI";

export function Toast() {
    const { toast } = useUI();
    if (!toast.visible) return null;

    return (
        <div className="absolute bottom-12 left-1/2 -translate-x-1/2 z-[999] animate-in slide-in-from-bottom-6 fade-in zoom-in-95 duration-300 pointer-events-none">
          <div
            className={`flex items-center gap-3 px-5 py-3 rounded-full backdrop-blur-xl border shadow-2xl ${
              toast.type === "success"
                ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-700 dark:text-emerald-400 shadow-emerald-500/10"
                : toast.type === "error"
                ? "bg-red-500/10 border-red-500/20 text-red-700 dark:text-red-400 shadow-red-500/10"
                : toast.type === "warning"
                ? "bg-amber-500/10 border-amber-500/20 text-amber-700 dark:text-amber-400 shadow-amber-500/10"
                : "bg-navi-500/10 border-navi-500/20 text-navi-700 dark:text-navi-400 shadow-navi-500/10"
            }`}
          >
            {toast.type === "success" && <CheckCircle2 className="w-5 h-5" />}
            {toast.type === "error" && <AlertCircle className="w-5 h-5" />}
            {toast.type === "warning" && <AlertTriangle className="w-5 h-5" />}
            {toast.type === "info" && <Info className="w-5 h-5" />}
            <span className="text-sm font-bold tracking-wide">
              {toast.message}
            </span>
          </div>
        </div>
      );
    }