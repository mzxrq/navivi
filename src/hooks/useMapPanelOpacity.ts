import { useEffect, useState } from "react";

// How see-through the floating map panels (elevation profile, gradient key) are. A per-viewer preference, kept in localStorage.
const KEY = "navivi_map_panel_opacity";
const EVENT = "map-panel-opacity";
export const MAP_PANEL_OPACITY = { min: 0.2, max: 1, fallback: 0.9 };

export function getMapPanelOpacity(): number {
  try {
    const raw = localStorage.getItem(KEY);
    const value = raw === null ? NaN : Number(raw);
    return Number.isFinite(value) ? Math.min(MAP_PANEL_OPACITY.max, Math.max(MAP_PANEL_OPACITY.min, value)) : MAP_PANEL_OPACITY.fallback;
  } catch {
    return MAP_PANEL_OPACITY.fallback;
  }
}

export function setMapPanelOpacity(value: number) {
  try {
    localStorage.setItem(KEY, String(value));
  } catch {}
  window.dispatchEvent(new Event(EVENT));
}

// The CSS variable the panels use as their background alpha: `bg-white/(--panel-alpha)`.
export const panelAlphaStyle = (opacity: number) => ({ "--panel-alpha": `${Math.round(opacity * 100)}%` }) as React.CSSProperties;

export function useMapPanelOpacity(): number {
  const [opacity, setOpacity] = useState(getMapPanelOpacity);
  useEffect(() => {
    const sync = () => setOpacity(getMapPanelOpacity());
    window.addEventListener(EVENT, sync);
    return () => window.removeEventListener(EVENT, sync);
  }, []);
  return opacity;
}
