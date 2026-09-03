import { useState } from "react";
import { useUI } from "../../hooks/useUI";
import { useTheme } from "../../hooks/useTheme";
import {
  X,
  Key,
  ExternalLink,
  Moon,
  Sun,
  Monitor,
  Map,
  Settings,
  Palette,
  Save,
} from "./icons";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useAnimatedUnmount } from "../../hooks/useAnimatedUnmount";

type SettingsTab = "general" | "appearance" | "api";

export function AppSettings() {
  const { settings, updateSettings } = useWorkspace();
  const { showAppSettings, setShowAppSettings } = useUI();
  const { theme, setTheme, mapTheme, setMapTheme } = useTheme();

  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const { shouldRender, isAnimatingOut } = useAnimatedUnmount(
    showAppSettings,
    150,
  );

  if (!shouldRender) return null;

  // Make sure auto_save_interval exists in your settings state (default to 3)
  const autoSaveInterval = settings.auto_save_interval ?? 3;

  return (
    <div
      className={`fixed inset-0 z-999 flex items-center justify-center bg-black/60 backdrop-blur-sm ${isAnimatingOut ? "animate-out fade-out duration-200" : "animate-in fade-in duration-200"}`}
    >
      <div
        className={`w-135 bg-white dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded-xl shadow-2xl overflow-hidden ${isAnimatingOut ? "animate-out zoom-out-95 duration-200" : "animate-in zoom-in-95 duration-200"}`}
      >
        {/* Header Section */}
        <div className="px-5 py-4 border-b border-zinc-100 dark:border-navidark-400 bg-zinc-50/50 dark:bg-navidark-800 flex items-center justify-between shrink-0">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <Settings className="w-4 h-4 text-navi" /> Settings
          </h3>
          <button
            onClick={() => setShowAppSettings(false)}
            className="text-zinc-400 hover:text-zinc-700 dark:hover:text-white transition-colors p-1 rounded-md hover:bg-zinc-200 dark:hover:bg-navidark-600"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex min-h-90">
          {/* Sidebar Tabs */}
          <div className="w-36 bg-zinc-50 dark:bg-navidark-800 border-r border-zinc-100 dark:border-navidark-400 p-2 flex flex-col gap-1 shrink-0">
            <TabButton
              active={activeTab === "general"}
              onClick={() => setActiveTab("general")}
              icon={Settings}
              label="General"
            />
            <TabButton
              active={activeTab === "appearance"}
              onClick={() => setActiveTab("appearance")}
              icon={Palette}
              label="Appearance"
            />
            <TabButton
              active={activeTab === "api"}
              onClick={() => setActiveTab("api")}
              icon={Key}
              label="API Keys"
            />
          </div>

          {/* Body Section */}
          <div className="flex-1 p-5 overflow-y-auto custom-scrollbar bg-white dark:bg-navidark-900">
            {/* GENERAL TAB */}
            {activeTab === "general" && (
              <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-300">
                <div className="space-y-3">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <Save className="w-3.5 h-3.5" /> Auto-Save Interval
                  </label>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    How long should Navivi wait after your last edit before
                    saving in the background?
                  </p>
                  <select
                    value={autoSaveInterval}
                    onChange={(e) =>
                      updateSettings({
                        auto_save_interval: parseInt(e.target.value),
                      })
                    }
                    className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2.5 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                  >
                    <option value={0}>Disabled (Manual Save Only)</option>
                    <option value={3}>3 Seconds (Aggressive)</option>
                    <option value={10}>10 Seconds (Standard)</option>
                    <option value={30}>30 Seconds</option>
                    <option value={60}>1 Minute (Relaxed)</option>
                  </select>
                </div>
              </div>
            )}

            {/* APPEARANCE TAB */}
            {activeTab === "appearance" && (
              <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-300">
                {/* App Theme */}
                <div className="space-y-3">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <Monitor className="w-3.5 h-3.5" /> UI Theme
                  </label>
                  <div className="flex p-1 bg-zinc-100 dark:bg-navidark-800 rounded-lg border border-zinc-200 dark:border-navidark-400">
                    {[
                      { id: "light", icon: Sun, label: "Light" },
                      { id: "dark", icon: Moon, label: "Dark" },
                      { id: "system", icon: Monitor, label: "System" },
                    ].map((t) => (
                      <button
                        key={t.id}
                        onClick={() => setTheme(t.id as any)}
                        className={`flex-1 flex items-center justify-center gap-2 py-2 text-xs font-bold rounded-md transition-all duration-200 ${
                          theme === t.id
                            ? "bg-white dark:bg-navidark-600 text-navi shadow-sm"
                            : "text-zinc-500 dark:text-navidark-150 hover:text-zinc-700 dark:hover:text-zinc-200"
                        }`}
                      >
                        <t.icon className="w-3.5 h-3.5" /> {t.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Map Theme */}
                <div className="space-y-3 pt-4 border-t border-zinc-100 dark:border-navidark-700">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <Map className="w-3.5 h-3.5" /> Map Style
                  </label>
                  <div className="flex p-1 bg-zinc-100 dark:bg-navidark-800 rounded-lg border border-zinc-200 dark:border-navidark-400">
                    {[
                      { id: "light", label: "Light Map" },
                      { id: "dark", label: "Dark Map" },
                      { id: "sync", label: "Sync with UI" },
                    ].map((t) => (
                      <button
                        key={t.id}
                        onClick={() => setMapTheme(t.id as any)}
                        className={`flex-1 py-2 text-xs font-bold rounded-md transition-all duration-200 ${
                          mapTheme === t.id
                            ? "bg-white dark:bg-navidark-600 text-navi shadow-sm"
                            : "text-zinc-500 dark:text-navidark-150 hover:text-zinc-700 dark:hover:text-zinc-200"
                        }`}
                      >
                        {t.label}
                      </button>
                    ))}
                  </div>
                  <p className="text-[10px] text-zinc-400 px-1">
                    "Sync with UI" will automatically switch the map to match
                    your App Theme.
                  </p>
                </div>
              </div>
            )}

            {/* API KEYS TAB */}
            {activeTab === "api" && (
              <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-300">
                <div className="space-y-3">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <Key className="w-3.5 h-3.5" /> Routing API Key
                  </label>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    Navivi uses OpenRouteService for driving and walking
                    directions. Provide your own free API key to enable routing.
                  </p>
                  <input
                    type="password"
                    value={settings.ors_api_key || ""}
                    onChange={(e) =>
                      updateSettings({ ors_api_key: e.target.value })
                    }
                    placeholder="Enter your ORS API Key..."
                    className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2.5 text-sm text-zinc-900 dark:text-white outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                    spellCheck={false}
                  />
                  <a
                    href="https://openrouteservice.org/dev/#/signup"
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-[11px] underline font-semibold text-navi-600 hover:text-navi-800 dark:text-navi-400 dark:hover:text-navi-300 transition-colors"
                  >
                    Get a free key here <ExternalLink className="w-3 h-3" />
                  </a>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Footer Section */}
        <div className="px-5 py-3 border-t border-zinc-100 dark:border-navidark-400 bg-zinc-50/50 dark:bg-navidark-800 flex justify-end shrink-0">
          <button
            onClick={() => setShowAppSettings(false)}
            className="px-5 py-2 bg-navi hover:bg-navi-600 text-white text-xs font-bold rounded-lg transition-colors shadow-sm"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

// Small helper component for the sidebar tabs
function TabButton({
  active,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: any;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-2 px-3 py-2 text-xs font-bold rounded-md transition-colors ${
        active
          ? "bg-white dark:bg-navidark-600 text-navi shadow-sm border border-zinc-200 dark:border-transparent"
          : "text-zinc-500 dark:text-navidark-150 hover:bg-zinc-200/50 dark:hover:bg-navidark-700 hover:text-zinc-800 dark:hover:text-zinc-200 border border-transparent"
      }`}
    >
      <Icon className="w-4 h-4" />
      {label}
    </button>
  );
}
