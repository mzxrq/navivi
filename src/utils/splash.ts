import { invoke } from "@tauri-apps/api/core";

// Tells the shell the app has rendered: it closes the startup window (after the logo has played) and shows this one.
export async function revealApp(): Promise<void> {
  if (!("__TAURI_INTERNALS__" in window)) return;
  // After the first paint, so the window never shows an empty page.
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  try {
    await invoke("app_ready");
  } catch (error) {
    console.warn("app_ready failed:", error);
  }
}
