import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { join } from "@tauri-apps/api/path";
import { open } from "@tauri-apps/plugin-dialog";
import { writeTextFile } from "@tauri-apps/plugin-fs";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useWorkspace } from "../../hooks/useWorkspace";
import { hasSubtitles, legsCsv, stopsCsv, subtitlesCsv } from "../../utils/projectCsv";
import { mapboxTileLoader, segmentElevations } from "../../utils/terrainElevation";
import { CheckCircle, Folder, Loader2 } from "./icons";
import { Checkbox } from "./Checkbox";
import { Dialog, dialogButton } from "./Dialog";

// Opened with: window.dispatchEvent(new CustomEvent("export-csv")). Exports the project that is open in the editor.
type Table = "stops" | "legs" | "subtitles";

// Excel needs the BOM to read UTF-8 (Japanese) instead of the system code page.
const BOM = "﻿";

export function ExportCsvDialog() {
  const { metadata, waypoints, routeSegments, timeline, settings } = useWorkspace();
  const [isOpen, setIsOpen] = useState(false);
  const [chosen, setChosen] = useState<Record<Table, boolean>>({ stops: true, legs: true, subtitles: true });
  const [phase, setPhase] = useState<"ready" | "working" | "done" | "error">("ready");
  const [folder, setFolder] = useState("");
  const [written, setWritten] = useState<string[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const show = () => {
      setIsOpen(true);
      setPhase("ready");
      setWritten([]);
      setError("");
    };
    window.addEventListener("export-csv", show);
    return () => window.removeEventListener("export-csv", show);
  }, []);

  if (!isOpen) return null;

  const routed = waypoints.filter((w) => !w.isStopBy || w.connectToRoute).length;
  const available: Record<Table, boolean> = { stops: waypoints.length > 0, legs: routed >= 2, subtitles: hasSubtitles(timeline) };
  const on = (k: Table) => available[k] && chosen[k];
  const anything = on("stops") || on("legs") || on("subtitles");
  const working = phase === "working";
  const close = () => !working && setIsOpen(false);
  const base = (metadata.project_name || "navivi").replace(/[\\/:*?"<>|]+/g, "_").trim() || "navivi";

  const run = async () => {
    try {
      const picked = await open({ directory: true, multiple: false });
      if (typeof picked !== "string") return;
      setPhase("working");
      const files: [string, string][] = [];
      if (on("stops")) files.push([`${base}_stops.csv`, stopsCsv(waypoints)]);
      if (on("legs")) {
        // Terrain heights give routed legs a climb; without a token or a connection the legs just have no climb.
        const token = settings.mapbox_api_key || import.meta.env.VITE_MAPBOX_TOKEN;
        const terrain = token ? await segmentElevations(routeSegments, waypoints, mapboxTileLoader(token)).catch(() => []) : [];
        files.push([`${base}_legs.csv`, legsCsv(waypoints, routeSegments, terrain)]);
      }
      if (on("subtitles")) files.push([`${base}_subtitles.csv`, subtitlesCsv(timeline)]);
      for (const [name, text] of files) await writeTextFile(await join(picked, name), BOM + text);
      setFolder(picked);
      setWritten(files.map(([name]) => name));
      setPhase("done");
    } catch (e: any) {
      setError(String(e?.message ?? e));
      setPhase("error");
    }
  };

  const rows: { key: Table; label: string; hint: string; off: string }[] = [
    { key: "stops", label: t`Stops`, hint: t`Name, position, route mode, scripts and media counts for each stop`, off: t`No stops yet` },
    { key: "legs", label: t`Route legs`, hint: t`Distance, climb, walking time and via points between neighbouring stops`, off: t`Needs at least two stops on the route` },
    { key: "subtitles", label: t`Subtitles`, hint: t`Every caption with its start and end time in the video`, off: t`Generate the video first` },
  ];

  return (
    <Dialog
      width="w-[440px]"
      title={phase === "done" ? <Trans>CSV exported</Trans> : <Trans>Export CSV</Trans>}
      subtitle={metadata.project_name}
      onClose={close}
      footer={
        phase === "done" ? (
          <>
            <button className={`${dialogButton.secondary} flex items-center gap-1.5`} onClick={() => invoke("open_in_explorer", { path: folder }).catch(() => undefined)}>
              <Folder className="w-3.5 h-3.5" /> <Trans>Show folder</Trans>
            </button>
            <button className={dialogButton.primary} onClick={close}>
              <Trans>Done</Trans>
            </button>
          </>
        ) : (
          <>
            <button className={dialogButton.secondary} disabled={working} onClick={close}>
              <Trans>Cancel</Trans>
            </button>
            <button className={dialogButton.primary} disabled={working || !anything} onClick={run}>
              {working ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trans>Choose folder…</Trans>}
            </button>
          </>
        )
      }
    >
      {phase === "done" ? (
        <div className="flex flex-col items-center gap-2 py-4 text-center">
          <CheckCircle className="w-9 h-9 text-emerald-500" />
          <p className="text-[12px] text-zinc-500 break-all">{folder}</p>
          <ul className="text-[13px] text-zinc-700 dark:text-zinc-200">
            {written.map((name) => (
              <li key={name} className="break-all">
                {name}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <>
          <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
            <Trans>One CSV file per table, saved into the folder you pick. They open in Excel or Google Sheets. Files with the same name there are replaced.</Trans>
          </p>
          <div className="mt-3 flex flex-col gap-3">
            {rows.map(({ key, label, hint, off }) => (
              <label key={key} className={`flex items-start gap-3 ${available[key] ? "cursor-pointer" : "opacity-60"}`}>
                <span className="mt-0.5">
                  <Checkbox checked={on(key)} onChange={(v) => setChosen((c) => ({ ...c, [key]: v }))} label={label} disabled={!available[key] || working} />
                </span>
                <span className="min-w-0">
                  <span className="block text-[13px] text-zinc-900 dark:text-zinc-100">{label}</span>
                  <span className="mt-0.5 block text-[12px] leading-snug text-zinc-500 dark:text-zinc-400">{available[key] ? hint : off}</span>
                </span>
              </label>
            ))}
          </div>
          {phase === "error" && <p className="mt-3 text-[12px] text-red-500 wrap-break-word">{error}</p>}
        </>
      )}
    </Dialog>
  );
}
