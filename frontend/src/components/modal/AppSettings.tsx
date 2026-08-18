import { useUI } from "../../hooks/useUI";
import { useTheme } from "../../hooks/useTheme";
import { X, Moon, Sun, Monitor, Map } from "lucide-react";

export function AppSettings() {
  const { showAppSettings, setShowAppSettings } = useUI();
  const { theme, setTheme, mapTheme, setMapTheme } = useTheme();

  if (!showAppSettings) return null;

  return (
    <div className="fixed inset-0 z-[999] flex items-center justify-center p-4 bg-black/60 animate-in fade-in duration-200">
      {" "}
      <div className="w-full max-w-md bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 rounded-2xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex justify-between items-center px-5 py-4 border-b border-zinc-200 dark:border-white/5 bg-zinc-50/50 dark:bg-zinc-900/50">
          <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
            Application Settings
          </h2>
          <button
            onClick={() => setShowAppSettings(false)}
            className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition-colors p-1"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-6">
          {/* App Theme */}
          <div className="space-y-3">
            <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-1.5">
              <Monitor className="w-3.5 h-3.5" /> UI Theme
            </label>
            <div className="flex p-1 bg-zinc-100 dark:bg-zinc-900/50 rounded-lg border border-zinc-200 dark:border-white/5">
              {[
                { id: "light", icon: Sun, label: "Light" },
                { id: "dark", icon: Moon, label: "Dark" },
                { id: "system", icon: Monitor, label: "System" },
              ].map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTheme(t.id as any)}
                  className={`flex-1 flex items-center justify-center gap-2 py-2 text-xs font-bold rounded-md transition-all ${
                    theme === t.id
                      ? "bg-white dark:bg-zinc-800 text-emerald-600 dark:text-emerald-400 shadow-sm"
                      : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
                  }`}
                >
                  <t.icon className="w-3.5 h-3.5" /> {t.label}
                </button>
              ))}
            </div>
          </div>

          {/* Map Theme */}
          <div className="space-y-3">
            <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-1.5">
              <Map className="w-3.5 h-3.5" /> Map Style
            </label>
            <div className="flex p-1 bg-zinc-100 dark:bg-zinc-900/50 rounded-lg border border-zinc-200 dark:border-white/5">
              {[
                { id: "light", label: "Light Map" },
                { id: "dark", label: "Dark Map" },
                { id: "sync", label: "Sync with UI" },
              ].map((t) => (
                <button
                  key={t.id}
                  onClick={() => setMapTheme(t.id as any)}
                  className={`flex-1 py-2 text-xs font-bold rounded-md transition-all ${
                    mapTheme === t.id
                      ? "bg-white dark:bg-zinc-800 text-emerald-600 dark:text-emerald-400 shadow-sm"
                      : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <p className="text-[10px] text-zinc-500 dark:text-zinc-400 px-1">
              "Sync with UI" will automatically switch the map to match your App
              Theme.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
