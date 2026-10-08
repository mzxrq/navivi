import { useLingui } from "@lingui/react";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { Fragment, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useAnimatedUnmount } from "../../hooks/useAnimatedUnmount";
import { MAP_PANEL_OPACITY, setMapPanelOpacity, useMapPanelOpacity } from "../../hooks/useMapPanelOpacity";
import { useTheme } from "../../hooks/useTheme";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import {
  getLocalModels,
  modelSeesPhotos,
  getModelSizes,
  pullModelStream,
} from "../../services/ollamaApi";
import { callSidecar, systemRamGb } from "../../services/sidecar";
import { DEFAULT_LOCAL_MODEL } from "../../services/ai/engine";
import { modelFit } from "../../utils/modelFit";
import { CaptionStyleFields } from "./CaptionStyleFields";
import { resolveCaptionStyle } from "../../utils/textStyle";
import type { TextStyle, VideoTextLanguage } from "../../types";
import { Segmented } from "./Segmented";
import { dynamicActivate } from "../../i18n";
import { db } from "../../services/db";
import { GLOBAL_DICTIONARY_KEY } from "../../config/constants";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Film,
  SlidersHorizontal,
  Key,
  MapPin,
  Download,
  ExternalLink,
  Info,
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
import { assOpacity, assToRgb, rgbToAss, withOpacity } from "../../utils/assColor";
import { CAPTION } from "../../utils/subtitleLook";
import { ColorSwatches, type RGB } from "./ColorSwatches";
import { ComboBox } from "./ComboBox";
import { Slider } from "./Slider";
import { SubtitleSample } from "./SubtitleSample";
import { StepButtons } from "./StepButtons";
import { Switch } from "./Switch";
import { VoiceTab } from "./VoiceSettings";
import { OnlineProviderSettings, ProviderPicker } from "./OnlineAiSettings";
import { ComponentsChecklist } from "./ComponentsChecklist";
import { AboutPanel } from "./AboutPanel";
import { CaptionPreview } from "./CaptionPreview";
import { inputClass, Row, secondaryButton, Section } from "./SettingsParts";
import { Select } from "./Select";
import { OpenProjectSettings } from "../view/ProjectSettingsModal";
import { isOnlineProvider, type OnlineProvider } from "../../services/ai/providers";

type SettingsTab =
  | "general"
  | "appearance"
  | "api"
  | "project"
  | "video"
  | "ai"
  | "voice"
  | "setup"
  | "about"
  | "tts_dictionary";

const WHITE: RGB = [255, 255, 255];
const BLACK: RGB = [0, 0, 0];

const SUBTITLE_SIZES = ["12", "14", "16", "18", "20", "22", "24", "28", "32"];
// Common fonts; the saved one is always listed, so a project made with another font keeps it.
const SUBTITLE_FONTS = [
  "Yu Gothic UI",
  "Yu Gothic",
  "Meiryo",
  "Meiryo UI",
  "MS Gothic",
  "MS PGothic",
  "BIZ UDPGothic",
  "Noto Sans JP",
  "Noto Serif JP",
  "Segoe UI",
  "Calibri",
  "Arial",
  "Verdana",
  "Tahoma",
  "Times New Roman",
  "Georgia",
  "Consolas",
];
const subtitleFonts = (current: string) =>
  SUBTITLE_FONTS.some((f) => f.toLowerCase() === current.toLowerCase())
    ? SUBTITLE_FONTS
    : [current, ...SUBTITLE_FONTS];

export function AppSettings() {
  const { settings, updateSettings, setIsDirty } = useWorkspace();
  const { i18n } = useLingui();
  const { showAppSettings, setShowAppSettings, currentView } = useUI();
  const { theme, setTheme, accentTheme, setAccentTheme } = useTheme();
  const mapPanelOpacity = useMapPanelOpacity();

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

  // Voice and video settings belong to a project; outside the editor only app-wide tabs are shown.
  const inEditor = currentView === "editor";
  useEffect(() => {
    if (activeTab === "ai" && !settings.ai_features_enabled)
      setActiveTab("general");
    if (!inEditor && (activeTab === "project" || activeTab === "video" || activeTab === "voice"))
      setActiveTab("general");
  }, [activeTab, settings.ai_features_enabled, inEditor]);

  const [dictScope, setDictScope] = useState<"project" | "global">("project");
  const [globalDictionary, setGlobalDictionary] = useState<DictionaryEntry[]>(
    [],
  );
  const globalSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!showAppSettings) return;
    db.appSettings
      .get<DictionaryEntry[]>(GLOBAL_DICTIONARY_KEY)
      .then((saved) => setGlobalDictionary(Array.isArray(saved) ? saved : []))
      .catch((err) =>
        console.error(
          "Could not load the shared pronunciation dictionary:",
          err,
        ),
      );
  }, [showAppSettings]);

  const saveGlobalDictionary = (next: DictionaryEntry[]) => {
    setGlobalDictionary(next);
    if (globalSaveTimer.current) clearTimeout(globalSaveTimer.current);
    globalSaveTimer.current = setTimeout(
      () =>
        db.appSettings
          .set(GLOBAL_DICTIONARY_KEY, next)
          .catch((err) =>
            console.error("Could not save the shared dictionary:", err),
          ),
      400,
    );
    if (inEditor) setIsDirty(true); // the open project keeps a copy, written on its next save
  };

  if (!shouldRender) return null;

  const autoSaveInterval = settings.auto_save_interval ?? 3;

  const updateProject = (patch: Parameters<typeof updateSettings>[0]) => {
    updateSettings(patch);
    setIsDirty(true);
  };

  type TabInfo = { id: SettingsTab; icon: any; label: string };
  const tabGroups: TabInfo[][] = [
    inEditor ? [{ id: "project", icon: SlidersHorizontal, label: t`Project` }] : [],
    inEditor
      ? [
          { id: "video", icon: Film, label: t`Video` },
          { id: "voice", icon: Volume2, label: t`Voice` },
        ]
      : [],
    [{ id: "tts_dictionary", icon: Mic, label: t`Pronunciation` }],
    [
      { id: "general", icon: Settings, label: t`General` },
      { id: "appearance", icon: Palette, label: t`Appearance` },
      { id: "api", icon: Key, label: t`API keys` },
      ...(settings.ai_features_enabled
        ? [{ id: "ai" as const, icon: Sparkles, label: t`AI models` }]
        : []),
      { id: "setup", icon: Download, label: t`Setup` },
      { id: "about", icon: Info, label: t`About` },
    ],
  ].filter((group) => group.length > 0) as TabInfo[][];
  const tabs = tabGroups.flat();
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
        className={`flex w-[clamp(46rem,78vw,72rem)] max-w-full h-[clamp(34rem,82vh,52rem)] max-h-full rounded-2xl overflow-hidden bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-2xl ${isAnimatingOut ? "animate-out zoom-out-95 duration-150" : "animate-in zoom-in-95 duration-150"}`}
      >
        <nav className="w-48 min-[1100px]:w-52 max-[700px]:w-40 shrink-0 flex flex-col p-2 bg-zinc-50 dark:bg-black/20 border-r border-zinc-200/80 dark:border-white/5">
          <h2 className="px-2.5 pt-2 pb-3 text-[13px] font-semibold text-zinc-900 dark:text-zinc-100">
            <Trans>Settings</Trans>
          </h2>
          <div
            role="tablist"
            aria-orientation="vertical"
            className="flex flex-col gap-0.5"
          >
            {tabGroups.map((group, index) => (
              <Fragment key={group[0].id}>
                {index > 0 && <div role="separator" className="my-1.5 mx-2.5 h-px bg-zinc-200/80 dark:bg-white/10" />}
                {group.map(({ id, icon: Icon, label }) => {
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
              </Fragment>
            ))}
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
            className="flex-1 overflow-y-auto custom-scrollbar px-6 py-5 animate-in fade-in duration-150"
          >
            <div className="space-y-6">
            {activeTab === "general" && (
              <>
                <Section title={t`Application`}>
                  <Row
                    title={t`Language`}
                    description={t`Choose your preferred language for the application`}
                  >
                    <Select
                      label={t`Language`}
                      value={i18n.locale}
                      onChange={(newLocale) => {
                        localStorage.setItem("navivi_locale", newLocale);
                        dynamicActivate(newLocale);
                      }}
                      options={[
                        { value: "en", label: "English" },
                        { value: "ja", label: "日本語" },
                      ]}
                      className="w-40"
                    />
                  </Row>
                  <Row
                    title={t`Auto-save`}
                    description={t`Controls auto save of editors that have unsaved changes`}
                  >
                    <Select
                      label={t`Auto-save`}
                      value={String(autoSaveInterval)}
                      onChange={(v) => updateSettings({ auto_save_interval: parseInt(v) })}
                      options={[
                        { value: "0", label: t`Off` },
                        { value: "3", label: t`3 seconds` },
                        { value: "30", label: t`30 seconds` },
                        { value: "60", label: t`1 minute` },
                        { value: "600", label: t`10 minutes` },
                      ]}
                      className="w-40"
                    />
                  </Row>
                  <Row
                    title={t`AI features`}
                    badge={<Badge tone="violet">{t`Ollama or online AI`}</Badge>}
                    description={t`The assistant, Auto-Write script buttons and overview narration, in every project. Needs Ollama running locally, or an online provider set up in AI models.`}
                  >
                    <Switch
                      checked={!!settings.ai_features_enabled}
                      onChange={(v) => updateSettings({ ai_features_enabled: v })}
                      label={t`AI features`}
                    />
                  </Row>
                </Section>

                {currentView === "editor" && (
                  <Section
                    title={t`This project`}
                    hint={t`Saved with the project`}
                  >
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
                        {
                          id: "system",
                          icon: Monitor,
                          label: i18n._("System"),
                        },
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
                  <Row title={t`Map panel opacity`} info={t`How solid the elevation profile and the uphill/downhill key on the map are.`}>
                    <div className="flex items-center gap-2">
                      <Slider
                        value={mapPanelOpacity}
                        min={MAP_PANEL_OPACITY.min}
                        max={MAP_PANEL_OPACITY.max}
                        step={0.05}
                        label={t`Map panel opacity`}
                        onChange={setMapPanelOpacity}
                        className="w-36"
                      />
                      <span className="w-10 text-right text-[12px] tabular-nums text-zinc-500 dark:text-zinc-400">
                        {Math.round(mapPanelOpacity * 100)}%
                      </span>
                    </div>
                  </Row>
                  <Row title={t`Accent color`}>
                    <div className="flex items-center gap-2">
                      {[
                        {
                          id: "navi",
                          color: "#4287f5",
                          label: i18n._("Navi Blue"),
                        },
                        {
                          id: "emerald",
                          color: "#10b981",
                          label: i18n._("Emerald"),
                        },
                        {
                          id: "violet",
                          color: "#8b5cf6",
                          label: i18n._("Violet"),
                        },
                        {
                          id: "amber",
                          color: "#f59e0b",
                          label: i18n._("Amber"),
                        },
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
                              selected
                                ? "ring-2 ring-zinc-900/25 dark:ring-white/40"
                                : "hover:scale-110"
                            }`}
                          >
                            {selected && (
                              <Check
                                className="w-3.5 h-3.5 text-white"
                                strokeWidth={3}
                              />
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </Row>
                </Section>

                <Section title={t`Map`}>
                  <Row
                    title={t`Route marker`}
                    description={`${t`Default marker for all waypoints. Can be overridden per-stop.`} ${t`Your own image is also drawn as the pin in the video; the built-in icons show on the map only.`}`}
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
                          <img
                            src={preset}
                            alt=""
                            className="w-6 h-6 object-contain"
                          />
                        </MarkerTile>
                      ))}
                      {settings.routeMarker &&
                        !settings.routeMarker.startsWith("/defaults/") && (
                          <MarkerTile
                            selected
                            onClick={() => {}}
                            label={t`Custom Marker`}
                          >
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
                    description={t`Color the route by steepness, using the GPX elevation or 3D terrain`}
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
              <Section title={t`Services`} hint={t`Saved on this PC only, never inside projects or shared files`}>
                <Row
                  title={t`Mapbox`}
                  description={t`Required for map rendering and 3D terrain`}
                  stacked
                >
                  <input
                    type="text"
                    value={settings.mapbox_api_key || ""}
                    onChange={(e) =>
                      updateSettings({ mapbox_api_key: e.target.value })
                    }
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
                    onChange={(e) =>
                      updateSettings({ ors_api_key: e.target.value })
                    }
                    placeholder={t`API key`}
                    spellCheck={false}
                    className={`${inputClass} w-full text-[12px]`}
                  />
                </Row>
              </Section>
            )}

            {activeTab === "project" && <OpenProjectSettings />}

            {activeTab === "video" && (
              <>
                <Section title={t`Output`}>
                  <Row title={t`Target FPS`}>
                    <NumberInput
                      value={settings.fps || 60}
                      onChange={(v) => updateProject({ fps: v })}
                    />
                  </Row>
                  <Row
                    title={t`Language of the text in the video`}
                    description={t`Labels, route banners and cards drawn into the video. Auto follows the language the app was in when the project was last saved.`}
                  >
                    <Segmented<VideoTextLanguage>
                      value={settings.video_text_language ?? "auto"}
                      onChange={(v) => updateProject({ video_text_language: v })}
                      options={[
                        { id: "auto", label: t`Auto` },
                        { id: "en", label: "English" },
                        { id: "ja", label: "日本語" },
                      ]}
                      className="w-64"
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
                    <Select
                      label={t`Hardware mode`}
                      value={settings.hardware_spec_override || "auto"}
                      onChange={(v) => updateProject({ hardware_spec_override: v as any })}
                      options={[
                        { value: "auto", label: t`Auto-Detect (Recommended)` },
                        { value: "low", label: t`Low-spec Mode` },
                        { value: "high", label: t`High-spec Mode` },
                      ]}
                      className="w-56"
                    />
                  </Row>
                </Section>

                <CaptionStyleSection
                  style={resolveCaptionStyle(settings)}
                  onChange={(patch) =>
                    updateProject({ caption_style: { ...(settings.caption_style ?? {}), ...patch } })
                  }
                />
              </>
            )}

            {activeTab === "voice" && <VoiceTab />}

            {activeTab === "setup" && <ComponentsChecklist />}

            {activeTab === "about" && <AboutPanel />}

            {activeTab === "tts_dictionary" && (
              <>
                <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
                  <Trans>
                    Correct words or kanji that are read incorrectly by the AI
                    voice. You can auto-extract entries from scripts by typing{" "}
                    <code className="bg-zinc-100 dark:bg-zinc-800 px-1 rounded">
                      漢字(よみがな)
                    </code>{" "}
                    in any narration script.
                  </Trans>
                </p>

                {inEditor && (
                  <div
                    role="tablist"
                    className="inline-flex p-0.5 rounded-lg bg-zinc-100 dark:bg-white/5"
                  >
                    {(
                      [
                        ["project", t`This project`],
                        ["global", t`All projects`],
                      ] as const
                    ).map(([id, label]) => (
                      <button
                        key={id}
                        type="button"
                        role="tab"
                        aria-selected={dictScope === id}
                        onClick={() => setDictScope(id)}
                        className={`h-7 px-3 rounded-md text-[12px] font-medium transition-colors ${
                          dictScope === id
                            ? "bg-white dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100 shadow-sm"
                            : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                )}
                {(!inEditor || dictScope === "global") && (
                  <p className="text-[11px] text-zinc-400 -mt-1">
                    <Trans>
                      Words here apply to every project. A project's own entry
                      for the same word wins.
                    </Trans>
                  </p>
                )}

                {inEditor && dictScope === "project" ? (
                  <PronunciationEditor
                    entries={dictionary}
                    onChange={setDictionary}
                  />
                ) : (
                  <PronunciationEditor
                    entries={globalDictionary}
                    onChange={saveGlobalDictionary}
                  />
                )}
              </>
            )}

            {activeTab === "ai" && settings.ai_features_enabled && (
              <AiModelsTab />
            )}
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

interface DictionaryEntry {
  word: string;
  reading: string;
  auto?: boolean;
}

function PronunciationEditor({
  entries,
  onChange,
}: {
  entries: DictionaryEntry[];
  onChange: (next: DictionaryEntry[]) => void;
}) {
  return (
    <>
      <div className="rounded-xl border border-zinc-200 dark:border-white/10 overflow-hidden">
        {entries.length > 0 ? (
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
              {entries.map((entry, idx) => (
                <div
                  key={idx}
                  className="group flex items-center gap-2 px-2 py-1.5"
                >
                  <input
                    type="text"
                    placeholder={t`Word (e.g. 加太)`}
                    value={entry.word}
                    onChange={(e) => {
                      const next = [...entries];
                      next[idx] = { word: e.target.value, reading: next[idx].reading };
                      onChange(next);
                    }}
                    className={`${inputClass} flex-1 border-transparent dark:border-transparent bg-transparent dark:bg-transparent hover:border-zinc-200 dark:hover:border-white/10`}
                  />
                  <input
                    type="text"
                    placeholder={t`Reading (e.g. かだ)`}
                    value={entry.reading}
                    onChange={(e) => {
                      const next = [...entries];
                      next[idx] = { word: next[idx].word, reading: e.target.value };
                      onChange(next);
                    }}
                    className={`${inputClass} flex-1 border-transparent dark:border-transparent bg-transparent dark:bg-transparent hover:border-zinc-200 dark:hover:border-white/10`}
                  />
                  {entry.auto && (
                    <span
                      title={t`Reading guessed automatically from the scripts. Edit it to keep your own.`}
                      className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium bg-sky-500/10 text-sky-600 dark:text-sky-400"
                    >
                      <Trans>auto</Trans>
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() =>
                      // An auto word would come back on the next scan, so removing one keeps it as written instead.
                      onChange(
                        entry.auto
                          ? entries.map((e, i) => (i === idx ? { word: e.word, reading: e.word } : e))
                          : entries.filter((_, i) => i !== idx),
                      )
                    }
                    aria-label={entry.auto ? t`Keep as written` : t`Remove`}
                    title={entry.auto ? t`Keep as written` : t`Remove`}
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
                Add words below or extract them from narration scripts.
              </Trans>
            </p>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onChange([...entries, { word: "", reading: "" }])}
          className={secondaryButton}
        >
          <Plus className="w-3.5 h-3.5" /> <Trans>Add word</Trans>
        </button>

        {entries.some((e) => !e.reading && e.word) && (
          <button
            type="button"
            onClick={async () => {
              const emptyWords = entries
                .filter((e) => e.word && !e.reading)
                .map((e) => e.word);
              if (emptyWords.length === 0) return;

              const reply = await callSidecar<{
                readings: Record<string, string>;
              }>("get_furigana", emptyWords);
              if (!reply.success) {
                if (!reply.cancelled)
                  console.error("get_furigana failed:", reply.error);
                return;
              }
              onChange(
                entries.map((e) => ({
                  ...e,
                  reading:
                    !e.reading && reply.readings?.[e.word]
                      ? reply.readings[e.word]
                      : e.reading,
                })),
              );
            }}
            className={secondaryButton}
          >
            <Trans>Auto-fill readings</Trans>
          </button>
        )}
      </div>
    </>
  );
}

function Badge({
  tone,
  children,
}: {
  tone: "violet" | "amber";
  children: React.ReactNode;
}) {
  const tones = {
    violet: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
    amber: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
  };
  return (
    <span
      className={`h-4.5 px-1.5 inline-flex items-center rounded-md text-[10px] font-medium whitespace-nowrap ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

function CaptionStyleSection({
  style,
  onChange,
}: {
  style: Required<TextStyle>;
  onChange: (patch: TextStyle) => void;
}) {
  return (
    <Section title={t`Subtitles`} hint={t`Every subtitle starts from this look`}>
      <div className="p-4 flex justify-center">
        <div className="w-full max-w-sm">
          <CaptionPreview style={style} />
        </div>
      </div>
      <CaptionStyleFields
        style={style}
        onChange={onChange}
        row={(key, label, control, hint) => (
          <Row key={key} title={label} description={hint}>
            <div className="w-64 flex justify-end">{control}</div>
          </Row>
        )}
      />
    </Section>
  );
}

function NumberInput({
  value,
  onChange,
}: {
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="relative w-24">
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className={`${inputClass} w-full pr-6 text-right tabular-nums`}
      />
      <StepButtons onStep={(dir) => onChange((Number(value) || 0) + dir)} />
    </div>
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

  // Only a model that is really installed counts as selected; the unset default is not shown as if it were there.
  const configuredModel = settings.ai_model || DEFAULT_LOCAL_MODEL;
  const activeModel = localModels.includes(configuredModel) ? configuredModel : "";
  const [seesPhotos, setSeesPhotos] = useState<boolean | null>(null);
  useEffect(() => {
    let current = true;
    setSeesPhotos(null);
    if (!activeModel) return;
    modelSeesPhotos(activeModel).then(
      (result) => current && setSeesPhotos(result),
    );
    return () => {
      current = false;
    };
  }, [activeModel, localModels]);

  const [modelSizes, setModelSizes] = useState<Record<string, number>>({});
  const [ramGb, setRamGb] = useState<number | undefined>();
  useEffect(() => {
    getModelSizes().then(setModelSizes);
  }, [localModels]);
  useEffect(() => {
    systemRamGb().then(setRamGb);
  }, []);
  const fit = modelFit(modelSizes[activeModel], ramGb);

  const recommendedModels = [
    { id: "gemma4:26b", name: "Gemma 4 (26B)", size: "~16GB" },
    { id: "gemma4:12b", name: "Gemma 4 (12B)", size: "~7.7GB" },
    { id: "gemma4:e4b", name: "Gemma 4 (E4B)", size: "~9.5GB" },
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

  const online = isOnlineProvider(settings.ai_provider);

  return (
    <>
      <ProviderPicker />
      {online ? (
        <OnlineProviderSettings provider={settings.ai_provider as OnlineProvider} />
      ) : (
        <>
      {localModels.length === 0 && (
        <div className="flex items-start gap-2.5 rounded-xl border border-zinc-200 dark:border-white/10 px-4 py-3">
          <div className="flex-1 min-w-0 text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
            <Trans>
              No local models found. To write scripts on this PC, install Ollama and keep it running, then download a model below. Or pick an
              online provider above, which needs nothing installed.
            </Trans>
          </div>
          <button
            type="button"
            className={secondaryButton}
            onClick={() => invoke("plugin:opener|open_url", { url: "https://ollama.com/download" }).catch(console.error)}
          >
            <ExternalLink className="w-3.5 h-3.5" /> <Trans>Get Ollama</Trans>
          </button>
        </div>
      )}
      <Section title={t`Narration`}>
        <Row
          title={t`Active model`}
          description={t`The model that writes narration scripts and answers in the assistant chat. Only downloaded models are shown.`}
        >
          <Select
            label={t`Active model`}
            value={activeModel}
            placeholder={t`Choose a model`}
            onChange={(model) => {
              updateSettings({ ai_model: model });
              setIsDirty(true);
            }}
            options={
              localModels.length === 0
                ? [{ value: "", label: t`No models installed` }]
                : localModels.map((modelId) => ({ value: modelId, label: modelId }))
            }
            className="w-52"
          />
        </Row>
        {fit?.tooBig && (
          <div className="px-4 py-3">
            <div className="flex items-start gap-2 rounded-lg bg-amber-500/10 px-3 py-2 text-[12px] leading-snug text-amber-700 dark:text-amber-400">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>
                <Trans>
                  This model is about {fit.sizeGb.toFixed(0)} GB and this PC has{" "}
                  {fit.ramGb.toFixed(0)} GB of memory, so it loads slowly and
                  writes only a word or two a second. A 3-4B model is much
                  faster here.
                </Trans>
              </span>
            </div>
          </div>
        )}
        {seesPhotos === false && (
          <div className="px-4 py-3">
            <div className="flex items-start gap-2 rounded-lg bg-amber-500/10 px-3 py-2 text-[12px] leading-snug text-amber-700 dark:text-amber-400">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>
                <Trans>
                  This model cannot read photos. Scripts for stops with photos
                  are written from the place name and location facts only. A
                  vision model such as Gemma 4 can use the photos.
                </Trans>
              </span>
            </div>
          </div>
        )}
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
                  <span className="text-[11px] text-zinc-400 tabular-nums">
                    {model.size}
                  </span>
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
                      aria-label={
                        dlStatus.failed ? t`Clear` : t`Cancel download`
                      }
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ) : isLocal ? (
                  <span className="inline-flex items-center gap-1 text-[12px] font-medium text-emerald-600 dark:text-emerald-400">
                    <CheckCircle2 className="w-3.5 h-3.5" />{" "}
                    <Trans>Ready</Trans>
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
      )}
    </>
  );
}
