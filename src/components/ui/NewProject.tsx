import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useUI } from "../../hooks/useUI";
import { 
  FolderPlus, ChevronRight, Navigation, 
  Car, Footprints, Plane, Search, Loader2, MapPin, X, Info
} from "../ui/icons";

interface SearchResult {
  place_id: number;
  display_name: string;
  lat: string;
  lon: string;
}

export function NewProject() {
  const { setCurrentView } = useUI();
  const { updateMetadata, updateSettings, resetWorkspace } = useWorkspace();

  const [projectName, setProjectName] = useState("Untitled Project");
  const [travelMode, setTravelMode] = useState<"driving" | "walking" | "flying">("driving");
  
  // Origin Search State (Defaults to Osaka)
  const [originQuery, setOriginQuery] = useState("Osaka, Japan");
  const [selectedCoords, setSelectedCoords] = useState<[number, number]>([34.6937, 135.5023]);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);

  const searchRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    window.addEventListener("mousedown", handleClickOutside);
    return () => window.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Press ESC to close modal
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setCurrentView("title_screen");
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [setCurrentView]);

  // Origin Search Effect
  useEffect(() => {
    // Only search if the user is typing (not if they just clicked a result)
    if (!originQuery.trim() || originQuery === "Osaka, Japan") {
      setSearchResults([]);
      setShowDropdown(false);
      setIsSearching(false);
      return;
    }

    setIsSearching(true);
    const delayDebounceFn = setTimeout(async () => {
      try {
        const res = await fetch(
          `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(
            originQuery
          )}&limit=5&accept-language=en`
        );
        if (!res.ok) throw new Error("No Internet Connection.");
        const data = await res.json();
        setSearchResults(data);
        setShowDropdown(true);           
      } catch (error) {
        console.error("Search failed:", error);
      } finally {
        setIsSearching(false);
      }
    }, 600);

    return () => clearTimeout(delayDebounceFn);
  }, [originQuery]);

  const handleSelectPlace = (place: SearchResult) => {
    setSelectedCoords([parseFloat(place.lat), parseFloat(place.lon)]);
    setOriginQuery(place.display_name.split(",")[0]); // Set input to the clean name
    setShowDropdown(false);
  };

  const handleCreate = () => {
    resetWorkspace();
    
    updateMetadata({
      project_name: projectName || "Untitled Project",
      project_id: "",
      status: "initialized",
    });

    updateSettings({
      start_coords: selectedCoords,
      resolution: "1080p", // Hidden defaults
      fps: 30,             // Hidden defaults
    });
    
    setCurrentView("editor");
  };

  return createPortal(
    <div className="fixed inset-0 z-99999 flex items-center justify-center bg-zinc-950/40 backdrop-blur-[2px] animate-in fade-in duration-200 select-none">
      <div className="w-full max-w-130 bg-white dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded-2xl shadow-2xl p-8 animate-in zoom-in-95 duration-200">
        
        {/* Header */}
        <div className="flex items-center gap-4 mb-8">
          <div className="w-12 h-12 rounded-xl bg-navi-50 dark:bg-navi/10 flex items-center justify-center border border-navi-200 dark:border-navi/20 shrink-0">
            <FolderPlus className="w-6 h-6 text-navi-600 dark:text-navi-500" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-zinc-900 dark:text-white tracking-tight">
              Create New Route
            </h2>
            <p className="text-sm text-zinc-500 dark:text-navidark-125 mt-0.5">
              Set your starting coordinates and routing behavior.
            </p>
          </div>
        </div>

        <div className="space-y-6">
          {/* Project Name (Fused Input) */}
          <div className="space-y-2">
            <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-150 uppercase tracking-widest flex items-center gap-1.5">
              Project Name
            </label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              className="w-full bg-zinc-100 dark:bg-navidark-800 border-none rounded-lg px-4 py-3 text-sm font-semibold text-zinc-900 dark:text-white outline-none focus:ring-2 focus:ring-navi/50 transition-all shadow-inner placeholder-zinc-400 dark:placeholder-navidark-200"
              placeholder="e.g. Kyoto Temple Run"
              autoFocus
            />
          </div>

          {/* Searchable Starting Location (Fused Input) */}
          <div className="space-y-2" ref={searchRef}>
            <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-150 uppercase tracking-widest flex items-center gap-1.5">
              Starting Origin
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                <Search className="h-4 w-4 text-zinc-400 dark:text-navidark-150" />
              </div>

              <input
                type="text"
                value={originQuery}
                onChange={(e) => setOriginQuery(e.target.value)}
                onFocus={() => { if (searchResults.length > 0) setShowDropdown(true); }}
                placeholder="Search for a city, landmark, or address..."
                className="w-full bg-zinc-100 dark:bg-navidark-800 border-none rounded-lg pl-10 pr-10 py-3 text-sm font-semibold text-zinc-900 dark:text-white outline-none focus:ring-2 focus:ring-navi/50 transition-all shadow-inner placeholder-zinc-400 dark:placeholder-navidark-200"
              />

              <div className="absolute inset-y-0 right-0 pr-3 flex items-center">
                {isSearching ? (
                  <Loader2 className="h-4 w-4 text-navi animate-spin" />
                ) : (
                  originQuery && (
                    <button
                      onClick={() => { setOriginQuery(""); setSearchResults([]); }}
                      className="p-1 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 transition-colors"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )
                )}
              </div>

              {/* Search Results Dropdown */}
              {showDropdown && searchResults.length > 0 && (
                <div className="absolute top-full left-0 right-0 mt-1.5 bg-white dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg shadow-xl z-50 max-h-48 overflow-y-auto custom-scrollbar animate-in fade-in zoom-in-95">
                  {searchResults.map((place) => (
                    <button
                      key={place.place_id}
                      onClick={() => handleSelectPlace(place)}
                      className="w-full text-left px-3 py-2.5 hover:bg-zinc-50 dark:hover:bg-navidark-700 transition-colors flex items-start gap-2 border-b border-zinc-100 dark:border-navidark-600 last:border-0"
                    >
                      <MapPin className="w-4 h-4 text-zinc-400 dark:text-navidark-150 shrink-0 mt-0.5" />
                      <div className="flex flex-col min-w-0">
                        <span className="text-xs font-bold text-zinc-900 dark:text-zinc-100 truncate">
                          {place.display_name.split(",")[0]}
                        </span>
                        <span className="text-[10px] text-zinc-500 dark:text-navidark-125 truncate mt-0.5">
                          {place.display_name.split(",").slice(1).join(",")}
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Default Travel Mode */}
          <div className="space-y-2 pt-2">
            <div className="flex flex-col gap-1">
              <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-150 uppercase tracking-widest flex items-center gap-1.5">
                <Navigation className="w-3.5 h-3.5" /> Default Routing Mode
              </label>
              <p className="text-[10px] text-zinc-500 dark:text-navidark-150 flex items-center gap-1">
                <Info className="w-3 h-3" /> Sets the default pathfinding engine when placing waypoints.
              </p>
            </div>
            
            <div className="grid grid-cols-3 gap-2">
              {[
                { id: "driving", icon: Car, label: "Driving" },
                { id: "walking", icon: Footprints, label: "Walking" },
                { id: "flying", icon: Plane, label: "Direct/Fly" },
              ].map((mode) => (
                <button
                  key={mode.id}
                  onClick={() => setTravelMode(mode.id as any)}
                  className={`flex items-center justify-center gap-2 py-3 rounded-xl border transition-all ${
                    travelMode === mode.id
                      ? "border-navi bg-navi-50 dark:bg-navi/10 text-navi-800 dark:text-navi-400 shadow-sm"
                      : "border-zinc-200 dark:border-navidark-400 bg-zinc-50 dark:bg-navidark-800 text-zinc-600 dark:text-navidark-125 hover:border-zinc-300 dark:hover:border-navidark-200"
                  }`}
                >
                  <mode.icon className="w-4 h-4 shrink-0" />
                  <span className="text-xs font-bold">{mode.label}</span>
                </button>
              ))}
            </div>
          </div>

        </div>

        {/* Footer Actions */}
        <div className="mt-8 pt-6 border-t border-zinc-200 dark:border-navidark-400 flex justify-end gap-3">
          <button
            onClick={() => setCurrentView("title_screen")}
            className="px-5 py-2.5 text-xs font-bold text-zinc-500 dark:text-navidark-125 hover:bg-zinc-100 dark:hover:bg-navidark-800 hover:text-zinc-800 dark:hover:text-white rounded-xl transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            className="px-6 py-2.5 rounded-xl bg-navi hover:bg-navi-600 text-white text-xs font-bold transition-all flex items-center gap-2 shadow-md hover:shadow-lg"
          >
            Start Editing <ChevronRight className="w-4 h-4 opacity-70" />
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}