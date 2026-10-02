import { basename, join } from "@tauri-apps/api/path";

const normalizePath = (p: string) => p.replace(/\\/g, "/").toLowerCase();

// FNV-1a of the source path: a short, stable tag that tells two same-named files apart.
const pathTag = (p: string) => {
  let h = 2166136261;
  for (const ch of normalizePath(p)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return (h >>> 0).toString(36).slice(0, 6);
};

// The file name each source gets inside `destDir`. Files already there keep their name; a new file keeps its own name
// unless another source shares it, then each one gets a tag from its source path, so the names do not depend on order.
export async function planFileNames(destDir: string, sources: string[]): Promise<Map<string, string>> {
  const plan = new Map<string, string>();
  const unique = [...new Set(sources)];
  const taken = new Set<string>();
  const outside: { src: string; name: string }[] = [];
  for (const src of unique) {
    const name = await basename(src);
    if (normalizePath(await join(destDir, name)) === normalizePath(src)) {
      plan.set(src, name);
      taken.add(name.toLowerCase());
    } else {
      outside.push({ src, name });
    }
  }
  const sharing = new Map<string, number>();
  for (const { name } of outside) sharing.set(name.toLowerCase(), (sharing.get(name.toLowerCase()) ?? 0) + 1);
  for (const { src, name } of outside) {
    let chosen = name;
    if (taken.has(name.toLowerCase()) || (sharing.get(name.toLowerCase()) ?? 0) > 1) {
      const dot = name.lastIndexOf(".");
      const stem = dot > 0 ? name.slice(0, dot) : name;
      const ext = dot > 0 ? name.slice(dot) : "";
      chosen = `${stem}-${pathTag(src)}${ext}`;
      for (let n = 2; taken.has(chosen.toLowerCase()); n++) chosen = `${stem}-${pathTag(src)}-${n}${ext}`;
    }
    plan.set(src, chosen);
    taken.add(chosen.toLowerCase());
  }
  return plan;
}
