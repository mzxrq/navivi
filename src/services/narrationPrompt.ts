import { tidyPlaceName } from "../utils/gpxTrack";

// Where a stop sits in the route, so "arriving" talks about the real previous stop and nothing repeats.
export interface RouteContext {
    previous?: string;
    next?: string;
    index?: number;
    total?: number;
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

const NARRATION_STYLE_EXAMPLE = `例(書き方の参考だけ。内容や言い回しは使わないこと):
湖のほとりの小さな駅に着きました。ホームに降りると、ひんやりとした風が頬をなでていきます。ここから歩いて十分ほどで、湖畔の遊歩道に出られます。`;

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

    let task = "";
    let length = "";
    if (scriptType === "arriving") {
        length = "2〜3文、80〜130文字";
        if (isFirstWaypoint) {
            task = `旅の出発地点「${place}」からのナレーションです。これから始まる旅への期待感を伝え、${next ? `最後に次の場所「${next}」へ向かうことにふれてください。` : "旅立ちの気持ちを伝えてください。"}`;
        } else if (isLast) {
            task = `旅の最後の場所「${place}」に着くまでのナレーションです。${from}ここまでの道のりと、到着した気持ちを伝えてください。`;
        } else {
            task = `${from}移動して「${place}」に近づき、到着するまでのナレーションです。道中の景色や、着いたときの期待感に絞り、歴史や詳しい解説は次のナレーションに任せてください。`;
        }
    } else {
        length = "3〜5文、120〜200文字";
        task = `「${place}」に到着したあとの、見どころ解説ナレーションです。この場所ならではの特徴や魅力を、与えられた情報をもとに具体的に紹介してください。`;
    }

    const noRepeat =
        scriptType === "arriving"
            ? "「みなさん、こんにちは」のような歓迎の挨拶は入れないこと(旅の冒頭で済んでいます)。"
            : "「到着しました」など、直前のナレーションと同じ内容を繰り返さないこと。";

    const prompt = `あなたは旅行番組のプロのナレーターです。${theme ? `この旅のテーマは「${theme}」です。` : ""}
${task}

【場所】${place}
${routeLines ? routeLines + "\n" : ""}${userPrompt ? `【ユーザーからの要望(最優先で反映する)】\n${userPrompt}\n` : ""}${facts ? `【参考にしてよい情報】\n${facts}\n` : ""}
【内容のルール】
1. 上の情報、ユーザーの要望、添付された写真に書かれている・写っていることだけを根拠にすること。年代、数字、人名、名物、営業時間などを推測や想像で書き足さないこと。
2. 確かな情報が少ないときは、具体的な事実を無理に作らず、場所の雰囲気や歩いて感じることを、短く控えめに語ること。
3. 写真がある場合は、実際に写っている景色や特徴だけを自然に触れること。写っていないものや、写真から場所の名前を断定することはしないこと。
4. 前の場所・次の場所の名前は、上に書かれているものだけを使うこと。
5. ${noRepeat}

【書き方のルール】
1. 日本語の「です・ます調」で、聞いて分かりやすい自然な話し言葉にすること。
2. 長さは${length}。1つの段落にまとめること。
3. 音声合成でそのまま読み上げるため、見出し、箇条書き、記号、絵文字、括弧書きの演出(例: [笑顔で])、URLは絶対に書かないこと。
4. 前置きや説明(「以下がナレーションです」など)、タイトル、話者名、引用符は付けず、ナレーションの本文だけを出力すること。

${NARRATION_STYLE_EXAMPLE}`;

    return prompt;
}
