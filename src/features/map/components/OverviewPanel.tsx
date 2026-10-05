import { useState } from "react";
import { ChevronDown, Clapperboard } from "../../../components/ui/icons";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

export function OverviewPanel() {
  const { metadata, updateMetadata, setIsDirty } = useWorkspace();
  const [isOpen, setIsOpen] = useState(false);

  const isEnabled = metadata.enable_intro !== false;
  const title = metadata.video_title || metadata.project_name || "";
  const summary = !isEnabled
    ? t`Off`
    : [title, metadata.video_subtitle].filter(Boolean).join(" · ") ||
      t`Title card at the start of the video`;

  const update = (patch: Parameters<typeof updateMetadata>[0]) => {
    updateMetadata(patch);
    setIsDirty(true);
  };

  return (
    <section className="rounded-lg border border-zinc-200 dark:border-white/8 bg-white dark:bg-white/2">
      <div className="flex items-center gap-2.5 pl-2 pr-2.5 py-2">
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          aria-expanded={isOpen}
          className="flex-1 min-w-0 flex items-center gap-2.5 text-left rounded-md -my-1 py-1 -ml-1 pl-1 hover:bg-zinc-50 dark:hover:bg-white/4 transition-colors"
        >
          <span
            className={`w-7 h-7 rounded-md flex items-center justify-center shrink-0 transition-colors ${
              isEnabled
                ? "bg-navi/10 text-navi"
                : "bg-zinc-100 dark:bg-white/5 text-zinc-400"
            }`}
          >
            <Clapperboard className="w-3.5 h-3.5" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
              <Trans>Intro</Trans>
            </span>
            <span
              className={`block text-[11px] truncate ${isEnabled ? "text-zinc-500" : "text-zinc-400 dark:text-zinc-600"}`}
              title={summary}
            >
              {summary}
            </span>
          </span>
          <ChevronDown
            className={`w-3.5 h-3.5 text-zinc-400 shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`}
          />
        </button>

        <button
          type="button"
          role="switch"
          aria-checked={isEnabled}
          aria-label={t`Generate intro video`}
          title={t`Generate intro video`}
          onClick={() => update({ enable_intro: !isEnabled })}
          className={`relative w-7 h-4 rounded-full shrink-0 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-navi/40 ${
            isEnabled ? "bg-navi" : "bg-zinc-300 dark:bg-zinc-700"
          }`}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-white shadow-sm transition-transform ${
              isEnabled ? "translate-x-3" : ""
            }`}
          />
        </button>
      </div>

      {isOpen && (
        <div className="px-3 pb-3 pt-1 space-y-2.5 border-t border-zinc-100 dark:border-white/5 animate-in fade-in duration-150">
          {isEnabled ? (
            <>
              <label className="block pt-1.5">
                <span className="block text-[11px] font-medium text-zinc-500 mb-1">
                  <Trans>Title</Trans>
                </span>
                <input
                  type="text"
                  value={metadata.video_title || ""}
                  onChange={(e) => update({ video_title: e.target.value })}
                  placeholder={metadata.project_name || t`Title`}
                  className="w-full h-8 px-2.5 rounded-md bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 text-[13px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-600 focus:outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition-colors"
                />
                <span className="block text-[10px] text-zinc-400 mt-1">
                  <Trans>Leave blank to use the project name.</Trans>
                </span>
              </label>

              <label className="block">
                <span className="block text-[11px] font-medium text-zinc-500 mb-1">
                  <Trans>Subtitle</Trans>
                </span>
                <input
                  type="text"
                  value={metadata.video_subtitle || ""}
                  onChange={(e) => update({ video_subtitle: e.target.value })}
                  placeholder={t`E.g. Tomogashima and Kada area...`}
                  className="w-full h-8 px-2.5 rounded-md bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 text-[13px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-600 focus:outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition-colors"
                />
              </label>

              <div
                aria-hidden
                className="aspect-video w-full rounded-md bg-zinc-900 ring-1 ring-black/5 dark:ring-white/10 flex flex-col items-center justify-center gap-1 px-4 text-center overflow-hidden"
              >
                <span className="text-white text-sm font-semibold truncate max-w-full">
                  {title || t`Project Title`}
                </span>
                {metadata.video_subtitle && (
                  <span className="text-zinc-400 text-[10px] truncate max-w-full">
                    {metadata.video_subtitle}
                  </span>
                )}
              </div>
            </>
          ) : (
            <p className="pt-1.5 text-[11px] text-zinc-500 leading-relaxed">
              <Trans>
                The video starts directly on the route. Turn the intro on to add a
                title card.
              </Trans>
            </p>
          )}
        </div>
      )}
    </section>
  );
}
