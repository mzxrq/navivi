import { describe, expect, it } from "vitest";
import { authUrl, base64Url, challengeFor, newVerifier } from "./openrouterAuth";

describe("PKCE helpers", () => {
  it("matches the RFC 7636 example", async () => {
    expect(await challengeFor("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
  });

  it("makes URL-safe verifiers of a valid length", () => {
    const v = newVerifier();
    expect(v).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(newVerifier()).not.toBe(v);
    expect(base64Url(new Uint8Array([251, 255, 254]))).toBe("-__-");
  });

  it("points the callback at the local port", () => {
    const url = new URL(authUrl(51423, "abc"));
    expect(url.origin + url.pathname).toBe("https://openrouter.ai/auth");
    expect(url.searchParams.get("callback_url")).toBe("http://localhost:51423/callback");
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
  });
});
