import { documentDir, join } from "@tauri-apps/api/path";
import { fileSystem } from "../config/constants";
import { callSidecar } from "./sidecar";

// Photos the app takes in. iPhones save HEIC/HEIF, which the webview cannot show and the pipeline cannot read,
// so those are converted to JPEG (keeping their GPS tags) when they are imported.
export const PHOTO_EXTENSIONS = ["jpg", "jpeg", "png", "heic", "heif"];

export const isHeic = (path: string) => /\.(heic|heif)$/i.test(path);
export const isPhoto = (path: string) => /\.(jpe?g|png|heic|heif)$/i.test(path);

export interface PreparedPhotos {
  // The same photos in the same order, HEIC ones replaced by their JPEG; photos that could not be converted are left out.
  paths: string[];
  converted: number;
  failed: string[];
}

// Throws with a readable message when the converter itself cannot run (e.g. pillow-heif is not installed).
export async function preparePhotos(paths: string[]): Promise<PreparedPhotos> {
  const heic = paths.filter(isHeic);
  if (heic.length === 0) return { paths, converted: 0, failed: [] };

  const outDir = await join(await documentDir(), fileSystem.rootFolder, "Imports", String(Date.now()));
  const reply = await callSidecar<{ images: Record<string, string>; failed: Record<string, string> }>("convert_images", {
    paths: heic,
    out_dir: outDir,
  });
  if (!reply.success) throw new Error(reply.cancelled ? "The photo conversion was interrupted. Try again." : reply.error);

  const failed = heic.filter((p) => !reply.images[p]);
  return {
    paths: paths.flatMap((p) => (isHeic(p) ? (reply.images[p] ? [reply.images[p]] : []) : [p])),
    converted: heic.length - failed.length,
    failed,
  };
}
