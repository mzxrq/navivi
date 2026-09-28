import { useState, useEffect } from "react";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import { extractLocationsFromDocument, generateWaypointScriptStream } from "../../services/ollamaApi";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

export function AutoDirectorModal() {
  const { autoDirectorData, setAutoDirectorData, showToast } = useUI();
  const { setWaypoints, updateSettings, setIsDirty, settings } = useWorkspace();
  const [status, setStatus] = useState("");
  const [proposedWaypoints, setProposedWaypoints] = useState<any[]>([]);
  const [bgm, setBgm] = useState("Cinematic Travel Theme");
  const [isProcessing, setIsProcessing] = useState(false);
  const [isProposal, setIsProposal] = useState(false);

  useEffect(() => {
    if (autoDirectorData?.state === "processing" && !isProcessing) {
      processDocument(autoDirectorData.content);
    }
  }, [autoDirectorData, isProcessing]);

  const processDocument = async (text: string) => {
    setIsProcessing(true);
    try {
      setStatus(t`Extracting locations using AI...`);
      const locations = await extractLocationsFromDocument(text);
      
      if (!locations || locations.length === 0) {
        showToast(t`No locations found in document`, "warning");
        setAutoDirectorData(null);
        setIsProcessing(false);
        return;
      }

      setStatus(t`Found ${locations.length} locations. Geocoding...`);
      const waypoints = [];
      const mapboxToken = settings?.mapbox_api_key || import.meta.env.VITE_MAPBOX_TOKEN;
      for (let i = 0; i < locations.length; i++) {
        const loc = locations[i];
        
        try {
          if (mapboxToken) {
            const res = await fetch(`https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(loc)}.json?access_token=${mapboxToken}`);
            const data = await res.json();
            if (data.features && data.features.length > 0) {
              waypoints.push({
                id: crypto.randomUUID(),
                lat: data.features[0].center[1],
                lng: data.features[0].center[0],
                name: loc,
                narration: "",
                routeMode: "driving",
                images: [],
                imagePans: []
              });
            }
          } else {
            if (i > 0) await new Promise(r => setTimeout(r, 1100)); // Rate limit
            const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(loc)}`);
            const data = await res.json();
            if (data && data.length > 0) {
              waypoints.push({
                id: crypto.randomUUID(),
                lat: parseFloat(data[0].lat),
                lng: parseFloat(data[0].lon),
                name: loc,
                narration: "",
                routeMode: "driving",
                images: [],
                imagePans: []
              });
            }
          }
        } catch(e) {
            console.warn(e);
        }
      }

      if (waypoints.length === 0) {
          showToast(t`Failed to geocode any locations.`, "error");
          setAutoDirectorData(null);
          setIsProcessing(false);
          return;
      }

      setStatus(t`Writing scripts with AI...`);
      for (const wp of waypoints) {
         let fullScript = "";
         await generateWaypointScriptStream(
             wp.name, 
             t`Context from document: ${text.substring(0, 500)}`, 
             "schroneko/gemma-2-2b-jpn-it", 
             "", 
             (chunk) => {
                 fullScript = chunk;
             }, 
             wp.lat, 
             wp.lng
         );
         wp.narration = fullScript;
      }

      setProposedWaypoints(waypoints);
      setIsProposal(true);
      setStatus("");
    } catch(e) {
      console.error(e);
      showToast(t`Failed to process document`, "error");
      setAutoDirectorData(null);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleApply = () => {
     setWaypoints(proposedWaypoints);
     updateSettings({ 
         default_export_resolution: "1080p",
     });
     setIsDirty(true);
     showToast(t`Auto-Director applied successfully!`, "success");
     setAutoDirectorData(null);
  };

  if (!autoDirectorData) return null;

  return (
    <div className="fixed inset-0 bg-black/60 z-[9999] flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-zinc-900 rounded-2xl max-w-xl w-full p-6 shadow-2xl border border-white/10 flex flex-col gap-4 max-h-[80vh] overflow-hidden">
        <h2 className="text-xl font-bold flex items-center gap-2">🎬 <Trans>Auto-Director Proposal</Trans></h2>
        
        {autoDirectorData.state === "processing" && !isProposal && (
            <div className="flex flex-col items-center justify-center p-10 gap-4 text-zinc-500">
                <div className="animate-spin w-8 h-8 border-4 border-navi-500 border-t-transparent rounded-full"></div>
                <p>{status}</p>
            </div>
        )}

        {isProposal && (
            <div className="flex flex-col gap-4 overflow-hidden h-full">
                <p className="text-sm text-zinc-600 dark:text-zinc-400 shrink-0">
                    <Trans>Successfully processed the document. Here is the proposed route and script:</Trans>
                </p>
                <div className="bg-zinc-100 dark:bg-black/20 p-4 rounded-xl flex flex-col gap-3 shrink-0">
                    <h3 className="font-semibold text-sm text-zinc-500 uppercase"><Trans>Settings Applied</Trans></h3>
                    <div className="flex gap-4 text-sm">
                        <span>🎵 <strong>BGM:</strong> {bgm}</span>
                        <span>📺 <strong>Resolution:</strong> 1080p</span>
                    </div>
                </div>
                <div className="flex flex-col gap-2 overflow-y-auto pr-2 flex-1">
                    <h3 className="font-semibold text-sm text-zinc-500 uppercase"><Trans>Locations & Scripts</Trans></h3>
                    {proposedWaypoints.map((wp, i) => (
                        <div key={wp.id} className="bg-white dark:bg-zinc-800 p-3 rounded-xl border border-zinc-200 dark:border-white/5">
                            <div className="font-bold flex gap-2">
                                <span className="bg-navi-500 text-white w-5 h-5 flex items-center justify-center rounded-full text-xs">{i+1}</span>
                                {wp.name}
                            </div>
                            <p className="text-sm text-zinc-600 dark:text-zinc-300 mt-2 italic whitespace-pre-wrap">{wp.narration}</p>
                        </div>
                    ))}
                </div>
                <div className="flex justify-end gap-3 mt-4 shrink-0">
                    <button 
                        onClick={() => setAutoDirectorData(null)}
                        className="px-4 py-2 rounded-lg font-medium hover:bg-zinc-100 dark:hover:bg-white/5"
                    >
                        <Trans>Cancel</Trans>
                    </button>
                    <button 
                        onClick={handleApply}
                        className="px-6 py-2 rounded-lg font-medium bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg"
                    >
                        <Trans>Accept & Apply to Project</Trans>
                    </button>
                </div>
            </div>
        )}
      </div>
    </div>
  );
}
