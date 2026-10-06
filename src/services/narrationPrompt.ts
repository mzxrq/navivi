import { tidyPlaceName } from "../utils/gpxTrack";

// Where a stop sits in the route, so "arriving" talks about the real previous stop and nothing repeats.
export interface RouteContext {
    previous?: string;
    next?: string;
    index?: number;
    total?: number;
    // The stop's other script (arriving <-> attraction), so the two don't say the same things.
    otherScript?: string;
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
    attraction: "境内に入ると、大きな杉の木が静かに迎えてくれます。苔むした石段の先には、落ち着いた佇まいの本堂が見えてきます。耳を澄ませると、鳥のさえずりと風の音だけが聞こえてきます。",
};

export interface WaypointPromptInput {
    place: string;
    theme: string;
    userPrompt: string;
    facts: string;
    scriptType: "arriving" | "attraction";
    isFirstWaypoint: boolean;
    route: RouteContext;
}

export function buildWaypointPrompt({ place, theme, userPrompt, facts, scriptType, isFirstWaypoint, route }: WaypointPromptInput): string {
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
        length = "3〜5文、120〜200文字";
        task = `「${place}」の見どころ解説ナレーションです。最初の文から、この場所ならではの特徴(建物、景色、雰囲気など)を語り始め、その魅力を与えられた情報をもとに具体的に紹介してください。`;
    }

    const noRepeat =
        scriptType === "arriving"
            ? "「みなさん、こんにちは」のような歓迎の挨拶は入れないこと(旅の冒頭で済んでいます)。"
            : "移動のことは直前のナレーションで済んでいるので、この場所そのものの話だけをすること。";
    const noRepeatOther = other
        ? `
6. 【${otherHeading}】と同じ事実、言い回し、文の始め方を使わないこと。同じ場所の別の面を語ること。`
        : "";

    const prompt = `あなたは旅行番組のプロのナレーターです。${theme ? `この旅のテーマは「${theme}」です。` : ""}
${task}

【場所】${place}
${routeLines ? routeLines + "\n" : ""}${userPrompt ? `【ユーザーからの要望(最優先で反映する)】\n${userPrompt}\n` : ""}${facts ? `【参考にしてよい情報】\n${facts}\n` : ""}${other ? `【${otherHeading}(内容を重ねないこと)】\n${other}\n` : ""}
【内容のルール】
1. 上の情報、ユーザーの要望、添付された写真に書かれている・写っていることだけを根拠にすること。年代、数字、人名、名物、営業時間などを推測や想像で書き足さないこと。
2. 確かな情報が少ないときは、具体的な事実を無理に作らず、場所の雰囲気や歩いて感じることを、短く控えめに語ること。
3. 写真がある場合は、実際に写っている景色や特徴だけを自然に触れること。写っていないものや、写真から場所の名前を断定することはしないこと。
4. 前の場所・次の場所の名前は、上に書かれているものだけを使うこと。
5. ${noRepeat}${noRepeatOther}

【書き方のルール】
1. 日本語の「です・ます調」で、聞いて分かりやすい自然な話し言葉にすること。
2. 長さは${length}。1つの段落にまとめること。
3. 音声合成でそのまま読み上げるため、見出し、箇条書き、記号、絵文字、括弧書きの演出(例: [笑顔で])、URLは絶対に書かないこと。
4. 前置きや説明(「以下がナレーションです」など)、タイトル、話者名、引用符は付けず、ナレーションの本文だけを出力すること。

例(書き方の参考だけ。内容や言い回しは使わないこと):
${STYLE_EXAMPLES[scriptType === "arriving" ? (isFirstWaypoint ? "start" : "arriving") : "attraction"]}`;

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
