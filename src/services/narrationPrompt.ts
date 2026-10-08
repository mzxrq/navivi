import { tidyPlaceName } from "../utils/gpxTrack";

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
const STYLE_EXAMPLES = {
    arriving: "湖のほとりの小さな駅に着きました。ホームに降りると、ひんやりとした風が頬をなでていきます。ここから歩いて十分ほどで、湖畔の遊歩道に出られます。",
    start: "旅のはじまりは、海沿いの小さな駅から。改札を出ると、潮の香りがふわりと漂ってきます。さあ、山あいの古いお寺を目指して歩き出しましょう。",
};

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
export function usedWords(scripts: string[], limit = 15): string[] {
    const counts = new Map<string, number>();
    for (const script of scripts) for (const w of STOCK_WORDS) if (script.includes(w)) counts.set(w, (counts.get(w) ?? 0) + 1);
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

export function buildWaypointPrompt({ place, theme, userPrompt, facts, scriptType, isFirstWaypoint, hasPhotos, route }: WaypointPromptInput): string {
    const previous = route.previous ? tidyPlaceName(route.previous) : "";
    const next = route.next ? tidyPlaceName(route.next) : "";
    const isLast = route.index !== undefined && route.total !== undefined && route.total > 1 && route.index === route.total - 1;
    const routeLines = [previous && `前の立ち寄り場所: ${previous}`, next && `次の立ち寄り場所: ${next}`].filter(Boolean).join("\n");
    const from = previous ? `「${previous}」から` : "前の場所から";
    const other = route.otherScript?.trim() ?? "";
    const otherHeading = scriptType === "arriving" ? "到着後に読み上げるナレーション" : "直前に読み上げるナレーション";

    let task = "";
    let length = "";
    if (scriptType === "arriving") {
        length = "2〜3文、80〜130文字";
        if (isFirstWaypoint) {
            task = `旅のはじまりを告げるナレーションです。ここ「${place}」から出発します。これから始まる旅への期待感を伝え、${next ? `最後に次の場所「${next}」へ向かうことにふれてください。` : "旅立ちの気持ちを伝えてください。"}`;
        } else if (isLast) {
            task = `旅の最後の場所「${place}」に着くまでのナレーションです。${from}ここまでの道のりと、到着した気持ちを伝えてください。`;
        } else {
            task = `${from}移動して「${place}」に近づき、到着するまでのナレーションです。道中の景色や、着いたときの期待感に絞り、歴史や詳しい解説は次のナレーションに任せてください。`;
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
    const used = usedWords(route.otherStops ?? []);
    const usedRule = used.length
        ? `
5. 【ほかの場所で使った言葉】は使わず、この場所に合った別の言葉で表現すること。`
        : "";

    const persona = scriptType === "attraction" ? "あなたは、この土地をよく知る散策コースの案内人です。" : "あなたは旅行番組のプロのナレーターです。";
    const prompt = `${persona}${theme ? `この旅のテーマは「${theme}」です。` : ""}
${task}

【場所】${place}
${routeLines ? routeLines + "\n" : ""}${userPrompt ? `【ユーザーからの要望(最優先で反映する)】\n${userPrompt}\n` : ""}${facts ? `【参考にしてよい情報】\n${facts}\n` : ""}${other ? `【${otherHeading}(内容を重ねないこと)】\n${other}\n` : ""}${used.length ? `【ほかの場所で使った言葉】${used.join("、")}\n` : ""}
【内容のルール】
1. 上の情報、ユーザーの要望、添付された写真に書かれている・写っていることだけを根拠にすること。年代、数字、人名、名物、営業時間などを推測や想像で書き足さないこと。
2. ${scriptType === "attraction" ? `確かな情報が少ないときは、事実を作らず「${place}です。」だけにすること。写真が添付されているときだけ、実際に写っているものを一言添えてよい(「写真」という言葉は使わない)。` : "確かな情報が少ないときは、具体的な事実を無理に作らず、場所の雰囲気や歩いて感じることを、短く控えめに語ること。"}
3. 写真がある場合は、実際に写っている景色や特徴だけを自然に触れること。写っていないものや、写真から場所の名前を断定することはしないこと。
4. 前の場所・次の場所の名前は、上に書かれているものだけを使うこと。
5. ${noRepeat}${noRepeatOther}

【書き方のルール】
1. 日本語の「です・ます調」で、聞いて分かりやすい自然な話し言葉にすること。
2. 長さは${length}。1つの段落にまとめること。
3. 音声合成でそのまま読み上げるため、見出し、箇条書き、記号、絵文字、括弧書きの演出(例: [笑顔で])、URLは絶対に書かないこと。
4. 前置きや説明(「以下がナレーションです」など)、タイトル、話者名、引用符は付けず、ナレーションの本文だけを出力すること。${usedRule}

${scriptType === "arriving" ? `例(書き方の参考だけ。内容や言い回しは使わないこと):
${STYLE_EXAMPLES[isFirstWaypoint ? "start" : "arriving"]}` : `人が書いた別のコースの例(文の形の参考だけ。地名や事実は使わないこと):
${ATTRACTION_EXAMPLES.join("\n")}`}`;

    return prompt;
}

// "落ち着いた" (calm) is not an arrival.
const ARRIVAL = /到着|(?<!落ち)着(?:きました|いた)|やって[来き]ました/;
const sentencesOf = (text: string) => text.match(/[^。！？!?\n]+[。！？!?]*\s*/g) ?? [];
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
