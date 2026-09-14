import { useState, useRef, useEffect } from "react";
import { Layers } from "../../../ui/icons"; 
import { mapStyles } from "../../../../config/constants"; 

interface MapStyleMenuProps {
  selectedStyle: string;
  setSelectedStyle: (id: string) => void;
  mapboxToken: string;
}

export function MapStyleMenu({ selectedStyle, setSelectedStyle, mapboxToken }: MapStyleMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Automatically close the dropdown if the user clicks the map
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    window.addEventListener("mousedown", handleClickOutside);
    return () => window.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-center w-10 h-10 rounded-full transition-all font-bold bg-white dark:bg-zinc-800 text-zinc-700 hover:bg-zinc-200 dark:text-zinc-200 dark:hover:bg-zinc-500 drop-shadow-xl"
        title="Map Style & Terrain"
      >
        <Layers className="w-4 h-4" />
      </button>

      {/* Vertical List with Cached Actual Map Previews */}
      {isOpen && (
        <div className="absolute top-12 right-0 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl shadow-2xl p-2 flex flex-col gap-2 w-48 z-1000 animate-in slide-in-from-top-2">
          <div className="px-2 pt-1 pb-1">
            <span className="text-[10px] font-black text-zinc-400 uppercase tracking-widest">
              Map Style
            </span>
          </div>

          {mapStyles.map((style) => {
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
              // Mapbox Static API
              let mbStyle = "outdoors-v12";
              if (style.id === "satellite") mbStyle = "satellite-streets-v12";
              if (style.id === "dark") mbStyle = "dark-v11";
              if (style.id === "light") mbStyle = "light-v11";
              if (style.id === "standard") mbStyle = "streets-v12";

              previewUrl = `https://api.mapbox.com/styles/v1/mapbox/${mbStyle}/static/${previewLon},${previewLat},${previewZ}/200x60?access_token=${mapboxToken}`;
            }

            return (
              <button
                key={style.id}
                onClick={() => {
                  setSelectedStyle(style.id);
                  setIsOpen(false);
                }}
                className={`relative w-full h-11.5 rounded-lg overflow-hidden transition-all duration-200 group text-left bg-zinc-200 dark:bg-zinc-700 ${
                  isSelected
                    ? "ring-2 ring-navi-500 shadow-md"
                    : "ring-1 ring-black/10 dark:ring-white/10 hover:ring-navi-400"
                }`}
              >
                <div
                  className="absolute inset-0 bg-cover bg-center transition-transform duration-500 group-hover:scale-110"
                  style={{ backgroundImage: `url('${previewUrl}')` }}
                />
                <div
                  className={`absolute inset-0 transition-colors ${isSelected ? "bg-navi-900/40" : "bg-black/50 group-hover:bg-black/30"}`}
                />
                <div className="absolute inset-0 px-3 flex items-center">
                  <span className="text-xs font-bold text-white drop-shadow-md">
                    {style.label.split(" (")[0]}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}