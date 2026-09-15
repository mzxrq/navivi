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
        className={`flex items-center justify-center gap-2 px-3 h-10 rounded-full transition-all font-bold drop-shadow-xl ${
          isOpen
            ? "bg-zinc-400 hover:bg-zinc-600 text-white shadow-zinc-200/25"
            : "bg-white dark:bg-zinc-800 text-zinc-700 hover:bg-zinc-200 dark:text-zinc-200 dark:hover:bg-zinc-500"
        }`}
        title="Layer Manager"
      >
        <Layers className="w-4 h-4" />
        <span className="text-xs">Layers</span>
      </button>

      {isOpen && (
        <div
          ref={panelRef}
          className="absolute top-12 right-0 w-64 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-xl rounded-2xl shadow-2xl p-5 z-40 animate-in fade-in zoom-in-95"
        >
          <div className="flex justify-between pb-4">
            <h3 className="text-sm font-bold text-zinc-800 dark:text-zinc-200 flex items-center gap-2">
              <Layers className="w-4 h-4 text-zinc-500" /> Layer Manager
            </h3>
            <button
              onClick={() => setIsOpen(false)}
              className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition-colors p-1"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="flex flex-col">
            {/* Terrain Toggle (Pill Style) */}
            <label className="flex items-center justify-between pb-4 border-b border-zinc-200/80 dark:border-zinc-800 cursor-pointer select-none group">
              <div className="flex flex-col pr-4">
                <span className="text-xs font-semibold text-zinc-600 dark:text-zinc-400 group-hover:text-zinc-900 dark:group-hover:text-white transition-colors">
                  Enable 3D Terrain
                </span>
                <span className="text-[10px] text-zinc-500">
                  Show elevation and 3D buildings.
                </span>
              </div>

              {/* Custom Animated Switch */}
              <div className="relative flex items-center">
                <input
                  type="checkbox"
                  checked={is3D}
                  onChange={(e) => setIs3D(e.target.checked)}
                  className="sr-only"
                />
                <div
                  className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-200 ease-in-out ${
                    is3D ? "bg-navi" : "bg-zinc-300 dark:bg-zinc-700"
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow-sm transition-transform duration-200 ease-in-out ${
                      is3D ? "translate-x-4.5" : "translate-x-0.5"
                    }`}
                  />
                </div>
              </div>
            </label>

            {/* Base Map Styles (Vertical List) */}
            <div className="flex flex-col gap-3 pt-4">
              <h4 className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">
                Base Map Style
              </h4>
              {/* ✨ Increased max height to accommodate taller boxes */}
              <div className="grid grid-cols-1 gap-2 max-h-36 overflow-y-auto custom-scrollbar p-1">
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
                    if (style.id === "satellite")
                      mbStyle = "satellite-streets-v12";
                    if (style.id === "dark") mbStyle = "dark-v11";
                    if (style.id === "light") mbStyle = "light-v11";
                    if (style.id === "standard") mbStyle = "streets-v12";

                    // ✨ Increased requested image resolution to stay crisp
                    previewUrl = `https://api.mapbox.com/styles/v1/mapbox/${mbStyle}/static/${previewLon},${previewLat},${previewZ}/300x100?access_token=${mapboxToken}`;
                  }

                  return (
                    <button
                      key={style.id}
                      onClick={() => setSelectedStyle(style.id)}
                      className={`relative w-full h-16 rounded-xl overflow-hidden transition-all duration-200 group text-left bg-zinc-200 dark:bg-zinc-700 ${
                        isSelected
                          ? "ring-2 ring-navi-500 shadow-md scale-[0.98]"
                          : "ring-1 ring-black/10 dark:ring-white/10 hover:ring-navi-400"
                      }`}
                    >
                      <div
                        className="absolute inset-0 bg-cover bg-center transition-transform duration-500 group-hover:scale-110"
                        style={{ backgroundImage: `url('${previewUrl}')` }}
                      />
                      {/* Subtler gradient overlay so the map is highly visible */}
                      <div
                        className={`absolute inset-0 transition-colors ${
                          isSelected
                            ? "bg-navi-900/30"
                            : "bg-linear-to-t from-black/60 via-black/10 to-transparent group-hover:from-black/50"
                        }`}
                      />
                      {/* ✨ Shifted text to the bottom left corner */}
                      <div className="absolute inset-0 p-3 flex items-end">
                        <span className="text-xs font-bold text-white drop-shadow-md truncate">
                          {style.label.split(" (")[0]}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
