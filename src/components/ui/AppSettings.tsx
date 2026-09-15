import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { useUI } from "../../hooks/useUI";
import { useTheme } from "../../hooks/useTheme";
import {
  X,
  Moon,
  Sun,
  Monitor,
  Settings,
  Palette,
  Save,
  MapPin,
  Key,
} from "./icons";
import { open } from "@tauri-apps/plugin-dialog";
import { convertFileSrc } from "@tauri-apps/api/core";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useAnimatedUnmount } from "../../hooks/useAnimatedUnmount";

type SettingsTab = "general" | "appearance" | "api";

export function AppSettings() {
  const { settings, updateSettings, setIsDirty } = useWorkspace();
  const { showAppSettings, setShowAppSettings, currentView } = useUI();
  const { theme, setTheme } = useTheme();

  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const { shouldRender, isAnimatingOut } = useAnimatedUnmount(
    showAppSettings,
    150,
  );

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape" && showAppSettings) {
        setShowAppSettings(false);
      }
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [showAppSettings, setShowAppSettings]);

  if (!shouldRender) return null;

  const autoSaveInterval = settings.auto_save_interval ?? 3;

  return createPortal(
    <div
      className={`fixed inset-0 z-99999 flex items-center justify-center bg-zinc-950/40 backdrop-blur-[2px] select-none ${isAnimatingOut ? "animate-out fade-out duration-200" : "animate-in fade-in duration-200"}`}
    >
      <div
        className={`w-135 bg-white dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded-xl shadow-2xl overflow-hidden flex flex-col ${isAnimatingOut ? "animate-out zoom-out-95 duration-200" : "animate-in zoom-in-95 duration-200"}`}
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
                    Controls auto save of editors that have unsaved changes
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
                    <option value={0}>Off</option>
                    <option value={3}>After Delay (3 seconds)</option>
                    <option value={30}>30 seconds</option>
                    <option value={60}>1 minute</option>
                    <option value={600}>10 minutes</option>
                  </select>
                </div>

                {/* FAST RENDER MODE */}
                {currentView === "editor" && (
                  <div className="space-y-3 pt-4 border-t border-zinc-100 dark:border-navidark-700">
                    <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                      Project Overrides
                    </label>
                    <div
                      onClick={() => {
                        updateSettings({
                          skip_rich_media: !settings.skip_rich_media,
                        });
                        setIsDirty(true);
                      }}
                      className={`flex items-center justify-between p-4 rounded-xl border-2 transition-all cursor-pointer select-none group ${
                        settings.skip_rich_media
                          ? "border-navi bg-navi-50/50 dark:border-navi/50 dark:bg-navi/10 shadow-sm"
                          : "border-zinc-200 dark:border-navidark-400 bg-zinc-50 dark:bg-navidark-800 hover:border-zinc-300 dark:hover:border-navidark-300"
                      }`}
                    >
                      <div className="flex flex-col gap-1 pr-6">
                        <span
                          className={`text-xs font-bold transition-colors ${
                            settings.skip_rich_media
                              ? "text-navi-700 dark:text-navi-400"
                              : "text-zinc-700 dark:text-zinc-200 group-hover:text-zinc-900 dark:group-hover:text-white"
                          }`}
                        >
                          Fast Render Mode
                        </span>
                        <span className="text-[10px] text-zinc-500 dark:text-navidark-150 leading-relaxed">
                          Skip AI voiceover synthesis and pop-up images during
                          generation. Perfect for quickly previewing route
                          paths.
                        </span>
                      </div>

                      <div
                        className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-200 ease-in-out ${
                          settings.skip_rich_media
                            ? "bg-navi"
                            : "bg-zinc-300 dark:bg-zinc-700"
                        }`}
                      >
                        <span
                          className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow-sm transition-transform duration-200 ease-in-out ${
                            settings.skip_rich_media
                              ? "translate-x-4.5"
                              : "translate-x-0.5"
                          }`}
                        />
                      </div>
                    </div>

                    {/* HISTORICAL WEATHER SYNC */}
                    <div
                      onClick={() => {
                        updateSettings({
                          weather_sync_enabled: !settings.weather_sync_enabled,
                        });
                        setIsDirty(true);
                      }}
                      className={`flex items-center justify-between p-4 rounded-xl border-2 transition-all cursor-pointer select-none group ${
                        settings.weather_sync_enabled
                          ? "border-navi bg-navi-50/50 dark:border-navi/50 dark:bg-navi/10 shadow-sm"
                          : "border-zinc-200 dark:border-navidark-400 bg-zinc-50 dark:bg-navidark-800 hover:border-zinc-300 dark:hover:border-navidark-300"
                      }`}
                    >
                      <div className="flex flex-col gap-1 pr-6">
                        <div className="flex items-center gap-2">
                          <span
                            className={`text-xs font-bold transition-colors ${
                              settings.weather_sync_enabled
                                ? "text-navi-700 dark:text-navi-400"
                                : "text-zinc-700 dark:text-zinc-200 group-hover:text-zinc-900 dark:group-hover:text-white"
                            }`}
                          >
                            Historical Weather Sync
                          </span>
                          <span className="text-[9px] font-semibold tracking-wider uppercase px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:bg-amber-400/10 dark:text-amber-400 border border-amber-500/20">
                            Experimental
                          </span>
                        </div>
                        <span className="text-[10px] text-zinc-500 dark:text-navidark-150 leading-relaxed">
                          Synchronize historical weather conditions from photo EXIF dates using Open-Meteo to dynamically apply atmospheric fog and rain effects.
                        </span>
                      </div>

                      <div
                        className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-200 ease-in-out ${
                          settings.weather_sync_enabled
                            ? "bg-navi"
                            : "bg-zinc-300 dark:bg-zinc-700"
                        }`}
                      >
                        <span
                          className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow-sm transition-transform duration-200 ease-in-out ${
                            settings.weather_sync_enabled
                              ? "translate-x-4.5"
                              : "translate-x-0.5"
                          }`}
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* APPEARANCE TAB */}
            {activeTab === "appearance" && (
              <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-300">
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

                <div className="space-y-3 pt-4 border-t border-zinc-100 dark:border-navidark-700">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <MapPin className="w-3.5 h-3.5" /> Global Route Marker
                  </label>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    Default marker for all waypoints. Can be overridden
                    per-stop.
                  </p>
                  <div className="flex items-center gap-3">
                    {settings.routeMarker ? (
                      <div className="relative w-12 h-12 rounded-lg border border-zinc-200 dark:border-white/10 flex items-center justify-center bg-zinc-50 dark:bg-navidark-700/50 group">
                        <img
                          src={
                            settings.routeMarker.startsWith("/") ||
                            settings.routeMarker.match(/^[a-zA-Z]:\\/)
                              ? convertFileSrc(settings.routeMarker)
                              : settings.routeMarker
                          }
                          alt="Route Marker"
                          className="w-8 h-8 object-contain"
                        />
                        <button
                          onClick={() => {
                            updateSettings({ routeMarker: "" });
                            setIsDirty(true);
                          }}
                          className="absolute -top-2 -right-2 p-1 bg-red-500 text-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity shadow-md"
                          title="Remove Marker"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                    ) : (
                      <div className="w-12 h-12 rounded-lg border border-dashed border-zinc-300 dark:border-white/20 flex items-center justify-center bg-zinc-50 dark:bg-navidark-700/30">
                        <MapPin className="w-5 h-5 text-zinc-300 dark:text-zinc-600" />
                      </div>
                    )}
                    <button
                      onClick={async () => {
                        const selected = await open({
                          multiple: false,
                          filters: [
                            {
                              name: "Images",
                              extensions: ["svg", "png", "jpg", "jpeg"],
                            },
                          ],
                        });
                        if (selected && typeof selected === "string") {
                          updateSettings({ routeMarker: selected });
                          setIsDirty(true);
                        }
                      }}
                      className="flex-1 py-2 text-xs font-semibold rounded-xl border border-zinc-200 dark:border-white/10 bg-white dark:bg-navidark-600 hover:bg-zinc-50 dark:hover:bg-white/5 transition-colors text-zinc-700 dark:text-zinc-300 shadow-sm"
                    >
                      {settings.routeMarker
                        ? "Change Marker"
                        : "Select Custom Marker"}
                    </button>
                  </div>
                  <div className="flex gap-2 mt-2">
                    {[
                      "/defaults/markers/map_pin.svg",
                      "/defaults/markers/walking.svg",
                      "/defaults/markers/car.svg",
                    ].map((preset) => (
                      <button
                        key={preset}
                        onClick={() => {
                          updateSettings({ routeMarker: preset });
                          setIsDirty(true);
                        }}
                        className={`w-10 h-10 rounded-lg border flex items-center justify-center transition-colors ${
                          settings.routeMarker === preset
                            ? "border-navi bg-navi-50 dark:bg-navi-900/20"
                            : "border-zinc-200 dark:border-white/10 bg-zinc-50 dark:bg-navidark-700/50 hover:bg-zinc-100 dark:hover:bg-navidark-600"
                        }`}
                      >
                        <img src={preset} className="w-6 h-6 object-contain" />
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* API TAB */}
            {activeTab === "api" && (
              <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-300">
                <div className="space-y-3">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <Key className="w-3.5 h-3.5" /> Mapbox API Key
                  </label>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    Required for map rendering and 3D terrain.
                  </p>
                  <input
                    type="text"
                    value={settings.mapbox_api_key || ""}
                    onChange={(e) => {
                      updateSettings({ mapbox_api_key: e.target.value });
                      setIsDirty(true);
                    }}
                    placeholder="pk.eyJ1..."
                    className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2.5 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                  />
                </div>
                <div className="space-y-3 pt-4 border-t border-zinc-100 dark:border-navidark-700">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <Key className="w-3.5 h-3.5" /> OpenRouteService API Key
                  </label>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    Required for walking and some driving routes (fallback).
                  </p>
                  <input
                    type="text"
                    value={settings.ors_api_key || ""}
                    onChange={(e) => {
                      updateSettings({ ors_api_key: e.target.value });
                      setIsDirty(true);
                    }}
                    placeholder="5b3ce3597851110001cf6248..."
                    className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2.5 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                  />
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
    </div>,
    document.body,
  );
}

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
