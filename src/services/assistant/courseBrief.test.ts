import { describe, expect, it } from "vitest";
import { courseBriefPrompt, introFacts, mergeChain, minutesOf, parseCourseBrief, parseCourseTimes } from "./courseBrief";

describe("parseCourseBrief", () => {
  it("reads a fenced reply with stops, directions and minutes", () => {
    const reply = '```json\n{"travel":"walking","stops":[{"name":"Kyoshi Sta.","directions":"","minutes":0},{"name":" Kosen-ji Temple ","directions":"Turn left along the tracks.","minutes":15}],"distance":"10 km","advice":["Wear hiking shoes","",5],"returnTrip":"Bus to Wakayamashi Sta."}\n```';
    expect(parseCourseBrief(reply)).toEqual({
      stops: [{ name: "Kyoshi Sta." }, { name: "Kosen-ji Temple", directions: "Turn left along the tracks.", minutes: 15 }],
      travel: "walking",
      distance: "10 km",
      advice: ["Wear hiking shoes"],
      returnTrip: "Bus to Wakayamashi Sta.",
    });
  });

  it("drops malformed fields instead of guessing", () => {
    const brief = parseCourseBrief('{"stops":["Kyoto",{"name":"Nara","minutes":-4},{"nope":1}],"travel":"flying"}');
    expect(brief).toEqual({ stops: [{ name: "Kyoto" }, { name: "Nara" }] });
  });

  it("is null for a reply that is not a course", () => {
    expect(parseCourseBrief("I cannot do that")).toBeNull();
    expect(parseCourseBrief('["Kyoto","Nara"]')).toBeNull();
  });

  it("lists only the facts the course has for the introduction", () => {
    expect(introFacts({ stops: [], distance: "10 km", advice: ["Wear boots", "Check signposts"] })).toBe("Distance: 10 km\nAdvice: Wear boots / Check signposts");
    expect(introFacts({ stops: [] })).toBe("");
  });

  it("puts the document in the prompt", () => {
    expect(courseBriefPrompt("Leave the station")).toContain("Leave the station");
  });
});

describe("course times chain", () => {
  const text = "[text]\nsome story\n[course times: stop -> time -> stop]\nKyoshi Sta. (Nankai Main Line) -> 15 min. -> Kosen-ji Temple -> 1 hr. 20 min. -> Mt. Iimori\n[labels and captions on the page: not in travel order]\nMt. Fudo";

  it("reads durations", () => {
    expect([minutesOf("25 min."), minutesOf("1 hr. 20 min."), minutesOf("2 hours"), minutesOf("1時間20分"), minutesOf("Mt. Fudo")]).toEqual([25, 80, 120, 80, 0]);
  });

  it("gives the stops in order with the minutes from the previous stop", () => {
    expect(parseCourseTimes(text)).toEqual([{ name: "Kyoshi Sta." }, { name: "Kosen-ji Temple", minutes: 15 }, { name: "Mt. Iimori", minutes: 80 }]);
    expect(parseCourseTimes("no chain here")).toEqual([]);
  });

  it("keeps the model's directions for stops it names the same way, and the chain's order and minutes", () => {
    const merged = mergeChain(parseCourseTimes(text), { stops: [{ name: "Kyoshi Station", directions: "Turn left." }, { name: "Mt. Iimori", directions: "Climb.", minutes: 5 }, { name: "Mt. Fujito" }], intro: "A walk." });
    expect(merged.stops).toEqual([{ name: "Kyoshi Sta.", directions: "Turn left." }, { name: "Kosen-ji Temple", minutes: 15 }, { name: "Mt. Iimori", minutes: 80, directions: "Climb." }]);
    expect(merged).toMatchObject({ intro: "A walk.", travel: "walking" });
    expect(mergeChain(parseCourseTimes(text), null).stops).toHaveLength(3);
  });
});
