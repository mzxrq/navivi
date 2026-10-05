import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { appConfig } from "../../config/constants";
import stockVoices from "../../../scripts/stock-voices.json";
import { Check, Copy, ExternalLink } from "./icons";
import { Row, secondaryButton, Section } from "./SettingsParts";

const REPO = "https://github.com/mzxrq/navivi";

const open = (url: string) => invoke("plugin:opener|open_url", { url }).catch(console.error);

function LinkButton({ url, label }: { url: string; label: string }) {
  return (
    <button type="button" className={secondaryButton} onClick={() => open(url)}>
      <ExternalLink className="w-3.5 h-3.5" /> {label}
    </button>
  );
}

export function AboutPanel() {
  const [version, setVersion] = useState(appConfig.version);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    getVersion().then((v) => v && setVersion(v)).catch(() => {});
  }, []);

  const details = `Navivi ${version}\n${navigator.userAgent}\n${navigator.language}`;
  const copyDetails = async () => {
    try {
      await navigator.clipboard.writeText(details);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (error) {
      console.error(error);
    }
  };

  const builtWith: { name: string; role: string; url: string }[] = [
    { name: "Tauri", role: t`The desktop shell`, url: "https://tauri.app" },
    { name: "React", role: t`The app's interface`, url: "https://react.dev" },
    { name: "Mapbox GL JS", role: t`The map you edit on`, url: "https://www.mapbox.com" },
    { name: "deck.gl", role: t`The 3D route flythroughs`, url: "https://deck.gl" },
    { name: "FFmpeg", role: t`Joins clips, narration and subtitles into the video`, url: "https://ffmpeg.org" },
    { name: "Playwright", role: t`Records the route animation`, url: "https://playwright.dev" },
    { name: "Ollama", role: t`Writes narration scripts on your PC`, url: "https://ollama.com" },
    { name: "Irodori-TTS", role: t`Natural voice`, url: "https://github.com/Aratako/Irodori-TTS" },
    { name: "Qwen3-TTS", role: t`Balanced voice`, url: "https://github.com/QwenLM/Qwen3-TTS" },
    { name: "Kokoro", role: t`Fast voice`, url: "https://github.com/hexgrad/kokoro" },
    { name: "ComfyUI", role: t`Animates attraction photos`, url: "https://www.comfy.org" },
  ];

  const credits = stockVoices.voices.filter((v) => v.verified && v.credit);

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-4 rounded-xl border border-zinc-200 dark:border-white/10 px-5 py-4">
        <img src="/navivi.svg" alt="" className="w-14 h-14 shrink-0" />
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <h3 className="text-[18px] font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">{appConfig.name}</h3>
            <span className="text-[12px] tabular-nums text-zinc-500 dark:text-zinc-400">{t`Version ${version}`}</span>
          </div>
          <p className="mt-1 text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
            <Trans>Turns waypoints and GPS tracks into narrated, cinematic map-route travel videos. Everything runs on your PC.</Trans>
          </p>
        </div>
      </div>

      <Section title={t`Project`}>
        <Row title={t`Source code`} description={REPO.replace("https://", "")}>
          <LinkButton url={REPO} label={t`Open`} />
        </Row>
        <Row title={t`Report a problem`} description={t`Include the version and system details from "This copy" so it is easier to reproduce.`}>
          <LinkButton url={`${REPO}/issues`} label={t`Open`} />
        </Row>
        <Row title={t`This copy`} description={`${t`Version ${version}`} · ${navigator.language}`}>
          <button type="button" className={secondaryButton} onClick={copyDetails}>
            {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />} {copied ? t`Copied` : t`Copy details`}
          </button>
        </Row>
      </Section>

      <Section title={t`Built with`}>
        {builtWith.map((lib) => (
          <Row key={lib.name} title={lib.name} description={lib.role}>
            <button type="button" className={secondaryButton} aria-label={t`Open ${lib.name} website`} onClick={() => open(lib.url)}>
              <ExternalLink className="w-3.5 h-3.5" />
            </button>
          </Row>
        ))}
      </Section>

      <Section title={t`Map data`}>
        <Row title="© Mapbox, © OpenStreetMap contributors" description={t`Base maps and place names.`}>
          <LinkButton url="https://www.openstreetmap.org/copyright" label={t`Details`} />
        </Row>
        <Row title="OpenRouteService" description={t`Routes between stops, when you let the app find them.`}>
          <LinkButton url="https://openrouteservice.org" label={t`Open`} />
        </Row>
        <Row title="国土地理院 (GSI Japan)" description={t`Road and path data that drawn routes snap to in Japan.`}>
          <LinkButton url="https://maps.gsi.go.jp" label={t`Open`} />
        </Row>
      </Section>

      {credits.length > 0 && (
        <Section title={t`Voices that come with Navivi`}>
          {credits.map((v) => (
            <Row key={v.id} title={v.id} description={v.credit}>
              <span />
            </Row>
          ))}
        </Section>
      )}
    </div>
  );
}
