// The project brief the assistant fills in during the chat. Its fields mirror the "final project prompt" of the
// hand-off document (name, purpose, audience, languages, length, tone, word count, scope, must include / avoid, visuals, call to action).

export type BriefLanguage = "ja" | "en";

export interface ProjectBrief {
  name: string;
  purpose: string;
  audience: string;
  languages: BriefLanguage[];
  durationMin: number | null;
  tone: string;
  wordCount: { min: number; max: number } | null;
  scope: string; // which topics / places the script covers, in the user's words
  mustInclude: string[];
  avoid: string[];
  visuals: string;
  callToAction: string;
  places: string[]; // stops in travel order, as place names to geocode
}

export const EMPTY_BRIEF: ProjectBrief = {
  name: "",
  purpose: "",
  audience: "",
  languages: [],
  durationMin: null,
  tone: "",
  wordCount: null,
  scope: "",
  mustInclude: [],
  avoid: [],
  visuals: "",
  callToAction: "",
  places: [],
};

const text = (v: unknown): string | undefined => (typeof v === "string" ? v.trim() : undefined);
const list = (v: unknown): string[] | undefined =>
  Array.isArray(v) ? v.map((x) => (typeof x === "string" ? x.trim() : "")).filter(Boolean) : undefined;

// Turns whatever the model returned for a brief into valid fields only; anything malformed is dropped, not guessed.
export function cleanBriefPatch(raw: unknown): Partial<ProjectBrief> {
  if (!raw || typeof raw !== "object") return {};
  const r = raw as Record<string, unknown>;
  const patch: Partial<ProjectBrief> = {};
  for (const key of ["name", "purpose", "audience", "tone", "scope", "visuals", "callToAction"] as const) {
    const v = text(r[key]);
    if (v !== undefined) patch[key] = v;
  }
  for (const key of ["mustInclude", "avoid", "places"] as const) {
    const v = list(r[key]);
    if (v) patch[key] = v;
  }
  const languages = list(r.languages)?.map((l) => l.toLowerCase()).filter((l): l is BriefLanguage => l === "ja" || l === "en");
  if (languages) patch.languages = [...new Set(languages)];
  const minutes = Number(r.durationMin);
  if (r.durationMin !== null && r.durationMin !== undefined && Number.isFinite(minutes) && minutes > 0 && minutes <= 180) patch.durationMin = minutes;
  const wc = r.wordCount as { min?: unknown; max?: unknown } | null | undefined;
  if (wc && typeof wc === "object") {
    const min = Number(wc.min);
    const max = Number(wc.max);
    if (Number.isFinite(min) && Number.isFinite(max) && min > 0 && max >= min) patch.wordCount = { min: Math.round(min), max: Math.round(max) };
  }
  return patch;
}

export function mergeBrief(brief: ProjectBrief, patch: Partial<ProjectBrief>): ProjectBrief {
  return { ...brief, ...patch };
}

// What still has to be known before a project can be built: at least somewhere to go.
export function missingForBuild(brief: ProjectBrief): string[] {
  return brief.places.length === 0 ? ["places"] : [];
}
