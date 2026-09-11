import { fetch } from '@tauri-apps/plugin-http';

const IRODORI_URL = "http://127.0.0.1:5000";

/**
 * Calls a local Irodori TTS endpoint to synthesize audio from text.
 * Assumes the endpoint returns an array buffer (e.g. WAV or MP3 data).
 */
export async function synthesizeAudio(text: string): Promise<{ buffer: ArrayBuffer, contentType: string }> {
    const res = await fetch(`${IRODORI_URL}/synthesize`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ text })
    });

    if (!res.ok) {
        throw new Error(`Irodori API failed with status ${res.status}`);
    }

    return {
        buffer: await res.arrayBuffer(),
        contentType: res.headers.get("Content-Type") || "audio/wav"
    };
}

