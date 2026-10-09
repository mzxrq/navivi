import { distanceMeters, tidyPlaceName } from "../utils/gpxTrack";

// Where a stop sits in the route, so "arriving" talks about the real previous stop and nothing repeats.
export interface RouteContext {
    previous?: string;
    next?: string;
    index?: number;
    total?: number;
    // The stop's other script (arriving <-> attraction), so the two don't say the same things.
    otherScript?: string;
    // Scripts already written for the other stops, so every stop doesn't reuse the same words.
    otherStops?: string[];
    // The leg the arriving line talks about: where it starts and ends, and how it is travelled.
    from?: { lat: number; lng: number };
    to?: { lat: number; lng: number };
    mode?: string;
    // The language the script is written in (unset: Japanese, the prompt's own).
    language?: "ja" | "en";
    // What the source document says about getting to this stop from the previous one, and how long it takes.
    directions?: string;
    minutes?: number;
}

const COMPASS = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"];
const MODE_WORDS: Record<string, string> = { walking: "歩いて", driving: "車で", ferry: "船で" };

type LegStop = { lat: number; lng: number; routeMode?: string };

// The leg into stop `index` (the first stop: the leg out of it); a leg leaves with its start's routeMode.
export function legOf(stops: LegStop[], index: number): Pick<RouteContext, "from" | "to" | "mode"> {
    const a = stops[index === 0 ? 0 : index - 1];
    const b = stops[index === 0 ? 1 : index];
    return a && b ? { from: { lat: a.lat, lng: a.lng }, to: { lat: b.lat, lng: b.lng }, mode: a.routeMode } : {};
}

// Compass direction, rough distance and means of travel of a leg, worded for the prompt. "" without both ends.
export function legDirection(route: RouteContext): string {
    const { from, to } = route;
    if (!from || !to || (!from.lat && !from.lng) || (!to.lat && !to.lng)) return "";
    const rad = Math.PI / 180;
    const dLng = (to.lng - from.lng) * rad;
    const y = Math.sin(dLng) * Math.cos(to.lat * rad);
    const x = Math.cos(from.lat * rad) * Math.sin(to.lat * rad) - Math.sin(from.lat * rad) * Math.cos(to.lat * rad) * Math.cos(dLng);
    const bearing = (Math.atan2(y, x) / rad + 360) % 360;
    const meters = distanceMeters([from.lat, from.lng], [to.lat, to.lng]);
    const near = meters < 300 ? "すぐ近く" : meters < 1500 ? "少し先" : "離れた場所";
    const mode = MODE_WORDS[route.mode ?? ""];
    return [`方角: ${COMPASS[Math.round(bearing / 45) % 8]}`, `距離の感じ: ${near}`, mode && `移動手段: ${mode}`].filter(Boolean).join("、");
}

// Strips what a text-to-speech voice would read aloud wrongly: labels, quotes, stage directions, markdown, emoji.
export function cleanNarration(text: string): string {
    return text
        .replace(/^\s*(?:ナレーション|台本|出力|Narration)\s*[:：]\s*/i, "")
        .replace(/\[[^\]]*\]|【[^】]*】/g, "")
        .replace(/[*#_`>]+/g, "")
        .replace(/\p{Extended_Pictographic}/gu, "")
        .replace(/^[「『"]+|[」』"]+$/g, "")
        .replace(/[ \t]+\n/g, "\n")
        .trimStart();
}

// One per kind of script: a small model copies how its example opens, so the attraction one must not open with an arrival.
// Several shapes for the arriving line, so every stop doesn't get the same 「〜へ向かいます」.
const STYLE_EXAMPLES = {
    arriving: [
        "ここから北東へ、少し先のお寺まで歩いて向かいます。",
        "次は西の方角へ。車で次の町を目指します。",
        "南へ少し歩けば、次の目的地です。",
        "船に乗り、東に浮かぶ島へ渡ります。",
    ],
    start: ["旅はこの駅から。まずは南へ、次の目的地を目指して歩き出しましょう。"],
};

// Openings and verbs the direction-only arriving line leans on (the mode words, 歩いて etc., are facts, not listed).
const ARRIVING_STOCK = [
    "向かいます", "向かう", "目指", "進みます", "進んで", "足を延ば", "移動", "出発", "歩き出", "たどり", "渡ります",
    "行きます", "次は", "続いて", "ここから", "さあ", "まずは", "そのまま", "いよいよ", "方角",
];

// Stop lines from the user's hand-written course script (加太・友ヶ島). Shown together so the model sees several
// sentence shapes and picks one, instead of giving every stop the same 「〜な、Xです。」.
const ATTRACTION_EXAMPLES = [
    "ここは南海加太線の終点、加太駅。このコースの出発点です。",
    "道すがら、角に見えるのが、加太淡嶋神社への道を示す古い石標です。",
    "加太淡嶋神社です。人形供養と、ひな流しの神事で全国に知られています。",
    "阿字ヶ峰の階段を登りつめたところに、修験道の開祖・役行者の像を祀る行者堂があります。",
    "島の最高峰、タカノス山の山頂展望台です。",
    "加太港です。友ヶ島行きのフェリーは、ここから出航します。",
];

// Stock travel-show words a small model leans on at every stop.
const STOCK_WORDS = [
    "静か", "穏やか", "落ち着いた", "佇まい", "雰囲気", "魅力", "癒やし", "心地よ", "楽しむ", "楽しめ", "感じ", "広が",
    "迎えて", "耳を澄ませ", "訪れ", "豊かな", "美しい", "素晴らしい", "ゆったり", "のんびり", "ひととき", "息づ", "歴史",
];

// Stock words the other stops' scripts already used, most used first: listed in the prompt so this stop picks others.
// Only stock words: another stop's names and facts in the list get copied into this stop as if true.
export function usedWords(scripts: string[], limit = 15, words = STOCK_WORDS): string[] {
    const counts = new Map<string, number>();
    for (const script of scripts) for (const w of words) if (script.includes(w)) counts.set(w, (counts.get(w) ?? 0) + 1);
    return [...counts].sort((a, b) => b[1] - a[1]).slice(0, limit).map(([w]) => w);
}

export interface WaypointPromptInput {
    place: string;
    theme: string;
    userPrompt: string;
    facts: string;
    scriptType: "arriving" | "attraction";
    isFirstWaypoint: boolean;
    hasPhotos?: boolean;
    route: RouteContext;
}

const COMPASS_EN = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"];
const MODE_EN: Record<string, string> = { walking: "on foot", driving: "by car", ferry: "by ferry" };

// The English twin of the prompt below: same facts, same rules (only what is given, no invented history, the direction only
// while travelling), written in English so a small model answers in English instead of translating Japanese instructions.
export function buildEnglishWaypointPrompt({ place, theme, userPrompt, facts, scriptType, isFirstWaypoint, hasPhotos, route }: WaypointPromptInput): string {
    const previous = route.previous ? tidyPlaceName(route.previous) : "";
    const next = route.next ? tidyPlaceName(route.next) : "";
    const isLast = route.index !== undefined && route.total !== undefined && route.total > 1 && route.index === route.total - 1;
    const arriving = scriptType === "arriving";
    const { from, to } = route;
    let direction = "";
    if (arriving && from && to && (from.lat || from.lng) && (to.lat || to.lng)) {
        const rad = Math.PI / 180;
        const dLng = (to.lng - from.lng) * rad;
        const y = Math.sin(dLng) * Math.cos(to.lat * rad);
        const x = Math.cos(from.lat * rad) * Math.sin(to.lat * rad) - Math.sin(from.lat * rad) * Math.cos(to.lat * rad) * Math.cos(dLng);
        const bearing = (Math.atan2(y, x) / rad + 360) % 360;
        const meters = distanceMeters([from.lat, from.lng], [to.lat, to.lng]);
        const near = meters < 300 ? "very close" : meters < 1500 ? "a short way ahead" : "some distance away";
        const mode = MODE_EN[route.mode ?? ""];
        direction = [`direction: ${COMPASS_EN[Math.round(bearing / 45) % 8]}`, `distance: ${near}`, mode && `travelled ${mode}`].filter(Boolean).join(", ");
    }
    const directions = arriving ? route.directions?.trim() ?? "" : "";
    const info = [
        `Place: ${place}`,
        previous && `Previous stop: ${previous}`,
        next && `Next stop: ${next}`,
        direction && `This leg: ${direction}`,
        directions && `The source document's directions for this leg: ${directions}`,
        directions && route.minutes && `The source document's travel time: about ${route.minutes} minutes`,
        userPrompt && `Requests from the user (highest priority):\n${userPrompt}`,
        facts && `Facts you may use:\n${facts}`,
        route.otherScript?.trim() && `${arriving ? "The narration read after arriving" : "The narration read just before"} (do not repeat its facts or wording):\n${route.otherScript.trim()}`,
    ]
        .filter(Boolean)
        .join("\n");

    let task: string;
    let length: string;
    if (arriving) {
        length = directions ? "1-2 sentences, 15-45 words" : "1 sentence, 8-25 words";
        const only = directions
            ? "Tell only how to get there, using the document's directions. No scenery, feelings, history or explanation (the next narration covers them)."
            : "Tell only which way and how to go. No scenery, feelings, history or explanation (the next narration covers them).";
        task = isFirstWaypoint
            ? `Write a short narration that announces the start of the trip: leaving ${place}${next ? ` for ${next}` : ""}. ${only}`
            : `Write a short narration spoken while travelling ${previous ? `from ${previous} ` : ""}to ${isLast ? "the last stop, " : ""}${place}. ${only}`;
    } else {
        length = "2-3 sentences, 30-70 words";
        task = `Write the narration a local guide speaks to people walking the course at ${place}. The first sentence says the name of ${place}. Then 1-2 short sentences describe what can be seen here, from the facts or photo given. One fact per sentence.${route.index === 0 ? " This is the start of the course." : isLast ? " This is the end of the course." : ""} Do not write stock feelings such as "wonderful" or "breathtaking".`;
        if (!facts.trim() && !userPrompt.trim() && !hasPhotos) task += ` There is no information about this place, so write only "${place}."`;
    }
    const rules = [
        "Use only the information above and what the attached photos show. Do not add dates, numbers, names, specialties or opening hours from guesswork.",
        arriving
            ? "Give the direction and the means of travel only if they are written above. Give directions and times only if they are written above as the document's. Do not write distances."
            : "If you are not sure, do not make up facts; say only the name. Mention a photo's contents only if they are really visible, and never use the word \"photo\".",
        arriving ? "No welcome greeting (the start of the trip already had one)." : "Do not talk about the journey here: the previous narration did that. Talk about this place only.",
        "Write natural spoken English that is easy to listen to. Use no Japanese characters.",
        `Length: ${length}, one paragraph.`,
        "The text is read aloud by a voice: no headings, lists, symbols, emoji, stage directions in brackets, or URLs.",
        "Output only the narration: no preface, title, speaker name or quotation marks.",
    ];
    return `${arriving ? "You are the professional narrator of a travel video." : "You are a local guide who knows this area well."}${theme ? ` The theme of this trip is "${theme}".` : ""}
${task}

${info}

Rules:
${rules.map((r, i) => `${i + 1}. ${r}`).join("\n")}`;
}

export function buildWaypointPrompt(input: WaypointPromptInput): string {
    if (input.route.language === "en") return buildEnglishWaypointPrompt(input);
    const { place, theme, userPrompt, facts, scriptType, isFirstWaypoint, hasPhotos, route } = input;
    const previous = route.previous ? tidyPlaceName(route.previous) : "";
    const next = route.next ? tidyPlaceName(route.next) : "";
    const isLast = route.index !== undefined && route.total !== undefined && route.total > 1 && route.index === route.total - 1;
    const direction = scriptType === "arriving" ? legDirection(route) : "";
    const directions = scriptType === "arriving" ? route.directions?.trim() ?? "" : "";
    const routeLines = [previous && `前の立ち寄り場所: ${previous}`, next && `次の立ち寄り場所: ${next}`, direction && `この移動の${direction}`, directions && `資料にあるこの区間の道順: ${directions}`, directions && route.minutes && `資料にある所要時間: 約${route.minutes}分`]
        .filter(Boolean)
        .join("\n");
    const from = previous ? `「${previous}」から` : "前の場所から";
    const other = route.otherScript?.trim() ?? "";
    const otherHeading = scriptType === "arriving" ? "到着後に読み上げるナレーション" : "直前に読み上げるナレーション";

    let task = "";
    let length = "";
    if (scriptType === "arriving") {
        length = directions ? "1〜2文、30〜80文字" : "1文、20〜50文字";
        const brief = directions
            ? "資料にある道順をもとに、どう向かうかだけを短く伝えてください。景色、気持ち、歴史や解説は書かないでください(次のナレーションに任せます)。"
            : "どの方角へ、どうやって向かうかだけを短く伝えてください。景色、気持ち、歴史や解説は書かないでください(次のナレーションに任せます)。";
        if (isFirstWaypoint) {
            task = `旅の出発を告げる短いナレーションです。ここ「${place}」から${next ? `次の場所「${next}」へ` : ""}出発します。${brief}`;
        } else {
            task = `${from}${isLast ? "最後の場所" : ""}「${place}」へ向かう移動中の短いナレーションです。${brief}`;
        }
    } else {
        length = "2〜3文、60〜120文字";
        task = `「${place}」で、コースを歩く人に地元の案内人が語りかけるナレーションです。最初の文で、例のようにこの場所に合った形で「${place}」の名前を言ってください。名前の前の説明は短く一つまでにしてください。続く1〜2文で、与えられた情報や写真をもとに、ここで何が見られるか、どんな場所かを具体的に描写してください。事実は一文に一つずつ、短い文に分けてください。${route.index === 0 ? "ここはこのコースの出発点です。" : isLast ? "ここはこのコースの終点です。" : ""}「素晴らしい」「心が癒される」のような決まり文句の感想や気持ちは書かないでください。`;
        // Nothing to go on: anything past the name would be invented.
        if (!facts.trim() && !userPrompt.trim() && !hasPhotos) task += `この場所についての情報がないので、「${place}です。」とだけ書いてください。`;
    }

    const noRepeat =
        scriptType === "arriving"
            ? "「みなさん、こんにちは」のような歓迎の挨拶は入れないこと(旅の冒頭で済んでいます)。"
            : "移動のことは直前のナレーションで済んでいるので、この場所そのものの話だけをすること。";
    const noRepeatOther = other
        ? `
6. 【${otherHeading}】と同じ事実、言い回し、文の始め方を使わないこと。同じ場所の別の面を語ること。`
        : "";
    const used = usedWords(route.otherStops ?? [], 15, scriptType === "arriving" ? ARRIVING_STOCK : STOCK_WORDS);
    const usedRule = used.length
        ? `
5. 【ほかの場所で使った言葉】は使わず、${scriptType === "arriving" ? "別の言い回しと、ほかの場所とは違う文の形にすること。" : "この場所に合った別の言葉で表現すること。"}`
        : "";

    const persona = scriptType === "attraction" ? "あなたは、この土地をよく知る散策コースの案内人です。" : "あなたは旅行番組のプロのナレーターです。";
    const prompt = `${persona}${theme ? `この旅のテーマは「${theme}」です。` : ""}
${task}

【場所】${place}
${routeLines ? routeLines + "\n" : ""}${userPrompt ? `【ユーザーからの要望(最優先で反映する)】\n${userPrompt}\n` : ""}${facts ? `【参考にしてよい情報】\n${facts}\n` : ""}${other ? `【${otherHeading}(内容を重ねないこと)】\n${other}\n` : ""}${used.length ? `【ほかの場所で使った言葉】${used.join("、")}\n` : ""}
【内容のルール】
1. 上の情報、ユーザーの要望、添付された写真に書かれている・写っていることだけを根拠にすること。年代、数字、人名、名物、営業時間などを推測や想像で書き足さないこと。
2. ${scriptType === "attraction" ? `確かな情報が少ないときは、事実を作らず「${place}です。」だけにすること。写真が添付されているときだけ、実際に写っているものを一言添えてよい(「写真」という言葉は使わない)。` : "方角と移動手段は上に書かれているものだけを使うこと。書かれていなければ方角は言わないこと。道順や所要時間は「資料にある」と書かれているものだけを使い、ないものは書かないこと。距離の数字は書かないこと。"}
3. 写真がある場合は、実際に写っている景色や特徴だけを自然に触れること。写っていないものや、写真から場所の名前を断定することはしないこと。
4. 前の場所・次の場所の名前は、上に書かれているものだけを使うこと。
5. ${noRepeat}${noRepeatOther}

【書き方のルール】
1. 日本語の「です・ます調」で、聞いて分かりやすい自然な話し言葉にすること。
2. 長さは${length}。1つの段落にまとめること。
3. 音声合成でそのまま読み上げるため、見出し、箇条書き、記号、絵文字、括弧書きの演出(例: [笑顔で])、URLは絶対に書かないこと。
4. 前置きや説明(「以下がナレーションです」など)、タイトル、話者名、引用符は付けず、ナレーションの本文だけを出力すること。${usedRule}

${scriptType === "arriving" ? `例(書き方の参考だけ。内容や言い回しは使わないこと):
${STYLE_EXAMPLES[isFirstWaypoint ? "start" : "arriving"].join("\n")}` : `人が書いた別のコースの例(文の形の参考だけ。地名や事実は使わないこと):
${ATTRACTION_EXAMPLES.join("\n")}`}`;

    return prompt;
}

// "落ち着いた" (calm) is not an arrival.
const ARRIVAL = /到着|(?<!落ち)着(?:きました|いた)|やって[来き]ました|\b(?:you(?:'ve| have)? arrived|we(?:'ve| have)? arrived|you arrive|welcome to)\b/i;
// English sentences end at . ! ? but not after "Mt.", "Sta." and the like, nor inside a number.
const EN_SENTENCE = /(?:\b(?:Mt|Sta|St|Dr|Mr|Mrs|Ms|Jr|Sr|vs|No)\.|\d\.\d|[^.!?])+(?:[.!?]+\s*|$)/g;
const sentencesOf = (text: string) => (text.match(/[^。！？!?\n]+[。！？!?]*\s*/g) ?? []).flatMap((piece) => piece.match(EN_SENTENCE) ?? [piece]);
const bigrams = (text: string) => {
    const t = text.replace(/[\s、。！？!?]/g, "");
    return new Set(Array.from({ length: Math.max(0, t.length - 1) }, (_, i) => t.slice(i, i + 2)));
};
const overlap = (a: Set<string>, b: Set<string>) => {
    if (!a.size || !b.size) return 0;
    let shared = 0;
    for (const x of a) if (b.has(x)) shared++;
    return shared / Math.min(a.size, b.size);
};

// Small models ignore "don't repeat" and copy the stop's other script, or open the attraction one with an arrival:
// those sentences are dropped. "" when every sentence was one of those.
export function dropRepeatedSentences(text: string, otherScript: string | undefined, scriptType: "arriving" | "attraction"): string {
    const others = sentencesOf(otherScript ?? "").map(bigrams);
    const sentences = sentencesOf(text);
    const kept = sentences.filter((sentence) => {
        if (scriptType === "attraction" && ARRIVAL.test(sentence)) return false;
        const grams = bigrams(sentence);
        return !others.some((o) => overlap(grams, o) >= 0.6);
    });
    return kept.join("").trim();
}
