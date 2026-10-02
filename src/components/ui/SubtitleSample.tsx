import { t } from "@lingui/core/macro";
import { assToCss } from "../../utils/assColor";

interface SubtitleSampleProps {
  font: string;
  size: number;
  color: string;
  outlineColor: string;
  bold?: boolean;
}

// The burned-in subtitles are drawn by libass, which sizes everything against a 288-line frame (measured: size 30 on a 1080p
// frame gives capitals about 74 px tall). Container-query units keep that ratio at whatever width the sample is shown.
const LIBASS_LINES = 288;
const OUTLINE = 2;
const MARGIN_V = 10;
const cq = (lines: number) => `${(lines / LIBASS_LINES) * 100}cqh`;

export function SubtitleSample({ font, size, color, outlineColor, bold }: SubtitleSampleProps) {
  return (
    <div
      className="relative aspect-video w-full max-w-sm overflow-hidden rounded-lg ring-1 ring-black/10 dark:ring-white/10 bg-linear-to-r from-zinc-100 to-zinc-800"
      style={{ containerType: "size" }}
    >
      <p
        className="absolute inset-x-0 text-center leading-tight px-[4cqw]"
        style={{
          bottom: cq(MARGIN_V),
          fontFamily: `"${font}", sans-serif`,
          fontSize: cq(size),
          fontWeight: bold ? 700 : 400,
          color: assToCss(color, [255, 255, 255]),
          WebkitTextStroke: `${cq(OUTLINE * 2)} ${assToCss(outlineColor, [0, 0, 0])}`,
          paintOrder: "stroke fill",
        }}
      >
        {t`How your subtitles will look`}
      </p>
    </div>
  );
}
