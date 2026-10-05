import { t } from "@lingui/core/macro";
import type { TextStyle } from "../../types";
import { textStyleToCss, wrapText } from "../../utils/textStyle";

const ALIGN = { bottom: "items-end", middle: "items-center", top: "items-start" } as const;

// A 16:9 frame with a sample caption, drawn like the video preview and the export draw it (1080 px = the frame's height).
export function CaptionPreview({ style }: { style: Required<TextStyle> }) {
  const edge = `${(style.margin_v / 1080) * 100}cqh`;
  const sample = t`The first sunlight reaches the harbour, and the town slowly wakes up.`;
  return (
    <div
      aria-hidden
      className="relative aspect-video w-full overflow-hidden rounded-xl ring-1 ring-black/10 dark:ring-white/10"
      style={{ backgroundImage: "linear-gradient(160deg, #1b3d8c 0%, #4b3f8f 45%, #c76a58 100%)" }}
    >
      <div
        className={`absolute inset-0 flex ${ALIGN[style.position]} justify-center px-6`}
        style={{
          containerType: "size",
          paddingBottom: style.position === "bottom" ? edge : undefined,
          paddingTop: style.position === "top" ? edge : undefined,
        }}
      >
        <span style={textStyleToCss(style)} className="max-w-[85%] rounded-md leading-snug text-center whitespace-pre-line">
          {wrapText(sample, style.max_chars_per_line)}
        </span>
      </div>
    </div>
  );
}
