import { useState, useRef, useEffect } from "react";
import { Check, Layers, X } from "../../../../components/ui/icons";
import { Switch } from "../../../../components/ui/Switch";
import { mapStyles } from "../../../../config/constants";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

interface LayerManagerProps {
  selectedStyle: string;
  setSelectedStyle: (id: string) => void;
  mapboxToken: string;
  is3D: boolean;
  setIs3D: (val: boolean) => void;
}

function previewUrlFor(styleId: string, mapboxToken: string) {
  if (styleId === "osm") return "https://a.tile.openstreetmap.org/11/1792/815.png";
  if (styleId === "gsi-japan") return "https://cyberjapandata.gsi.go.jp/xyz/std/11/1792/815.png";
  const mbStyle =
    {
      satellite: "satellite-streets-v12",
      dark: "dark-v11",
      light: "light-v11",
      standard: "streets-v12",
    }[styleId] ?? "outdoors-v12";
  return `https://api.mapbox.com/styles/v1/mapbox/${mbStyle}/static/135.0667,34.2744,11/240x120?access_token=${mapboxToken}`;
}

/** Base map style + 3D terrain, opened from the map's top-right controls. */
export function LayerManager({
  selectedStyle,
  setSelectedStyle,
  mapboxToken,
  is3D,
  setIs3D,
}: LayerManagerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!panelRef.current?.contains(e.target as Node)) setIsOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [isOpen]);

  return (
    <div ref={panelRef} className="relative">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        title={t`Layer Manager`}
        className={`flex items-center gap-1.5 h-7 px-2 rounded-lg text-[12px] font-medium transition-colors ${
          isOpen
            ? "bg-navi text-white shadow-sm"
            : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-white/5"
        }`}
      >
        <Layers className="w-3.5 h-3.5" />
        <Trans>Layers</Trans>
      </button>

      {isOpen && (
        <div className="absolute top-full right-0 mt-2 w-72 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-lg z-40 animate-in fade-in zoom-in-95 duration-100">
          <div className="flex items-center justify-between px-3.5 pt-3 pb-2">
            <h3 className="text-[13px] font-semibold text-zinc-900 dark:text-zinc-100">
              <Trans>Base Map Style</Trans>
            </h3>
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              title={t`Close`}
              aria-label={t`Close`}
              className="p-1 -mr-1 rounded-md text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/5 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="px-3.5 pb-3 grid grid-cols-2 gap-2">
            {mapStyles.map((style) => {
              const isSelected = selectedStyle === style.id;
              return (
                <button
                  key={style.id}
                  type="button"
                  onClick={() => setSelectedStyle(style.id)}
                  aria-pressed={isSelected}
                  className="group text-left"
                >
                  <span
                    className={`relative block h-14 rounded-md overflow-hidden bg-zinc-200 dark:bg-zinc-800 bg-cover bg-center transition-shadow ${
                      isSelected
                        ? "ring-2 ring-navi"
                        : "ring-1 ring-black/10 dark:ring-white/10 group-hover:ring-zinc-400 dark:group-hover:ring-zinc-500"
                    }`}
                    style={{ backgroundImage: `url('${previewUrlFor(style.id, mapboxToken)}')` }}
                  >
                    {isSelected && (
                      <span className="absolute top-1 right-1 w-4 h-4 rounded-full bg-navi text-white flex items-center justify-center">
                        <Check className="w-2.5 h-2.5" strokeWidth={3} />
                      </span>
                    )}
                  </span>
                  <span
                    className={`block mt-1 text-[11px] truncate ${
                      isSelected ? "text-zinc-900 dark:text-zinc-100 font-medium" : "text-zinc-500"
                    }`}
                  >
                    {style.label.split(" (")[0]}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="px-3.5 py-3 flex items-center gap-3 border-t border-zinc-100 dark:border-white/5">
            <div className="flex-1 min-w-0">
              <p className="text-[12px] text-zinc-700 dark:text-zinc-300">
                <Trans>Enable 3D Terrain</Trans>
              </p>
              <p className="text-[11px] text-zinc-500">
                <Trans>Show elevation and 3D buildings</Trans>
              </p>
            </div>
            <Switch checked={is3D} onChange={setIs3D} label={t`Enable 3D Terrain`} />
          </div>
        </div>
      )}
    </div>
  );
}
