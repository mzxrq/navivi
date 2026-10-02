import { assToCss } from "../../utils/assColor";
import { CAPTION } from "../../utils/subtitleLook";

interface CaptionProps {
  text: string;
  font?: string;
  size?: number;
  color?: string;
  boxColor?: string;
  bold?: boolean;
}

// Container-query units keep libass's proportions (everything is a share of a 288-line frame) at any size, so the parent must be
// a size container (`containerType: "size"`) with the frame's aspect ratio.
const cq = (lines: number) => `${(lines / CAPTION.lines) * 100}cqh`;

export function Caption({ text, font, size, color, boxColor, bold }: CaptionProps) {
  return (
    <div className="absolute inset-x-0 flex justify-center pointer-events-none" style={{ bottom: cq(CAPTION.marginV) }}>
      <span
        className="block text-center whitespace-pre-line"
        style={{
          maxWidth: `${CAPTION.maxWidth * 100}%`,
          padding: cq(CAPTION.padding),
          fontFamily: `"${font || CAPTION.font}", sans-serif`,
          fontSize: cq(size || CAPTION.defaultSize),
          fontWeight: bold ? 700 : 400,
          lineHeight: 1.3,
          color: assToCss(color || CAPTION.textColor, [255, 255, 255]),
          backgroundColor: assToCss(boxColor || CAPTION.boxColor, [0, 0, 0]),
        }}
      >
        {text}
      </span>
    </div>
  );
}
