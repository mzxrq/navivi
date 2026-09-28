import { useLingui } from "@lingui/react";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { convertFileSrc } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useAnimatedUnmount } from "../../hooks/useAnimatedUnmount";
import { useTheme } from "../../hooks/useTheme";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import { getLocalModels, pullModelStream } from "../../services/ollamaApi";
import { dynamicActivate } from "../../i18n";
import {
  CheckCircle2,
  Film,
  Key,
  MapPin,
  Monitor,
  Moon,
  NaviviType,
  Palette,
  Save,
  Settings,
  Sparkles,
  Sun,
  X,
  Globe,
} from "./icons";

type SettingsTab = "general" | "appearance" | "api" | "video" | "ai";

export function AppSettings() {
  const { settings, updateSettings, setIsDirty } = useWorkspace();
  const { i18n } = useLingui();
  const { showAppSettings, setShowAppSettings, currentView } = useUI();
  const { theme, setTheme, accentTheme, setAccentTheme } = useTheme();

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
        className={`w-162.5 max-w-[95vw] h-137.5 max-h-[95vh] bg-white dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded-xl shadow-2xl overflow-hidden flex flex-col ${isAnimatingOut ? "animate-out zoom-out-95 duration-200" : "animate-in zoom-in-95 duration-200"}`}
      >
        {/* Header Section */}
        <div className="px-5 py-3 border-b border-zinc-100 dark:border-navidark-400 bg-zinc-50/50 dark:bg-navidark-800 flex items-center justify-between shrink-0">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <Settings className="w-4 h-4 text-navi" /> <Trans>Settings</Trans>
          </h3>
          <button
            onClick={() => setShowAppSettings(false)}
            className="text-zinc-400 hover:text-zinc-700 dark:hover:text-white transition-colors p-1 rounded-md hover:bg-zinc-200 dark:hover:bg-navidark-600"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex flex-1 overflow-hidden">
          {/* Sidebar Tabs */}
          <div className="w-40 bg-zinc-50 dark:bg-navidark-800 border-r border-zinc-100 dark:border-navidark-400 p-2 flex flex-col gap-1 shrink-0 overflow-y-auto custom-scrollbar">
            <TabButton
              active={activeTab === "general"}
              onClick={() => setActiveTab("general")}
              icon={Settings}
              label={t`General`}
            />
            <TabButton
              active={activeTab === "appearance"}
              onClick={() => setActiveTab("appearance")}
              icon={Palette}
              label={t`Appearance`}
            />
            <TabButton
              active={activeTab === "api"}
              onClick={() => setActiveTab("api")}
              icon={Key}
              label={t`API Keys`}
            />
            <TabButton
              active={activeTab === "video"}
              onClick={() => setActiveTab("video")}
              icon={Film}
              label={t`Video Editor`}
            />
            <TabButton
              active={activeTab === "ai"}
              onClick={() => setActiveTab("ai")}
              icon={Sparkles}
              label={t`AI Models`}
            />
          </div>

          {/* Body Section */}
          <div className="flex-1 p-5 overflow-y-auto custom-scrollbar bg-white dark:bg-navidark-900">
            {/* GENERAL TAB */}
            {activeTab === "general" && (
              <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-300">
                <div className="space-y-3">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <Globe className="w-3.5 h-3.5" /> <Trans>Language</Trans>
                  </label>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    <Trans>
                      Choose your preferred language for the application
                    </Trans>
                  </p>
                  <select
                    value={i18n.locale}
                    onChange={(e) => {
                      const newLocale = e.target.value;
                      localStorage.setItem("navivi_locale", newLocale);
                      dynamicActivate(newLocale);
                    }}
                    className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2.5 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                  >
                    <option value="en">English</option>
                    <option value="ja">日本語</option>
                  </select>
                </div>

                <div className="space-y-3">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <Save className="w-3.5 h-3.5" />{" "}
                    <Trans>Auto-Save Interval</Trans>
                  </label>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    <Trans>
                      Controls auto save of editors that have unsaved changes
                    </Trans>
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
                    <option value={0}>
                      <Trans>Off</Trans>
                    </option>
                    <option value={3}>
                      <Trans>3 seconds</Trans>
                    </option>
                    <option value={30}>
                      <Trans>30 seconds</Trans>
                    </option>
                    <option value={60}>
                      <Trans>1 minute</Trans>
                    </option>
                    <option value={600}>
                      <Trans>10 minutes</Trans>
                    </option>
                  </select>
                </div>

                {/* FAST RENDER MODE */}
                {currentView === "editor" && (
                  <div className="space-y-3 pt-4 border-t border-zinc-100 dark:border-navidark-700">
                    <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                      <Trans>Advanced Features</Trans>
                    </label>

                    {/* ENABLE AI FEATURES TOGGLE */}
                    <div
                      onClick={() => {
                        updateSettings({
                          ai_features_enabled: !settings.ai_features_enabled,
                        });
                        setIsDirty(true);
                      }}
                      className={`flex items-center justify-between p-4 rounded-xl border-2 transition-all cursor-pointer select-none group ${
                        settings.ai_features_enabled
                          ? "border-navi bg-navi-50/50 dark:border-navi/50 dark:bg-navi/10 shadow-sm"
                          : "border-zinc-200 dark:border-navidark-400 bg-zinc-50 dark:bg-navidark-800 hover:border-zinc-300 dark:hover:border-navidark-300"
                      }`}
                    >
                      <div className="flex flex-col gap-1 pr-6">
                        <div className="flex items-center gap-2">
                          <span
                            className={`text-xs font-bold transition-colors ${
                              settings.ai_features_enabled
                                ? "text-navi-700 dark:text-navi-400"
                                : "text-zinc-700 dark:text-zinc-200 group-hover:text-zinc-900 dark:group-hover:text-white"
                            }`}
                          >
                            <Trans>Enable AI Features</Trans>
                          </span>
                          <span className="text-[9px] font-semibold tracking-wider uppercase px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-600 dark:bg-violet-400/10 dark:text-violet-400 border border-violet-500/20">
                            <Trans>Requires Ollama</Trans>
                          </span>
                        </div>
                        <span className="text-[10px] text-zinc-500 dark:text-navidark-150 leading-relaxed">
                          <Trans>
                            Show Auto-Write script buttons and overview
                            narration. Requires Ollama to be installed and
                            running locally.
                          </Trans>
                        </span>
                      </div>

                      <div
                        className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-200 ease-in-out ${
                          settings.ai_features_enabled
                            ? "bg-navi"
                            : "bg-zinc-300 dark:bg-zinc-700"
                        }`}
                      >
                        <span
                          className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow-sm transition-transform duration-200 ease-in-out ${
                            settings.ai_features_enabled
                              ? "translate-x-4.5"
                              : "translate-x-0.5"
                          }`}
                        />
                      </div>
                    </div>

                    <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                      <Trans>Project Overrides</Trans>
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
                          <Trans>Fast Render Mode</Trans>
                        </span>
                        <span className="text-[10px] text-zinc-500 dark:text-navidark-150 leading-relaxed">
                          <Trans>
                            Skip AI voiceover synthesis and pop-up images during
                            generation
                          </Trans>
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
                            <Trans>Historical Weather Sync</Trans>
                          </span>
                          <span className="text-[9px] font-semibold tracking-wider uppercase px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:bg-amber-400/10 dark:text-amber-400 border border-amber-500/20">
                            <Trans>Experimental</Trans>
                          </span>
                        </div>
                        <span className="text-[10px] text-zinc-500 dark:text-navidark-150 leading-relaxed">
                          <Trans>
                            Synchronize historical weather conditions from photo
                            EXIF dates using Open-Meteo to dynamically apply
                            atmospheric fog and rain effects
                          </Trans>
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
                <div className="mt-8 flex justify-center opacity-50">
                  <NaviviType className="h-6 text-zinc-500" />
                </div>
              </div>
            )}

            {/* APPEARANCE TAB */}
            {activeTab === "appearance" && (
              <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-300">
                <div className="space-y-3">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <Monitor className="w-3.5 h-3.5" /> <Trans>UI Theme</Trans>
                  </label>
                  <div className="flex p-1 bg-zinc-100 dark:bg-navidark-800 rounded-lg border border-zinc-200 dark:border-navidark-400">
                    {[
                      { id: "light", icon: Sun, label: i18n._("Light") },
                      { id: "dark", icon: Moon, label: i18n._("Dark") },
                      { id: "system", icon: Monitor, label: i18n._("System") },
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
                    <Palette className="w-3.5 h-3.5" />{" "}
                    <Trans>Accent Color</Trans>
                  </label>
                  <div className="flex gap-2">
                    {[
                      {
                        id: "navi",
                        color: "bg-[#4287f5]",
                        label: i18n._("Navi Blue"),
                      },
                      {
                        id: "emerald",
                        color: "bg-[#10b981]",
                        label: i18n._("Emerald"),
                      },
                      {
                        id: "violet",
                        color: "bg-[#8b5cf6]",
                        label: i18n._("Violet"),
                      },
                      {
                        id: "amber",
                        color: "bg-[#f59e0b]",
                        label: i18n._("Amber"),
                      },
                      {
                        id: "rose",
                        color: "bg-[#f43f5e]",
                        label: i18n._("Rose"),
                      },
                    ].map((t) => (
                      <button
                        key={t.id}
                        onClick={() => setAccentTheme(t.id as any)}
                        title={t.label}
                        className={`w-8 h-8 rounded-full ${t.color} flex items-center justify-center transition-transform hover:scale-110 ${
                          accentTheme === t.id
                            ? "ring-2 ring-offset-2 ring-offset-white dark:ring-offset-navidark-900 ring-zinc-400 dark:ring-zinc-500 scale-110 shadow-sm"
                            : "opacity-80 hover:opacity-100"
                        }`}
                      >
                        {accentTheme === t.id && (
                          <div className="w-2 h-2 rounded-full bg-white opacity-80" />
                        )}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="space-y-3 pt-4 border-t border-zinc-100 dark:border-navidark-700">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <MapPin className="w-3.5 h-3.5" />{" "}
                    <Trans>Global Route Marker</Trans>
                  </label>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    <Trans>
                      Default marker for all waypoints. Can be overridden
                      per-stop.
                    </Trans>
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
                          alt={t`Route Marker`}
                          className="w-8 h-8 object-contain"
                        />
                        <button
                          onClick={() => {
                            updateSettings({ routeMarker: "" });
                            setIsDirty(true);
                          }}
                          className="absolute -top-2 -right-2 p-1 bg-red-500 text-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity shadow-md"
                          title={t`Remove Marker`}
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
                        ? i18n._("Change Marker")
                        : i18n._("Select Custom Marker")}
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

                <div className="space-y-3 pt-4 border-t border-zinc-100 dark:border-navidark-700">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <MapPin className="w-3.5 h-3.5" />{" "}
                    <Trans>Map Features</Trans>
                  </label>
                  <label className="flex items-center gap-3 cursor-pointer group">
                    <div className="relative flex items-center">
                      <input
                        type="checkbox"
                        className="peer sr-only"
                        checked={settings.show_route_heatmap || false}
                        onChange={(e) => {
                          updateSettings({
                            show_route_heatmap: e.target.checked,
                          });
                          setIsDirty(true);
                        }}
                      />
                      <div className="w-8 h-4.5 bg-zinc-300 dark:bg-zinc-700 rounded-full peer-checked:bg-navi transition-colors duration-200" />
                      <div className="absolute left-0.5 top-0.5 w-3.5 h-3.5 bg-white rounded-full shadow-sm peer-checked:translate-x-3.5 transition-transform duration-200" />
                    </div>
                    <div className="flex flex-col">
                      <span className="text-sm font-semibold text-zinc-800 dark:text-zinc-200 group-hover:text-navi transition-colors">
                        <Trans>Show Route Elevation Heatmap</Trans>
                      </span>
                      <span className="text-xs text-zinc-500 dark:text-zinc-400">
                        <Trans>
                          Color GPX routes dynamically based on steepness
                        </Trans>
                      </span>
                    </div>
                  </label>
                </div>
              </div>
            )}

            {/* API TAB */}
            {activeTab === "api" && (
              <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-300">
                <div className="space-y-3">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <Key className="w-3.5 h-3.5" />{" "}
                    <Trans>Mapbox API Key</Trans>
                  </label>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    <Trans>Required for map rendering and 3D terrain</Trans>
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
                    <Key className="w-3.5 h-3.5" />{" "}
                    <Trans>OpenRouteService API Key</Trans>
                  </label>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    <Trans>Required for driving and some hiking routes</Trans>
                  </p>
                  <input
                    type="text"
                    value={settings.ors_api_key || ""}
                    onChange={(e) => {
                      updateSettings({ ors_api_key: e.target.value });
                      setIsDirty(true);
                    }}
                    placeholder="API Key"
                    className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2.5 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                  />
                </div>
              </div>
            )}
            {/* VIDEO EDITOR TAB */}
            {activeTab === "video" && (
              <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-300">
                <div className="space-y-3">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <Film className="w-3.5 h-3.5" />{" "}
                    <Trans>Video Editor Settings</Trans>
                  </label>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                        <Trans>Target FPS</Trans>
                      </label>
                      <input
                        type="number"
                        value={settings.fps || 60}
                        onChange={(e) => {
                          updateSettings({ fps: Number(e.target.value) });
                          setIsDirty(true);
                        }}
                        className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                      />
                    </div>

                    <div className="space-y-2">
                      <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                        <Trans>Duration (seconds)</Trans>
                      </label>
                      <input
                        type="number"
                        value={settings.duration_seconds || 15}
                        onChange={(e) => {
                          updateSettings({
                            duration_seconds: Number(e.target.value),
                          });
                          setIsDirty(true);
                        }}
                        className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                      />
                    </div>

                    <div className="space-y-2">
                      <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                        <Trans>Residential Duration</Trans>
                      </label>
                      <input
                        type="number"
                        value={settings.res_duration || 5}
                        onChange={(e) => {
                          updateSettings({
                            res_duration: Number(e.target.value),
                          });
                          setIsDirty(true);
                        }}
                        className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                      />
                    </div>
                  </div>

                  <div className="space-y-3 pt-4 border-t border-zinc-100 dark:border-navidark-700">
                    <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                      <Trans>Generation Workflow & Hardware Routing</Trans>
                    </label>
                    <label className="flex items-start gap-2.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={settings.quick_export || false}
                        onChange={(e) => {
                          updateSettings({ quick_export: e.target.checked });
                          setIsDirty(true);
                        }}
                        className="mt-0.5 w-4 h-4 rounded border-zinc-300 text-navi focus:ring-navi"
                      />
                      <div className="flex flex-col">
                        <span className="text-xs font-semibold text-zinc-800 dark:text-zinc-200">
                          <Trans>
                            Quick Export (Auto-stitch on generation)
                          </Trans>
                        </span>
                        <span className="text-[10px] text-zinc-500">
                          <Trans>
                            Skips asset review and automatically stitches &
                            exports finished video
                          </Trans>
                        </span>
                      </div>
                    </label>

                    <div className="pt-2">
                      <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                        <Trans>Hardware Spec Mode (Regeneration Routing)</Trans>
                      </label>
                      <select
                        value={settings.hardware_spec_override || "auto"}
                        onChange={(e) => {
                          updateSettings({
                            hardware_spec_override: e.target.value as any,
                          });
                          setIsDirty(true);
                        }}
                        className="w-full mt-1 bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi"
                      >
                        <option value="auto">
                          <Trans>Auto-Detect (Recommended)</Trans>
                        </option>
                        <option value="low">
                          <Trans>Low-spec Mode</Trans>
                        </option>
                        <option value="high">
                          <Trans>High-spec Mode</Trans>
                        </option>
                      </select>
                    </div>
                  </div>

                  <div className="space-y-2 pt-4 border-t border-zinc-100 dark:border-navidark-700">
                    <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                      <Trans>Subtitle Format</Trans>
                    </label>

                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                          <Trans>Font</Trans>
                        </label>
                        <input
                          type="text"
                          value={settings.subtitle_font || "Calibri"}
                          onChange={(e) => {
                            updateSettings({ subtitle_font: e.target.value });
                            setIsDirty(true);
                          }}
                          className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                          <Trans>Font Size</Trans>
                        </label>
                        <input
                          type="number"
                          value={settings.subtitle_font_size || 30}
                          onChange={(e) => {
                            updateSettings({
                              subtitle_font_size: Number(e.target.value),
                            });
                            setIsDirty(true);
                          }}
                          className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                          <Trans>Primary Color (ASS)</Trans>
                        </label>
                        <input
                          type="text"
                          value={settings.subtitle_color || "&H00FFFFFF"}
                          onChange={(e) => {
                            updateSettings({ subtitle_color: e.target.value });
                            setIsDirty(true);
                          }}
                          className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                          <Trans>Outline Color (ASS)</Trans>
                        </label>
                        <input
                          type="text"
                          value={
                            settings.subtitle_outline_color || "&H00000000"
                          }
                          onChange={(e) => {
                            updateSettings({
                              subtitle_outline_color: e.target.value,
                            });
                            setIsDirty(true);
                          }}
                          className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* AI MODELS TAB */}
            {activeTab === "ai" && <AiModelsTab />}
          </div>
        </div>

        {/* Footer Section */}
        <div className="px-5 py-3 border-t border-zinc-100 dark:border-navidark-400 bg-zinc-50/50 dark:bg-navidark-800 flex justify-end shrink-0">
          <button
            onClick={() => setShowAppSettings(false)}
            className="px-5 py-2 bg-navi hover:bg-navi-600 text-white text-xs font-bold rounded-lg transition-colors shadow-sm"
          >
            <Trans>Done</Trans>
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
      className={`w-full flex items-center gap-2 px-3 py-2 text-xs font-bold rounded-md transition-colors text-nowrap ${
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

function AiModelsTab() {
  const { settings, updateSettings, setIsDirty } = useWorkspace();
  const { i18n } = useLingui();
  const [localModels, setLocalModels] = useState<string[]>([]);
  const [downloading, setDownloading] = useState<{
    [key: string]: {
      status: string;
      progress: number;
      controller?: AbortController;
    };
  }>({});

  useEffect(() => {
    getLocalModels().then(setLocalModels);
  }, []);

  const recommendedModels = [
    {
      id: "schroneko/gemma-2-2b-jpn-it",
      name: "Gemma 2 (2B JPN IT)",
      size: "~1.5GB",
    },
    { id: "gemma2:2b", name: "Gemma 2 (2B)", size: "~1.6GB" },
    { id: "qwen2.5:3b", name: "Qwen 2.5 (3B)", size: "~1.9GB" },
  ];

  const handleDownload = async (modelId: string) => {
    const controller = new AbortController();
    setDownloading((prev) => ({
      ...prev,
      [modelId]: { status: i18n._("Starting..."), progress: 0, controller },
    }));

    try {
      await pullModelStream(
        modelId,
        (status, completed, total) => {
          let progress = 0;
          if (completed && total)
            progress = Math.round((completed / total) * 100);

          setDownloading((prev) => {
            if (!prev[modelId]) return prev;
            return {
              ...prev,
              [modelId]: {
                ...prev[modelId],
                status,
                progress: progress || prev[modelId].progress,
              },
            };
          });
        },
        controller.signal,
      );

      // on complete
      setDownloading((prev) => {
        const next = { ...prev };
        delete next[modelId];
        return next;
      });

      // Refresh models
      const updated = await getLocalModels();
      setLocalModels(updated);
    } catch (error: any) {
      console.error("Download failed:", error);
      if (error.name === "AbortError" || error.message?.includes("Abort")) {
        setDownloading((prev) => {
          const next = { ...prev };
          delete next[modelId];
          return next;
        });
      } else {
        setDownloading((prev) => {
          if (!prev[modelId]) return prev;
          // Extract a short error message
          const errMsg = error.message || String(error);
          return {
            ...prev,
            [modelId]: {
              ...prev[modelId],
              status: `Failed: ${errMsg}`,
              progress: 0,
            },
          };
        });
      }
    }
  };

  const handleCancel = (modelId: string) => {
    downloading[modelId]?.controller?.abort();
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-300">
      <div className="space-y-3">
        <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
          <Sparkles className="w-3.5 h-3.5" />{" "}
          <Trans>Recommended AI Models</Trans>
        </label>

        <div className="border border-zinc-200 dark:border-navidark-400 rounded-lg overflow-hidden bg-white dark:bg-navidark-800">
          <table className="w-full text-left text-sm text-zinc-700 dark:text-zinc-300">
            <thead className="bg-zinc-50 dark:bg-navidark-800 border-b border-zinc-200 dark:border-navidark-400">
              <tr>
                <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider text-zinc-500">
                  <Trans>Model</Trans>
                </th>
                <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider text-zinc-500">
                  <Trans>Size</Trans>
                </th>
                <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider text-zinc-500 w-48">
                  <Trans>Action</Trans>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-navidark-400">
              {recommendedModels.map((model) => {
                const isLocal = localModels.includes(model.id);
                const dlStatus = downloading[model.id];
                const isDownloading = !!dlStatus;

                return (
                  <tr
                    key={model.id}
                    className="hover:bg-zinc-50/50 dark:hover:bg-white/5 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div className="font-bold text-zinc-900 dark:text-zinc-100">
                        {model.name}
                      </div>
                      <div className="text-[11px] font-mono text-zinc-500 dark:text-zinc-400 mt-0.5">
                        {model.id}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-zinc-500">
                      {model.size}
                    </td>
                    <td className="px-4 py-3">
                      {isDownloading ? (
                        <div className="flex items-center gap-2">
                          <div className="flex flex-col gap-1.5 w-full min-w-24">
                            <span
                              className={`text-[10px] truncate font-medium ${dlStatus.status === "Failed" ? "text-red-500" : "text-navi"}`}
                            >
                              {dlStatus.status}
                            </span>
                            <div className="w-full bg-zinc-200 dark:bg-navidark-600 h-1.5 rounded-full overflow-hidden">
                              <div
                                className={`h-full transition-all duration-300 ease-out ${dlStatus.status === "Failed" ? "bg-red-500" : "bg-navi"}`}
                                style={{ width: `${dlStatus.progress}%` }}
                              />
                            </div>
                          </div>
                          <button
                            onClick={() => handleCancel(model.id)}
                            className="p-1 rounded-md text-zinc-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 transition-colors shrink-0"
                            title={
                              dlStatus.status === "Failed"
                                ? "Clear"
                                : "Cancel download"
                            }
                          >
                            <X className="w-4 h-4" />
                          </button>
                        </div>
                      ) : isLocal ? (
                        <div className="flex items-center gap-1.5 px-2 py-1 bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 rounded text-xs font-bold w-max">
                          <CheckCircle2 className="w-3.5 h-3.5" />{" "}
                          <Trans>Ready</Trans>
                        </div>
                      ) : (
                        <button
                          onClick={() => handleDownload(model.id)}
                          className="px-3 py-1.5 bg-zinc-100 hover:bg-zinc-200 dark:bg-navidark-700 dark:hover:bg-navidark-600 text-zinc-700 dark:text-zinc-200 text-[11px] font-bold rounded-md transition-colors w-full border border-zinc-200/50 dark:border-white/5"
                        >
                          <Trans>Download</Trans>
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="space-y-3 pt-4 border-t border-zinc-100 dark:border-navidark-700">
        <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
          <Sparkles className="w-3.5 h-3.5" /> <Trans>Active Model</Trans>
        </label>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          <Trans>
            Select which model to use for narration synthesis, only downloaded
            models are shown
          </Trans>
        </p>
        <select
          value={settings.ai_model || "schroneko/gemma-2-2b-jpn-it"}
          onChange={(e) => {
            updateSettings({ ai_model: e.target.value });
            setIsDirty(true);
          }}
          className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2.5 text-sm font-medium text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
        >
          {localModels.length === 0 ? (
            <option value="" disabled>
              <Trans>No models installed</Trans>
            </option>
          ) : (
            localModels.map((modelId) => (
              <option key={modelId} value={modelId}>
                {modelId}
              </option>
            ))
          )}
        </select>
      </div>
    </div>
  );
}
