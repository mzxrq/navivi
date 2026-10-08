import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { primaryButton } from "../../../components/ui/SettingsParts";
import { useUI } from "../../../hooks/useUI";

// Shown over the map until a Mapbox token is saved (the app ships without one; each user enters their own).
export function MapTokenNotice() {
  const { setShowAppSettings } = useUI();
  const open = () => {
    setShowAppSettings(true);
    setTimeout(() => window.dispatchEvent(new CustomEvent("open-app-settings-tab", { detail: "api" })), 50);
  };
  return (
    <div
      role="status"
      className="absolute z-20 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-80 max-w-[calc(100%-2rem)] rounded-xl border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900 shadow-lg px-4 py-3.5 space-y-2.5"
    >
      <p className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
        <Trans>The map needs a Mapbox token</Trans>
      </p>
      <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
        <Trans>Add your own token in Settings. A free Mapbox account is enough, and the token stays on this PC.</Trans>
      </p>
      <button type="button" className={primaryButton} onClick={open}>
        {t`Open API keys`}
      </button>
    </div>
  );
}
