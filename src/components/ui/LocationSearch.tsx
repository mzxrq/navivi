import { useState, useEffect } from "react";
import { Search, Loader2, MapPin, X } from "../ui/icons";
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
    if(!query.trim()) {
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
          <Search className="h-3.5 w-3.5 text-zinc-400" />
        </div>

        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search location..."
          className="w-full bg-zinc-100 dark:bg-zinc-900 border border-transparent focus:border-emerald-500 focus:bg-white dark:focus:bg-zinc-950 text-xs rounded-xl pl-8 pr-8 py-2 text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-none transition-all shadow-sm"
        />

        {/* Dynamic Right Icon: Loading spinner OR Clear button */}
        <div className="absolute inset-y-0 right-0 pr-2 flex items-center">
          {isSearching ? (
            <Loader2 className="h-3.5 w-3.5 text-emerald-500 animate-spin" />
          ) : (
            query && (
              <button
                onClick={() => setQuery("")}
                className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-md text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 transition-colors"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )
          )}
        </div>
      </div>

        {/* Results */}
        {isOpen && results.length > 0 && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 rounded-xl shadow-2xl z-50 max-h-56 overflow-y-auto custom-scrollbar animate-in fade-in zoom-in-95">
                {results.map((place) => (
                    <button
                        key={place.place_id}
                        onClick={() => handleSelectPlace(place)}
                        className="w-full text-left px-3 py-2 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors flex items-start gap-2 border-b border-zinc-100 dark:border-white/5 last:border-0"
                    >
                        <MapPin className="w-3.5 h-3.5 text-zinc-400 shrink-0 mt-0.5" />
                        <div className="flex flex-col min-w-0">
                            <span className="text-xs font-medium text-zinc-900 dark:text-zinc-100 truncate">
                                {place.display_name.split(",")[0]}
                            </span>
                            <span className="text-[10px] text-zinc-500 truncate">
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