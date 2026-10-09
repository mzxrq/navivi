import { useState, useEffect, useRef } from "react";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import { aiEngine } from "../../services/ai/engine";
import { buildProject, type BuildProgress } from "../../services/assistant/buildProject";
import { EMPTY_BRIEF } from "../../services/assistant/brief";
import { resolveNarrationLanguage } from "../../utils/narrationLanguage";
import { i18n } from "@lingui/core";
import type { Waypoint } from "../../types";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { AlertTriangle, ChevronDown, Loader2, MapPin, Search, Trash2, X } from "./icons";
import { dialogInput } from "./Dialog";
import { distanceKm, medianPoint, searchPlaces, type PlaceCandidate } from "../../services/geocode";

// A stop this far from the middle of the others is most likely a namesake elsewhere (a walk is small, a drive is not).
const farFromRouteKm = (walking: boolean) => (walking ? 25 : 120);

// One proposed stop. Closed it is a line; open it shows where the stop was placed (a still map) and lets the person pick
// another place by searching or type the coordinates, so the project never receives a stop on the wrong spot.
function StopRow({ wp, index, uncertain, token, open, onToggle, onChange, onRemove }: {
  wp: Waypoint;
  index: number;
  uncertain: boolean;
  token?: string;
  open: boolean;
  onToggle: () => void;
  onChange: (patch: Partial<Waypoint>) => void;
  onRemove: () => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PlaceCandidate[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [coords, setCoords] = useState(`${wp.lat.toFixed(5)}, ${wp.lng.toFixed(5)}`);
  const [coordsBad, setCoordsBad] = useState(false);

  useEffect(() => {
    setCoords(`${wp.lat.toFixed(5)}, ${wp.lng.toFixed(5)}`);
    setCoordsBad(false);
  }, [wp.lat, wp.lng]);

  const search = async () => {
    if (!query.trim() || searching) return;
    setSearching(true);
    try {
      setResults(await searchPlaces(query, { mapboxToken: token, near: { lat: wp.lat, lng: wp.lng } }));
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  const commitCoords = () => {
    const m = coords.match(/^\s*(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)\s*$/);
    const [lat, lng] = m ? [parseFloat(m[1]), parseFloat(m[2])] : [NaN, NaN];
    if (!(Math.abs(lat) <= 90 && Math.abs(lng) <= 180)) return setCoordsBad(true);
    setCoordsBad(false);
    if (lat !== wp.lat || lng !== wp.lng) onChange({ lat, lng });
  };

  const preview = token
    ? `https://api.mapbox.com/styles/v1/mapbox/outdoors-v12/static/pin-s+4287f5(${wp.lng},${wp.lat})/${wp.lng},${wp.lat},12.5,0/560x200@2x?access_token=${token}`
    : null;

  return (
    <div className={`rounded-lg border ${uncertain ? "border-amber-300/70 dark:border-amber-400/30" : "border-zinc-200 dark:border-white/5"}`}>
      <div className="flex items-center gap-3 p-2.5">
        <span className="w-5 h-5 shrink-0 flex items-center justify-center rounded-full bg-navi text-white text-[11px] font-semibold tabular-nums">{index + 1}</span>
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100 truncate">{wp.name}</div>
          <div className="text-[11px] tabular-nums text-zinc-500 truncate">
            {wp.lat.toFixed(4)}, {wp.lng.toFixed(4)}
          </div>
        </div>
        {uncertain && (
          <span className="shrink-0 flex items-center gap-1 text-[11px] text-amber-600 dark:text-amber-400">
            <AlertTriangle className="w-3 h-3" />
            <Trans>Check location</Trans>
          </span>
        )}
        <button type="button" onClick={onToggle} aria-expanded={open} className="shrink-0 flex items-center gap-1 h-7 px-2 rounded-md text-[12px] text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors">
          <MapPin className="w-3.5 h-3.5" />
          <Trans>Location</Trans>
          <ChevronDown className={`w-3 h-3 opacity-60 transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
        <button type="button" onClick={onRemove} title={t`Leave this stop out`} aria-label={t`Leave this stop out`} className="shrink-0 p-1.5 rounded-md text-zinc-400 hover:text-red-500 hover:bg-red-500/10 transition-colors">
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>

      {open && (
        <div className="flex flex-col gap-2.5 px-2.5 pb-2.5 border-t border-zinc-100 dark:border-white/5 pt-2.5">
          {preview ? (
            <img src={preview} alt="" className="w-full h-28 object-cover rounded-md bg-zinc-100 dark:bg-zinc-800" />
          ) : (
            <p className="text-[12px] text-zinc-500">
              <Trans>Add a Mapbox key in Settings to see a map here.</Trans>
            </p>
          )}
          <div className="flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search()}
              placeholder={t`Search for the right place`}
              className={`${dialogInput} select-text h-8`}
            />
            <button type="button" onClick={search} disabled={searching || !query.trim()} className="shrink-0 flex items-center gap-1.5 h-8 px-3 rounded-lg text-[12px] font-medium bg-zinc-100 dark:bg-white/10 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-200 dark:hover:bg-white/15 disabled:opacity-40 transition-colors">
              {searching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
              <Trans>Search</Trans>
            </button>
          </div>
          {results && (
            <div className="flex flex-col rounded-lg border border-zinc-200 dark:border-white/10 divide-y divide-zinc-100 dark:divide-white/5 max-h-36 overflow-y-auto custom-scrollbar">
              {results.length === 0 ? (
                <p className="px-2.5 py-2 text-[12px] text-zinc-500">
                  <Trans>Nothing found. Try another spelling, or type the coordinates below.</Trans>
                </p>
              ) : (
                results.map((r, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => {
                      onChange({ lat: r.lat, lng: r.lng });
                      setResults(null);
                    }}
                    className="text-left px-2.5 py-1.5 hover:bg-zinc-50 dark:hover:bg-white/5 transition-colors"
                  >
                    <div className="text-[12px] text-zinc-800 dark:text-zinc-200 truncate">{r.name}</div>
                    <div className="text-[11px] tabular-nums text-zinc-500">{r.lat.toFixed(5)}, {r.lng.toFixed(5)}</div>
                  </button>
                ))
              )}
            </div>
          )}
          <label className="flex items-center gap-2 text-[12px] text-zinc-500">
            <span className="shrink-0"><Trans>Coordinates</Trans></span>
            <input
              value={coords}
              onChange={(e) => setCoords(e.target.value)}
              onBlur={commitCoords}
              onKeyDown={(e) => e.key === "Enter" && commitCoords()}
              aria-invalid={coordsBad}
              placeholder="34.2908, 135.1508"
              className={`${dialogInput} select-text h-8 tabular-nums ${coordsBad ? "border-red-400!" : ""}`}
            />
          </label>
        </div>
      )}
    </div>
  );
}

// The window that turns an imported document into stops. `autoDirectorData` carries the title of the action that opened it
// (File > Import document...) and the file name, so the window is named after what the user did, not after the engine.
export function AutoDirectorModal() {
  const { autoDirectorData, setAutoDirectorData, showToast } = useUI();
  const { waypoints, setWaypoints, updateSettings, setIsDirty, settings } = useWorkspace();
  const merging = waypoints.length > 0;
  const [status, setStatus] = useState("");
  const [proposedWaypoints, setProposedWaypoints] = useState<Waypoint[]>([]);
  const [uncertain, setUncertain] = useState<Record<string, boolean>>({});
  const [openId, setOpenId] = useState<string | null>(null);
  const [intro, setIntro] = useState("");
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [isProcessing, setIsProcessing] = useState(false);
  const [isProposal, setIsProposal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (autoDirectorData?.state === "processing" && !isProcessing && !isProposal && !error) {
      processDocument(autoDirectorData.content);
    }
  }, [autoDirectorData, isProcessing, isProposal, error]);

  const progressText = ({ step, done, total, label }: BuildProgress) => {
    if (step === "places") return t`Finding the places in the document...`;
    if (step === "geocode") return t`Locating places (${done} of ${total}) ${label}`;
    return t`Writing scripts (${done} of ${total}) ${label}`;
  };

  const close = () => {
    abortRef.current?.abort();
    setIsProposal(false);
    setOpenId(null);
    setError(null);
    setStatus("");
    setAutoDirectorData(null);
  };

  const processDocument = async (text: string) => {
    setIsProcessing(true);
    setStatus(t`Reading the document...`);
    abortRef.current = new AbortController();
    try {
      const built = await buildProject({
        brief: { ...EMPTY_BRIEF, languages: [resolveNarrationLanguage(settings?.narration_language, [text], i18n.locale)] },
        sourceText: text,
        engine: aiEngine(settings),
        mapboxToken: settings?.mapbox_api_key || import.meta.env.VITE_MAPBOX_TOKEN,
        signal: abortRef.current.signal,
        onProgress: (p) => setStatus(progressText(p)),
      });

      if (built.waypoints.length === 0) {
        setError(
          built.failedPlaces.length > 0
            ? t`No places could be located on the map. Tried: ${built.failedPlaces.slice(0, 5).join(", ")}`
            : t`No places were found in this document.`,
        );
        return;
      }

      setProposedWaypoints(built.waypoints);
      setIntro(built.overviewIntro ?? "");
      setChecked({});
      setUncertain(Object.fromEntries(built.waypoints.map((w, i) => [w.id, built.uncertain[i]])));
      setOpenId(built.waypoints.find((_, i) => built.uncertain[i])?.id ?? null);
      setIsProposal(true);
      setStatus("");
    } catch (e: any) {
      if (e?.name === "AbortError") return;
      console.error(e);
      setError(e?.message ? t`The document could not be processed: ${e.message}` : t`The document could not be processed.`);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleApply = () => {
    if (merging) {
      setWaypoints((prev) => [...prev, ...proposedWaypoints]);
      showToast(t`Added ${proposedWaypoints.length} stops to the project.`, "success");
    } else {
      setWaypoints(proposedWaypoints);
      updateSettings({ default_export_resolution: "1080p" });
      showToast(t`Created ${proposedWaypoints.length} stops from the document.`, "success");
    }
    // The course introduction opens the overview video ("course" style); a project that already has one keeps it.
    if (intro.trim() && !settings?.overview_intro?.trim()) {
      updateSettings({ overview_intro: intro.trim(), ...(merging ? {} : { overview_style: "course" as const }) });
    }
    setIsDirty(true);
    close();
  };

  if (!autoDirectorData) return null;

  const title: string = autoDirectorData.title || t`Import document`;
  const fileName: string = autoDirectorData.fileName || "";
  const count = proposedWaypoints.length;
  const token: string | undefined = settings?.mapbox_api_key || import.meta.env.VITE_MAPBOX_TOKEN;
  const canSeedIntro = !settings?.overview_intro?.trim();
  // A name that matched is not a place that is right: stops far from where most of the route is get the same mark as guessed ones.
  const middle = proposedWaypoints.length >= 4 ? medianPoint(proposedWaypoints) : null;
  const reach = farFromRouteKm(proposedWaypoints[0]?.routeMode === "walking");
  const needsCheck = (w: Waypoint) => !checked[w.id] && (!!uncertain[w.id] || (!!middle && distanceKm(w, middle) > reach));
  const toCheck = proposedWaypoints.filter(needsCheck).length;
  const patchStop = (id: string, patch: Partial<Waypoint>) => {
    setProposedWaypoints((list) => list.map((w) => (w.id === id ? { ...w, ...patch } : w)));
    setUncertain((u) => ({ ...u, [id]: false }));
    setChecked((c) => ({ ...c, [id]: true }));
  };
  const quietButton =
    "h-8 px-3 rounded-lg text-[13px] font-medium text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors";
  const primaryButton = "h-8 px-4 rounded-lg text-[13px] font-medium bg-navi text-white hover:brightness-110 transition";
  const footer = "flex justify-end gap-2 px-5 py-3 border-t border-zinc-100 dark:border-white/5 shrink-0";

  return (
    <div className="fixed inset-x-0 top-10 bottom-0 bg-zinc-950/30 backdrop-blur-[2px] z-99999 flex items-center justify-center p-4">
      <div
        role="dialog"
        aria-label={title}
        className="select-none bg-white dark:bg-zinc-900 rounded-xl w-full max-w-xl shadow-xl border border-zinc-200 dark:border-white/10 flex flex-col max-h-[80vh] overflow-hidden"
      >
        <div className="flex items-start gap-3 px-5 pt-4 pb-3 border-b border-zinc-100 dark:border-white/5 shrink-0">
          <div className="flex-1 min-w-0">
            <h2 className="text-[14px] font-semibold text-zinc-900 dark:text-zinc-100">{title}</h2>
            {fileName && (
              <p className="text-[12px] text-zinc-500 truncate" title={fileName}>
                {fileName}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={close}
            aria-label={t`Close`}
            title={t`Close`}
            className="p-1 -mr-1 rounded-md text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/5 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {error ? (
          <>
            <div className="flex items-start gap-3 px-5 py-6">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-amber-500" />
              <p className="text-[13px] leading-relaxed text-zinc-700 dark:text-zinc-300">{error}</p>
            </div>
            <div className={footer}>
              <button type="button" onClick={close} className={primaryButton}>
                <Trans>Close</Trans>
              </button>
            </div>
          </>
        ) : !isProposal ? (
          <>
            <div className="flex items-center gap-3 px-5 py-8 text-zinc-500">
              <Loader2 className="w-4 h-4 animate-spin text-navi shrink-0" />
              <p className="text-[13px] min-w-0 truncate">{status}</p>
            </div>
            <div className={footer}>
              <button type="button" onClick={close} className={quietButton}>
                <Trans>Cancel</Trans>
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="px-5 pt-3 pb-2 text-[12px] text-zinc-500 shrink-0">
              {merging
                ? t`${count} stops found. They will be added after the stops already in this project.`
                : t`${count} stops found.`}{" "}
              {toCheck > 0 ? t`Check the ${toCheck} marked locations before adding; the others were matched by name.` : t`Open Location on a stop to check where it was placed.`}
            </p>
            <div className="flex flex-col gap-1.5 overflow-y-auto custom-scrollbar px-5 pb-3 flex-1">
              {canSeedIntro && intro && (
                <label className="flex flex-col gap-1 p-2.5 rounded-lg border border-zinc-200 dark:border-white/5">
                  <span className="text-[12px] font-medium text-zinc-700 dark:text-zinc-300">
                    <Trans>Introduction for the overview video</Trans>
                  </span>
                  <textarea
                    value={intro}
                    onChange={(e) => setIntro(e.target.value)}
                    rows={3}
                    className={`${dialogInput} select-text h-auto py-2 leading-relaxed resize-none`}
                  />
                  <span className="text-[11px] text-zinc-500">
                    <Trans>Written from the document's own course details. Clear it to leave the introduction empty.</Trans>
                  </span>
                </label>
              )}
              {proposedWaypoints.map((wp, i) => (
                <StopRow
                  key={wp.id}
                  wp={wp}
                  index={i}
                  uncertain={needsCheck(wp)}
                  token={token}
                  open={openId === wp.id}
                  onToggle={() => setOpenId(openId === wp.id ? null : wp.id)}
                  onChange={(patch) => patchStop(wp.id, patch)}
                  onRemove={() => setProposedWaypoints((list) => list.filter((w) => w.id !== wp.id))}
                />
              ))}
            </div>
            <div className={footer}>
              <button type="button" onClick={close} className={quietButton}>
                <Trans>Cancel</Trans>
              </button>
              <button type="button" onClick={handleApply} disabled={count === 0} className={`${primaryButton} disabled:opacity-40 disabled:pointer-events-none`}>
                {merging ? t`Add ${count} stops` : t`Create ${count} stops`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
