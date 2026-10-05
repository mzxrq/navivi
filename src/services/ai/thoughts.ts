// Some models write their reasoning inline between markers; the script is what is left once those blocks are removed.
const THOUGHT_BLOCKS = /(?:<think>|<\|channel>thought|<thought>)([\s\S]*?)(?:<\/think>|<\/thought>|<channel\|>|$)/g;

export function splitThoughts(full: string): { text: string; thoughts: string } {
  const thoughts = [...full.matchAll(THOUGHT_BLOCKS)].map((m) => m[1]).join("\n");
  const text = full
    .replace(/<think>[\s\S]*?(<\/think>|$)/g, "")
    .replace(/<\|channel>thought[\s\S]*?(<channel\|>|$)/g, "")
    .replace(/<\|think\|>[\s\S]*?(<turn\|>|$)/g, "")
    .replace(/<thought>[\s\S]*?(<\/thought>|$)/g, "");
  return { text, thoughts };
}
