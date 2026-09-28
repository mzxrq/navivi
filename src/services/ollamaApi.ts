import { fetch } from '@tauri-apps/plugin-http';

const OLLAMA_URL = "http://127.0.0.1:11434";

export function detectLanguage(...texts: (string | undefined)[]): "Japanese" | "English" {
    const combinedText = texts.filter(Boolean).join(" ");
    const jpRegex = /[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]/;
    return jpRegex.test(combinedText) ? "Japanese" : "English";
}

export async function checkModelExists(targetModel: string = "schroneko/gemma-2-2b-jpn-it"): Promise<boolean> {
    try {
        const res = await fetch(`${OLLAMA_URL}/api/tags`);
        if (!res.ok) {
            console.error(`Ollama /api/tags answered HTTP ${res.status}`);
            return false;
        }
        const data = await res.json();
        // Ollama lists a model as "<name>:<tag>" (e.g. ":latest"); accept either form.
        const wanted = targetModel.replace(/:latest$/, "");
        return (data.models ?? []).some((m: any) =>
            [m.name, m.model].some((n) => typeof n === "string" && n.replace(/:latest$/, "").includes(wanted)),
        );
    } catch (error) {
        // Not "model missing": Ollama itself could not be reached.
        console.error("Could not reach Ollama at " + OLLAMA_URL, error);
        return false;
    }
}

export async function getLocalModels(): Promise<string[]> {
    try {
        const res = await fetch(`${OLLAMA_URL}/api/tags`);
        if (!res.ok) return [];
        const data = await res.json();
        return data.models.map((m: any) => m.name);
    } catch (error) {
        return [];
    }
}

export async function pullModelStream(
    model: string,
    onProgress: (status: string, completed?: number, total?: number) => void,
    signal?: AbortSignal
): Promise<void> {
    const res = await fetch(`${OLLAMA_URL}/api/pull`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: model, stream: true }),
        signal,
    });

    if (!res.ok || !res.body) throw new Error(`HTTP Error: ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
            if (line.trim() !== "") {
                try {
                    const parsed = JSON.parse(line);
                    if (parsed.status) {
                        onProgress(parsed.status, parsed.completed, parsed.total);
                    }
                } catch (e) {
                    console.warn("Failed to parse JSON chunk in pullModelStream:", line);
                }
            }
        }
    }
}

async function fetchLocationContext(lat: number, lng: number): Promise<{ geo: string; searchTerms: string; }> {
    try {
        const res = await fetch(
            `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}&zoom=18&addressdetails=1`,
            { headers: { "User-Agent": "NaviviApp/1.0" } },
        );
        if (!res.ok) return { geo: "", searchTerms: "" };

        const data = await res.json();
        const landmark = data.name || data.address?.tourism || data.address?.historic || "";
        const city = data.address?.city || data.address.town || "";

        return {
            geo: `Geographic Context: ${lat}, ${lng}. Landmark: ${landmark}. City: ${city}.`,
            searchTerms: `${landmark} ${city}`.trim()
        };
    } catch {
        return { geo: "", searchTerms: "" };
    }
}

async function fetchKeylessWebContext(searchTerms: string): Promise<string> {
    if (!searchTerms) return "";
    try {
        const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(searchTerms + " explain")}`;
        const res = await fetch(url, { method: "GET" });
        const html = await res.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "text/html");

        const snippets = Array.from(doc.querySelectorAll('.result__snippet')).slice(0, 3).map(el => el.textContent?.trim() || "").filter(text => text.length > 0);

        return snippets.length > 0 ? `Web context: ${snippets.join(" ")}` : "";
    } catch (error) {
        return "";
    }
}

// ✨ NEW: Unified Streaming Engine
async function streamLLM(prompt: string, engine: string, onChunk: (text: string) => void, signal?: AbortSignal) {
    const res = await fetch(`${OLLAMA_URL}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: engine, prompt, stream: true }),
        signal,
    });

    if (!res.ok || !res.body) throw new Error(`HTTP Error: ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let fullText = "";
    let buffer = "";
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
            if (line.trim() !== "") {
                try {
                    const parsed = JSON.parse(line);
                    if (parsed.response) {
                        fullText += parsed.response;
                        onChunk(fullText);
                    }
                } catch (e) {
                    console.warn("Failed to parse JSON chunk in streamLLM:", line);
                }
            }
        }
    }
}

// ✨ Stream Overview Script
export async function generateOverviewScriptStream(
    waypoints: string[],
    engine: string = "schroneko/gemma-2-2b-jpn-it",
    theme: string = "",
    onChunk: (text: string) => void,
    signal?: AbortSignal
): Promise<void> {
    const routeNames = waypoints.join("、");
    const themeContext = theme ? `このコースの全体テーマは「${theme}」です。` : "";

    const prompt = `あなたは旅行番組のプロのナレーターです。
${themeContext}
以下の立ち寄り場所を巡る旅のオープニングナレーションを、視聴者を惹きつけるように3〜4文で作成してください。
立ち寄り場所: ${routeNames}

ルール:
1. 日本語の「です・ます調」で、自然な話し言葉にすること。
2. 音声合成で読み上げるため、効果音や映像の指示（例：[波の音]、[カメラがズーム]など）は絶対に書かないこと。
3. 歓迎の挨拶から始めること。`;

    await streamLLM(prompt, engine, onChunk, signal);
}

// ✨ Stream Waypoint Script
export async function generateWaypointScriptStream(
    locationName: string,
    userPrompt: string,
    engine: string = "schroneko/gemma-2-2b-jpn-it",
    theme: string = "",
    onChunk: (text: string) => void,
    lat: number = 0,
    lng: number = 0,
): Promise<void> {
    let contextStr = "";

    if (lat !== 0 && lng !== 0) {
        const { geo, searchTerms } = await fetchLocationContext(lat, lng);
        const webContext = await fetchKeylessWebContext(searchTerms);
        contextStr = `地理情報: ${geo}\n参考情報: ${webContext}`;
    }

    const themeContext = theme ? `この旅のテーマは「${theme}」です。` : "";

    const prompt = `あなたは旅行番組のプロのナレーターです。
${themeContext}
現在地「${locationName}」に到着した際、または紹介する際のナレーションを2〜3文で作成してください。

コンテキスト・要望: ${userPrompt}
${contextStr}

ルール:
1. 日本語の「です・ます調」で、親しみやすい言葉遣いにすること。
2. 音声合成で読み上げるため、括弧書きの指示（例：[笑顔で]など）は絶対に書かないこと。
3. 簡潔に、その場所の魅力や歴史が伝わるようにすること。`;

    await streamLLM(prompt, engine, onChunk);
}

export async function extractLocationsFromDocument(
    text: string,
    engine: string = "schroneko/gemma-2-2b-jpn-it"
): Promise<string[]> {
    const prompt = `Extract a list of geographic locations mentioned in the following text, in chronological order. Return ONLY a JSON array of strings, e.g. ["Paris", "London"]. No other text. Text: ${text}`;
    
    let result = "";
    try {
        await streamLLM(prompt, engine, (chunk) => {
            result = chunk;
        });
        const match = result.match(/\[.*\]/s);
        if (match) return JSON.parse(match[0]);
        return JSON.parse(result);
    } catch (e) {
        console.warn("Failed to extract locations", e);
        return [];
    }
}

// ✨ Stream Video Prompt for Wan 2.1
export async function generateVideoPromptStream(
    locationName: string,
    narrationText: string,
    engine: string = "schroneko/gemma-2-2b-jpn-it",
    onChunk: (text: string) => void
): Promise<void> {
    const prompt = `You are an expert video prompt engineer for Wan 2.1 (a high-quality video generation AI).
Translate and expand the following Japanese narration and location into a highly descriptive, cinematic English visual prompt.
Focus on visuals, lighting, camera angles, and atmosphere. Do NOT include any text, dialogue, or audio descriptions.

Location: ${locationName}
Narration: ${narrationText}

English Visual Prompt:`;

    await streamLLM(prompt, engine, onChunk);
}