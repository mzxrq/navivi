import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useAssistant } from "../../hooks/useAssistant";
import { useAiReady } from "../../hooks/useAiReady";
import { useUI } from "../../hooks/useUI";
import { X } from "../../components/ui/icons";
import { AssistantChat } from "./AssistantChat";

// The chat inside the editor: a floating panel under the title bar, kept out of the way of the map and timeline.
export function AssistantPanel() {
  const { panelOpen, setPanelOpen } = useAssistant();
  const { currentView } = useUI();
  const aiReady = useAiReady();
  if (currentView !== "editor" || !panelOpen || !aiReady) return null;
  return (
    <aside className="fixed top-12 right-3 bottom-10 w-[26rem] max-w-[calc(100vw-1.5rem)] z-9000 flex flex-col rounded-xl border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900 shadow-xl animate-in fade-in duration-150">
      <div className="flex items-center justify-between px-4 h-11 shrink-0 border-b border-zinc-100 dark:border-white/5">
        <h3 className="text-[13px] font-semibold text-zinc-900 dark:text-zinc-100">
          <Trans>Assistant</Trans>
        </h3>
        <button type="button" onClick={() => setPanelOpen(false)} aria-label={t`Close`} className="w-7 h-7 rounded-lg flex items-center justify-center text-zinc-500 hover:bg-zinc-100 dark:hover:bg-white/10 transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="flex-1 min-h-0 p-3 flex flex-col justify-end">
        <AssistantChat variant="panel" />
      </div>
    </aside>
  );
}
