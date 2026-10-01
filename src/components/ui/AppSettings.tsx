import { useLingui } from "@lingui/react";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
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
  Check,
  CheckCircle2,
  Film,
  Key,
  MapPin,
  Mic,
  Monitor,
  Moon,
  NaviviType,
  Palette,
  Plus,
  Settings,
  Sparkles,
  Sun,
  Trash2,
  Volume2,
  X,
} from "./icons";
import { Switch } from "./Switch";
import { VoiceTab } from "./VoiceSettings";

type SettingsTab =
  | "general"
  | "appearance"
  | "api"
  | "video"
  | "ai"
  | "voice"
  | "tts_dictionary";

const inputClass =
  "h-8 min-w-0 px-2.5 rounded-lg bg-white dark:bg-zinc-950/40 border border-zinc-200 dark:border-white/10 text-[13px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition";
const selectClass = `${inputClass} pr-7 cursor-pointer`;
const secondaryButton =
  "inline-flex items-center justify-center gap-1.5 h-8 px-3 rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-white/5 text-[12px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-white/10 transition-colors";

export function AppSettings() {
  const { settings, updateSettings, setIsDirty } = useWorkspace();
  const { i18n } = useLingui();
  const { showAppSettings, setShowAppSettings, currentView } = useUI();
  const { theme, setTheme, accentTheme, setAccentTheme } = useTheme();

  const [activeTab, setActiveTab] = useState<SettingsTab>("general");

  useEffect(() => {
    const handleOpenTab = (e: CustomEvent) => {
      if (e.detail) {
        setActiveTab(e.detail as SettingsTab);
      }
    };
    window.addEventListener("open-app-settings-tab" as any, handleOpenTab);
    return () =>
      window.removeEventListener("open-app-settings-tab" as any, handleOpenTab);
  }, []);
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

  useEffect(() => {
    if (activeTab === "ai" && !settings.ai_features_enabled) setActiveTab("general");
  }, [activeTab, settings.ai_features_enabled]);

  if (!shouldRender) return null;

  const autoSaveInterval = settings.auto_save_interval ?? 3;

  const updateProject = (patch: Parameters<typeof updateSettings>[0]) => {
    updateSettings(patch);
    setIsDirty(true);
  };

  const tabs: { id: SettingsTab; icon: any; label: string }[] = [
    { id: "general", icon: Settings, label: t`General` },
    { id: "appearance", icon: Palette, label: t`Appearance` },
    { id: "api", icon: Key, label: t`API keys` },
    { id: "video", icon: Film, label: t`Video` },
    { id: "voice", icon: Volume2, label: t`Voice` },
    { id: "tts_dictionary", icon: Mic, label: t`Pronunciation` },
    ...(settings.ai_features_enabled
      ? [{ id: "ai" as const, icon: Sparkles, label: t`AI models` }]
      : []),
  ];
  const activeLabel = tabs.find((tab) => tab.id === activeTab)?.label;

  const dictionary = settings.pronunciation_dictionary || [];
  const setDictionary = (next: typeof dictionary) =>
    updateProject({ pronunciation_dictionary: next });

  const markerSrc = (marker: string) =>
    marker.startsWith("/") && !marker.startsWith("/defaults/")
      ? convertFileSrc(marker)
      : marker.match(/^[a-zA-Z]:\\/)
        ? convertFileSrc(marker)
        : marker;

  return createPortal(
    <div
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) setShowAppSettings(false);
      }}
      className={`fixed inset-x-0 top-10 bottom-0 z-99999 flex items-center justify-center p-4 bg-zinc-950/30 backdrop-blur-[2px] select-none ${isAnimatingOut ? "animate-out fade-out duration-150" : "animate-in fade-in duration-150"}`}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t`Settings`}
        className={`flex w-184 max-w-full h-144 max-h-full rounded-2xl overflow-hidden bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-2xl ${isAnimatingOut ? "animate-out zoom-out-95 duration-150" : "animate-in zoom-in-95 duration-150"}`}
      >
        <nav className="w-48 max-[700px]:w-40 shrink-0 flex flex-col p-2 bg-zinc-50 dark:bg-black/20 border-r border-zinc-200/80 dark:border-white/5">
          <h2 className="px-2.5 pt-2 pb-3 text-[13px] font-semibold text-zinc-900 dark:text-zinc-100">
            <Trans>Settings</Trans>
          </h2>
          <div role="tablist" aria-orientation="vertical" className="flex flex-col gap-0.5">
            {tabs.map(({ id, icon: Icon, label }) => {
              const active = activeTab === id;
              return (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setActiveTab(id)}
                  className={`flex items-center gap-2.5 h-8 px-2.5 rounded-lg text-[13px] text-left whitespace-nowrap transition-colors ${
                    active
                      ? "bg-navi/10 text-navi font-medium"
                      : "text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200/60 dark:hover:bg-white/5 hover:text-zinc-900 dark:hover:text-zinc-100"
                  }`}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  {label}
                </button>
              );
            })}
          </div>
          <NaviviType className="mt-auto mb-2 mx-2.5 h-3.5 self-start text-zinc-300 dark:text-zinc-700" />
        </nav>

        <div className="flex-1 min-w-0 flex flex-col">
          <header className="flex items-center justify-between h-12 pl-6 pr-3 shrink-0 border-b border-zinc-100 dark:border-white/5">
            <h3 className="text-[14px] font-semibold text-zinc-900 dark:text-zinc-100">
              {activeLabel}
            </h3>
            <button
              type="button"
              onClick={() => setShowAppSettings(false)}
              aria-label={t`Close`}
              title={t`Close`}
              className="flex items-center justify-center w-8 h-8 rounded-lg text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/5 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </header>

          <div
            key={activeTab}
            className="flex-1 overflow-y-auto custom-scrollbar px-6 py-5 space-y-6 animate-in fade-in duration-150"
          >
            {activeTab === "general" && (
              <>
                <Section title={t`Application`}>
                  <Row
                    title={t`Language`}
                    description={t`Choose your preferred language for the application`}
                  >
                    <select
                      value={i18n.locale}
                      onChange={(e) => {
                        const newLocale = e.target.value;
                        localStorage.setItem("navivi_locale", newLocale);
                        dynamicActivate(newLocale);
                      }}
                      className={`${selectClass} w-40`}
                    >
                      <option value="en">English</option>
                      <option value="ja">日本語</option>
                    </select>
                  </Row>
                  <Row
                    title={t`Auto-save`}
                    description={t`Controls auto save of editors that have unsaved changes`}
                  >
                    <select
                      value={autoSaveInterval}
                      onChange={(e) =>
                        updateSettings({
                          auto_save_interval: parseInt(e.target.value),
                        })
                      }
                      className={`${selectClass} w-40`}
                    >
                      <option value={0}>{t`Off`}</option>
                      <option value={3}>{t`3 seconds`}</option>
                      <option value={30}>{t`30 seconds`}</option>
                      <option value={60}>{t`1 minute`}</option>
                      <option value={600}>{t`10 minutes`}</option>
                    </select>
                  </Row>
                </Section>

                {currentView === "editor" && (
                  <Section
                    title={t`This project`}
                    hint={t`Saved with the project`}
                  >
                    <Row
                      title={t`AI features`}
                      badge={<Badge tone="violet">{t`Requires Ollama`}</Badge>}
                      description={t`Show Auto-Write script buttons and overview narration. Requires Ollama to be installed and running locally.`}
                    >
                      <Switch
                        checked={!!settings.ai_features_enabled}
                        onChange={(v) => updateProject({ ai_features_enabled: v })}
                        label={t`AI features`}
                      />
                    </Row>
                    <Row
                      title={t`Fast render mode`}
                      description={t`Skip AI voiceover synthesis and pop-up images during generation`}
                    >
                      <Switch
                        checked={!!settings.skip_rich_media}
                        onChange={(v) => updateProject({ skip_rich_media: v })}
                        label={t`Fast render mode`}
                      />
                    </Row>
                    <Row
                      title={t`Historical weather`}
                      badge={<Badge tone="amber">{t`Experimental`}</Badge>}
                      description={t`Synchronize historical weather conditions from photo EXIF dates using Open-Meteo to dynamically apply atmospheric fog and rain effects`}
                    >
                      <Switch
                        checked={!!settings.weather_sync_enabled}
                        onChange={(v) => updateProject({ weather_sync_enabled: v })}
                        label={t`Historical weather`}
                      />
                    </Row>
                  </Section>
                )}
              </>
            )}

            {activeTab === "appearance" && (
              <>
                <Section title={t`Interface`}>
                  <Row title={t`Theme`}>
                    <div className="flex items-center p-0.5 rounded-lg bg-zinc-100 dark:bg-white/5">
                      {[
                        { id: "light", icon: Sun, label: i18n._("Light") },
                        { id: "dark", icon: Moon, label: i18n._("Dark") },
                        { id: "system", icon: Monitor, label: i18n._("System") },
                      ].map((option) => (
                        <button
                          key={option.id}
                          type="button"
                          aria-pressed={theme === option.id}
                          onClick={() => setTheme(option.id as any)}
                          className={`flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[12px] font-medium transition-colors ${
                            theme === option.id
                              ? "bg-white dark:bg-zinc-800 text-navi shadow-sm"
                              : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
                          }`}
                        >
                          <option.icon className="w-3.5 h-3.5" /> {option.label}
                        </button>
                      ))}
                    </div>
                  </Row>
                  <Row title={t`Accent colour`}>
                    <div className="flex items-center gap-2">
                      {[
                        { id: "navi", color: "#4287f5", label: i18n._("Navi Blue") },
                        { id: "emerald", color: "#10b981", label: i18n._("Emerald") },
                        { id: "violet", color: "#8b5cf6", label: i18n._("Violet") },
                        { id: "amber", color: "#f59e0b", label: i18n._("Amber") },
                        { id: "rose", color: "#f43f5e", label: i18n._("Rose") },
                      ].map((swatch) => {
                        const selected = accentTheme === swatch.id;
                        return (
                          <button
                            key={swatch.id}
                            type="button"
                            onClick={() => setAccentTheme(swatch.id as any)}
                            title={swatch.label}
                            aria-label={swatch.label}
                            aria-pressed={selected}
                            style={{ backgroundColor: swatch.color }}
                            className={`w-6 h-6 rounded-full flex items-center justify-center transition ring-offset-2 ring-offset-white dark:ring-offset-zinc-900 ${
                              selected ? "ring-2 ring-zinc-900/25 dark:ring-white/40" : "hover:scale-110"
                            }`}
                          >
                            {selected && <Check className="w-3.5 h-3.5 text-white" strokeWidth={3} />}
                          </button>
                        );
                      })}
                    </div>
                  </Row>
                </Section>

                <Section title={t`Map`}>
                  <Row
                    title={t`Route marker`}
                    description={t`Default marker for all waypoints. Can be overridden per-stop.`}
                    stacked
                  >
                    <div className="flex items-center gap-2 flex-wrap">
                      <MarkerTile
                        selected={!settings.routeMarker}
                        onClick={() => updateProject({ routeMarker: "" })}
                        label={t`Default pin`}
                      >
                        <MapPin className="w-4.5 h-4.5 text-zinc-400" />
                      </MarkerTile>
                      {[
                        "/defaults/markers/map_pin.svg",
                        "/defaults/markers/walking.svg",
                        "/defaults/markers/car.svg",
                      ].map((preset) => (
                        <MarkerTile
                          key={preset}
                          selected={settings.routeMarker === preset}
                          onClick={() => updateProject({ routeMarker: preset })}
                          label={preset.split("/").pop()!.replace(".svg", "")}
                        >
                          <img src={preset} alt="" className="w-6 h-6 object-contain" />
                        </MarkerTile>
                      ))}
                      {settings.routeMarker &&
                        !settings.routeMarker.startsWith("/defaults/") && (
                          <MarkerTile selected onClick={() => {}} label={t`Custom Marker`}>
                            <img
                              src={markerSrc(settings.routeMarker)}
                              alt=""
                              className="w-6 h-6 object-contain"
                            />
                          </MarkerTile>
                        )}
                      <button
                        type="button"
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
                            updateProject({ routeMarker: selected });
                          }
                        }}
                        className={`${secondaryButton} ml-1`}
                      >
                        <Trans>Choose file…</Trans>
                      </button>
                    </div>
                  </Row>
                  <Row
                    title={t`Elevation heatmap`}
                    description={t`Color GPX routes dynamically based on steepness`}
                  >
                    <Switch
                      checked={!!settings.show_route_heatmap}
                      onChange={(v) => updateProject({ show_route_heatmap: v })}
                      label={t`Elevation heatmap`}
                    />
                  </Row>
                </Section>
              </>
            )}

            {activeTab === "api" && (
              <Section title={t`Services`}>
                <Row
                  title={t`Mapbox`}
                  description={t`Required for map rendering and 3D terrain`}
                  stacked
                >
                  <input
                    type="text"
                    value={settings.mapbox_api_key || ""}
                    onChange={(e) => updateProject({ mapbox_api_key: e.target.value })}
                    placeholder="pk.eyJ1..."
                    spellCheck={false}
                    className={`${inputClass} w-full text-[12px]`}
                  />
                </Row>
                <Row
                  title={t`OpenRouteService`}
                  description={t`Required for driving and some hiking routes`}
                  stacked
                >
                  <input
                    type="text"
                    value={settings.ors_api_key || ""}
                    onChange={(e) => updateProject({ ors_api_key: e.target.value })}
                    placeholder={t`API key`}
                    spellCheck={false}
                    className={`${inputClass} w-full text-[12px]`}
                  />
                </Row>
              </Section>
            )}

            {activeTab === "video" && (
              <>
                <Section title={t`Output`}>
                  <Row title={t`Target FPS`}>
                    <NumberInput
                      value={settings.fps || 60}
                      onChange={(v) => updateProject({ fps: v })}
                    />
                  </Row>
                  <Row title={t`Duration`} description={t`Seconds`}>
                    <NumberInput
                      value={settings.duration_seconds || 15}
                      onChange={(v) => updateProject({ duration_seconds: v })}
                    />
                  </Row>
                  <Row title={t`Residential duration`} description={t`Seconds`}>
                    <NumberInput
                      value={settings.res_duration || 5}
                      onChange={(v) => updateProject({ res_duration: v })}
                    />
                  </Row>
                </Section>

                <Section title={t`Generation`}>
                  <Row
                    title={t`Quick export`}
                    description={t`Skips asset review and automatically stitches & exports finished video`}
                  >
                    <Switch
                      checked={!!settings.quick_export}
                      onChange={(v) => updateProject({ quick_export: v })}
                      label={t`Quick export`}
                    />
                  </Row>
                  <Row
                    title={t`Hardware mode`}
                    description={t`Which pipeline to use when regenerating assets`}
                  >
                    <select
                      value={settings.hardware_spec_override || "auto"}
                      onChange={(e) =>
                        updateProject({ hardware_spec_override: e.target.value as any })
                      }
                      className={`${selectClass} w-56`}
                    >
                      <option value="auto">{t`Auto-Detect (Recommended)`}</option>
                      <option value="low">{t`Low-spec Mode`}</option>
                      <option value="high">{t`High-spec Mode`}</option>
                    </select>
                  </Row>
                </Section>

                <Section title={t`Subtitles`}>
                  <Row title={t`Font`}>
                    <input
                      type="text"
                      value={settings.subtitle_font || "Calibri"}
                      onChange={(e) => updateProject({ subtitle_font: e.target.value })}
                      className={`${inputClass} w-48`}
                    />
                  </Row>
                  <Row title={t`Font size`}>
                    <NumberInput
                      value={settings.subtitle_font_size || 30}
                      onChange={(v) => updateProject({ subtitle_font_size: v })}
                    />
                  </Row>
                  <Row title={t`Text colour`} description={t`ASS colour, e.g. &H00FFFFFF`}>
                    <input
                      type="text"
                      value={settings.subtitle_color || "&H00FFFFFF"}
                      onChange={(e) => updateProject({ subtitle_color: e.target.value })}
                      spellCheck={false}
                      className={`${inputClass} w-36 text-[12px] tabular-nums`}
                    />
                  </Row>
                  <Row title={t`Outline colour`} description={t`ASS colour, e.g. &H00000000`}>
                    <input
                      type="text"
                      value={settings.subtitle_outline_color || "&H00000000"}
                      onChange={(e) =>
                        updateProject({ subtitle_outline_color: e.target.value })
                      }
                      spellCheck={false}
                      className={`${inputClass} w-36 text-[12px] tabular-nums`}
                    />
                  </Row>
                </Section>
              </>
            )}

            {activeTab === "voice" && <VoiceTab />}

            {activeTab === "tts_dictionary" && (
              <>
                <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400 select-text">
                  <Trans>
                    Correct words or kanji that are read incorrectly by the AI
                    voice. You can auto-extract entries from scripts by typing{" "}
                    <code className="bg-zinc-100 dark:bg-zinc-800 px-1 rounded">
                      漢字(よみがな)
                    </code>{" "}
                    in any narration script.
                  </Trans>
                </p>

                <div className="rounded-xl border border-zinc-200 dark:border-white/10 overflow-hidden">
                  {dictionary.length > 0 ? (
                    <>
                      <div className="flex items-center gap-2 h-8 px-3 bg-zinc-50 dark:bg-white/3 border-b border-zinc-200 dark:border-white/10 text-[11px] font-medium text-zinc-500">
                        <span className="flex-1">
                          <Trans>Word / Kanji</Trans>
                        </span>
                        <span className="flex-1">
                          <Trans>Reading (Furigana)</Trans>
                        </span>
                        <span className="w-7" />
                      </div>
                      <div className="divide-y divide-zinc-100 dark:divide-white/5">
                        {dictionary.map((entry, idx) => (
                          <div key={idx} className="group flex items-center gap-2 px-2 py-1.5">
                            <input
                              type="text"
                              placeholder={t`Word (e.g. 加太)`}
                              value={entry.word}
                              onChange={(e) => {
                                const next = [...dictionary];
                                next[idx] = { ...next[idx], word: e.target.value };
                                setDictionary(next);
                              }}
                              className={`${inputClass} flex-1 border-transparent dark:border-transparent bg-transparent dark:bg-transparent hover:border-zinc-200 dark:hover:border-white/10`}
                            />
                            <input
                              type="text"
                              placeholder={t`Reading (e.g. かだ)`}
                              value={entry.reading}
                              onChange={(e) => {
                                const next = [...dictionary];
                                next[idx] = { ...next[idx], reading: e.target.value };
                                setDictionary(next);
                              }}
                              className={`${inputClass} flex-1 border-transparent dark:border-transparent bg-transparent dark:bg-transparent hover:border-zinc-200 dark:hover:border-white/10`}
                            />
                            <button
                              type="button"
                              onClick={() => setDictionary(dictionary.filter((_, i) => i !== idx))}
                              aria-label={t`Remove`}
                              title={t`Remove`}
                              className="flex items-center justify-center w-7 h-7 rounded-lg text-zinc-400 opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-red-500 hover:bg-red-500/10 transition"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="py-10 text-center">
                      <Mic className="w-6 h-6 mx-auto mb-2 text-zinc-300 dark:text-zinc-600" />
                      <p className="text-[13px] text-zinc-600 dark:text-zinc-300">
                        <Trans>No entries yet.</Trans>
                      </p>
                      <p className="text-[12px] text-zinc-400 mt-0.5">
                        <Trans>
                          Add words below or extract them from narration
                          scripts.
                        </Trans>
                      </p>
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setDictionary([...dictionary, { word: "", reading: "" }])}
                    className={secondaryButton}
                  >
                    <Plus className="w-3.5 h-3.5" /> <Trans>Add word</Trans>
                  </button>

                  {dictionary.some((e) => !e.reading && e.word) && (
                    <button
                      type="button"
                      onClick={async () => {
                        const emptyWords = dictionary
                          .filter((e) => e.word && !e.reading)
                          .map((e) => e.word);
                        if (emptyWords.length === 0) return;

                        try {
                          const res = await invoke<string>("run_python_blueprint", {
                            action: "get_furigana",
                            payload: JSON.stringify(emptyWords),
                          });
                          const parsed = JSON.parse(res);
                          if (parsed.success && parsed.readings) {
                            setDictionary(
                              dictionary.map((e) => ({
                                ...e,
                                reading:
                                  !e.reading && parsed.readings[e.word]
                                    ? parsed.readings[e.word]
                                    : e.reading,
                              })),
                            );
                          }
                        } catch (err) {
                          console.error("get_furigana failed:", err);
                        }
                      }}
                      className={secondaryButton}
                    >
                      <Trans>Auto-fill readings</Trans>
                    </button>
                  )}
                </div>
              </>
            )}

            {activeTab === "ai" && settings.ai_features_enabled && <AiModelsTab />}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}


function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="flex items-baseline justify-between mb-2 px-0.5">
        <h4 className="text-[12px] font-semibold text-zinc-500 dark:text-zinc-400">{title}</h4>
        {hint && <span className="text-[11px] text-zinc-400 dark:text-zinc-500">{hint}</span>}
      </div>
      <div className="rounded-xl border border-zinc-200 dark:border-white/10 divide-y divide-zinc-100 dark:divide-white/5">
        {children}
      </div>
    </section>
  );
}

function Row({
  title,
  description,
  badge,
  stacked,
  children,
}: {
  title: string;
  description?: string;
  badge?: React.ReactNode;
  stacked?: boolean;
  children: React.ReactNode;
}) {
  const text = (
    <div className="min-w-0">
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100">{title}</span>
        {badge}
      </div>
      {description && (
        <p className="mt-0.5 text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
          {description}
        </p>
      )}
    </div>
  );
  if (stacked) {
    return (
      <div className="px-4 py-3 space-y-2.5">
        {text}
        {children}
      </div>
    );
  }
  return (
    <div className="flex items-center justify-between gap-6 px-4 py-3">
      {text}
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function Badge({ tone, children }: { tone: "violet" | "amber"; children: React.ReactNode }) {
  const tones = {
    violet: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
    amber: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
  };
  return (
    <span className={`h-4.5 px-1.5 inline-flex items-center rounded-md text-[10px] font-medium whitespace-nowrap ${tones[tone]}`}>
      {children}
    </span>
  );
}

function NumberInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className={`${inputClass} w-24 text-right tabular-nums`}
    />
  );
}

function MarkerTile({
  selected,
  onClick,
  label,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={selected}
      className={`w-10 h-10 rounded-lg border flex items-center justify-center transition-colors ${
        selected
          ? "border-navi bg-navi/10 ring-2 ring-navi/20"
          : "border-zinc-200 dark:border-white/10 hover:bg-zinc-50 dark:hover:bg-white/5"
      }`}
    >
      {children}
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
      failed?: boolean;
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
              failed: true,
            },
          };
        });
      }
    }
  };

  const handleCancel = (modelId: string) => {
    const entry = downloading[modelId];
    if (entry?.failed) {
      setDownloading((prev) => {
        const next = { ...prev };
        delete next[modelId];
        return next;
      });
      return;
    }
    entry?.controller?.abort();
  };

  return (
    <>
      <Section title={t`Narration`}>
        <Row
          title={t`Active model`}
          description={t`Select which model to use for narration synthesis, only downloaded models are shown`}
        >
          <select
            value={settings.ai_model || "schroneko/gemma-2-2b-jpn-it"}
            onChange={(e) => {
              updateSettings({ ai_model: e.target.value });
              setIsDirty(true);
            }}
            className={`${selectClass} w-52`}
          >
            {localModels.length === 0 ? (
              <option value="" disabled>
                {t`No models installed`}
              </option>
            ) : (
              localModels.map((modelId) => (
                <option key={modelId} value={modelId}>
                  {modelId}
                </option>
              ))
            )}
          </select>
        </Row>
      </Section>

      <Section title={t`Recommended models`}>
        {recommendedModels.map((model) => {
          const isLocal = localModels.some(
            (local) => local === model.id || local.startsWith(model.id + ":"),
          );
          const dlStatus = downloading[model.id];

          return (
            <div key={model.id} className="flex items-center gap-4 px-4 py-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
                    {model.name}
                  </span>
                  <span className="text-[11px] text-zinc-400 tabular-nums">{model.size}</span>
                </div>
                <div className="text-[11px] tracking-tight text-zinc-500 dark:text-zinc-400 truncate select-text">
                  {model.id}
                </div>
              </div>

              <div className="w-40 shrink-0 flex justify-end">
                {dlStatus ? (
                  <div className="flex items-center gap-2 w-full">
                    <div className="flex-1 min-w-0 space-y-1">
                      <span
                        title={dlStatus.status}
                        className={`block text-[11px] truncate ${dlStatus.failed ? "text-red-500" : "text-zinc-500"}`}
                      >
                        {dlStatus.status}
                      </span>
                      <div className="h-1 rounded-full overflow-hidden bg-zinc-200 dark:bg-white/10">
                        <div
                          className={`h-full transition-all duration-300 ease-out ${dlStatus.failed ? "bg-red-500" : "bg-navi"}`}
                          style={{ width: `${dlStatus.progress}%` }}
                        />
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleCancel(model.id)}
                      className="flex items-center justify-center w-7 h-7 rounded-lg text-zinc-400 hover:text-red-500 hover:bg-red-500/10 transition-colors shrink-0"
                      title={dlStatus.failed ? t`Clear` : t`Cancel download`}
                      aria-label={dlStatus.failed ? t`Clear` : t`Cancel download`}
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ) : isLocal ? (
                  <span className="inline-flex items-center gap-1 text-[12px] font-medium text-emerald-600 dark:text-emerald-400">
                    <CheckCircle2 className="w-3.5 h-3.5" /> <Trans>Ready</Trans>
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => handleDownload(model.id)}
                    className={secondaryButton}
                  >
                    <Trans>Download</Trans>
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </Section>
    </>
  );
}
