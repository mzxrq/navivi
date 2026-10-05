import type { IntroStyle } from "../types";

// Mirrors INTRO_* in src-tauri/src-python/services/tuning.py; sizes are pixels of the 1920-wide intro frame.
export const INTRO_FRAME_WIDTH = 1920;
export const INTRO_SIZE_MIN = 20;
export const INTRO_SIZE_MAX = 200;

type Rgb = [number, number, number];
export interface IntroLook {
  title_size: number;
  title_color: Rgb;
  title_bold: boolean;
  subtitle_size: number;
  subtitle_color: Rgb;
  subtitle_bold: boolean;
}

export const INTRO_DEFAULTS: IntroLook = {
  title_size: 74,
  title_color: [255, 255, 255],
  title_bold: true,
  subtitle_size: 36,
  subtitle_color: [255, 255, 255],
  subtitle_bold: true,
};

export function introLookOf(style: IntroStyle | undefined): IntroLook {
  return { ...INTRO_DEFAULTS, ...style };
}

// Font size as a share of the frame width, for drawing the preview at any width.
export const introSizeToCqw = (size: number) => `${((size / INTRO_FRAME_WIDTH) * 100).toFixed(3)}cqw`;
