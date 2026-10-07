import { useState, useEffect, useRef } from "react";
import {
  ChevronUp,
  ChevronDown,
  X,
  Trash2,
  MapPin,
  LocateFixed,
  Sparkles,
  BookOpen,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ArrowDown,
  ZoomIn,
  ZoomOut,
  Footprints,
  Plus,
  Search,
  Loader2,
  RotateCcw,
  Mic,
  Film,
  Subtitles,
} from "../../../components/ui/icons";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { invoke, convertFileSrc } from "@tauri-apps/api/core";
import { ScriptInput } from "../../../components/ui/ScriptInput";
import { Switch } from "../../../components/ui/Switch";
import { Segmented } from "../../../components/ui/Segmented";
import { MAX_VIDEOS, WaypointVideos } from "./WaypointVideos";
import { openContextMenu, separator } from "../../../components/ui/menuItems";
import { Folder, Video } from "../../../components/ui/icons";
import { open } from "@tauri-apps/plugin-dialog";
import {
  checkModelExists,
  generateWaypointScriptStream,
} from "../../../services/ollamaApi";
import { aiEngine, isOnlineEngine } from "../../../services/ai/engine";
import { PROVIDERS } from "../../../services/ai/providers";
import { stopLabel } from "../../../utils/stopLabel";
import { readTextFile } from "@tauri-apps/plugin-fs";
import { probeDuration, toAbsoluteProjectPath } from "../../../services/fileSystem";
import { RegenKind, refreshStopMedia, regenModes, runRegen } from "../../../services/stopRegen";
import { PHOTO_EXTENSIONS, isHeic, preparePhotos } from "../../../services/imageImport";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { placeNameOf } from "../../../utils/placeName";
import { downloadPhotos, findPlacePhotos } from "../../../services/placePhotos";
import { MAX_PHOTOS_PER_STOP, creditLine, shortCredit, withFoundPhotos } from "../../../utils/photoCredits";

const MAX_IMAGES = MAX_PHOTOS_PER_STOP;

function useCameraMotions() {
  return [
    { value: "pan-left", label: t`Pan Left`, icon: ArrowLeft },
    { value: "pan-right", label: t`Pan Right`, icon: ArrowRight },
    { value: "pan-up", label: t`Pan Up`, icon: ArrowUp },
    { value: "pan-down", label: t`Pan Down`, icon: ArrowDown },
    { value: "zoom-in", label: t`Dolly In`, icon: ZoomIn },
    { value: "zoom-out", label: t`Dolly Out`, icon: ZoomOut },
    { value: "walk-in", label: t`Walk In`, icon: Footprints },
  ];
}

function OptionRow({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex-1 min-w-0">
        <p className="text-[12px] font-medium text-zinc-800 dark:text-zinc-200">{title}</p>
        <p className="text-[11px] text-zinc-500 leading-snug">{description}</p>
      </div>
      <div className="pt-0.5">{children}</div>
    </div>
  );
}

export function WaypointEditor({
  wpId,
  onClose,
}: {
  wpId: string;
  onClose: () => void;
}) {
  const {
    waypoints,
    setWaypoints,
    updateWaypoint,
    setIsDirty,
    setActiveWaypointId,
    metadata,
    settings,
    saveProject,
    timeline,
    setTimeline,
  } = useWorkspace();
  const { showToast, markedWaypointIds, isRendering, setShowAppSettings } = useUI();
  const isMarkedForRegen = markedWaypointIds?.includes(wpId);
  const cameraMotions = useCameraMotions();

  const wp = waypoints.find((w) => w.id === wpId);
  const wpIndex = waypoints.findIndex((w) => w.id === wpId);

  const [activeTab, setActiveTab] = useState<"scripts" | "images" | "videos">("scripts");
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isLocating, setIsLocating] = useState(false);
  const [findingPhotos, setFindingPhotos] = useState(false);
  const photoAbortRef = useRef<AbortController | null>(null);
  const latestWp = useRef(wp);
  latestWp.current = wp;
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [regenBusy, setRegenBusy] = useState<RegenKind | null>(null);
  const liveTimeline = useRef(timeline);
  liveTimeline.current = timeline;
  const [thoughtProcess, setThoughtProcess] = useState("");
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    setIsCollapsed(false);
    setConfirmDelete(false);
    return () => photoAbortRef.current?.abort(); // a lookup for the stop that was just left must not add photos to it later
  }, [wpId]);

  if (!wp) return null;

  const wpImages = wp.images || [];
  const imagePans = wp.imagePans || [];
  const isStart = wpIndex === 0;
  const isDest = wpIndex === waypoints.length - 1 && waypoints.length > 1;
  const isEndpoint = isStart || isDest;
  const isStopBy = !!wp.isStopBy && !isEndpoint;
  const isLinked = wp.connectToRoute !== false;
  const label = stopLabel(waypoints, wpIndex);

  const hasArrivalVoice = !!wp.arrivingNarration?.trim();
  const hasAttractionVoice = !!wp.attractionNarration?.trim() && !(isStopBy && !isLinked);
  const canRegen = !!metadata.directory_path && !wp.skipAssetGeneration && !wp.isStub;

  // Redo one stop's files through the single-stop CLI modes (one sidecar call at a time), then re-read them in the timeline.
  const regenerate = async (kind: RegenKind) => {
    const dir = metadata.directory_path;
    if (!dir || regenBusy || isRendering) return;
    const index = wpIndex;
    setRegenBusy(kind);
    showToast(
      kind === "voice" ? t`Making the new voice for this stop. The first one can take a while.` : kind === "subtitles" ? t`Making the subtitles for this stop.` : t`Making the photo clip for this stop. This can take a few minutes.`,
      "info",
    );
    try {
      await saveProject();
      const { skipped } = await runRegen(`${dir}/job_config.json`, regenModes(kind, index, { hasArrivalVoice, hasAttractionVoice }));
      const next = await refreshStopMedia(liveTimeline.current, index, kind, {
        probe: async (rel, mediaKind) => probeDuration(convertFileSrc(await toAbsoluteProjectPath(rel, dir)), mediaKind, 0),
        readText: async (rel) => readTextFile(await toAbsoluteProjectPath(rel, dir)),
      });
      if (next) setTimeline(next);
      if (skipped) showToast(t`Nothing was made: ${skipped}`, "warning");
      else if (kind === "voice") showToast(hasAttractionVoice ? t`The voice is ready. If its length changed, redo the photo clip so it fits.` : t`The voice is ready.`, "success");
      else showToast(kind === "subtitles" ? t`The subtitles are ready.` : t`The photo clip is ready.`, "success");
    } catch (err: any) {
      const message = String(err?.message ?? err);
      if (/process was cancelled/i.test(message)) showToast(t`Stopped before it finished.`, "info");
      else showToast(t`Could not make that again: ${message}`, "error");
    } finally {
      setRegenBusy(null);
    }
  };

  const openRegenMenu = (e: React.MouseEvent<HTMLButtonElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    openContextMenu({ clientX: box.right - 170, clientY: box.bottom + 4 }, [
      { type: "label", label: t`Make again for this stop` },
      { label: t`Voice`, icon: Mic, disabled: !hasArrivalVoice && !hasAttractionVoice, onSelect: () => regenerate("voice") },
      { label: t`Subtitles`, icon: Subtitles, disabled: !hasArrivalVoice, onSelect: () => regenerate("subtitles") },
      { label: t`Photo clip`, icon: Film, disabled: wpImages.length === 0, onSelect: () => regenerate("photo") },
    ]);
  };

  const removeWaypoint = () => {
    setWaypoints(waypoints.filter((w) => w.id !== wp.id));
    setIsDirty(true);
    setActiveWaypointId(null);
  };

  const lookUpName = async () => {
    setIsLocating(true);
    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${wp.lat}&lon=${wp.lng}`,
      );
      const data = await res.json();
      updateWaypoint(wp.id, {
        name: placeNameOf(data, t`Unknown Location`),
      });
    } catch {
      showToast(t`Couldn't look up a place name for this location.`, "error");
    } finally {
      setIsLocating(false);
    }
  };

  const handleImageSelect = async () => {
    try {
      const selected = await open({
        multiple: true,
        filters: [{ name: "Images", extensions: ["svg", ...PHOTO_EXTENSIONS] }],
      });
      let picked = Array.isArray(selected) ? selected : selected ? [selected] : [];
      if (picked.length === 0) return;
      if (picked.some(isHeic)) {
        showToast(t`Converting iPhone photos...`, "info");
        try {
          const prepared = await preparePhotos(picked);
          picked = prepared.paths;
          if (prepared.failed.length > 0) showToast(t`Some photos could not be converted and were skipped.`, "warning");
        } catch (e: any) {
          showToast(e?.message ?? t`Could not convert the iPhone photos.`, "error");
          picked = picked.filter((p) => !isHeic(p));
        }
        if (picked.length === 0) return;
      }
      updateWaypoint(wp.id, {
        images: [...wpImages, ...picked].slice(0, MAX_IMAGES),
        imagePans: [...imagePans, ...picked.map(() => "none")].slice(0, MAX_IMAGES),
      });
    } catch (e) {
      console.error(e);
    }
  };

  // Free photos of this place from Wikimedia Commons go into the empty photo slots; the ones already there are left alone.
  const findOnline = async () => {
    if (findingPhotos) return;
    photoAbortRef.current?.abort();
    const controller = new AbortController();
    photoAbortRef.current = controller;
    setFindingPhotos(true);
    try {
      const room = MAX_IMAGES - wpImages.length;
      const candidates = await findPlacePhotos({ name: wp.name, lat: wp.lat, lng: wp.lng }, { limit: room, signal: controller.signal });
      const saved = await downloadPhotos(candidates, controller.signal);
      const current = latestWp.current ?? wp;
      const patch = withFoundPhotos(current, saved, MAX_IMAGES);
      if (!patch) {
        showToast(t`No free photos of this place were found.`, "info");
        return;
      }
      updateWaypoint(wp.id, patch);
      setIsDirty(true);
      showToast(t`Added ${saved.length} photos from Wikimedia Commons. Check that they show the right place.`, "success");
    } catch (e: any) {
      if (!controller.signal.aborted) showToast(t`Could not look for photos: ${e?.message ?? e}`, "error");
    } finally {
      setFindingPhotos(false);
    }
  };

  const removeImage = (idx: number) => {
    const images = [...wpImages];
    const pans = [...imagePans];
    images.splice(idx, 1);
    pans.splice(idx, 1);
    updateWaypoint(wp.id, { images, imagePans: pans });
  };

  const updateImagePan = (idx: number, pan: string) => {
    const pans = [...imagePans];
    pans[idx] = pan;
    updateWaypoint(wp.id, { imagePans: pans });
  };

  const handleGenerateScript = async (type: "arriving" | "attraction", prompt: string) => {
    const engine = aiEngine(settings);

    abortControllerRef.current?.abort();
    abortControllerRef.current = new AbortController();

    try {
      setThoughtProcess("");
      updateWaypoint(wp.id, { generatingScriptType: type });

      if (!(await checkModelExists(engine))) {
        showToast(
          isOnlineEngine(engine)
            ? t`Add your ${PROVIDERS[engine.provider].label} API key in Settings > AI models`
            : t`Model "${engine}" not found. Please install it from the App Settings`,
          "error",
        );
        updateWaypoint(wp.id, { generatingScriptType: null });
        return;
      }

      updateWaypoint(wp.id, type === "arriving" ? { arrivingNarration: "" } : { attractionNarration: "" });

      await generateWaypointScriptStream(
        wp.name,
        prompt,
        engine,
        metadata.theme || "",
        (chunk) => {
          setWaypoints((prev) =>
            prev.map((w) =>
              w.id !== wp.id
                ? w
                : type === "arriving"
                  ? { ...w, arrivingNarration: chunk }
                  : { ...w, attractionNarration: chunk },
            ),
          );
        },
        wp.lat,
        wp.lng,
        wp.images || [],
        (thoughtChunk) => setThoughtProcess(thoughtChunk),
        type,
        isStart,
        abortControllerRef.current.signal,
        {
          previous: waypoints[wpIndex - 1]?.name,
          next: waypoints[wpIndex + 1]?.name,
          index: wpIndex,
          total: waypoints.length,
          otherScript: type === "arriving" ? wp.attractionNarration : wp.arrivingNarration,
        },
      );
    } catch (err: any) {
      if (err.name !== "AbortError") {
        console.error("Script generation failed:", err);
        showToast(err.message || t`Failed to generate script`, "error");
      }
    } finally {
      updateWaypoint(wp.id, { generatingScriptType: null });
    }
  };

  const cancelGeneration = () => {
    updateWaypoint(wp.id, { generatingScriptType: null });
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    invoke("cancel_python_blueprint").catch(console.error);
  };

  const scriptSections = [
    {
      type: "arriving" as const,
      title: t`Arriving Script`,
      description: t`Spoken while the route travels to this stop.`,
      value: wp.arrivingNarration || "",
      onChange: (v: string) => updateWaypoint(wp.id, { arrivingNarration: v }),
    },
    ...(isStopBy && !isLinked
      ? []
      : [
          {
            type: "attraction" as const,
            title: t`Attraction Script`,
            description: t`Spoken over this stop's photos once you arrive.`,
            value: wp.attractionNarration || "",
            onChange: (v: string) => updateWaypoint(wp.id, { attractionNarration: v }),
          },
        ]),
  ];

  const badgeClass = isStopBy
    ? "w-5 h-5 text-[9px] border border-dashed border-zinc-400 dark:border-zinc-600 text-zinc-500"
    : isEndpoint
      ? "w-6 h-6 text-[11px] bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
      : "w-6 h-6 text-[11px] bg-navi text-white";

  return (
    <div className="absolute bottom-4 left-0 right-0 z-50 px-4 flex justify-center pointer-events-none">
      <div
        className={`relative flex flex-col bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-white/10 shadow-[0_-8px_40px_-12px_rgba(0,0,0,0.35)] pointer-events-auto overflow-hidden select-none text-zinc-900 dark:text-zinc-100 animate-in fade-in slide-in-from-bottom-2 duration-200 ${
          isCollapsed ? "w-full max-w-sm" : "w-full max-w-4xl h-[min(27rem,52vh)]"
        }`}
      >
        {isRendering && (
          <div className="absolute inset-0 z-60 cursor-not-allowed bg-zinc-900/5 dark:bg-white/5" />
        )}

        <div className="flex items-center gap-2 h-12 pl-3 pr-2 border-b border-zinc-100 dark:border-white/5 shrink-0">
          <span
            className={`rounded-full flex items-center justify-center font-semibold tabular-nums shrink-0 ${badgeClass}`}
          >
            {label}
          </span>

          {isCollapsed ? (
            <button
              type="button"
              onClick={() => setIsCollapsed(false)}
              className="flex-1 min-w-0 text-left text-[14px] font-semibold truncate px-1.5"
            >
              {wp.name}
            </button>
          ) : (
            <>
              <input
                type="text"
                value={wp.name}
                onChange={(e) => updateWaypoint(wp.id, { name: e.target.value })}
                placeholder={t`Location Name`}
                aria-label={t`Location Name`}
                className="flex-1 min-w-0 h-8 px-1.5 rounded-md bg-transparent text-[14px] font-semibold truncate hover:bg-zinc-100 dark:hover:bg-white/5 focus:bg-white dark:focus:bg-zinc-950 focus:outline-none focus:ring-2 focus:ring-navi/30 transition-colors"
              />
              <button
                type="button"
                onClick={lookUpName}
                disabled={isLocating}
                title={t`Get name from coordinate`}
                aria-label={t`Get name from coordinate`}
                className="p-1.5 rounded-md text-zinc-400 hover:text-zinc-800 hover:bg-zinc-100 dark:hover:text-zinc-100 dark:hover:bg-white/5 transition-colors disabled:animate-pulse"
              >
                <LocateFixed className="w-3.5 h-3.5" />
              </button>

              <div className="w-px h-5 bg-zinc-200 dark:bg-white/10 mx-1" />

              {isEndpoint ? (
                <span className="h-6 px-2 flex items-center rounded-md bg-zinc-100 dark:bg-white/5 text-[11px] font-medium text-zinc-600 dark:text-zinc-400 shrink-0">
                  {isStart ? <Trans>Start</Trans> : <Trans>Destination</Trans>}
                </span>
              ) : (
                <div className="flex items-center rounded-md bg-zinc-100 dark:bg-white/5 p-0.5 shrink-0">
                  {[
                    { stopBy: false, label: t`Stop` },
                    { stopBy: true, label: t`Stop-by` },
                  ].map((option) => (
                    <button
                      key={option.label}
                      type="button"
                      onClick={() => updateWaypoint(wp.id, { isStopBy: option.stopBy })}
                      aria-pressed={isStopBy === option.stopBy}
                      className={`h-6 px-2 rounded text-[11px] font-medium transition-colors ${
                        isStopBy === option.stopBy
                          ? "bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-sm"
                          : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              )}

              {isStopBy && (
                <label className="flex items-center gap-1.5 pl-2 text-[11px] text-zinc-600 dark:text-zinc-400 shrink-0">
                  <Switch
                    checked={isLinked}
                    onChange={(v) => updateWaypoint(wp.id, { connectToRoute: v })}
                    label={t`Connected to route`}
                  />
                  <span className="max-[1159px]:hidden">
                    <Trans>On route</Trans>
                  </span>
                </label>
              )}
            </>
          )}

          <div className="flex items-center shrink-0 ml-1">
            {!isCollapsed && canRegen && (
              <button
                type="button"
                onClick={openRegenMenu}
                disabled={!!regenBusy || isRendering}
                title={regenBusy ? t`Making this stop again...` : t`Make this stop's files again`}
                aria-label={t`Make this stop's files again`}
                className="p-1.5 rounded-md text-zinc-400 hover:text-zinc-800 hover:bg-zinc-100 dark:hover:text-zinc-100 dark:hover:bg-white/5 transition-colors disabled:opacity-60"
              >
                {regenBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />}
              </button>
            )}
            <button
              type="button"
              onClick={() => setIsCollapsed(!isCollapsed)}
              title={isCollapsed ? t`Expand` : t`Collapse`}
              aria-label={isCollapsed ? t`Expand` : t`Collapse`}
              className="p-1.5 rounded-md text-zinc-400 hover:text-zinc-800 hover:bg-zinc-100 dark:hover:text-zinc-100 dark:hover:bg-white/5 transition-colors"
            >
              {isCollapsed ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
            <button
              type="button"
              onClick={onClose}
              title={t`Close`}
              aria-label={t`Close`}
              className="p-1.5 rounded-md text-zinc-400 hover:text-zinc-800 hover:bg-zinc-100 dark:hover:text-zinc-100 dark:hover:bg-white/5 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {!isCollapsed && (
          <div className="flex-1 min-h-0 flex">
            <div className="flex-1 min-w-0 flex flex-col">
              <div className="flex items-center gap-4 px-4 h-10 border-b border-zinc-100 dark:border-white/5 shrink-0">
                {(
                  [
                    ["scripts", t`Narration`, null],
                    ["images", t`Photos`, `${wpImages.length}/${MAX_IMAGES}`],
                    ["videos", t`Videos`, `${(wp.videos ?? []).length}/${MAX_VIDEOS}`],
                  ] as const
                ).map(([id, tabLabel, count]) => (
                  <button
                    key={id}
                    type="button"
                    role="tab"
                    aria-selected={activeTab === id}
                    onClick={() => setActiveTab(id)}
                    className={`relative h-full flex items-center gap-1.5 text-[12px] font-medium transition-colors ${
                      activeTab === id
                        ? "text-zinc-900 dark:text-zinc-100 after:absolute after:left-0 after:right-0 after:bottom-0 after:h-0.5 after:rounded-full after:bg-navi"
                        : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                    }`}
                  >
                    {tabLabel}
                    {count && <span className="text-[11px] text-zinc-400 tabular-nums">{count}</span>}
                  </button>
                ))}

                {activeTab === "scripts" && (
                  <button
                    type="button"
                    onClick={() => {
                      setShowAppSettings(true);
                      setTimeout(
                        () =>
                          window.dispatchEvent(
                            new CustomEvent("open-app-settings-tab", { detail: "tts_dictionary" }),
                          ),
                        50,
                      );
                    }}
                    className="ml-auto flex items-center gap-1.5 h-6 px-2 rounded-md text-[11px] font-medium text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100 dark:hover:text-zinc-100 dark:hover:bg-white/5 transition-colors"
                  >
                    <BookOpen className="w-3 h-3" />
                    <Trans>TTS Pronunciation Dictionary</Trans>
                  </button>
                )}
              </div>

              <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar p-4">
                {activeTab === "scripts" ? (
                  <div className="space-y-5 max-w-2xl">
                    {scriptSections.map((section) => (
                      <section key={section.type}>
                        <h3 className="text-[12px] font-semibold text-zinc-800 dark:text-zinc-200">
                          {section.title}
                        </h3>
                        <p className="text-[11px] text-zinc-500 mb-1">{section.description}</p>
                        <ScriptInput
                          showLabel={false}
                          thoughtProcess={thoughtProcess}
                          value={section.value}
                          onChange={section.onChange}
                          isGenerating={wp.generatingScriptType === section.type}
                          onCancel={cancelGeneration}
                          onGenerate={(prompt) => handleGenerateScript(section.type, prompt)}
                          aiEnabled={!!settings.ai_features_enabled}
                        />
                      </section>
                    ))}
                  </div>
                ) : activeTab === "videos" ? (
                  <WaypointVideos wp={wp} />
                ) : (
                  <div>
                    <div className="flex items-start justify-between gap-3 mb-3">
                      <p className="text-[11px] text-zinc-500">
                        <Trans>Add up to 3 images that will pop up during the narration at this stop</Trans>
                      </p>
                      <button
                        type="button"
                        onClick={() => void findOnline()}
                        disabled={findingPhotos || wpImages.length >= MAX_IMAGES}
                        title={t`Looks on Wikimedia Commons for free photos of this place. Sends the place name and position to Wikimedia.`}
                        className="shrink-0 inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md border border-zinc-200 dark:border-white/10 text-[11px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-white/5 disabled:opacity-40 disabled:pointer-events-none transition-colors"
                      >
                        {findingPhotos ? <Loader2 className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />}
                        {findingPhotos ? <Trans>Looking…</Trans> : <Trans>Find photos online</Trans>}
                      </button>
                    </div>
                    <div className="flex flex-wrap gap-3">
                      {wpImages.map((img, idx) => {
                        const currentPan = imagePans[idx] || "none";
                        return (
                          <div
                            key={`${img}-${idx}`}
                            onContextMenu={(e) =>
                              openContextMenu(e, [
                                { type: "label", label: img.split(/\\|\//).pop() || img },
                                {
                                  label: t`Camera Angle`,
                                  icon: Video,
                                  submenu: [
                                    {
                                      label: t`None`,
                                      checked: currentPan === "none",
                                      onSelect: () => updateImagePan(idx, "none"),
                                    },
                                    separator,
                                    ...cameraMotions.map(({ value, label: motionLabel, icon }) => ({
                                      label: motionLabel,
                                      icon,
                                      checked: currentPan === value,
                                      onSelect: () => updateImagePan(idx, value),
                                    })),
                                  ],
                                },
                                {
                                  label: t`Reveal in File Explorer`,
                                  icon: Folder,
                                  onSelect: () =>
                                    void invoke("open_in_explorer", { path: img }).catch(console.error),
                                },
                                separator,
                                {
                                  label: t`Remove Image`,
                                  icon: Trash2,
                                  danger: true,
                                  onSelect: () => removeImage(idx),
                                },
                              ])
                            }
                            className="group w-48 rounded-lg border border-zinc-200 dark:border-white/10 overflow-hidden bg-white dark:bg-zinc-950"
                          >
                            <div className="relative aspect-4/3 bg-zinc-100 dark:bg-zinc-800">
                              <img
                                src={convertFileSrc(img)}
                                alt={t`Waypoint ${idx}`}
                                className="w-full h-full object-cover"
                              />
                              <button
                                type="button"
                                onClick={() => removeImage(idx)}
                                title={t`Remove Image`}
                                aria-label={t`Remove Image`}
                                className="absolute top-1.5 right-1.5 p-1 rounded-md bg-black/55 text-white opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-red-500 transition"
                              >
                                <Trash2 className="w-3 h-3" />
                              </button>
                            </div>
                            <div className="p-2 space-y-1.5">
                              <p className="text-[11px] text-zinc-600 dark:text-zinc-400 truncate" title={img}>
                                {img.split(/\\|\//).pop()}
                              </p>
                              {wp.imageCredits?.[img] && (
                                <button
                                  type="button"
                                  onClick={() => void invoke("plugin:opener|open_url", { url: wp.imageCredits![img].url }).catch(console.error)}
                                  title={`${creditLine(wp.imageCredits[img])}
${t`Open the photo's page on Wikimedia Commons`}`}
                                  className="block w-full text-left text-[10px] text-zinc-400 hover:text-navi truncate transition-colors"
                                >
                                  {shortCredit(wp.imageCredits[img])}
                                </button>
                              )}
                              <div>
                                <p className="text-[10px] text-zinc-400 mb-1">
                                  <Trans>Camera Angle</Trans>
                                </p>
                                <div className="flex items-center gap-0.5" role="radiogroup">
                                  {cameraMotions.map(({ value, label: motionLabel, icon: Icon }) => {
                                    const selected = currentPan === value;
                                    return (
                                      <button
                                        key={value}
                                        type="button"
                                        role="radio"
                                        aria-checked={selected}
                                        onClick={() => updateImagePan(idx, selected ? "none" : value)}
                                        title={motionLabel}
                                        aria-label={motionLabel}
                                        className={`flex-1 h-6 flex items-center justify-center rounded transition-colors ${
                                          selected
                                            ? "bg-navi text-white"
                                            : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800 dark:hover:bg-white/5 dark:hover:text-zinc-200"
                                        }`}
                                      >
                                        <Icon className="w-3 h-3" />
                                      </button>
                                    );
                                  })}
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })}

                      {wpImages.length < MAX_IMAGES && (
                        <button
                          type="button"
                          onClick={handleImageSelect}
                          className="w-48 aspect-4/3 rounded-lg border border-dashed border-zinc-300 dark:border-white/15 flex flex-col items-center justify-center gap-1.5 text-zinc-500 hover:text-zinc-800 hover:border-zinc-400 hover:bg-zinc-50 dark:hover:text-zinc-200 dark:hover:border-white/25 dark:hover:bg-white/2 transition-colors"
                        >
                          <span className="w-8 h-8 rounded-full bg-zinc-100 dark:bg-white/5 flex items-center justify-center">
                            <Plus className="w-4 h-4" />
                          </span>
                          <span className="text-[12px] font-medium">
                            <Trans>Add photo</Trans>
                          </span>
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>

            <aside className="w-60 max-[1159px]:w-48 shrink-0 border-l border-zinc-100 dark:border-white/5 bg-zinc-50/60 dark:bg-white/1.5 flex flex-col overflow-y-auto custom-scrollbar">
              <div className="p-4 space-y-4 flex-1">
                {isMarkedForRegen && (
                  <div className="p-2.5 rounded-md bg-amber-500/10 border border-amber-500/25 flex items-start gap-2">
                    <Sparkles className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-0.5" />
                    <span className="text-[11px] text-amber-800 dark:text-amber-300 leading-snug">
                      <Trans>
                        Marked for Regeneration: Edit image, narration, or route mode, then click Resume
                        Generation
                      </Trans>
                    </span>
                  </div>
                )}

                <OptionRow
                  title={t`Skip in Video Export`}
                  description={
                    isEndpoint
                      ? t`The start and destination are always included.`
                      : t`Skips this location during video generation`
                  }
                >
                  <Switch
                    checked={!!wp.skipAssetGeneration}
                    disabled={isEndpoint}
                    onChange={(v) => updateWaypoint(wp.id, { skipAssetGeneration: v })}
                    label={t`Skip in Video Export`}
                  />
                </OptionRow>

                <OptionRow
                  title={t`Pause at Location`}
                  description={t`Adds a brief pause in the generated video at this waypoint before continuing the journey`}
                >
                  <Switch
                    checked={
                      wp.pauseAtWaypoint !== undefined
                        ? wp.pauseAtWaypoint
                        : waypoints[wpIndex + 1]?.isStopBy === true
                    }
                    onChange={(v) => updateWaypoint(wp.id, { pauseAtWaypoint: v })}
                    label={t`Pause at Location`}
                  />
                </OptionRow>

                {!!wp.images?.length && (
                  <OptionRow title={t`Photo card`} description={t`Boxed keeps the photo in a card with its caption; full photo fills the frame.`}>
                    <Segmented<"pip" | "cover">
                      compact
                      value={wp.imageDisplay === "cover" ? "cover" : "pip"}
                      onChange={(v) => updateWaypoint(wp.id, { imageDisplay: v })}
                      options={[
                        { id: "pip", label: t`Boxed` },
                        { id: "cover", label: t`Full photo` },
                      ]}
                    />
                  </OptionRow>
                )}

                <OptionRow title={t`Describe in the overview`} description={t`Off keeps this stop out of the overview narration.`}>
                  <Switch
                    checked={wp.overviewHighlight !== false}
                    onChange={(v) => updateWaypoint(wp.id, { overviewHighlight: v ? undefined : false })}
                    label={t`Describe in the overview`}
                  />
                </OptionRow>

                <div>
                  <p className="text-[12px] font-medium text-zinc-800 dark:text-zinc-200 mb-1.5">
                    <Trans>Custom Marker</Trans>
                  </p>
                  <div className="flex items-center gap-2">
                    <span className="w-9 h-9 rounded-md border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-950 flex items-center justify-center shrink-0 overflow-hidden">
                      {wp.customMarker ? (
                        <img src={convertFileSrc(wp.customMarker)} alt="" className="w-6 h-6 object-contain" />
                      ) : (
                        <MapPin className="w-4 h-4 text-zinc-300 dark:text-zinc-600" />
                      )}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-[11px] text-zinc-500 truncate" title={wp.customMarker || ""}>
                        {wp.customMarker ? wp.customMarker.split(/[\\/]/).pop() : t`Default pin`}
                      </p>
                      <div className="flex items-center gap-1 -ml-1.5">
                        <button
                          type="button"
                          onClick={async () => {
                            const selected = await open({
                              multiple: false,
                              filters: [{ name: "Images", extensions: ["svg", "png", "jpg", "jpeg"] }],
                            });
                            if (selected && typeof selected === "string") {
                              updateWaypoint(wp.id, { customMarker: selected });
                            }
                          }}
                          className="h-6 px-1.5 rounded-md text-[11px] font-medium text-navi hover:bg-navi/10 transition-colors"
                        >
                          <Trans>Choose…</Trans>
                        </button>
                        {wp.customMarker && (
                          <button
                            type="button"
                            onClick={() => updateWaypoint(wp.id, { customMarker: undefined })}
                            className="h-6 px-1.5 rounded-md text-[11px] font-medium text-zinc-500 hover:bg-zinc-200/60 dark:hover:bg-white/5 transition-colors"
                          >
                            <Trans>Reset</Trans>
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="p-3 border-t border-zinc-100 dark:border-white/5">
                {confirmDelete ? (
                  <div className="flex items-center gap-1.5">
                    <span className="flex-1 text-[11px] text-zinc-600 dark:text-zinc-400">
                      <Trans>Delete this stop?</Trans>
                    </span>
                    <button
                      type="button"
                      onClick={() => setConfirmDelete(false)}
                      className="h-7 px-2 rounded-md text-[11px] font-medium text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200/60 dark:hover:bg-white/5"
                    >
                      <Trans>Cancel</Trans>
                    </button>
                    <button
                      type="button"
                      onClick={removeWaypoint}
                      className="h-7 px-2.5 rounded-md text-[11px] font-semibold text-white bg-red-500 hover:bg-red-600"
                    >
                      <Trans>Delete</Trans>
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirmDelete(true)}
                    className="w-full h-7 flex items-center gap-1.5 px-2 rounded-md text-[12px] font-medium text-red-500 hover:bg-red-500/10 transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <Trans>Delete stop</Trans>
                  </button>
                )}
              </div>
            </aside>
          </div>
        )}
      </div>
    </div>
  );
}