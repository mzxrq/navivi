import { useEffect, useMemo, useState } from "react";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { callSidecar } from "../../services/sidecar";
import { FontLanguage, refreshInstalledFonts } from "../../hooks/useInstalledFonts";
import { Dialog, dialogButton, dialogInput } from "./Dialog";
import { Check, Download, Loader2 } from "./icons";

interface CatalogFont {
  family: string;
  category: string;
  bold: boolean;
  installed: boolean;
}

// Rows shown at once; the search narrows a long list (English has over a thousand).
const SHOWN = 80;

// Google Fonts' own CSS for previewing a family before it's installed, only the glyphs its row shows.
const previewed = new Set<string>();
function loadPreview(family: string, text: string) {
  if (previewed.has(family)) return;
  previewed.add(family);
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(family)}&text=${encodeURIComponent(text)}&display=swap`;
  document.head.appendChild(link);
}

export function FontDownloadDialog({ language, onClose }: { language: FontLanguage; onClose: () => void }) {
  const [fonts, setFonts] = useState<CatalogFont[] | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [installing, setInstalling] = useState<string | null>(null);
  const sample = language === "ja" ? "あア漢字 Aa" : "Aa Bb Gg 123";
  const languageName = language === "ja" ? t`Japanese` : t`English`;

  useEffect(() => {
    let live = true;
    callSidecar<{ fonts: CatalogFont[] }>("google_fonts_catalog", language).then((reply) => {
      if (!live) return;
      if (reply.success) setFonts(reply.fonts);
      else setError(reply.error);
    });
    return () => {
      live = false;
    };
  }, [language]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (fonts ?? []).filter((f) => !q || f.family.toLowerCase().includes(q)).slice(0, SHOWN);
  }, [fonts, query]);

  useEffect(() => {
    shown.forEach((f) => loadPreview(f.family, f.family + sample));
  }, [shown, sample]);

  const install = async (family: string) => {
    setInstalling(family);
    setError("");
    const reply = await callSidecar<{ files: string[] }>("install_google_font", family);
    if (reply.success) {
      setFonts((list) => list?.map((f) => (f.family === family ? { ...f, installed: true } : f)) ?? null);
      await refreshInstalledFonts();
    } else {
      setError(reply.error);
    }
    setInstalling(null);
  };

  return (
    <Dialog
      title={t`Get ${languageName} fonts`}
      subtitle={t`Free fonts from Google Fonts, installed for your Windows account`}
      width="w-[30rem]"
      onClose={onClose}
      footer={
        <button type="button" className={dialogButton.secondary} onClick={onClose}>
          <Trans>Close</Trans>
        </button>
      }
    >
      <input
        type="search"
        autoFocus
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={t`Search fonts`}
        className={dialogInput}
      />
      {error && <p className="mt-2 text-[12px] text-red-500 dark:text-red-400 break-words">{error}</p>}
      <ul className="mt-2 h-80 overflow-y-auto custom-scrollbar -mx-1">
        {!fonts && !error && (
          <li className="h-full flex items-center justify-center gap-2 text-[12px] text-zinc-400">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> <Trans>Loading the font list…</Trans>
          </li>
        )}
        {fonts && !shown.length && <li className="px-2 py-3 text-[12px] text-zinc-400">{t`No fonts match.`}</li>}
        {shown.map((f) => (
          <li key={f.family} className="flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-zinc-50 dark:hover:bg-white/5">
            <div className="min-w-0 flex-1">
              <div className="text-[16px] leading-tight truncate text-zinc-900 dark:text-zinc-100" style={{ fontFamily: `"${f.family}", sans-serif` }}>
                {f.family}
              </div>
              <div className="mt-0.5 text-[11px] text-zinc-400 truncate">
                <span style={{ fontFamily: `"${f.family}", sans-serif` }}>{sample}</span>
                {" · "}
                {f.category}
                {!f.bold && ` · ${t`no bold`}`}
              </div>
            </div>
            {f.installed ? (
              <span className="shrink-0 inline-flex items-center gap-1 text-[12px] text-emerald-600 dark:text-emerald-400">
                <Check className="w-3.5 h-3.5" /> <Trans>Installed</Trans>
              </span>
            ) : (
              <button
                type="button"
                disabled={installing !== null}
                onClick={() => install(f.family)}
                className="shrink-0 inline-flex items-center gap-1.5 h-7 px-2.5 rounded-lg border border-zinc-200 dark:border-white/10 text-[12px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-white/10 transition-colors disabled:opacity-40"
              >
                {installing === f.family ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                {installing === f.family ? t`Installing…` : t`Install`}
              </button>
            )}
          </li>
        ))}
      </ul>
    </Dialog>
  );
}
