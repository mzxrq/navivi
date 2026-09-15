import { join } from "@tauri-apps/api/path";
import {
    exists,
    mkdir,
    readTextFile,
    remove,
    writeTextFile,
} from "@tauri-apps/plugin-fs";
import {
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
const MAX_VERSIONS = 30;

interface VersionInput {
    projectId: string;
    projectName: string;
    label: string;
    waypoints: Waypoint[];
    routeSegments: RouteSegment[];
    metadata: ProjectMetadata;
    settings: ProjectSettings;
    timeline: TimelineData;
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

export async function listProjectVersions(projectDir: string, projectId: string): Promise<ProjectVersion[]> {
    if (!projectDir || !projectId) return [];
    const manifest = await readManifest(projectDir);
    if (manifest.projectId && manifest.projectId !== projectId) return [];

    return manifest.versions
        .filter((version) => version.projectId === projectId)
        .sort((left, right) => right.createdAt.localeCompare(left.createdAt));
}

export async function saveProjectVersion(input: VersionInput): Promise<ProjectVersion> {
    const { historyDir, manifestPath } = await getHistoryPaths(input.metadata.directory_path);
    await mkdir(historyDir, { recursive: true });

    const manifest = await readManifest(input.metadata.directory_path);
    const version: ProjectVersion = {
        id: crypto.randomUUID(),
        projectId: input.projectId,
        projectName: input.projectName,
        label: input.label.trim() || `Snapshot ${new Date().toLocaleString()}`,
        createdAt: new Date().toISOString(),
        waypointCount: input.waypoints.length,
        clipCount: input.timeline.clips.length,
    };
    const snapshot: ProjectVersionSnapshot = {
        ...version,
        waypoints: structuredClone(input.waypoints),
        routeSegments: structuredClone(input.routeSegments),
        metadata: structuredClone(input.metadata),
        settings: structuredClone(input.settings),
        timeline: structuredClone(input.timeline),
    };

    await writeTextFile(
        await join(historyDir, `${version.id}.json`),
        JSON.stringify(snapshot, null, 2),
    );

    const versions = [version, ...manifest.versions.filter((item) => item.id !== version.id)]
        .filter((item) => item.projectId === input.projectId)
        .sort((left, right) => right.createdAt.localeCompare(left.createdAt));
    const removedVersions = versions.slice(MAX_VERSIONS);
    for (const removed of removedVersions) {
        try {
            await remove(await join(historyDir, `${removed.id}.json`));
        } catch {
            // A missing old snapshot should not prevent new versions from being saved.
        }
    }

    await writeTextFile(
        manifestPath,
        JSON.stringify({ version: 1, projectId: input.projectId, versions: versions.slice(0, MAX_VERSIONS) }, null, 2),
    );
    return version;
}

export async function loadProjectVersion(
    projectDir: string,
    projectId: string,
    versionId: string,
): Promise<ProjectVersionSnapshot | null> {
    const versions = await listProjectVersions(projectDir, projectId);
    if (!versions.some((version) => version.id === versionId)) return null;

    try {
        const { historyDir } = await getHistoryPaths(projectDir);
        const snapshot = JSON.parse(
            await readTextFile(await join(historyDir, `${versionId}.json`)),
        ) as ProjectVersionSnapshot;
        if (snapshot.projectId !== projectId || snapshot.id !== versionId) return null;
        return snapshot;
    } catch (error) {
        console.error("Failed to load project version:", error);
        return null;
    }
}

export async function deleteProjectVersion(
    projectDir: string,
    projectId: string,
    versionId: string,
): Promise<boolean> {
    const manifest = await readManifest(projectDir);
    if (manifest.projectId && manifest.projectId !== projectId) return false;
    const version = manifest.versions.find(
        (item) => item.id === versionId && item.projectId === projectId,
    );
    if (!version) return false;

    const { historyDir, manifestPath } = await getHistoryPaths(projectDir);
    try {
        await remove(await join(historyDir, `${versionId}.json`));
    } catch {
        // Keep the manifest authoritative if the payload was already removed.
    }
    await writeTextFile(
        manifestPath,
        JSON.stringify(
            { version: 1, projectId, versions: manifest.versions.filter((item) => item.id !== versionId) },
            null,
            2,
        ),
    );
    return true;
}
