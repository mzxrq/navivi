import { invoke } from "@tauri-apps/api/core";
import { fetch } from "@tauri-apps/plugin-http";

// OpenRouter is the one provider that lets an app obtain a user's API key by sign-in (OAuth PKCE). Anthropic, OpenAI and
// Google only issue keys from their own consoles, so those stay paste-a-key.
const AUTH_PAGE = "https://openrouter.ai/auth";
const KEY_EXCHANGE = "https://openrouter.ai/api/v1/auth/keys";
const WAIT_SECONDS = 300;

export const base64Url = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

export const newVerifier = () => base64Url(crypto.getRandomValues(new Uint8Array(32)));

export async function challengeFor(verifier: string): Promise<string> {
  return base64Url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
}

export function authUrl(port: number, challenge: string): string {
  const callback = `http://localhost:${port}/callback`;
  return `${AUTH_PAGE}?callback_url=${encodeURIComponent(callback)}&code_challenge=${challenge}&code_challenge_method=S256`;
}

// Opens the browser, waits for the redirect on a local port, and trades the code for the user's own key.
export async function signInWithOpenRouter(): Promise<string> {
  const verifier = newVerifier();
  const port = await invoke<number>("oauth_listen_start");
  await invoke("plugin:opener|open_url", { url: authUrl(port, await challengeFor(verifier)) });
  const code = await invoke<string>("oauth_listen_wait", { timeoutSecs: WAIT_SECONDS });

  const res = await fetch(KEY_EXCHANGE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, code_verifier: verifier, code_challenge_method: "S256" }),
  });
  if (!res.ok) throw new Error(`OpenRouter did not give a key (HTTP ${res.status}).`);
  const key = (await res.json())?.key;
  if (typeof key !== "string" || !key) throw new Error("OpenRouter's answer had no key.");
  return key;
}
