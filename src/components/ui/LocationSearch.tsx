import { useState, useEffect } from "react";
import { Search, Loader2, MapPin, X } from "./icons";
import { useWorkspace } from "../../hooks/useWorkspace";

interface SearchResult {
  place_id: number;
  display_name: string;
  lat: string;
  lon: string;
}

export function LocationSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const { setWaypoints, setIsDirty } = useWorkspace();

  const currentLang = "en";

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      setIsOpen(false);
      setIsSearching(false);
      return;
    }

    setIsSearching(true);
    const delayDebounceFn = setTimeout(async () => {
      try {
        const res = await fetch(
          `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(
            query
          )}&limit=5&accept-language=${currentLang}`
        );

        if (!res.ok) throw new Error("No Internet Connection.");

        const data = await res.json();
        setResults(data);
        setIsOpen(true);           
      } catch (error) {
        console.error("Search failed:", error);
      } finally {
        setIsSearching(false);
      }
    }, 600);

    return () => clearTimeout(delayDebounceFn);
  }, [query, currentLang]);

  const handleSelectPlace = (place: SearchResult) => {
    const lat = parseFloat(place.lat);
    const lng = parseFloat(place.lon);

    setWaypoints((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        lat,
        lng,
        name: place.display_name.split(",")[0],
        images: [],
        imagePans: [],
        narration: "",
        routeMode: "driving",
      },
    ]);

    if (setIsDirty) setIsDirty(true);

    setQuery("");
    setIsOpen(false);
    setResults([]);
  };

  return (
    <div className="relative mb-2 shrink-0">
      <div className="relative">
        <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
          <Search className="h-3.5 w-3.5 text-zinc-400 dark:text-navidark-150" />
        </div>

        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search location..."
          className="w-full bg-zinc-100 dark:bg-navidark-800 border-none focus:ring-1 focus:ring-navi text-xs rounded-lg pl-9 pr-8 py-2.5 text-zinc-900 dark:text-white placeholder-zinc-400 dark:placeholder-navidark-150 focus:outline-none transition-all shadow-inner"
        />

        <div className="absolute inset-y-0 right-0 pr-2 flex items-center">
          {isSearching ? (
            <Loader2 className="h-3.5 w-3.5 text-navi animate-spin" />
          ) : (
            query && (
              <button
                onClick={() => setQuery("")}
                className="p-1 hover:bg-zinc-200 dark:hover:bg-navidark-600 rounded-md text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 transition-colors"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )
          )}
        </div>
      </div>

      {isOpen && results.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1.5 bg-white dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg shadow-xl z-50 max-h-56 overflow-y-auto custom-scrollbar animate-in fade-in zoom-in-95">
          {results.map((place) => (
            <button
              key={place.place_id}
              onClick={() => handleSelectPlace(place)}
              className="w-full text-left px-3 py-2.5 hover:bg-zinc-50 dark:hover:bg-navidark-700 transition-colors flex items-start gap-2 border-b border-zinc-100 dark:border-navidark-600 last:border-0 focus:outline-none focus:bg-zinc-50 dark:focus:bg-navidark-700"
            >
              <MapPin className="w-3.5 h-3.5 text-zinc-400 dark:text-navidark-150 shrink-0 mt-0.5" />
              <div className="flex flex-col min-w-0">
                <span className="text-xs font-bold text-zinc-900 dark:text-zinc-100 truncate">
                  {place.display_name.split(",")[0]}
                </span>
                <span className="text-[10px] text-zinc-500 dark:text-navidark-125 truncate">
                  {place.display_name.split(",").slice(1).join(",")}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}