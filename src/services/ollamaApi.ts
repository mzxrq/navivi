import { fetch } from '@tauri-apps/plugin-http';
import { readFile } from '@tauri-apps/plugin-fs';
import { invoke } from '@tauri-apps/api/core';
import { tidyPlaceName } from '../utils/gpxTrack';
import { buildWaypointPrompt, cleanNarration, RouteContext } from './narrationPrompt';
import { AiEngine, isOnlineEngine } from './ai/engine';
import { hasApiKey, streamOnline } from './ai/online';
import { shrinkForUpload, MAX_ONLINE_PHOTOS } from './ai/photos';
import { sniffImageMime } from './ai/providers';
import { splitThoughts } from './ai/thoughts';

const OLLAMA_URL = "http://127.0.0.1:11434";

// The http plugin sends the window's origin (http://tauri.localhost once installed), which Ollama answers with 403
// unless OLLAMA_ORIGINS lists it. An empty Origin makes the plugin leave the header out (needs its unsafe-headers feature).
const ollamaFetch = (url: string, init: RequestInit = {}) => {
    const headers = new Headers(init.headers);
    headers.set("Origin", "");
    return fetch(url, { ...init, headers });
};

// Models that answered 400 to a request with photos; they are not sent any again this session.
const textOnlyModels = new Set<string>();

// Keeps the model in memory between requests (Ollama's default unloads it after 5 minutes, and a big model takes a minute to load back).
const KEEP_ALIVE = "30m";

// A narration is 3-4 sentences; the cap stops a model that rambles from running for minutes on a CPU.
const SCRIPT_OPTIONS = { num_predict: 400, num_ctx: 4096 };

// Online reasoning models spend part of the cap on thinking, so it is far above the narration's real length.
const ONLINE_MAX_TOKENS = 2000;

function uint8ArrayToBase64(bytes: Uint8Array): string {
    const chunk = 0x8000;
    const c = [];
    for (let i = 0; i < bytes.length; i += chunk) {
        c.push(String.fromCharCode.apply(null, bytes.subarray(i, i + chunk) as any));
    }
    return btoa(c.join(""));
}


export function detectLanguage(...texts: (string | undefined)[]): "Japanese" | "English" {
    const combinedText = texts.filter(Boolean).join(" ");
    const jpRegex = /[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]/;
    return jpRegex.test(combinedText) ? "Japanese" : "English";
}

// Whether the engine can be used right now: an installed local model, or an online provider with a key saved.
export async function checkModelExists(targetModel: AiEngine = "schroneko/gemma-2-2b-jpn-it"): Promise<boolean> {
    if (isOnlineEngine(targetModel)) return hasApiKey(targetModel.provider);
    try {
        const res = await ollamaFetch(`${OLLAMA_URL}/api/tags`);
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
        const res = await ollamaFetch(`${OLLAMA_URL}/api/tags`);
        if (!res.ok) return [];
        const data = await res.json();
        return data.models.map((m: any) => m.name);
    } catch (error) {
        return [];
    }
}

// Disk size of each installed model in bytes; its weights take about as much memory when it runs.
export async function getModelSizes(): Promise<Record<string, number>> {
    try {
        const res = await ollamaFetch(`${OLLAMA_URL}/api/tags`);
        if (!res.ok) return {};
        const data = await res.json();
        return Object.fromEntries((data.models ?? []).map((m: any) => [m.name, Number(m.size) || 0]));
    } catch {
        return {};
    }
}

const warmed = new Set<string>();

// Loads the model into memory while the user is still typing, so the first script does not also pay the load (a minute for a big one).
// Quiet if Ollama is not running; once per model per session.
export function warmUpModel(model: AiEngine): void {
    if (isOnlineEngine(model) || !model || warmed.has(model)) return;
    warmed.add(model);
    ollamaFetch(`${OLLAMA_URL}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // Ollama reloads a model whose context differs from the request's, so warm it with the one scripts use.
        body: JSON.stringify({ model, keep_alive: KEEP_ALIVE, options: { num_ctx: SCRIPT_OPTIONS.num_ctx } }),
    }).catch(() => warmed.delete(model));
}

// Whether the model can read photos, from the capabilities Ollama reports; null when it can't tell (older Ollama, not running).
export async function modelSeesPhotos(model: string): Promise<boolean | null> {
    if (textOnlyModels.has(model)) return false;
    try {
        const res = await ollamaFetch(`${OLLAMA_URL}/api/show`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model }),
        });
        if (!res.ok) return null;
        const data = await res.json();
        return Array.isArray(data.capabilities) ? data.capabilities.includes("vision") : null;
    } catch {
        return null;
    }
}

async function ollamaAnswers(): Promise<boolean> {
    try {
        return (await ollamaFetch(`${OLLAMA_URL}/api/tags`)).ok;
    } catch {
        return false;
    }
}

// Starts the local Ollama server if nothing answers yet and waits for it; throws a readable error if it can't.
export async function ensureOllamaRunning(timeoutMs = 20000): Promise<void> {
    if (await ollamaAnswers()) return;
    try {
        await invoke("wake_up_ollama");
    } catch (e) {
        throw new Error(String(e));
    }
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        if (await ollamaAnswers()) return;
        await new Promise((r) => setTimeout(r, 500));
    }
    throw new Error("Ollama did not start in time");
}

export async function pullModelStream(
    model: string,
    onProgress: (status: string, completed?: number, total?: number) => void,
    signal?: AbortSignal
): Promise<void> {
    onProgress("Starting Ollama...");
    await ensureOllamaRunning();
    const res = await ollamaFetch(`${OLLAMA_URL}/api/pull`, {
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
        if (done) {
            
            break;
        }

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

// Ollama's own explanation of a failed request ("" when it sent none).
async function errorText(res: Response): Promise<string> {
    try {
        const text = await res.text();
        try {
            return JSON.parse(text)?.error ?? text;
        } catch {
            return text;
        }
    } catch {
        return "";
    }
}

// ✨ NEW: Unified Streaming Engine
// An online model writes the same script; a thinking model's reasoning is split off here as it is for Ollama.
async function streamOnlineLLM(prompt: string, engine: Extract<AiEngine, object>, onChunk: (text: string) => void, signal?: AbortSignal, images?: string[], onThought?: (text: string) => void, options?: Record<string, number>) {
    const photos = (images ?? []).map((base64) => ({ mime: sniffImageMime(base64), base64 }));
    await streamOnline(
        engine,
        { prompt, photos, maxTokens: ONLINE_MAX_TOKENS, temperature: options?.temperature },
        (full) => {
            const { text, thoughts } = splitThoughts(full);
            onChunk(text);
            if (onThought && thoughts) onThought(thoughts);
        },
        signal,
    );
}

async function streamLLM(prompt: string, engine: AiEngine, onChunk: (text: string) => void, signal?: AbortSignal, images?: string[], onThought?: (text: string) => void, options?: Record<string, number>) {
    if (isOnlineEngine(engine)) return streamOnlineLLM(prompt, engine, onChunk, signal, images, onThought, options);
    // Narration is short and fact-bound; a thinking model otherwise spends minutes on a CPU recounting characters before the first word.
    const payload: any = { model: engine, prompt, stream: true, think: false, keep_alive: KEEP_ALIVE };
    if (options) payload.options = options;
    if (images && images.length > 0 && !textOnlyModels.has(engine)) {
        payload.images = images;
    }

    const send = () => ollamaFetch(`${OLLAMA_URL}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal,
    });

    let res = await send();
    // A model without vision rejects photos; the script is still worth writing from the text alone.
    if (res.status === 400 && payload.images) {
        const reason = await errorText(res);
        console.warn(`${engine} rejected the photos (${reason || "no reason given"}); retrying without them.`);
        if (/image|vision|multimodal/i.test(reason)) textOnlyModels.add(engine);
        delete payload.images;
        res = await send();
    }

    if (!res.ok || !res.body) {
        const detail = await errorText(res);
        throw new Error(`HTTP Error: ${res.status}${detail ? `: ${detail}` : ""}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let fullText = "";
    let buffer = "";
    let consoleBuffer = "";
    while (true) {
        const { done, value } = await reader.read();
        if (done) {
            if (consoleBuffer) console.log("%c[Ollama Stream] %c" + consoleBuffer, "color: #a855f7; font-weight: bold;", "color: inherit;");
            break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
            if (line.trim() !== "") {
                try {
                    const parsed = JSON.parse(line);
                    if (parsed.response) {
                        fullText += parsed.response;
                        
                        consoleBuffer += parsed.response;
                        if (consoleBuffer.includes("\n")) {
                            const consoleLines = consoleBuffer.split("\n");
                            for (let i = 0; i < consoleLines.length - 1; i++) {
                                console.log("%c[Ollama Stream] %c" + consoleLines[i], "color: #a855f7; font-weight: bold;", "color: inherit;");
                            }
                            consoleBuffer = consoleLines[consoleLines.length - 1];
                        }
                        
                        const { text, thoughts } = splitThoughts(fullText);
                        onChunk(text);
                        if (onThought && thoughts) onThought(thoughts);
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
    engine: AiEngine = "schroneko/gemma-2-2b-jpn-it",
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

    await streamLLM(prompt, engine, onChunk, signal, undefined, undefined, SCRIPT_OPTIONS);
}

// ✨ Stream Waypoint Script
export async function generateWaypointScriptStream(
    locationName: string,
    userPrompt: string,
    engine: AiEngine = "schroneko/gemma-2-2b-jpn-it",
    theme: string = "",
    onChunk: (text: string) => void,
    lat: number = 0,
    lng: number = 0,
    imagePaths: string[] = [],
    onThought?: (text: string) => void,
    scriptType: "arriving" | "attraction" = "attraction",
    isFirstWaypoint: boolean = false,
    signal?: AbortSignal,
    route: RouteContext = {}
): Promise<void> {
    const place = tidyPlaceName(locationName) || locationName;
    let facts = "";

    if (lat !== 0 && lng !== 0) {
        const { geo, searchTerms } = await fetchLocationContext(lat, lng);
        const webContext = await fetchKeylessWebContext(searchTerms);
        facts = [geo && `地理情報: ${geo}`, webContext && `参考情報: ${webContext}`].filter(Boolean).join("\n");
    }

    const prompt = buildWaypointPrompt({ place, theme, userPrompt, facts, scriptType, isFirstWaypoint, route });

    const online = isOnlineEngine(engine);
    const base64Images: string[] = [];
    for (const p of online && !engine.sendPhotos ? [] : imagePaths.slice(0, online ? MAX_ONLINE_PHOTOS : undefined)) {
        try {
            const bytes = await readFile(p);
            const encoded = online ? await shrinkForUpload(bytes) : uint8ArrayToBase64(bytes);
            if (encoded) base64Images.push(encoded);
        } catch (e) {
            console.warn("Failed to load image for vision context", e);
        }
    }

    // Lower temperature keeps a small model close to the facts it was given.
    await streamLLM(
        prompt,
        engine,
        (text) => onChunk(cleanNarration(text)),
        signal,
        base64Images,
        onThought,
        { ...SCRIPT_OPTIONS, temperature: 0.4, top_p: 0.9, repeat_penalty: 1.1 },
    );
}

export async function extractLocationsFromDocument(
    text: string,
    engine: AiEngine = "schroneko/gemma-2-2b-jpn-it"
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
    engine: AiEngine = "schroneko/gemma-2-2b-jpn-it",
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