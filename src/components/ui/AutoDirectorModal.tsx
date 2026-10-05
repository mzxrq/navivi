import { useState, useEffect, useRef } from "react";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import { aiEngine } from "../../services/ai/engine";
import { buildProject, type BuildProgress } from "../../services/assistant/buildProject";
import { EMPTY_BRIEF } from "../../services/assistant/brief";
import type { Waypoint } from "../../types";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

export function AutoDirectorModal() {
  const { autoDirectorData, setAutoDirectorData, showToast } = useUI();
  const { setWaypoints, updateSettings, setIsDirty, settings } = useWorkspace();
  const [status, setStatus] = useState("");
  const [proposedWaypoints, setProposedWaypoints] = useState<Waypoint[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isProposal, setIsProposal] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (autoDirectorData?.state === "processing" && !isProcessing && !isProposal) {
      processDocument(autoDirectorData.content);
    }
  }, [autoDirectorData, isProcessing, isProposal]);

  const progressText = ({ step, done, total, label }: BuildProgress) => {
    if (step === "places") return t`Finding the places in the document...`;
    if (step === "geocode") return t`Locating places (${done} of ${total}) ${label}`;
    return t`Writing scripts (${done} of ${total}) ${label}`;
  };

  const close = () => {
    abortRef.current?.abort();
    setIsProposal(false);
    setAutoDirectorData(null);
  };

  const processDocument = async (text: string) => {
    setIsProcessing(true);
    abortRef.current = new AbortController();
    try {
      const built = await buildProject({
        brief: EMPTY_BRIEF,
        sourceText: text,
        engine: aiEngine(settings),
        mapboxToken: settings?.mapbox_api_key || import.meta.env.VITE_MAPBOX_TOKEN,
        signal: abortRef.current.signal,
        onProgress: (p) => setStatus(progressText(p)),
      });

      if (built.waypoints.length === 0) {
        showToast(built.failedPlaces.length > 0 ? t`Failed to geocode any locations.` : t`No locations found in document`, built.failedPlaces.length > 0 ? "error" : "warning");
        setAutoDirectorData(null);
        return;
      }

      setProposedWaypoints(built.waypoints);
      setIsProposal(true);
      setStatus("");
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        console.error(e);
        showToast(t`Failed to process document`, "error");
      }
      setAutoDirectorData(null);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleApply = () => {
    setWaypoints(proposedWaypoints);
    updateSettings({ default_export_resolution: "1080p" });
    setIsDirty(true);
    showToast(t`Auto-Director applied successfully!`, "success");
    setIsProposal(false);
    setAutoDirectorData(null);
  };

  if (!autoDirectorData) return null;

  return (
    <div className="fixed inset-x-0 top-10 bottom-0 bg-zinc-950/30 backdrop-blur-[2px] z-99999 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-zinc-900 rounded-2xl max-w-xl w-full p-6 shadow-2xl border border-zinc-200 dark:border-white/10 flex flex-col gap-4 max-h-[80vh] overflow-hidden">
        <h2 className="text-[14px] font-semibold text-zinc-900 dark:text-zinc-100">
          <Trans>Auto-Director proposal</Trans>
        </h2>

        {!isProposal && (
          <div className="flex flex-col items-center justify-center p-10 gap-4 text-zinc-500">
            <div className="animate-spin w-8 h-8 border-4 border-navi border-t-transparent rounded-full"></div>
            <p className="text-[13px]">{status}</p>
            <button type="button" onClick={close} className="px-4 py-2 rounded-lg text-[13px] font-medium hover:bg-zinc-100 dark:hover:bg-white/5">
              <Trans>Cancel</Trans>
            </button>
          </div>
        )}

        {isProposal && (
          <div className="flex flex-col gap-4 overflow-hidden h-full">
            <p className="text-[13px] text-zinc-600 dark:text-zinc-400 shrink-0">
              <Trans>Successfully processed the document. Here is the proposed route and script:</Trans>
            </p>
            <div className="flex flex-col gap-2 overflow-y-auto pr-2 flex-1">
              <h3 className="font-semibold text-[12px] text-zinc-500">
                <Trans>Locations and scripts</Trans>
              </h3>
              {proposedWaypoints.map((wp, i) => (
                <div key={wp.id} className="bg-white dark:bg-zinc-800 p-3 rounded-xl border border-zinc-200 dark:border-white/5">
                  <div className="font-semibold text-[13px] flex gap-2 items-center">
                    <span className="bg-navi text-white w-5 h-5 flex items-center justify-center rounded-full text-[11px]">{i + 1}</span>
                    {wp.name}
                  </div>
                  <p className="text-[13px] text-zinc-600 dark:text-zinc-300 mt-2 whitespace-pre-wrap">{wp.attractionNarration}</p>
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-3 mt-4 shrink-0">
              <button type="button" onClick={close} className="px-4 py-2 rounded-lg text-[13px] font-medium hover:bg-zinc-100 dark:hover:bg-white/5">
                <Trans>Cancel</Trans>
              </button>
              <button type="button" onClick={handleApply} className="px-6 py-2 rounded-lg text-[13px] font-semibold bg-navi text-white hover:brightness-110 transition">
                <Trans>Accept and apply to project</Trans>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
