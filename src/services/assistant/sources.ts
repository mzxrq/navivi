import { readTextFile } from "@tauri-apps/plugin-fs";
import { fetch } from "@tauri-apps/plugin-http";
import { callSidecar } from "../sidecar";

// Text for the assistant from something the user attached: a file on this PC or a web page.
// PDF and Word are read by the sidecar (main.py read_document); plain text and web pages are read here.

export const SOURCE_EXTENSIONS = ["txt", "md", "markdown", "csv", "pdf", "docx"] as const;

const TEXT_EXTENSIONS = new Set(["txt", "md", "markdown", "csv"]);
const MAX_CHARS = 60_000;

const extensionOf = (path: string) => path.split(/[\\/]/).pop()?.split(".").pop()?.toLowerCase() ?? "";

export const isSupportedDocument = (path: string) =>
  path.includes(".") && (SOURCE_EXTENSIONS as readonly string[]).includes(extensionOf(path));

export const isWebAddress = (input: string) => /^https?:\/\/\S+$/i.test(input.trim());

export interface SourceText {
  name: string;
  text: string;
  truncated: boolean;
}

const collapse = (s: string) =>
  s
    .replace(/ /g, " ")
    .replace(/[ \t]+/g, " ")
    .replace(/ ?\n ?/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

// The readable text of a page: scripts, styles and navigation dropped, the article or main part preferred.
export function htmlToText(html: string): { title: string; text: string } {
  const doc = new DOMParser().parseFromString(html, "text/html");
  doc.querySelectorAll("script, style, noscript, template, svg, iframe, nav, header, footer, aside, form, [hidden]").forEach((el) => el.remove());
  const root = doc.querySelector("article") ?? doc.querySelector("main") ?? doc.body;
  root?.querySelectorAll("br").forEach((br) => br.replaceWith("\n"));
  root?.querySelectorAll("p, div, section, li, tr, h1, h2, h3, h4, h5, h6, blockquote, pre").forEach((el) => el.append("\n"));
  return { title: collapse(doc.title ?? ""), text: collapse(root?.textContent ?? "") };
}

const cut = (name: string, text: string, alreadyCut = false): SourceText => ({
  name,
  text: text.slice(0, MAX_CHARS),
  truncated: alreadyCut || text.length > MAX_CHARS,
});

async function readWebPage(url: string): Promise<SourceText> {
  let res: Response;
  try {
    res = await fetch(url, { headers: { Accept: "text/html,text/plain" } });
  } catch {
    throw new Error("Could not reach that web page. Check the address and your connection.");
  }
  if (!res.ok) throw new Error(`That web page answered with an error (HTTP ${res.status}).`);
  const body = await res.text();
  const type = res.headers.get("content-type") ?? "";
  const { title, text } = /html/i.test(type) || /^\s*</.test(body) ? htmlToText(body) : { title: "", text: collapse(body) };
  if (text.length < 80) throw new Error("That page has no readable text. Some sites load their text with scripts; copy it into the chat instead.");
  return cut(title || new URL(url).hostname, text);
}

// `input` is a file path or an http(s) address. Throws an Error whose message can be shown to the user.
export async function readSource(input: string, signal?: AbortSignal): Promise<SourceText> {
  const source = input.trim();
  if (isWebAddress(source)) return readWebPage(source);

  const name = source.split(/[\\/]/).pop() || source;
  const extension = extensionOf(source);
  if (!isSupportedDocument(source)) throw new Error(`${name} is not a supported file. Use PDF, Word (.docx), text or Markdown.`);

  if (TEXT_EXTENSIONS.has(extension)) {
    let text: string;
    try {
      text = await readTextFile(source);
    } catch {
      throw new Error(`Could not read ${name}.`);
    }
    return cut(name, collapse(text));
  }

  // Rust runs one sidecar process at a time and kills it for the next call, so another screen's startup calls can cancel
  // this read; reading a file is safe to repeat, until the user presses Stop.
  const read = () => callSidecar<{ text: string; truncated: boolean }>("read_document", source);
  let reply = await read();
  for (let attempt = 0; attempt < 4 && !reply.success && reply.cancelled && !signal?.aborted; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 600));
    if (signal?.aborted) break;
    reply = await read();
  }
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
  if (!reply.success) throw new Error(reply.cancelled ? `Reading ${name} was interrupted. Try attaching it again.` : reply.error);
  return cut(name, reply.text, reply.truncated);
}
