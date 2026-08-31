import { fetch } from '@tauri-apps/plugin-http';

const OLLAMA_URL = "http://127.0.0.1:11434";

export function detectLanguage(...texts: (string | undefined)[]): "Japanese" | "English" {
    const combinedText = texts.filter(Boolean).join(" ");
    const jpRegex = /[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]/;
    return jpRegex.test(combinedText) ? "Japanese" : "English";
}

export async function checkModelExists(targetModel: string = "gemma2"): Promise<boolean> {
    try {
        const res = await fetch(`${OLLAMA_URL}/api/tags`);
        if (!res.ok) return false;
        const data = await res.json();
        return data.models.some((m: any) => m.name.includes(targetModel));
    } catch (error) {
        return false;
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
        const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(searchTerms + "explain")}`;
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

export async function generateOverviewScript(
    waypoints: string[],
    engine: string = "gemma2",
): Promise<string> {
    const detectedLang = detectLanguage(...waypoints);
    const routeNames = waypoints.join(", then ");
    const prompt = `You are a travel narrator. Write a short, exciting opening hook around 3-4 sentences summarizing a journey that stops at: ${routeNames}. Write the response in fluent ${detectedLang}. Do not include any sound effects narration.`;

    const res = await fetch(`${OLLAMA_URL}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: engine, prompt, stream: true }),
    });
    if (!res.ok) throw new Error(`HTTP Error: ${res.status}`);
    const data = await res.json();
    return data.response.trim();
}

export async function generateWaypointScriptStream(
    locationName: string,
    userPrompt: string,
    engine: string = "gemma2",
    onChunk: (text: string) => void,
    lat: number = 0,
    lng: number = 0,
): Promise<void> {
    const detectedLang = detectLanguage(locationName, userPrompt);
    const { geo, searchTerms } = await fetchLocationContext(lat, lng);
    const webContext = await fetchKeylessWebContext(searchTerms);

    const prompt = `You are an enthusiastic travel guide. Write a brief, 2-sentence narration for our arrival at ${locationName}. ${geo}
    ${webContext}
    Incorporate this specific context: ${userPrompt}.
    Keep it engaging, natural, and formatted as plain text meant to be spoken out loud. CRITICAL: Write the response in fluent ${detectedLang}. Do not include any sound effects narration.`;

    const res = await fetch(`${OLLAMA_URL}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: engine, prompt, stream: true }),
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
                const parsed = JSON.parse(line);
                if (parsed.response) {
                    fullText += parsed.response;
                    onChunk(fullText);
                }
            }
        }
    }
}
