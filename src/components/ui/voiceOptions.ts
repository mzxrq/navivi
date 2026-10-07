import { t } from "@lingui/core/macro";

// Mirrors tuning.TTS_CAPTION (the default speaking style of the natural voice); a project that never set one omits the key.
export const DEFAULT_TTS_CAPTION = "落ち着いた、親しみやすい語り口。";

// The engine accepts 0.25-4x (tuning.TTS_MIN_SPEED / TTS_MAX_SPEED); the default stays 1.25x.
export const TTS_SPEED_RANGE = { min: 0.25, max: 4, step: 0.05 };

/** The prompts are Japanese because the model reads them; only the button labels are translated. */
export const ttsCaptionPresets = (): { id: string; label: string; text: string }[] => [
  { id: "energetic", label: t`Energetic`, text: "明るく元気で、楽しそうな話し方。" },
  { id: "calm", label: t`Calm`, text: "落ち着いた、穏やかな話し方。" },
  { id: "warm", label: t`Warm`, text: "温かく、優しい語り口。" },
  { id: "serious", label: t`Serious`, text: "真面目で、落ち着いた口調。" },
];

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(0, Math.round(bytes / 1024))} KB`;
  const mb = bytes / 1024 / 1024;
  return mb < 1024 ? `${mb.toFixed(mb < 10 ? 1 : 0)} MB` : `${(mb / 1024).toFixed(1)} GB`;
}
