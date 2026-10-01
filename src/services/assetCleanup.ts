import { join } from "@tauri-apps/api/path";
import { exists, readDir, remove } from "@tauri-apps/plugin-fs";

export type AssetGroup = "voice" | "subtitles" | "route" | "photo" | "cards";

export type AssetCounts = Record<AssetGroup, number>;

export const ASSET_GROUPS: AssetGroup[] = ["voice", "subtitles", "route", "photo", "cards"];

// Folders from older versions kept these at the project root.
const folder = async (dir: string, ...parts: string[]) => {
  const current = await join(dir, "assets", ...parts);
  if (await exists(current)) return current;
  const legacy = await join(dir, ...parts);
  return (await exists(legacy)) ? legacy : current;
};

// Files only: assets/audio/music and assets/video/user hold the user's own files and are never touched.
const filesIn = async (path: string) => {
  try {
    if (!(await exists(path))) return [];
    const entries = await readDir(path);
    const files: string[] = [];
    for (const entry of entries) {
      if (entry.name && !entry.isDirectory) files.push(await join(path, entry.name));
    }
    return files;
  } catch (e) {
    console.warn("Could not list a project folder:", e);
    return [];
  }
};

const locate = async (dir: string): Promise<Record<AssetGroup, string[]>> => {
  const video = await folder(dir, "video");
  return {
    voice: [await folder(dir, "audio")],
    subtitles: [await folder(dir, "subtitles")],
    route: [await join(video, "route")],
    photo: [await join(video, "attraction")],
    cards: [video],
  };
};

const isMedia = (path: string) => /\.(mp4|wav|mp3|srt)$/i.test(path);

export async function scanAssets(dir: string): Promise<AssetCounts> {
  const places = await locate(dir);
  const counts = {} as AssetCounts;
  for (const group of ASSET_GROUPS) {
    const files = (await Promise.all(places[group].map(filesIn))).flat();
    counts[group] = files.filter(isMedia).length;
  }
  return counts;
}

// The subtitles are timed to the narration, so they go with it.
export const withDependents = (groups: AssetGroup[]): AssetGroup[] =>
  groups.includes("voice") && !groups.includes("subtitles") ? [...groups, "subtitles"] : groups;

export async function clearAssets(dir: string, groups: AssetGroup[]): Promise<number> {
  const places = await locate(dir);
  let removed = 0;
  for (const group of withDependents(groups)) {
    for (const path of (await Promise.all(places[group].map(filesIn))).flat()) {
      try {
        await remove(path);
        removed += 1;
      } catch (e) {
        console.warn("Could not remove an old asset:", e);
      }
    }
  }
  if (groups.includes("voice")) {
    for (const cues of [await join(dir, ".navivi", "narration_cues.json"), await join(dir, "narration_cues.json")]) {
      try {
        if (await exists(cues)) await remove(cues);
      } catch (e) {
        console.warn("Could not remove the narration cues:", e);
      }
    }
  }
  return removed;
}
