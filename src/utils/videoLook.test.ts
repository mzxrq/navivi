import { describe, expect, it } from "vitest";
import { videoLookDefaults } from "../config/constants";
import { applyOption, arrivedDefault, LOOK_KEYS, lookPatch, modeLineDefault } from "./videoLook";

describe("videoLook", () => {
  it("defaults match what the renderer does without the key", () => {
    expect(videoLookDefaults).toMatchObject({
      summary_card_style: "columns",
      theme: "dark",
      show_compass: true,
      waypoint_map_border: true,
      waypoint_intro_freeze: 2,
      show_leg_wide_intro: false,
      res_follow_pitch: 0,
      overview_max_leg_seconds: 10,
      overview_intro_card_scale: 1.3,
      overview_intro_clean_hold_seconds: 1.5,
      enable_ending_highlight: true,
      enable_outro: true,
      outro_style: "scroll",
      outro_route_info: true,
      overview_speed_multiplier: 4,
      camera_follow_distance_m: 14,
      bearing_smoothing: 0.15,
      enable_fullscreen_popups: true,
      hide_route_on_popup: false,
      upscale_popup_images: true,
    });
  });

  it("darkens the marker color for arrived pins like the renderer", () => {
    expect(arrivedDefault([100, 200, 255])).toEqual([78, 156, 198]);
    expect(arrivedDefault()).toEqual([30, 110, 200]);
  });

  it("uses the route line color for ordinary modes and its own for flights", () => {
    expect(modeLineDefault("walking", [1, 2, 3])).toEqual([1, 2, 3]);
    expect(modeLineDefault("airplane", [1, 2, 3])).toEqual([220, 60, 180]);
  });

  it("patches every look key, with null for the ones the file does not have", () => {
    const patch = lookPatch({ show_compass: false });
    expect(Object.keys(patch)).toEqual(LOOK_KEYS);
    expect(patch.show_compass).toBe(false);
    expect(patch.enable_outro).toBeNull();
    expect(patch).toHaveProperty("mode_line_colors", null);
  });

  it("nulls the modes that were reset, since the database merges nested objects", () => {
    const patch = lookPatch({ mode_line_colors: { ferry: [1, 2, 3] } });
    expect(patch.mode_line_colors).toEqual({ walking: null, driving: null, car: null, ferry: [1, 2, 3], airplane: null });
  });

  it("removes a key on reset and keeps the rest", () => {
    expect(applyOption({ a: 1, b: 2 }, { a: undefined, c: 3 })).toEqual({ b: 2, c: 3 });
  });
});
