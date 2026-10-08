import { useEffect, useState } from "react";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { getRuntimeStatus, installVcRuntime, VC_RUNTIME_EVENT } from "../../services/setup";
import { Dialog, dialogButton } from "./Dialog";
import { Loader2 } from "./icons";

// A clean Windows PC lacks the Visual C++ runtime that GPSBabel and the voice engines load. Asked at start, and again when a render hits it.
export function VcRuntimeGate() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const check = () =>
      getRuntimeStatus()
        .then((status) => !status.vcRuntime && setOpen(true))
        .catch(() => {});
    void check();
    const show = () => setOpen(true);
    window.addEventListener(VC_RUNTIME_EVENT, show);
    return () => window.removeEventListener(VC_RUNTIME_EVENT, show);
  }, []);

  if (!open) return null;

  const install = async () => {
    setBusy(true);
    setError("");
    try {
      await installVcRuntime();
      setOpen(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      width="w-[30rem]"
      title={t`A Windows component is missing`}
      subtitle={t`Microsoft Visual C++ runtime`}
      onClose={() => !busy && setOpen(false)}
      footer={
        <>
          <button type="button" className={dialogButton.secondary} disabled={busy} onClick={() => setOpen(false)}>
            <Trans>Not now</Trans>
          </button>
          <button type="button" className={dialogButton.primary} disabled={busy} onClick={install}>
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-1.5" />}
            {busy ? t`Installing…` : t`Install now`}
          </button>
        </>
      }
    >
      <div className="space-y-3 pb-1">
        <p className="text-[13px] leading-relaxed text-zinc-600 dark:text-zinc-300">
          <Trans>
            This PC does not have Microsoft's Visual C++ runtime. Without it, Navivi cannot read GPS files, render videos or run the voice engines, and Windows shows a
            "VCRUNTIME140.dll not found" message. Installing it downloads about 25 MB from Microsoft, and Windows asks for permission first.
          </Trans>
        </p>
        {error && <div className="rounded-lg bg-red-500/10 px-3 py-2 text-[12px] leading-snug text-red-600 dark:text-red-400 break-words">{error}</div>}
      </div>
    </Dialog>
  );
}
