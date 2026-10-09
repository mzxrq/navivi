export type NarrationLanguage = "auto" | "ja" | "en";

const JAPANESE = /[\u3040-\u30ff\u3400-\u9fff]/g;
const LATIN = /[A-Za-z]/g;

// The language a set of texts is mostly in, or null when they hold no letters at all.
export function textLanguage(texts: string[]): "ja" | "en" | null {
  const joined = texts.join("\n");
  const japanese = (joined.match(JAPANESE) ?? []).length;
  const latin = (joined.match(LATIN) ?? []).length;
  if (japanese + latin === 0) return null;
  return japanese > latin * 0.3 ? "ja" : "en";
}

// What the scripts are written in: the setting when it names a language, else the language of the texts at hand (stop names,
// narration, the document), else the language of the app.
export function resolveNarrationLanguage(setting: NarrationLanguage | undefined, texts: string[], uiLocale: string): "ja" | "en" {
  if (setting === "ja" || setting === "en") return setting;
  return textLanguage(texts) ?? (uiLocale.toLowerCase().startsWith("ja") ? "ja" : "en");
}
