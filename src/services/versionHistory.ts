import { join } from "@tauri-apps/api/path";
import { exists, readTextFile } from "@tauri-apps/plugin-fs";
import { db } from "./db";
import { emptyTimeline } from "../features/editor/model";
import {
    DbVersion,
    ProjectVersion,
    ProjectVersionSnapshot,
    RouteSegment,
    ProjectMetadata,
    ProjectSettings,
    TimelineData,
    Waypoint,
} from "../types";

const HISTORY_DIRECTORY = ".history";
const HISTORY_MANIFEST = "manifest.json";

interface VersionInput {
    projectId: string;
    projectName: string;
    label: string;
    waypoints: Waypoint[];
    routeSegments: RouteSegment[];
    metadata: ProjectMetadata;
    settings: ProjectSettings;
    timeline: TimelineData;
    routePoints: number[][];
    drawnRoute: [number, number][];
    routingCache: Record<string, [number, number][]>;
    activeWaypointId: string | null;
}

interface HistoryManifest {
    version: 1;
    projectId: string;
    versions: ProjectVersion[];
}

async function getHistoryPaths(projectDir: string) {
    const historyDir = await join(projectDir, HISTORY_DIRECTORY);
    return {
        historyDir,
        manifestPath: await join(historyDir, HISTORY_MANIFEST),
    };
}

async function readManifest(projectDir: string): Promise<HistoryManifest> {
    try {
        const { manifestPath } = await getHistoryPaths(projectDir);
        if (!(await exists(manifestPath))) {
            return { version: 1, projectId: "", versions: [] };
        }

        const parsed = JSON.parse(await readTextFile(manifestPath)) as Partial<HistoryManifest>;
        if (parsed.version !== 1 || !Array.isArray(parsed.versions)) {
            return { version: 1, projectId: "", versions: [] };
        }

        return {
            version: 1,
            projectId: typeof parsed.projectId === "string" ? parsed.projectId : "",
            versions: parsed.versions.filter((version): version is ProjectVersion =>
                Boolean(
                    version &&
                    typeof version.id === "string" &&
                    typeof version.projectId === "string" &&
                    typeof version.createdAt === "string",
                ),
            ),
        };
    } catch (error) {
        console.error("Failed to load version history:", error);
        return { version: 1, projectId: "", versions: [] };
    }
}

function readTimeline(value: unknown): TimelineData {
    const timeline = value as Partial<TimelineData> | null;
    // Snapshots from the old multi-track editor have no segments; they restore as an empty timeline.
    if (!timeline || !Array.isArray(timeline.segments)) return emptyTimeline();
    return {
        ...emptyTimeline(),
        ...timeline,
        segments: timeline.segments,
        subtitles: Array.isArray(timeline.subtitles) ? timeline.subtitles : [],
    };
}

function normalizeSnapshot(value: unknown, projectId: string, versionId: string): ProjectVersionSnapshot | null {
    if (!value || typeof value !== "object") return null;
    const snapshot = value as ProjectVersionSnapshot;
    if (snapshot.id !== versionId || snapshot.projectId !== projectId ||
        !Array.isArray(snapshot.waypoints) || !Array.isArray(snapshot.routeSegments) ||
        !snapshot.metadata || typeof snapshot.metadata !== "object" ||
        !snapshot.settings || typeof snapshot.settings !== "object") return null;
    return {
        ...snapshot,
        timeline: readTimeline(snapshot.timeline),
        routePoints: Array.isArray(snapshot.routePoints) ? snapshot.routePoints : [],
        drawnRoute: Array.isArray(snapshot.drawnRoute) ? snapshot.drawnRoute : [],
        routingCache: snapshot.routingCache && typeof snapshot.routingCache === "object" ? snapshot.routingCache : {},
        activeWaypointId: typeof snapshot.activeWaypointId === "string" ? snapshot.activeWaypointId : null,
    };
}

// Versions live in SQLite (the DB keeps the newest 30). `projectDir` stays in the
// signatures for callers; only the legacy `.history/` reader uses it.

export async function listProjectVersions(_projectDir: string, projectId: string): Promise<ProjectVersion[]> {
    if (!projectId) return [];
    try {
        return await db.versions.list(projectId);
    } catch (error) {
        console.error("Failed to load version history:", error);
        return [];
    }
}

export async function saveProjectVersion(input: VersionInput): Promise<ProjectVersion> {
    const version: ProjectVersion = {
        id: crypto.randomUUID(),
        projectId: input.projectId,
        projectName: input.projectName,
        label: input.label.trim() || `Snapshot ${new Date().toLocaleString()}`,
        createdAt: new Date().toISOString(),
        waypointCount: input.waypoints.length,
        clipCount: input.timeline.segments.length,
    };
    const snapshot: ProjectVersionSnapshot = {
        ...version,
        waypoints: structuredClone(input.waypoints),
        routeSegments: structuredClone(input.routeSegments),
        metadata: structuredClone(input.metadata),
        settings: structuredClone(input.settings),
        timeline: structuredClone(input.timeline),
        routePoints: structuredClone(input.routePoints),
        drawnRoute: structuredClone(input.drawnRoute),
        routingCache: structuredClone(input.routingCache),
        activeWaypointId: input.activeWaypointId,
    };
    return db.versions.create({ ...version, snapshot });
}

export async function loadProjectVersion(
    _projectDir: string,
    projectId: string,
    versionId: string,
): Promise<ProjectVersionSnapshot | null> {
    try {
        const row = await db.versions.get(projectId, versionId);
        return row ? normalizeSnapshot(row.snapshot, projectId, versionId) : null;
    } catch (error) {
        console.error("Failed to load project version:", error);
        return null;
    }
}

export async function renameProjectVersion(
    projectId: string,
    versionId: string,
    label: string,
): Promise<ProjectVersion> {
    return db.versions.rename(projectId, versionId, label);
}

export async function deleteProjectVersion(
    _projectDir: string,
    projectId: string,
    versionId: string,
): Promise<boolean> {
    return db.versions.delete(projectId, versionId);
}

/** Reads a pre-DB `.history/` folder so it can be imported once. */
export async function readLegacyHistory(projectDir: string, projectId: string): Promise<DbVersion[]> {
    if (!projectDir || !projectId) return [];
    const manifest = await readManifest(projectDir);
    if (manifest.projectId && manifest.projectId !== projectId) return [];

    const { historyDir } = await getHistoryPaths(projectDir);
    const out: DbVersion[] = [];
    for (const meta of manifest.versions.filter((v) => v.projectId === projectId)) {
        try {
            const path = await join(historyDir, `${meta.id}.json`);
            if (!(await exists(path))) continue;
            const snapshot = normalizeSnapshot(JSON.parse(await readTextFile(path)), projectId, meta.id);
            if (snapshot) out.push({ ...meta, label: meta.label || "Imported version", snapshot });
        } catch (error) {
            console.warn(`Skipping unreadable legacy version ${meta.id}:`, error);
        }
    }
    return out;
}
