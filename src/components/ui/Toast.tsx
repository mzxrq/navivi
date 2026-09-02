import { useState, useEffect } from "react";
import { CheckCircle2, AlertCircle, Info, AlertTriangle, X } from "../ui/icons";
import { useUI } from "../../hooks/useUI";

function ToastItem({ toast, hideToast }: { toast: any; hideToast: (id: string) => void}) {
    const [isExiting, setIsExiting] = useState(false);
    const triggerExit = () => {
        setIsExiting(true);
        setTimeout(() => {
            hideToast(toast.id);
        }, 300);
    };

    useEffect(() => {
        const timer = setTimeout(() => {
            triggerExit();
        }, 3700);
        return () => clearTimeout(timer);
        // eslint-disable-next-line React-hooks/exhaustive-deps
    }, []);

    return (
        <div className={`flex items-start gap-3 w-88 p-3 rounded-lg border shadow-2xl backdrop-blur-md pointer-events-auto
            ${isExiting ? "animate-out fade-out slide-out-to-right-8 duration-300" : "animate-in fade-in slide-in-from-right-8 duration-300"}
            ${
                toast.type === "success"
                ? "bg-white/95 dark:bg-navidark-800/95 border-navi-900/30 text-navi-900 dark:text-navi-800"
                : toast.type === "error"
                ? "bg-white/95 dark:bg-navidark-800/95 border-red-500/30 text-red-600 dark:text-red-400"
                : toast.type === "warning"
                ? "bg-white/95 dark:bg-navidark-800/95 border-amber-500/30 text-amber-600 dark:text-amber-400"
                : "bg-white/95 dark:bg-navidark-800/95 border-zinc-500/30 text-zinc-600 dark:text-navi-400"
            }
        `}
        >
            <div className="shrink-0 mt-0.5">
                {toast.type === "success" && <CheckCircle2 className="w-4 h-4" />}
                {toast.type === "error" && <AlertCircle className="w-4 h-4" />}
                {toast.type === "warning" && <AlertTriangle className="w-4 h-4"/>}
                {toast.type === "info" && <Info className="w-4 h-4" />}
            </div>

            <div className="flex-1 min-w-0 flex flex-col">
                <span className="text-[10px] font-bold uppercase tracking-wider opacity-80 mb-0.5">
                    {toast.type}
                </span>
                <span className="text-xs font-medium text-zinc-700 dark:text-zinc-200 leading-snug wrap-break-word">
                    {toast.message}
                </span>
            </div>

            <button
                onClick={triggerExit}
                className="shrink-0 opacity-50 hover:opacity-100 transition-opacity cursor-pointer"            
            >
                <X className="w-3.5 h-3.5"/>
            </button>
        </div>
    );
}

export function Toast() {
    const { activeToasts, hideToast } = useUI();
    if (!activeToasts || activeToasts.length === 0) return null;

    return (
        <div className="fixed bottom-9 right-1.75 z-999 flex flex-col gap-2 pointer-events-none">
            {activeToasts.map((toast) => (
                <ToastItem key={toast.id} toast={toast} hideToast={hideToast} />
            ))}
        </div>
    )
}

// export function Toast() {
//   const { activeToasts, hideToast } = useUI();

//   if (!activeToasts || activeToasts.length === 0) return null;

//   return (
//     <div className="fixed bottom-9 right-1.75 z-999 animate-in slide-in-from-right-8 fade-in-100 duration-600 pointer-events-auto">
//       {activeToasts.map((toast) => (
//         <div
//           className={`flex items-start gap-3 w-88 p-3 rounded-lg border shadow-2xl backdrop-blur-md ${
//             toast.type === "success"
//               ? "bg-white/95 dark:bg-navidark-800/95 border-emerald-500/30 text-emerald-600 dark:text-emerald-400"
//               : toast.type === "error"
//                 ? "bg-white/95 dark:bg-navidark-800/95 border-red-500/30 text-red-600 dark:text-red-400"
//                 : toast.type === "warning"
//                   ? "bg-white/95 dark:bg-navidark-800/95 border-amber-500/30 text-amber-600 dark:text-amber-400"
//                   : "bg-white/95 dark:bg-navidark-800/95 border-navi-500/30 text-navi-600 dark:text-navi-400"
//           }`}
//         >
//           {/* Icon */}
//           <div className="shrink-0 mt-0.5">
//             {toast.type === "success" && <CheckCircle2 className="w-4 h-4" />}
//             {toast.type === "error" && <AlertCircle className="w-4 h-4" />}
//             {toast.type === "warning" && <AlertTriangle className="w-4 h-4" />}
//             {toast.type === "info" && <Info className="w-4 h-4" />}
//           </div>

//           {/* Content */}
//           <div className="flex-1 min-w-0 flex flex-col">
//             <span className="text-[10px] font-bold uppercase tracking-wider opacity-80 mb-0.5">
//               {toast.type}
//             </span>
//             <span className="text-xs font-medium text-zinc-700 dark:text-zinc-200 leading-snug wrap-break-word">
//               {toast.message}
//             </span>
//           </div>

//           {/* Optional Close Button (mimicking desktop notifications) */}
//           <button
//             onClick={() => {
//               hideToast;
//             }}
//             className="shrink-0 opacity-50 hover:opacity-100 transition-opacity"
//           >
//             <X className="w-3.5 h-3.5" />
//           </button>
//         </div>
//       ))}
//     </div>
//   );
// }
