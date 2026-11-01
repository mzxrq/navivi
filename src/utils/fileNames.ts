import { invoke } from "@tauri-apps/api/core";
import { basename, dirname } from "@tauri-apps/api/path";
import { exists } from "@tauri-apps/plugin-fs";

const samePath = (a: string, b: string) => {
  const norm = (p: string) => p.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  return norm(a) === norm(b);
};

// Outside file -> its copy in the project, for this session: a stop keeps the outside path after a save, and
// comparing a multi-GB clip with its copy again on every autosave would be slow.
const imported = new Map<string, string>();

// The file name each source has inside `destDir`, copying it in when needed. copy_asset_file reuses a file there with
// the same bytes and otherwise picks "name (2).ext", so a different file of the same name is never overwritten or
// mistaken for this one. One at a time: two same-named files copied at once would both take the free name.
export async function importAssets(destDir: string, sources: string[]): Promise<Map<string, string>> {
  const names = new Map<string, string>();
  for (const src of new Set(sources)) {
    // Already in the project: kept by name, so a file the user deleted there doesn't fail the whole save.
    if (samePath(await dirname(src), destDir)) {
      names.set(src, await basename(src));
      continue;
    }
    const key = `${destDir}|${src}`;
    let target = imported.get(key);
    if (!target || !(await exists(target))) {
      target = await invoke<string>("copy_asset_file", { sourcePath: src, targetDir: destDir });
      imported.set(key, target);
    }
    names.set(src, await basename(target));
  }
  return names;
}
