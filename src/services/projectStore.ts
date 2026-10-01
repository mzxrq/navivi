import { join } from "@tauri-apps/api/path";
import { appConfig, fileSystem } from "../config/constants";
import { DbProject, DbProjectInput, RecentProjects } from "../types";
import { db } from "./db";
import { loadRouteCache } from "./fileSystem";
import { readLegacyHistory } from "./versionHistory";

type RouteCache = Record<string, [number, number][]>;

const LEGACY_RECENTS_KEY = "navivi-recents";
const MIGRATED_RECENTS = "migrated.recents";
const LEGACY_RECENTS = "recents.legacy";

const isAbsolute = (p: string) => /^[a-zA-Z]:[\\/]/.test(p) || p.startsWith("/") || p.startsWith("\\\\");

/** job_config.json (as returned by loadProjectData) -> DB row input. */
export function projectInputFromJobConfig(data: any, selectedPath?: string): DbProjectInput {
  const archive =
    selectedPath && selectedPath.endsWith(`.${fileSystem.extensions.project}`) ? selectedPath : null;
  return {
    id: data.project_id,
    name: data.project_name || appConfig.defaultProjectName,
    directoryPath: data.directory_path,
    userId: data.user_id ?? null,
    theme: data.theme ?? null,
    status: "saved",
    archivePath: archive,
    thumbnailPath: data.thumbnail_path || null,
    videoTitle: data.video_title || "",
    videoSubtitle: data.video_subtitle || "",
    enableIntro: data.enable_intro ?? true,
    overviewNarration: data.overview_narration || "",
    overviewNarrationIsAuto: Boolean(data.overview_narration_is_auto),
    overviewNarrationSourceIds: Array.isArray(data.overview_narration_source_ids)
      ? data.overview_narration_source_ids
      : [],
    createdAt: data.created_at || undefined,
  };
}

/**
 * Brings the DB in line with a project just read from disk and returns the data to show.
 * - Not in the DB yet: import it (plus `.history/` and `.routecache.json`).
 * - File newer than the DB row (other machine, or another project reusing the id): file wins.
 * - Otherwise the DB wins for metadata and settings. Waypoints and the overview-narration
 *   fields (written by the Python pipeline) always come from the file.
 */
export async function syncProjectOnOpen(
  data: any,
  selectedPath: string,
): Promise<{ data: any; routingCache: RouteCache; project: DbProject }> {
  const input = projectInputFromJobConfig(data, selectedPath);
  const dir = input.directoryPath;
  const fileUpdatedAt = typeof data.updated_at === "number" ? data.updated_at : 0;
  let row = await db.projects.get(input.id);

  if (!row) {
    const [versions, routeCache] = await Promise.all([
      readLegacyHistory(dir, input.id),
      loadRouteCache(dir),
    ]);
    const report = await db.projects.importLegacy({
      project: input,
      settings: data.settings ?? null,
      versions,
      routeCache,
    });
    console.log(
      `Imported project ${input.id} into the database (${report.versionsImported} versions, ${report.routesImported} routes).`,
    );
    row = report.project;
  } else if (fileUpdatedAt > row.updatedAt) {
    row = await db.projects.upsert(input);
    if (data.settings) await db.settings.put(row.id, data.settings);
    await db.routeCache.replace(row.id, await loadRouteCache(dir));
  } else {
    row = await db.projects.update(row.id, {
      directoryPath: dir,
      archivePath: "", // projects open from their folder now; an old archive path would reopen stale files
      overviewNarration: input.overviewNarration,
      overviewNarrationIsAuto: input.overviewNarrationIsAuto,
      overviewNarrationSourceIds: input.overviewNarrationSourceIds,
    });
  }

  row = await db.projects.touchOpened(row.id);
  const settings = (await db.settings.get(row.id)) ?? data.settings;
  const routingCache = await db.routeCache.getAll(row.id);

  return {
    project: row,
    routingCache,
    data: {
      ...data,
      project_name: row.name,
      user_id: row.userId ?? data.user_id,
      theme: row.theme ?? data.theme,
      created_at: row.createdAt,
      video_title: row.videoTitle,
      video_subtitle: row.videoSubtitle,
      enable_intro: row.enableIntro,
      settings,
    },
  };
}

async function toRecent(p: DbProject): Promise<RecentProjects> {
  let thumbnailPath = p.thumbnailPath || undefined;
  if (thumbnailPath && !isAbsolute(thumbnailPath)) {
    thumbnailPath = await join(p.directoryPath, thumbnailPath);
  }
  return {
    projectId: p.id,
    name: p.name,
    path: p.archivePath || p.directoryPath,
    lastOpened: p.lastOpenedAt ?? p.updatedAt,
    thumbnailPath,
  };
}

// Copies the localStorage recents list into the DB once; localStorage is left untouched.
async function migrateLegacyRecents(): Promise<RecentProjects[]> {
  if (await db.appSettings.get<boolean>(MIGRATED_RECENTS)) {
    return (await db.appSettings.get<RecentProjects[]>(LEGACY_RECENTS)) ?? [];
  }
  let legacy: RecentProjects[] = [];
  try {
    const raw = localStorage.getItem(LEGACY_RECENTS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed)) legacy = parsed.filter((r) => r && typeof r.path === "string");
  } catch {
    legacy = [];
  }
  await db.appSettings.set(LEGACY_RECENTS, legacy);
  await db.appSettings.set(MIGRATED_RECENTS, true);
  return legacy;
}

/** Recently opened projects from the DB, then pre-DB recents not yet opened again. */
export async function listRecents(limit = 50): Promise<RecentProjects[]> {
  const rows = await db.projects.list({ sort: "recent", limit });
  const recents = await Promise.all(rows.filter((r) => r.lastOpenedAt != null).map(toRecent));
  const known = new Set(recents.map((r) => r.path));
  const legacy = (await migrateLegacyRecents()).filter((r) => !known.has(r.path));
  return [...recents, ...legacy].slice(0, limit);
}

export async function removeRecent(entry: RecentProjects): Promise<void> {
  if (entry.projectId) await db.projects.forgetOpened(entry.projectId);
  const legacy = (await db.appSettings.get<RecentProjects[]>(LEGACY_RECENTS)) ?? [];
  if (legacy.some((r) => r.path === entry.path)) {
    await db.appSettings.set(LEGACY_RECENTS, legacy.filter((r) => r.path !== entry.path));
  }
}

export async function renameRecent(entry: RecentProjects, name: string): Promise<void> {
  if (entry.projectId) {
    await db.projects.update(entry.projectId, { name });
    return;
  }
  const legacy = (await db.appSettings.get<RecentProjects[]>(LEGACY_RECENTS)) ?? [];
  await db.appSettings.set(
    LEGACY_RECENTS,
    legacy.map((r) => (r.path === entry.path ? { ...r, name } : r)),
  );
}
