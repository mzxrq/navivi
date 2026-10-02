import { useState, useEffect, useRef, ReactNode } from "react";
import { createPortal } from "react-dom";
import { open } from "@tauri-apps/plugin-dialog";
import { useLingui } from "@lingui/react";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useUI } from "../../hooks/useUI";
import {
  Car,
  ChevronRight,
  Footprints,
  Loader2,
  MapIcon,
  MapPin,
  Plane,
  Route,
  Search,
  Ship,
  X,
} from "../ui/icons";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Switch } from "./Switch";
import { dialogButton, dialogInput } from "./Dialog";
import { setPendingImport } from "../../utils/pendingImport";
import { mapDefaults } from "../../config/constants";
import type { RouteMode } from "../../types";

interface SearchResult {
  place_id: number;
  display_name: string;
  lat: string;
  lon: string;
}

type Origin = { name: string; coords: [number, number] };
type StartFrom = "blank" | "route";

const LAST_ORIGIN_KEY = "navivi_last_origin";

function initialOrigin(locale: string): Origin {
  try {
    const saved = JSON.parse(localStorage.getItem(LAST_ORIGIN_KEY) || "null");
    if (saved?.name && Array.isArray(saved.coords)) return saved;
  } catch {}
  return {
    name: locale === "ja" ? "大阪府大阪市" : "Osaka, Japan",
    coords: mapDefaults.startCoords,
  };
}

const fileName = (path: string) => path.split(/[\\/]/).pop() || path;

export function NewProject() {
  const { setCurrentView } = useUI();
  const { updateMetadata, updateSettings, resetWorkspace } = useWorkspace();
  const { i18n } = useLingui();

  const [projectName, setProjectName] = useState(t`Untitled Project`);
  const [startFrom, setStartFrom] = useState<StartFrom>("blank");
  const [routePath, setRoutePath] = useState<string | null>(null);

  const [origin, setOrigin] = useState<Origin>(() => initialOrigin(i18n.locale));
  const [originQuery, setOriginQuery] = useState(origin.name);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);

  const [travelMode, setTravelMode] = useState<RouteMode>("driving");
  const [introEnabled, setIntroEnabled] = useState(true);
  const [introTitle, setIntroTitle] = useState("");
  const [introSubtitle, setIntroSubtitle] = useState("");
  const [skipRichMedia, setSkipRichMedia] = useState(false);

  const close = () => setCurrentView("title_screen");

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    window.addEventListener("mousedown", handleClickOutside);
    return () => window.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (showDropdown) setShowDropdown(false);
      else close();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [showDropdown]);

  useEffect(() => {
    if (!originQuery.trim() || originQuery === origin.name) {
      setSearchResults([]);
      setShowDropdown(false);
      setIsSearching(false);
      return;
    }

    setIsSearching(true);
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(
          `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(
            originQuery,
          )}&limit=5&accept-language=${i18n.locale}`,
        );
        if (!res.ok) throw new Error(t`no-internet`);
        setSearchResults(await res.json());
        setShowDropdown(true);
      } catch (error) {
        console.error("Search failed:", error);
      } finally {
        setIsSearching(false);
      }
    }, 600);

    return () => clearTimeout(timer);
  }, [originQuery, origin.name, i18n.locale]);

  const handleSelectPlace = (place: SearchResult) => {
    const name = place.display_name.split(",")[0];
    setOrigin({ name, coords: [parseFloat(place.lat), parseFloat(place.lon)] });
    setOriginQuery(name);
    setShowDropdown(false);
  };

  const pickRoute = async () => {
    const selected = await open({
      multiple: false,
      filters: [{ name: t`GPS/Text Files`, extensions: ["gpx", "fit", "tcx", "kml", "json", "txt", "md"] }],
    });
    if (typeof selected === "string") {
      setRoutePath(selected);
      setStartFrom("route");
    }
  };

  const missingFile = startFrom === "route" && !routePath;

  const handleCreate = () => {
    if (missingFile) return;
    const name = projectName.trim() || t`Untitled Project`;

    resetWorkspace();
    updateMetadata({
      project_name: name,
      project_id: "",
      status: "initialized",
      enable_intro: introEnabled,
      video_title: introTitle.trim(),
      video_subtitle: introSubtitle.trim(),
    });
    updateSettings({
      start_coords: origin.coords,
      fps: 30,
      skip_rich_media: skipRichMedia,
      default_route_mode: travelMode,
    });

    try {
      localStorage.setItem(LAST_ORIGIN_KEY, JSON.stringify(origin));
    } catch {}

    if (startFrom === "route" && routePath) setPendingImport({ kind: "route", path: routePath });
    else setPendingImport(null);

    setCurrentView("editor");
  };

  const modes: { id: RouteMode; icon: typeof Car; label: string }[] = [
    { id: "driving", icon: Car, label: t`Drive` },
    { id: "walking", icon: Footprints, label: t`Walk` },
    { id: "ferry", icon: Ship, label: t`Ferry` },
    { id: "curve", icon: Plane, label: t`Fly` },
  ];

  const sources: {
    id: StartFrom;
    icon: typeof Car;
    label: string;
    detail: string;
    onPick?: () => void;
  }[] = [
    { id: "blank", icon: MapIcon, label: t`Blank map`, detail: t`Add stops yourself` },
    {
      id: "route",
      icon: Route,
      label: t`GPS track`,
      detail: routePath ? fileName(routePath) : t`GPX, FIT, TCX or KML`,
      onPick: pickRoute,
    },
  ];

  return createPortal(
    <div
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
      className="fixed inset-x-0 top-10 bottom-0 z-99999 flex items-center justify-center p-4 bg-zinc-950/30 backdrop-blur-[2px] animate-in fade-in duration-150 select-none"
    >
      <form
        role="dialog"
        aria-modal="true"
        onSubmit={(e) => {
          e.preventDefault();
          handleCreate();
        }}
        className="w-136 max-w-full max-h-full flex flex-col rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-2xl overflow-hidden animate-in zoom-in-95 duration-150"
      >
        <div className="flex items-start justify-between gap-4 px-6 pt-6 pb-4 border-b border-zinc-100 dark:border-white/5">
          <div>
            <h2 className="text-[16px] font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
              <Trans>create-new-route</Trans>
            </h2>
            <p className="mt-0.5 text-[13px] text-zinc-500 dark:text-zinc-400">
              <Trans>create-new-route-detail</Trans>
            </p>
          </div>
          <button
            type="button"
            onClick={close}
            aria-label={t`Close`}
            className="flex items-center justify-center w-8 h-8 -mr-2 -mt-1 rounded-lg text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/5 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar px-6 py-5 space-y-6">
          <Field label={t`Project name`} htmlFor="new-project-name">
            <input
              id="new-project-name"
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              onFocus={(e) => e.currentTarget.select()}
              className={dialogInput}
              placeholder={t`project-name-placeholder`}
              autoFocus
            />
          </Field>

          <Field label={t`Start from`}>
            <div className="grid grid-cols-3 gap-2">
              {sources.map((source) => {
                const selected = startFrom === source.id;
                return (
                  <button
                    key={source.id}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => (source.onPick ? source.onPick() : setStartFrom(source.id))}
                    className={`flex flex-col items-start gap-2 p-3 rounded-xl border text-left transition-colors ${
                      selected
                        ? "border-navi bg-navi/5 ring-2 ring-navi/15"
                        : "border-zinc-200 dark:border-white/10 hover:bg-zinc-50 dark:hover:bg-white/5"
                    }`}
                  >
                    <source.icon className={`w-4.5 h-4.5 ${selected ? "text-navi" : "text-zinc-400"}`} />
                    <span className="min-w-0 w-full">
                      <span className="block text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
                        {source.label}
                      </span>
                      <span className="block text-[11px] text-zinc-500 dark:text-zinc-400 truncate" title={source.detail}>
                        {source.detail}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </Field>

          <Field
            label={t`Starting point`}
            htmlFor="new-project-origin"
            hint={startFrom === "blank" ? undefined : t`Where the map opens before your import is placed`}
          >
            <div ref={searchRef} className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400 pointer-events-none" />
              <input
                id="new-project-origin"
                type="text"
                value={originQuery}
                onChange={(e) => setOriginQuery(e.target.value)}
                onFocus={() => searchResults.length > 0 && setShowDropdown(true)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && showDropdown && searchResults[0]) {
                    e.preventDefault();
                    handleSelectPlace(searchResults[0]);
                  }
                }}
                placeholder={t`start-search-detail`}
                className={`${dialogInput} pl-9 pr-9`}
              />
              <span className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center">
                {isSearching ? (
                  <Loader2 className="w-4 h-4 mr-1 text-navi animate-spin" />
                ) : (
                  originQuery && (
                    <button
                      type="button"
                      onClick={() => {
                        setOriginQuery("");
                        setSearchResults([]);
                      }}
                      aria-label={t`Clear`}
                      className="flex items-center justify-center w-6 h-6 rounded-md text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/5 transition-colors"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )
                )}
              </span>

              {showDropdown && searchResults.length > 0 && (
                <div className="absolute top-full inset-x-0 mt-1.5 z-50 max-h-56 overflow-y-auto custom-scrollbar p-1 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-lg animate-in fade-in zoom-in-95 duration-100">
                  {searchResults.map((place) => (
                    <button
                      key={place.place_id}
                      type="button"
                      onClick={() => handleSelectPlace(place)}
                      className="w-full flex items-start gap-2.5 px-2.5 py-2 rounded-lg text-left hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors"
                    >
                      <MapPin className="w-4 h-4 mt-0.5 shrink-0 text-zinc-400" />
                      <span className="min-w-0">
                        <span className="block text-[13px] font-medium text-zinc-900 dark:text-zinc-100 truncate">
                          {place.display_name.split(",")[0]}
                        </span>
                        <span className="block text-[11px] text-zinc-500 dark:text-zinc-400 truncate">
                          {place.display_name.split(",").slice(1).join(",").trim()}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </Field>

          <Field label={t`Default travel mode`} hint={t`default-routing-mode-detail`}>
            <Segmented
              value={travelMode}
              onChange={setTravelMode}
              options={modes.map((m) => ({ id: m.id, label: m.label, icon: <m.icon className="w-4 h-4" /> }))}
            />
          </Field>

          <div className="rounded-xl border border-zinc-200 dark:border-white/10 divide-y divide-zinc-100 dark:divide-white/5">
            <div className="px-4 py-3">
              <ToggleRow
                title={t`Title card`}
                description={t`Shows the title and subtitle at the start of the video`}
                checked={introEnabled}
                onChange={setIntroEnabled}
              />
              {introEnabled && (
                <div className="grid grid-cols-2 gap-2 mt-3">
                  <input
                    type="text"
                    value={introTitle}
                    onChange={(e) => setIntroTitle(e.target.value)}
                    placeholder={projectName || t`Title`}
                    aria-label={t`Title`}
                    className={dialogInput}
                  />
                  <input
                    type="text"
                    value={introSubtitle}
                    onChange={(e) => setIntroSubtitle(e.target.value)}
                    placeholder={t`Subtitle (optional)`}
                    aria-label={t`Subtitle`}
                    className={dialogInput}
                  />
                </div>
              )}
            </div>
            <div className="px-4 py-3">
              <ToggleRow
                title={t`Fast render mode`}
                description={t`Skip AI voiceover synthesis and pop-up images during generation`}
                checked={skipRichMedia}
                onChange={setSkipRichMedia}
              />
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-zinc-100 dark:border-white/5">
          <button type="button" onClick={close} className={dialogButton.secondary}>
            <Trans>Cancel</Trans>
          </button>
          <button
            type="submit"
            disabled={missingFile}
            className={`${dialogButton.primary} flex items-center gap-1`}
          >
            <Trans>start-editing</Trans>
            <ChevronRight className="w-4 h-4 -mr-1 opacity-80" />
          </button>
        </div>
      </form>
    </div>,
    document.body,
  );
}

function Field({
  label,
  hint,
  htmlFor,
  children,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
  children: ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="block mb-1.5 text-[12px] font-medium text-zinc-600 dark:text-zinc-300">
        {label}
      </label>
      {children}
      {hint && <p className="mt-1.5 text-[12px] text-zinc-500 dark:text-zinc-400">{hint}</p>}
    </div>
  );
}

function Segmented<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { id: T; label: string; icon?: ReactNode }[];
}) {
  return (
    <div className="flex p-0.5 rounded-lg bg-zinc-100 dark:bg-white/5">
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          aria-pressed={value === option.id}
          onClick={() => onChange(option.id)}
          className={`flex-1 flex items-center justify-center gap-1.5 h-8 rounded-md text-[13px] font-medium transition-colors ${
            value === option.id
              ? "bg-white dark:bg-zinc-800 text-navi shadow-sm"
              : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
          }`}
        >
          {option.icon}
          {option.label}
        </button>
      ))}
    </div>
  );
}

function ToggleRow({
  title,
  description,
  checked,
  onChange,
}: {
  title: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-6 cursor-pointer">
      <span className="min-w-0">
        <span className="block text-[13px] font-medium text-zinc-900 dark:text-zinc-100">{title}</span>
        <span className="block mt-0.5 text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
          {description}
        </span>
      </span>
      <Switch checked={checked} onChange={onChange} label={title} />
    </label>
  );
}
