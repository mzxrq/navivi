import { useEffect, useRef, useState } from "react";
import { join } from "@tauri-apps/api/path";
import { readTextFile } from "@tauri-apps/plugin-fs";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Dialog, dialogButton, dialogInput } from "../ui/Dialog";
import { fileSystem } from "../../config/constants";
import type { RecentProjects } from "../../types";
import {
  collectTexts,
  createLanguageVersion,
  guessLanguage,
  type LanguageVersionProgress,
  type VersionLanguage,
} from "../../services/languageVersion";

interface Props {
  project: RecentProjects;
  onClose: () => void;
  onDone: (result: { dir: string; untranslated: number }) => void;
  onError: (message: string) => void;
}

const suffix = (language: VersionLanguage) => (language === "en" ? "English" : "日本語");

export function LanguageVersionDialog({ project, onClose, onDone, onError }: Props) {
  const [target, setTarget] = useState<VersionLanguage>("en");
  const [name, setName] = useState(`${project.name} (${suffix("en")})`);
  const [edited, setEdited] = useState(false);
  const [progress, setProgress] = useState<LanguageVersionProgress | null>(null);
  const abort = useRef<AbortController | null>(null);
  const running = progress !== null;

  // The project is in one language already: offer the other one first.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const config = JSON.parse(await readTextFile(await join(project.path, fileSystem.configFile)));
        const { names, scripts } = collectTexts(config);
        const language = guessLanguage([...Object.values(names), ...Object.values(scripts)]);
        if (alive) pick(language === "ja" ? "en" : "ja");
      } catch {
        // keep English
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.path]);

  const pick = (language: VersionLanguage) => {
    setTarget(language);
    if (!edited) setName(`${project.name} (${suffix(language)})`);
  };

  const start = async () => {
    abort.current = new AbortController();
    setProgress({ step: "copy", done: 0, total: 1 });
    try {
      const result = await createLanguageVersion({ source: project, target, name: name.trim(), signal: abort.current.signal, onProgress: setProgress });
      onDone(result);
    } catch (e: any) {
      if (e?.name !== "AbortError") onError(String(e?.message ?? e));
      onClose();
    }
  };

  const stepLabel = () => {
    if (!progress) return "";
    if (progress.step === "copy") return t`Copying the project…`;
    if (progress.step === "files") return t`Clearing the old audio and clips…`;
    return t`Translating ${progress.done} of ${progress.total}…`;
  };

  const options: { id: VersionLanguage; label: string }[] = [
    { id: "en", label: "English" },
    { id: "ja", label: "日本語" },
  ];

  return (
    <Dialog
      title={<Trans>Make a language version</Trans>}
      subtitle={project.name}
      onClose={running ? () => abort.current?.abort() : onClose}
      width="w-110"
      footer={
        <>
          <button type="button" onClick={running ? () => abort.current?.abort() : onClose} className={dialogButton.secondary}>
            <Trans>Cancel</Trans>
          </button>
          <button type="button" onClick={start} disabled={running || !name.trim()} className={dialogButton.primary}>
            <Trans>Create</Trans>
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <div>
          <div className="mb-1.5 text-[12px] font-medium text-zinc-600 dark:text-zinc-300">
            <Trans>Language of the new version</Trans>
          </div>
          <div className="flex gap-1.5">
            {options.map((o) => (
              <button
                key={o.id}
                type="button"
                disabled={running}
                onClick={() => pick(o.id)}
                className={`px-3 h-8 rounded-md text-[13px] border transition-colors ${
                  target === o.id ? "bg-navi/10 text-navi border-navi/40" : "border-zinc-200 dark:border-white/10 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-white/5"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="block mb-1.5 text-[12px] font-medium text-zinc-600 dark:text-zinc-300">
            <Trans>Name</Trans>
          </label>
          <input
            type="text"
            value={name}
            disabled={running}
            onChange={(e) => {
              setName(e.target.value);
              setEdited(true);
            }}
            className={dialogInput}
          />
        </div>
        <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
          {running ? (
            stepLabel()
          ) : (
            <Trans>
              This copies the stops, routes and photos into a new project and translates the stop names and scripts with your AI. The audio, captions and video clips are made again for the new language, so
              generate it once you have read the translation. The original project is not changed.
            </Trans>
          )}
        </p>
      </div>
    </Dialog>
  );
}
