import { useState } from "react";
import {
  PencilSparkles,
  ChevronUp,
  ChevronDown,
  MonitorPlay,
  Info,
} from "../../../components/ui/icons";
import { Tooltip } from "../../../components/ui/Tooltip";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

export function OverviewPanel() {
  const { metadata, updateMetadata, setIsDirty } = useWorkspace();

  const [showOverview, setShowOverview] = useState(
    !!metadata.video_title ||
      !!metadata.video_subtitle ||
      !!metadata.theme ||
      metadata.enable_intro !== false,
  );

  const hasData =
    !!metadata.video_title || !!metadata.video_subtitle || !!metadata.theme;
  const isEnabled = metadata.enable_intro !== false;
  const [showPreview, setShowPreview] = useState(false);

  if (!showOverview) {
    return (
      <button
        onClick={() => setShowOverview(true)}
        className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl border border-dashed border-zinc-300 dark:border-white/10 text-xs font-semibold text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-black/5 dark:hover:bg-white/5 transition-colors shrink-0"
      >
        <span>
          {hasData ? t`Intro Screen Settings` : t`+ Add Intro Screen`}
        </span>
        {hasData && <ChevronDown className="w-3.5 h-3.5" />}
      </button>
    );
  }

  return (
    <div className="bg-zinc-50/50 dark:bg-navidark-800/50 p-3.5 rounded-xl border border-zinc-200/80 dark:border-navidark-700 shrink-0 shadow-sm">
      <div className="flex justify-between items-center mb-4">
        <label className="text-[11px] font-bold text-zinc-800 dark:text-zinc-200 tracking-wide uppercase flex items-center gap-1.5">
          <PencilSparkles className="w-3.5 h-3.5 text-navi" />
          <Trans>Intro Screen</Trans>
        </label>
        <button
          onClick={() => setShowOverview(false)}
          title="Collapse"
          className="p-1 rounded-md text-zinc-400 hover:text-zinc-600 hover:bg-zinc-200 dark:hover:text-zinc-200 dark:hover:bg-navidark-700 transition-colors"
        >
          <ChevronUp className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="space-y-4">
        {/* Enable Toggle */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-medium text-zinc-700 dark:text-zinc-200">
              <Trans>Generate Intro Video</Trans>
            </span>
            <Tooltip content={<div className="w-48 text-center leading-snug"><Trans>This creates a cinematic title card at the very beginning of your exported video.</Trans></div>} position="top">
              <Info className="w-3.5 h-3.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition-colors cursor-help" />
            </Tooltip>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              className="sr-only peer"
              checked={isEnabled}
              onChange={(e) => {
                updateMetadata({ enable_intro: e.target.checked });
                setIsDirty(true);
              }}
            />
            <div className="w-8 h-4.5 bg-zinc-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-navi/30 rounded-full peer dark:bg-navidark-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:border-zinc-300 after:border after:rounded-full after:h-3.5 after:w-3.5 after:transition-all dark:border-navidark-600 peer-checked:bg-navi"></div>
          </label>
        </div>


        {/* Title & Subtitle */}
        {isEnabled && (
          <div className="space-y-3 pt-1 animate-in slide-in-from-top-2 fade-in duration-200">
            <div>
              <label className="block text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 mb-1.5 uppercase tracking-wide">
                <Trans>Video Title</Trans>
              </label>
              <input
                type="text"
                value={metadata.video_title || ""}
                onChange={(e) => {
                  updateMetadata({ video_title: e.target.value });
                  setIsDirty(true);
                }}
                placeholder={metadata.project_name || t`Title`}
                className="w-full bg-white dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-700 rounded-lg px-2.5 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-navi dark:focus:border-navi focus:ring-1 focus:ring-navi/30 shadow-sm transition-all placeholder:text-zinc-400 dark:placeholder:text-zinc-600"
              />
              <p className="text-[9px] text-zinc-400 dark:text-zinc-500 mt-1">
                <Trans>Leave blank to use the project name.</Trans>
              </p>
            </div>

            <div>
              <label className="block text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 mb-1.5 uppercase tracking-wide">
                <Trans>Subtitle / Description</Trans>
              </label>
              <input
                type="text"
                value={metadata.video_subtitle || ""}
                onChange={(e) => {
                  updateMetadata({ video_subtitle: e.target.value });
                  setIsDirty(true);
                }}
                placeholder={t`E.g. Tomogashima and Kada area...`}
                className="w-full bg-white dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-700 rounded-lg px-2.5 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-navi dark:focus:border-navi focus:ring-1 focus:ring-navi/30 shadow-sm transition-all placeholder:text-zinc-400 dark:placeholder:text-zinc-600"
              />
            </div>

            <div className="mt-2 pt-2 border-t border-zinc-200 dark:border-navidark-600">
              <button
                onClick={() => setShowPreview(!showPreview)}
                className="w-full flex items-center justify-between py-1.5 px-2 -mx-2 rounded-lg text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors uppercase tracking-wide"
              >
                <div className="flex items-center gap-1.5">
                  <MonitorPlay className="w-3.5 h-3.5" />
                  <Trans>Live Preview</Trans>
                </div>
                {showPreview ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              </button>
              
              {showPreview && (
                <div className="mt-2 aspect-video w-full bg-zinc-950 rounded-md overflow-hidden flex flex-col items-center justify-center p-4 relative shadow-inner ring-1 ring-white/10 animate-in fade-in zoom-in-95 duration-200">
                {/* Simulated Map Background */}
                <div className="absolute inset-0 bg-linear-to-br from-zinc-800/40 to-black/80 mix-blend-overlay" />
                
                {/* Text Layout */}
                <div className="relative z-10 text-center flex flex-col items-center gap-1.5 w-full">
                  <h4 className="text-white font-bold text-sm tracking-wide shadow-sm drop-shadow-md truncate w-full px-2" style={{ textShadow: "0 2px 4px rgba(0,0,0,0.8)" }}>
                    {metadata.video_title || metadata.project_name || t`Project Title`}
                  </h4>
                  {(metadata.video_subtitle || !metadata.video_title) && (
                    <p className="text-zinc-300 text-[9px] w-full px-2 truncate drop-shadow-md" style={{ textShadow: "0 1px 2px rgba(0,0,0,0.8)" }}>
                      {metadata.video_subtitle || t`Subtitle description...`}
                    </p>
                  )}
                </div>
              </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
