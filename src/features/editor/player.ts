import { useSyncExternalStore } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";

// The play position changes every frame; keeping it outside React state lets only the
// playhead, timecode and subtitle overlay re-render while it moves.
class PlayerStore {
  time = 0;
  playing = false;
  private listeners = new Set<() => void>();

  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  set(patch: { time?: number; playing?: boolean }) {
    let changed = false;
    if (patch.time !== undefined && patch.time !== this.time) {
      this.time = patch.time;
      changed = true;
    }
    if (patch.playing !== undefined && patch.playing !== this.playing) {
      this.playing = patch.playing;
      changed = true;
    }
    if (changed) this.listeners.forEach((fn) => fn());
  }
}

export const player = new PlayerStore();

export const usePlayerTime = () => useSyncExternalStore(player.subscribe, () => player.time);
export const usePlaying = () => useSyncExternalStore(player.subscribe, () => player.playing);

const isAbsolute = (p: string) => /^[a-zA-Z]:[\\/]/.test(p) || p.startsWith("/");

export function mediaUrl(projectDir: string, path: string | undefined): string {
  if (!path) return "";
  const abs = isAbsolute(path) ? path : `${projectDir}/${path}`;
  return convertFileSrc(abs.replace(/\\/g, "/"));
}

export function formatTime(seconds: number, withTenths = true): string {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  const whole = String(Math.floor(sec)).padStart(2, "0");
  return withTenths ? `${m}:${whole}.${Math.floor((sec % 1) * 10)}` : `${m}:${whole}`;
}
