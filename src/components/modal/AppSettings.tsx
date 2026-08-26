import { useUI } from "../../hooks/useUI";
import { useTheme } from "../../hooks/useTheme";
import { X, Key, ExternalLink, Moon, Sun, Monitor, Map } from "../ui/icons";
import { useWorkspace } from "../../hooks/useWorkspace";

export function AppSettings() {
  const { settings, updateSettings } = useWorkspace();
  const { showAppSettings, setShowAppSettings } = useUI();
  const { theme, setTheme, mapTheme, setMapTheme } = useTheme();

  if (!showAppSettings) return null;

  return (
    <div className="fixed inset-0 z-999 flex items-center justify-center bg-black/60 animate-in fade-in">
      <div className="w-480px bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 rounded-xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200">
        
        {/* Header Section */}
        <div className="px-5 py-4 border-b border-zinc-100 dark:border-white/5 bg-zinc-50/50 dark:bg-zinc-900/50 flex items-center justify-between">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-white">Application Settings</h3>
          <button 
            onClick={() => setShowAppSettings(false)} 
            className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body Section */}
        <div className="p-5 space-y-6 max-h-[70vh] overflow-y-auto custom-scrollbar">
          
          {/* ORS API Key */}
          <div className="space-y-3">
            <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-1.5">
              <Key className="w-3.5 h-3.5" /> Routing API Key
            </label>
            
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Navivi uses OpenRouteService for driving and walking directions. You need to provide your own free API key.
            </p>

            <input
              type="password"
              value={settings.ors_api_key || ""}
              onChange={(e) => updateSettings({ ors_api_key: e.target.value })}
              placeholder="Enter your ORS API Key..."
              className="w-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-white outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-all"
              spellCheck={false}
            />

            <a 
              href="https://openrouteservice.org/dev/#/signup" 
              target="_blank" 
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300 transition-colors"
            >
              Get a free key here <ExternalLink className="w-3 h-3" />
            </a>
          </div>

          {/* App Theme */}
          <div className="space-y-3 pt-2 border-t border-zinc-100 dark:border-white/5">
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
          <div className="space-y-3 pt-2 border-t border-zinc-100 dark:border-white/5">
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
              "Sync with UI" will automatically switch the map to match your App Theme.
            </p>
          </div>

        </div>

        {/* Footer Section */}
        <div className="px-5 py-4 border-t border-zinc-100 dark:border-white/5 bg-zinc-50/50 dark:bg-zinc-900/50 flex justify-end">
          <button 
            onClick={() => setShowAppSettings(false)} 
            className="px-4 py-2 bg-emerald-500 text-white text-xs font-bold rounded-lg hover:bg-emerald-600 transition-colors shadow-sm"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}