import { useState, useRef, useEffect } from "react";
import { Layers, X } from "../../../../components/ui/icons";
import { mapStyles } from "../../../../config/constants";

interface LayerManagerProps {
  selectedStyle: string;
  setSelectedStyle: (id: string) => void;
  mapboxToken: string;
  is3D: boolean;
  setIs3D: (val: boolean) => void;
}

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
    const handleClickOutside = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      window.addEventListener("mousedown", handleClickOutside);
    }
    return () => window.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  return (
    <div className="relative z-50">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-center gap-2 px-3 h-10 rounded-full transition-all font-bold bg-white dark:bg-zinc-800 text-zinc-700 hover:bg-zinc-200 dark:text-zinc-200 dark:hover:bg-zinc-500 drop-shadow-xl"
        title="Layer Manager"
      >
        <Layers className="w-4 h-4" />
        <span className="text-xs">Layers</span>
      </button>

      {isOpen && (
        <div
          ref={panelRef}
          className="absolute top-12 right-0 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-md border border-zinc-200 dark:border-white/10 rounded-2xl shadow-2xl w-80 p-4 flex flex-col gap-4 animate-in slide-in-from-top-4"
        >
          <div className="flex items-center justify-between border-b border-zinc-100 dark:border-white/5 pb-2">
            <h3 className="text-sm font-bold text-zinc-800 dark:text-white flex items-center gap-2">
              <Layers className="w-4 h-4 text-navi-500" /> Layer Manager
            </h3>
            <button
              onClick={() => setIsOpen(false)}
              className="text-zinc-400 hover:text-red-500 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Terrain Toggle */}
          <div className="flex flex-col gap-2">
            <h4 className="text-xs font-black text-zinc-400 uppercase tracking-widest">
              Terrain & 3D
            </h4>
            <label className="flex items-center justify-between p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-200 dark:border-white/5 cursor-pointer hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors">
              <div className="flex flex-col gap-1">
                <span className="text-xs font-bold text-zinc-800 dark:text-zinc-200">
                  Enable 3D Terrain
                </span>
                <span className="text-[10px] text-zinc-500">
                  Show elevation and 3D buildings.
                </span>
              </div>
              <input
                type="checkbox"
                checked={is3D}
                onChange={(e) => setIs3D(e.target.checked)}
                className="w-4 h-4 rounded text-navi-500 focus:ring-navi-500 border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 cursor-pointer"
              />
            </label>
          </div>

          {/* Base Map Styles */}
          <div className="flex flex-col gap-2">
            <h4 className="text-xs font-black text-zinc-400 uppercase tracking-widest">
              Base Map Style
            </h4>
            <div className="grid grid-cols-2 gap-2 max-h-60 overflow-y-auto custom-scrollbar pr-1">
              {mapStyles.map((style: any) => {
                const isSelected = selectedStyle === style.id;
                let previewUrl = "";
                const previewLon = "135.0667";
                const previewLat = "34.2744";
                const previewZ = "11";

                if (style.id === "osm") {
                  previewUrl = `https://a.tile.openstreetmap.org/11/1792/815.png`;
                } else if (style.id === "gsi-japan") {
                  previewUrl = `https://cyberjapandata.gsi.go.jp/xyz/std/11/1792/815.png`;
                } else {
                  let mbStyle = "outdoors-v12";
                  if (style.id === "satellite") mbStyle = "satellite-streets-v12";
                  if (style.id === "dark") mbStyle = "dark-v11";
                  if (style.id === "light") mbStyle = "light-v11";
                  if (style.id === "standard") mbStyle = "streets-v12";

                  previewUrl = `https://api.mapbox.com/styles/v1/mapbox/${mbStyle}/static/${previewLon},${previewLat},${previewZ}/200x100?access_token=${mapboxToken}`;
                }

                return (
                  <button
                    key={style.id}
                    onClick={() => setSelectedStyle(style.id)}
                    className={`relative w-full h-16 rounded-xl overflow-hidden transition-all duration-200 group text-left bg-zinc-200 dark:bg-zinc-700 ${
                      isSelected
                        ? "ring-2 ring-navi-500 shadow-md scale-95"
                        : "ring-1 ring-black/10 dark:ring-white/10 hover:ring-navi-400"
                    }`}
                  >
                    <div
                      className="absolute inset-0 bg-cover bg-center transition-transform duration-500 group-hover:scale-110"
                      style={{ backgroundImage: `url('${previewUrl}')` }}
                    />
                    <div
                      className={`absolute inset-0 transition-colors ${
                        isSelected ? "bg-navi-900/40" : "bg-black/50 group-hover:bg-black/30"
                      }`}
                    />
                    <div className="absolute inset-0 p-2 flex items-end">
                      <span className="text-[10px] font-bold text-white drop-shadow-md truncate">
                        {style.label.split(" (")[0]}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
