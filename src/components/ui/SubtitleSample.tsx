import { t } from "@lingui/core/macro";
import { Caption } from "./Caption";

interface SubtitleSampleProps {
  font?: string;
  size?: number;
  color?: string;
  boxColor?: string;
  bold?: boolean;
}

// A light-to-dark frame, so the text can be judged on a bright and on a dark picture.
export function SubtitleSample(props: SubtitleSampleProps) {
  return (
    <div
      className="relative aspect-video w-full max-w-sm overflow-hidden rounded-lg ring-1 ring-black/10 dark:ring-white/10 bg-linear-to-r from-zinc-100 to-zinc-800"
      style={{ containerType: "size" }}
    >
      <Caption text={t`How your subtitles will look`} {...props} />
    </div>
  );
}
