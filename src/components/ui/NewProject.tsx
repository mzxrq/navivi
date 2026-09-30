import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useLingui } from "@lingui/react";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useUI } from "../../hooks/useUI";
import { Car, ChevronRight, Footprints, Loader2, MapPin, Plane, Search, X } from "../ui/icons";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Switch } from "./Switch";
import { dialogButton, dialogInput } from "./Dialog";

interface SearchResult {
  place_id: number;
  display_name: string;
  lat: string;
  lon: string;
}

const DEFAULT_ORIGIN = "Osaka, Japan";

export function NewProject() {
  const { setCurrentView } = useUI();
  const { updateMetadata, updateSettings, resetWorkspace } = useWorkspace();
  const { i18n } = useLingui();

  const [projectName, setProjectName] = useState(t`Untitled Project`);
  const [travelMode, setTravelMode] = useState<"driving" | "walking" | "curve">("driving");

  // Origin Search State (Defaults to Osaka)
  const [originQuery, setOriginQuery] = useState(DEFAULT_ORIGIN);
  const [selectedCoords, setSelectedCoords] = useState<[number, number]>([34.6937, 135.5023]);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  // Set right after picking a result, so filling the input doesn't search again.
  const pickedRef = useRef(false);

  const [skipRichMedia, setSkipRichMedia] = useState(false);

  const searchRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    window.addEventListener("mousedown", handleClickOutside);
    return () => window.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Escape closes the results first, then the dialog.
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (showDropdown) setShowDropdown(false);
      else setCurrentView("title_screen");
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [setCurrentView, showDropdown]);

  // Origin Search Effect
  useEffect(() => {
    if (pickedRef.current) {
      pickedRef.current = false;
      return;
    }
    if (!originQuery.trim() || originQuery === DEFAULT_ORIGIN) {
      setSearchResults([]);
      setShowDropdown(false);
      setIsSearching(false);
      return;
    }

    setIsSearching(true);
    const delayDebounceFn = setTimeout(async () => {
      try {
        const res = await fetch(
          `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(
            originQuery,
          )}&limit=5&accept-language=${i18n.locale}`,
        );
        if (!res.ok) throw new Error(t`no-internet`);
        const data = await res.json();
        setSearchResults(data);
        setShowDropdown(true);
      } catch (error) {
        console.error("Search failed:", error);
      } finally {
        setIsSearching(false);
      }
    }, 600);

    return () => clearTimeout(delayDebounceFn);
  }, [originQuery, i18n.locale]);

  const handleSelectPlace = (place: SearchResult) => {
    pickedRef.current = true;
    setSelectedCoords([parseFloat(place.lat), parseFloat(place.lon)]);
    setOriginQuery(place.display_name.split(",")[0]); // Set input to the clean name
    setShowDropdown(false);
  };

  const handleCreate = () => {
    resetWorkspace();

    updateMetadata({
      project_name: projectName || t`Untitled Project`,
      project_id: "",
      status: "initialized",
    });

    updateSettings({
      start_coords: selectedCoords,
      fps: 30,
      skip_rich_media: skipRichMedia,
      default_route_mode: travelMode,
    });

    setCurrentView("editor");
  };

  const modes = [
    { id: "driving" as const, icon: Car, label: t`Drive` },
    { id: "walking" as const, icon: Footprints, label: t`Walk` },
    { id: "curve" as const, icon: Plane, label: t`Fly` },
  ];

  const label = "block mb-1.5 text-[12px] font-medium text-zinc-600 dark:text-zinc-300";

  return createPortal(
    <div
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) setCurrentView("title_screen");
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
        className="w-120 max-w-full max-h-full flex flex-col rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-2xl overflow-hidden animate-in zoom-in-95 duration-150"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4 px-6 pt-6">
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
            onClick={() => setCurrentView("title_screen")}
            aria-label={t`Close`}
            className="flex items-center justify-center w-8 h-8 -mr-2 -mt-1 rounded-lg text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/5 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-6 pt-5 space-y-5 overflow-y-auto">
          {/* Project name */}
          <div>
            <label htmlFor="new-project-name" className={label}>
              <Trans>Project name</Trans>
            </label>
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
          </div>

          {/* Starting location */}
          <div ref={searchRef}>
            <label htmlFor="new-project-origin" className={label}>
              <Trans>Starting point</Trans>
            </label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400 pointer-events-none" />
              <input
                id="new-project-origin"
                type="text"
                value={originQuery}
                onChange={(e) => setOriginQuery(e.target.value)}
                onFocus={() => {
                  if (searchResults.length > 0) setShowDropdown(true);
                }}
                onKeyDown={(e) => {
                  // Enter picks the first result instead of submitting.
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
          </div>

          {/* Default travel mode */}
          <div>
            <span className={label}>
              <Trans>Default travel mode</Trans>
            </span>
            <div className="flex p-0.5 rounded-lg bg-zinc-100 dark:bg-white/5">
              {modes.map((mode) => (
                <button
                  key={mode.id}
                  type="button"
                  aria-pressed={travelMode === mode.id}
                  onClick={() => setTravelMode(mode.id)}
                  className={`flex-1 flex items-center justify-center gap-1.5 h-8 rounded-md text-[13px] font-medium transition-colors ${
                    travelMode === mode.id
                      ? "bg-white dark:bg-zinc-800 text-navi shadow-sm"
                      : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
                  }`}
                >
                  <mode.icon className="w-4 h-4" />
                  {mode.label}
                </button>
              ))}
            </div>
            <p className="mt-1.5 text-[12px] text-zinc-500 dark:text-zinc-400">
              <Trans>default-routing-mode-detail</Trans>
            </p>
          </div>

          {/* Fast render */}
          <label className="flex items-center justify-between gap-6 px-4 py-3 rounded-xl border border-zinc-200 dark:border-white/10 cursor-pointer">
            <span className="min-w-0">
              <span className="block text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
                <Trans>Fast render mode</Trans>
              </span>
              <span className="block mt-0.5 text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
                <Trans>Skip AI voiceover synthesis and pop-up images during generation</Trans>
              </span>
            </span>
            <Switch checked={skipRichMedia} onChange={setSkipRichMedia} label={t`Fast render mode`} />
          </label>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-6 pt-5 pb-6">
          <button
            type="button"
            onClick={() => setCurrentView("title_screen")}
            className={dialogButton.secondary}
          >
            <Trans>Cancel</Trans>
          </button>
          <button type="submit" className={`${dialogButton.primary} flex items-center gap-1`}>
            <Trans>start-editing</Trans>
            <ChevronRight className="w-4 h-4 -mr-1 opacity-80" />
          </button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
