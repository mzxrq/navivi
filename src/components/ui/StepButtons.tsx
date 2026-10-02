import { t } from "@lingui/core/macro";
import { ChevronDown, ChevronUp } from "./icons";

const half =
  "flex-1 flex items-center justify-center text-zinc-400 dark:text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-white/10 transition-colors";

/** Up/down buttons for a number input, styled like the app (the browser's own spinner is hidden in App.css).
 * Put the input and this inside a `relative` wrapper and give the input `pr-6`. */
export function StepButtons({ onStep }: { onStep: (dir: 1 | -1) => void }) {
  return (
    <div className="absolute right-1 top-1 bottom-1 w-4 flex flex-col rounded overflow-hidden">
      {/* mousedown kept from the input so its own blur-commit doesn't fire first */}
      <button type="button" tabIndex={-1} aria-label={t`Increase`} onMouseDown={(e) => e.preventDefault()} onClick={() => onStep(1)} className={half}>
        <ChevronUp className="w-3 h-3" />
      </button>
      <button type="button" tabIndex={-1} aria-label={t`Decrease`} onMouseDown={(e) => e.preventDefault()} onClick={() => onStep(-1)} className={half}>
        <ChevronDown className="w-3 h-3" />
      </button>
    </div>
  );
}
