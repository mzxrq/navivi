import { describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/path", () => ({ join: vi.fn() }));
vi.mock("@tauri-apps/plugin-fs", () => ({ exists: vi.fn(), readDir: vi.fn(), readTextFile: vi.fn(), remove: vi.fn(), writeTextFile: vi.fn() }));
vi.mock("./fileSystem", () => ({ duplicateProjectFolder: vi.fn(), loadProjectData: vi.fn() }));
vi.mock("./projectStore", () => ({ syncProjectOnOpen: vi.fn() }));
vi.mock("./ollamaApi", () => ({ completeText: vi.fn() }));

import { applyTranslations, batches, collectTexts, ENGLISH_KOKORO_VOICE, guessLanguage, parseTranslations, translationPrompt } from "./languageVersion";

const project = () => ({
  project_name: "加太",
  video_title: "加太を歩く",
  overview_narration: "加太の旅です。",
  waypoints: [
    { id: "a", name: "西ノ庄駅", arrivingNarration: "駅から出発します。", attractionNarration: "", audioUrl: "x.wav" },
    { id: "b", name: "西念寺", attractionNarration: "古いお寺です。{end}", narration: "旧台本" },
  ],
  settings: {
    fps: 30,
    pronunciation_dictionary: [{ word: "加太", reading: "かだ" }],
    tts: { engine: "irodori", voice: "x", speed: 1.1 },
    intro_location: "和歌山県 和歌山市",
    intro_location_manual: true,
    marked_regeneration_waypoints: ["a"],
    overview_title: "加太コース",
  },
});

describe("guessLanguage", () => {
  it("says Japanese when kana or kanji make up most of the letters", () => {
    expect(guessLanguage(["駅から出発します。", "Station"])).toBe("ja");
    expect(guessLanguage(["Start at the station and walk north.", "駅"])).toBe("en");
    expect(guessLanguage([])).toBe("en");
  });
});

describe("collectTexts", () => {
  it("separates stop names from the narration and skips blanks", () => {
    const { names, scripts } = collectTexts(project());
    expect(names).toEqual({ "wp.0.name": "西ノ庄駅", "wp.1.name": "西念寺" });
    expect(Object.keys(scripts).sort()).toEqual(
      ["overview_narration", "settings.overview_title", "video_title", "wp.0.arrivingNarration", "wp.1.attractionNarration", "wp.1.narration"].sort(),
    );
  });
});

describe("applyTranslations", () => {
  const translated = { "wp.0.name": "Nishinosho Station", "wp.1.attractionNarration": "An old temple. {end}", video_title: "Walking Kada" };

  it("replaces what was translated, keeps what was not, and leaves the original alone", () => {
    const source = project();
    const next = applyTranslations(source, translated, "en", "Kada (English)");
    expect(next.project_name).toBe("Kada (English)");
    expect(next.waypoints[0].name).toBe("Nishinosho Station");
    expect(next.waypoints[1].name).toBe("西念寺");
    expect(next.waypoints[1].attractionNarration).toBe("An old temple. {end}");
    expect(next.waypoints[1].narration).toBe("旧台本");
    expect(next.video_title).toBe("Walking Kada");
    expect(next.overview_narration).toBe("加太の旅です。");
    expect(source.waypoints[0].name).toBe("西ノ庄駅");
  });

  it("resets what belongs to the old language", () => {
    const { settings, waypoints } = applyTranslations(project(), translated, "en", "x");
    expect(settings.video_text_language).toBe("en");
    expect(settings.pronunciation_dictionary).toEqual([]);
    expect(settings.intro_location_manual).toBe(false);
    expect(settings.intro_location_at).toBe("");
    expect(settings.marked_regeneration_waypoints).toBeUndefined();
    expect(settings.fps).toBe(30);
    expect(settings.tts).toEqual({ engine: "kokoro", kokoro_voice: ENGLISH_KOKORO_VOICE, speed: 1.1 });
    expect(waypoints[0].audioUrl).toBeUndefined();
  });

  it("keeps a translated overview script from being replaced by an auto-written one", () => {
    const source = { ...project(), overview_narration_is_auto: true };
    expect(applyTranslations(source, { overview_narration: "A trip to Kada." }, "en", "x").overview_narration_is_auto).toBe(false);
    expect(applyTranslations(source, {}, "en", "x").overview_narration_is_auto).toBe(true);
  });

  it("drops the voice choice when going back to Japanese", () => {
    expect(applyTranslations(project(), {}, "ja", "x").settings.tts).toBeUndefined();
  });
});

describe("parseTranslations", () => {
  it("reads a JSON object out of a chatty reply and keeps only the ids asked for", () => {
    const reply = 'Sure!\n```json\n{"a": " Hello ", "b": "", "c": 3, "z": "extra"}\n```';
    expect(parseTranslations(reply, ["a", "b", "c", "d"])).toEqual({ a: "Hello" });
  });
  it("returns nothing for text that is not JSON", () => {
    expect(parseTranslations("I cannot do that", ["a"])).toEqual({});
  });
});

describe("batches", () => {
  it("starts a new batch when the next text would not fit and never splits one text", () => {
    const out = batches({ a: "x".repeat(60), b: "y".repeat(60), c: "z".repeat(500) }, 100);
    expect(out.map((b) => Object.keys(b))).toEqual([["a"], ["b"], ["c"]]);
    expect(batches({}, 100)).toEqual([]);
  });
});

describe("translationPrompt", () => {
  it("names the languages, repeats the place-name glossary and carries the items", () => {
    const prompt = translationPrompt({ x: "駅" }, "en", { 西念寺: "Sainen-ji Temple" });
    expect(prompt).toContain("from Japanese to English");
    expect(prompt).toContain("西念寺 => Sainen-ji Temple");
    expect(prompt).toContain('{"x":"駅"}');
    expect(translationPrompt({ x: "Station" }, "ja")).toContain("from English to Japanese");
  });
});
