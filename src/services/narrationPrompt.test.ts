import { describe, expect, it } from "vitest";
import { buildWaypointPrompt, dropRepeatedSentences, legDirection, legOf, usedWords } from "./narrationPrompt";

const base = { place: "高仙寺", theme: "", userPrompt: "", facts: "", isFirstWaypoint: false };
const arriving = "孝子駅から歩いて高仙寺に着きました。";

describe("buildWaypointPrompt", () => {
  it("shows the attraction prompt what the arriving script already said", () => {
    const prompt = buildWaypointPrompt({ ...base, scriptType: "attraction", route: { otherScript: arriving } });
    expect(prompt).toContain(`【直前に読み上げるナレーション(内容を重ねないこと)】\n${arriving}\n`);
    expect(prompt).toContain("6. 【直前に読み上げるナレーション】と同じ事実");
  });

  it("shows the arriving prompt the attraction script it leads into", () => {
    const prompt = buildWaypointPrompt({ ...base, scriptType: "arriving", route: { otherScript: "本堂は静かです。" } });
    expect(prompt).toContain("【到着後に読み上げるナレーション(内容を重ねないこと)】\n本堂は静かです。");
  });

  it("adds nothing when the other script is empty", () => {
    const prompt = buildWaypointPrompt({ ...base, scriptType: "attraction", route: { otherScript: "  " } });
    expect(prompt).not.toContain("内容を重ねないこと");
    expect(prompt).not.toContain("\n6. ");
  });

  it("gives the arriving line the leg's direction and keeps it to one short sentence", () => {
    const route = legOf([{ lat: 34.27, lng: 135.06, routeMode: "walking" }, { lat: 34.28, lng: 135.07 }], 1);
    const prompt = buildWaypointPrompt({ ...base, scriptType: "arriving", route });
    expect(prompt).toContain("この移動の方角: 北東、距離の感じ: 少し先、移動手段: 歩いて");
    expect(prompt).toContain("1文、20〜50文字");
    expect(prompt).toContain("景色、気持ち、歴史や解説は書かないで");
  });

  it("tells the arriving line which phrasings the other stops' arriving lines used", () => {
    const otherStops = ["ここから北へ、歩いて向かいます。", "次は東へ、車で向かいます。"];
    const prompt = buildWaypointPrompt({ ...base, scriptType: "arriving", route: { otherStops } });
    expect(prompt).toContain("【ほかの場所で使った言葉】向かいます、ここから、次は\n");
    expect(prompt).toContain("違う文の形にすること");
  });

  it("leaves the direction out when a stop has no position", () => {
    const route = legOf([{ lat: 0, lng: 0 }, { lat: 34.28, lng: 135.07 }], 1);
    expect(legDirection(route)).toBe("");
    expect(buildWaypointPrompt({ ...base, scriptType: "attraction", route: legOf([{ lat: 34, lng: 135 }, { lat: 35, lng: 135 }], 1) })).not.toContain("方角:");
  });

  it("never asks the attraction script about arriving", () => {
    const prompt = buildWaypointPrompt({ ...base, scriptType: "attraction", route: {} });
    expect(prompt.split("例(書き方の参考")[0]).not.toMatch(/到着/);
    expect(prompt).not.toContain("着きました");
  });
});

describe("usedWords", () => {
  const stops = ["高仙寺の本堂は静かな佇まいです。", "海辺は静かで、雰囲気があります。"];

  it("lists the other stops' stock words, most used first, never their names or facts", () => {
    expect(usedWords(stops)).toEqual(["静か", "佇まい", "雰囲気"]);
  });

  it("tells the next stop to avoid them", () => {
    const prompt = buildWaypointPrompt({ ...base, place: "番所庭園", scriptType: "attraction", route: { otherStops: stops } });
    expect(prompt).toMatch(/【ほかの場所で使った言葉】静か、/);
    expect(prompt).toContain("5. 【ほかの場所で使った言葉】は使わず");
  });
});

describe("dropRepeatedSentences", () => {
  // The 孝子駅 stop from the kyoushitofudatateyama project: the attraction script copied the arriving one.
  const arrivingScript =
    "南海本線孝子駅に到着しました。山間にあるこの駅は、静かで穏やかな雰囲気が感じられる場所です。駅周辺には自然豊かな風景が広がり、新鮮な空気を吸いながら散策を楽しむことができます。これから訪れる高仙寺への道のりは、自然と一体になれるような旅に満ちており、期待が高まります。";

  it("empties a copy of the other script", () => {
    const copied = "南海本線孝子駅に到着しました。山間にあるこの駅は、静かで穏やかな雰囲気が感じられる場所です。駅周辺には自然豊かな風景が広がり、新鮮な空気を吸いながら散策を楽しむことができます。";
    expect(dropRepeatedSentences(copied, arrivingScript, "attraction")).toBe("");
  });

  it("keeps the new sentences and drops the repeated ones", () => {
    const mixed = "南海本線孝子駅に到着しました。小さな木造の駅舎が、ホームの端に建っています。駅周辺には自然豊かな風景が広がり、散策を楽しむことができます。";
    expect(dropRepeatedSentences(mixed, arrivingScript, "attraction")).toBe("小さな木造の駅舎が、ホームの端に建っています。");
  });

  it("drops an arrival from the attraction script but keeps 落ち着いた", () => {
    expect(dropRepeatedSentences("高仙寺に着きました。落ち着いた本堂が見えます。", undefined, "attraction")).toBe("落ち着いた本堂が見えます。");
  });

  it("leaves the arriving script's own arrival alone", () => {
    expect(dropRepeatedSentences("高仙寺に着きました。", undefined, "arriving")).toBe("高仙寺に着きました。");
  });
});
