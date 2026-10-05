import { useEffect, useRef, useState } from "react";
import { ChevronDown, Clapperboard } from "../../../components/ui/icons";
import { useWorkspace } from "../../../hooks/useWorkspace";
import type { Waypoint } from "../../../types";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

// Prefecture + city of a point, e.g. "和歌山・和歌山市" (県/府 and 東京都's 都 dropped).
// Same rule as route_brief.on_route for the count.
async function detectLocation(lat: number, lng: number): Promise<string> {
  const res = await fetch(
    `https://nominatim.openstreetmap.org/reverse?format=json&accept-language=ja&zoom=10&lat=${lat}&lon=${lng}`,
  );
  const a = (await res.json())?.address ?? {};
  const region = String(a.province || a.state || "").replace(/^東京都$/, "東京").replace(/[県府]$/, "");
  const city = a.city || a.town || a.village || a.county || "";
  return [region, city].filter(Boolean).filter((v, i, xs) => xs.indexOf(v) === i).join("・");
}

const placeCount = (waypoints: Waypoint[]) => waypoints.filter((w) => !(w.isStopBy && !w.connectToRoute)).length;

const inputClass =
  "w-full h-8 px-2.5 rounded-md bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 text-[13px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-600 focus:outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition-colors";

export function OverviewPanel() {
  const { metadata, updateMetadata, settings, updateSettings, waypoints, setIsDirty } = useWorkspace();
  const [isOpen, setIsOpen] = useState(false);
  const [detecting, setDetecting] = useState(false);

  const isEnabled = metadata.enable_intro !== false;
  const title = metadata.video_title || metadata.project_name || "";
  const location = settings.intro_location ?? "";
  const showCount = settings.intro_place_count !== false;
  const count = placeCount(waypoints);
  const subtitleLine = [metadata.video_subtitle?.trim(), showCount && count ? `${count} か所` : ""]
    .filter(Boolean)
    .join(" · ");
  const summary = !isEnabled
    ? t`Off`
    : [title, metadata.video_subtitle].filter(Boolean).join(" · ") ||
      t`Title card at the start of the video`;

  const update = (patch: Parameters<typeof updateMetadata>[0]) => {
    updateMetadata(patch);
    setIsDirty(true);
  };
  const updateSetting = (patch: Parameters<typeof updateSettings>[0]) => {
    updateSettings(patch);
    setIsDirty(true);
  };

  // Follows the first waypoint (~100 m grid, so a drag doesn't spam Nominatim) until the user types their own.
  const first = waypoints[0];
  const pointKey = first ? `${first.lat.toFixed(3)},${first.lng.toFixed(3)}` : "";
  const manual = settings.intro_location_manual === true;
  const request = useRef(0);

  const detect = async (key: string, lat: number, lng: number) => {
    const id = ++request.current;
    setDetecting(true);
    try {
      const found = await detectLocation(lat, lng);
      if (id !== request.current) return;
      if (found && (found !== settings.intro_location || key !== settings.intro_location_at)) {
        updateSetting({ intro_location: found, intro_location_at: key, intro_location_manual: false });
      }
    } catch {
      // Offline: keep the last one; the user can type it.
    } finally {
      if (id === request.current) setDetecting(false);
    }
  };

  useEffect(() => {
    if (manual || !first || pointKey === settings.intro_location_at) return;
    const timer = setTimeout(() => detect(pointKey, first.lat, first.lng), 800);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pointKey, manual, settings.intro_location_at]);

  return (
    <section className="rounded-lg border border-zinc-200 dark:border-white/8 bg-white dark:bg-white/2">
      <div className="flex items-center gap-2.5 pl-2 pr-2.5 py-2">
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          aria-expanded={isOpen}
          className="flex-1 min-w-0 flex items-center gap-2.5 text-left rounded-md -my-1 py-1 -ml-1 pl-1 hover:bg-zinc-50 dark:hover:bg-white/4 transition-colors"
        >
          <span
            className={`w-7 h-7 rounded-md flex items-center justify-center shrink-0 transition-colors ${
              isEnabled
                ? "bg-navi/10 text-navi"
                : "bg-zinc-100 dark:bg-white/5 text-zinc-400"
            }`}
          >
            <Clapperboard className="w-3.5 h-3.5" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
              <Trans>Intro</Trans>
            </span>
            <span
              className={`block text-[11px] truncate ${isEnabled ? "text-zinc-500" : "text-zinc-400 dark:text-zinc-600"}`}
              title={summary}
            >
              {summary}
            </span>
          </span>
          <ChevronDown
            className={`w-3.5 h-3.5 text-zinc-400 shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`}
          />
        </button>

        <button
          type="button"
          role="switch"
          aria-checked={isEnabled}
          aria-label={t`Generate intro video`}
          title={t`Generate intro video`}
          onClick={() => update({ enable_intro: !isEnabled })}
          className={`relative w-7 h-4 rounded-full shrink-0 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-navi/40 ${
            isEnabled ? "bg-navi" : "bg-zinc-300 dark:bg-zinc-700"
          }`}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-white shadow-sm transition-transform ${
              isEnabled ? "translate-x-3" : ""
            }`}
          />
        </button>
      </div>

      {isOpen && (
        <div className="px-3 pb-3 pt-1 space-y-2.5 border-t border-zinc-100 dark:border-white/5 animate-in fade-in duration-150">
          {isEnabled ? (
            <>
              <label className="block pt-1.5">
                <span className="block text-[11px] font-medium text-zinc-500 mb-1">
                  <Trans>Location</Trans>
                </span>
                <div className="flex gap-1.5">
                  <input
                    type="text"
                    value={location}
                    onChange={(e) => updateSetting({ intro_location: e.target.value, intro_location_manual: true })}
                    placeholder={detecting ? t`Detecting...` : t`E.g. Wakayama, Wakayama City`}
                    className={inputClass}
                  />
                  <button
                    type="button"
                    onClick={() => updateSetting({ intro_location_manual: false, intro_location_at: "" })}
                    disabled={detecting || !waypoints.length || (!manual && pointKey === settings.intro_location_at)}
                    title={t`Follow the first waypoint again`}
                    className="h-8 px-2.5 shrink-0 rounded-md border border-zinc-200 dark:border-white/10 text-[11px] text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-white/5 disabled:opacity-50 transition-colors"
                  >
                    <Trans>Detect</Trans>
                  </button>
                </div>
                <span className="block text-[10px] text-zinc-400 mt-1">
                  <Trans>Small line above the title, from the first waypoint. Also shown on the outro.</Trans>
                </span>
              </label>

              <label className="block">
                <span className="block text-[11px] font-medium text-zinc-500 mb-1">
                  <Trans>Title</Trans>
                </span>
                <input
                  type="text"
                  value={metadata.video_title || ""}
                  onChange={(e) => update({ video_title: e.target.value })}
                  placeholder={metadata.project_name || t`Title`}
                  className={inputClass}
                />
                <span className="block text-[10px] text-zinc-400 mt-1">
                  <Trans>Leave blank to use the project name.</Trans>
                </span>
              </label>

              <label className="block">
                <span className="block text-[11px] font-medium text-zinc-500 mb-1">
                  <Trans>Subtitle</Trans>
                </span>
                <input
                  type="text"
                  value={metadata.video_subtitle || ""}
                  onChange={(e) => update({ video_subtitle: e.target.value })}
                  placeholder={t`E.g. Tomogashima and Kada area...`}
                  className={inputClass}
                />
              </label>

              <label className="flex items-center gap-2 text-[11px] text-zinc-500 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={showCount}
                  onChange={(e) => updateSetting({ intro_place_count: e.target.checked })}
                  className="accent-navi"
                />
                <Trans>Add the number of places ({count} か所)</Trans>
              </label>

              <div
                aria-hidden
                className="aspect-video w-full rounded-md bg-linear-to-b from-zinc-800 to-zinc-950 ring-1 ring-black/5 dark:ring-white/10 flex flex-col items-center justify-center gap-1 px-4 text-center overflow-hidden"
              >
                {location && (
                  <span className="text-zinc-300 text-[9px] tracking-[0.15em] truncate max-w-full">{location}</span>
                )}
                <span className="text-white text-sm font-semibold truncate max-w-full">
                  {title || t`Project Title`}
                </span>
                {subtitleLine && (
                  <span className="text-zinc-300 text-[10px] font-medium truncate max-w-full">{subtitleLine}</span>
                )}
              </div>
            </>
          ) : (
            <p className="pt-1.5 text-[11px] text-zinc-500 leading-relaxed">
              <Trans>
                The video starts directly on the route. Turn the intro on to add a
                title card.
              </Trans>
            </p>
          )}
        </div>
      )}
    </section>
  );
}
