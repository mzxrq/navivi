import { documentDir, homeDir, join } from "@tauri-apps/api/path";

// Linux without xdg-user-dirs (WSL, minimal installs) has no Documents entry, so documentDir() throws "unknown path"; Python also uses ~/Documents.
export async function docsDir(): Promise<string> {
  try {
    return await documentDir();
  } catch {
    return join(await homeDir(), "Documents");
  }
}
