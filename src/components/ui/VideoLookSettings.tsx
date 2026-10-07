import { t } from "@lingui/core/macro";
import { videoLookDefaults as d } from "../../config/constants";
import type { LookMode, ProjectSettings, SummaryCardStyle } from "../../types";
import { arrivedDefault, modeLineDefault } from "../../utils/videoLook";
import { ColorSwatches, type RGB } from "./ColorSwatches";
import { Segmented } from "./Segmented";
import { Section, Row, inputClass } from "./SettingsParts";
import { Slider } from "./Slider";
import { Switch } from "./Switch";

interface Props {
  options: Partial<ProjectSettings>;
  /** A key set to undefined is removed (back to what the renderer always did). */
  onChange: (patch: Record<string, unknown>) => void;
}

function Fader({ value, min, max, step, label, unit, onChange }: { value: number; min: number; max: number; step: number; label: string; unit?: string; onChange: (v: number) => void }) {
  return (
    <div className="flex items-center gap-3">
      <Slider value={value} min={min} max={max} step={step} label={label} onChange={onChange} className="w-36" />
      <span className="w-12 text-right text-[12px] tabular-nums text-zinc-500 dark:text-zinc-400">
        {+value.toFixed(2)}
        {unit ?? ""}
      </span>
    </div>
  );
}

function ColorChoice({ color, fallback, onChange }: { color?: RGB; fallback: RGB; onChange: (c: RGB | undefined) => void }) {
  return (
    <div className="flex items-center gap-2">
      <ColorSwatches color={color ?? fallback} onChange={onChange} />
      <button
        type="button"
        disabled={!color}
        onClick={() => onChange(undefined)}
        className="text-[12px] text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 disabled:invisible"
      >
        {t`Reset`}
      </button>
    </div>
  );
}

/** The "Look of the video" groups of the Project settings dialog. Unset keys show the renderer's own defaults. */
export function VideoLookSettings({ options, onChange }: Props) {
  const on = (key: keyof typeof d) => (options[key as keyof ProjectSettings] as boolean | undefined) ?? (d[key] as boolean);
  const num = (key: keyof typeof d) => (options[key as keyof ProjectSettings] as number | undefined) ?? (d[key] as number);
  const set = (key: string) => (value: unknown) => onChange({ [key]: value });
  const modeColors = options.mode_line_colors ?? {};
  const setModeColor = (modes: LookMode[], color: RGB | undefined) => {
    const next: Record<string, RGB> = { ...modeColors };
    for (const mode of modes) {
      if (color) next[mode] = color;
      else delete next[mode];
    }
    onChange({ mode_line_colors: Object.keys(next).length ? next : undefined });
  };
  const modeRows: { modes: LookMode[]; label: string }[] = [
    { modes: ["walking"], label: t`Walking` },
    { modes: ["driving", "car"], label: t`Driving` },
    { modes: ["ferry"], label: t`Ferry` },
    { modes: ["airplane"], label: t`Flying` },
  ];

  return (
    <div className="space-y-4">
      <Section title={t`Cards and overlays`}>
        <Row title={t`Summary card`} description={t`How the card after each leg and the overview is laid out.`}>
          <Segmented<SummaryCardStyle>
            compact
            value={options.summary_card_style ?? d.summary_card_style}
            onChange={set("summary_card_style")}
            options={[
              { id: "glass", label: t`Glass` },
              { id: "taskbar", label: t`Taskbar` },
              { id: "stacked", label: t`Stacked` },
              { id: "columns", label: t`Columns` },
            ]}
          />
        </Row>
        <Row title={t`Overlay theme`} description={t`The map overlays and cards in the video, not the app.`}>
          <Segmented<"light" | "dark">
            compact
            value={options.theme ?? d.theme}
            onChange={set("theme")}
            options={[
              { id: "light", label: t`Light` },
              { id: "dark", label: t`Dark` },
            ]}
          />
        </Row>
        <Row title={t`Card border color`}>
          <ColorChoice color={options.card_border_color} fallback={d.card_border_color} onChange={set("card_border_color")} />
        </Row>
        <Row title={t`Card border width`}>
          <Fader value={num("card_border_thickness")} min={0} max={6} step={1} unit=" px" label={t`Card border width`} onChange={set("card_border_thickness")} />
        </Row>
        <Row title={t`Map label size`}>
          <Fader value={num("map_font_size")} min={14} max={40} step={1} label={t`Map label size`} onChange={set("map_font_size")} />
        </Row>
        <Row title={t`Compass on stop maps`}>
          <Switch checked={on("show_compass")} onChange={set("show_compass")} label={t`Compass on stop maps`} />
        </Row>
        <Row title={t`Border around stop maps`}>
          <Switch checked={on("waypoint_map_border")} onChange={set("waypoint_map_border")} label={t`Border around stop maps`} />
        </Row>
        <Row title={t`Wide view before each leg`} description={t`Opens a leg zoomed out before the camera moves in.`}>
          <Switch checked={on("show_leg_wide_intro")} onChange={set("show_leg_wide_intro")} label={t`Wide view before each leg`} />
        </Row>
      </Section>

      <Section title={t`Pins and lines`}>
        <Row title={t`Start pin`}>
          <ColorChoice color={options.start_pin_color} fallback={d.start_pin_color} onChange={set("start_pin_color")} />
        </Row>
        <Row title={t`End pin`}>
          <ColorChoice color={options.end_pin_color} fallback={d.end_pin_color} onChange={set("end_pin_color")} />
        </Row>
        <Row title={t`Stop-by pin`}>
          <ColorChoice color={options.stopby_pin_color} fallback={d.stopby_pin_color} onChange={set("stopby_pin_color")} />
        </Row>
        <Row title={t`Drawn route pin`}>
          <ColorChoice color={options.drawn_pin_color} fallback={d.drawn_pin_color} onChange={set("drawn_pin_color")} />
        </Row>
        <Row title={t`Visited pin`} description={t`Unset, it is the marker color, darker.`}>
          <ColorChoice color={options.arrived_marker_color} fallback={arrivedDefault(options.marker_color)} onChange={set("arrived_marker_color")} />
        </Row>
        {modeRows.map(({ modes, label }) => (
          <Row key={modes[0]} title={t`Line color: ${label}`}>
            <ColorChoice
              color={modeColors[modes[0]]}
              fallback={modeLineDefault(modes[0], options.line_color)}
              onChange={(c) => setModeColor(modes, c)}
            />
          </Row>
        ))}
      </Section>

      <Section title={t`Pace and camera`}>
        <Row title={t`Overview speed`} description={t`How much faster the overview plays than the paced route.`}>
          <Fader value={num("overview_speed_multiplier")} min={1} max={8} step={0.5} unit="x" label={t`Overview speed`} onChange={set("overview_speed_multiplier")} />
        </Row>
        <Row title={t`Longest leg in the overview`}>
          <Fader value={num("overview_max_leg_seconds")} min={3} max={20} step={1} unit=" s" label={t`Longest leg in the overview`} onChange={set("overview_max_leg_seconds")} />
        </Row>
        <Row title={t`Typical leg length`} description={t`Aimed-for seconds per leg in the street-level view.`}>
          <Fader value={num("res_target_avg_seconds")} min={6} max={30} step={1} unit=" s" label={t`Typical leg length`} onChange={set("res_target_avg_seconds")} />
        </Row>
        <Row title={t`Longest leg`}>
          <Fader value={num("res_max_segment_seconds")} min={8} max={40} step={1} unit=" s" label={t`Longest leg`} onChange={set("res_max_segment_seconds")} />
        </Row>
        <Row title={t`Camera distance`} description={t`How far behind the traveler the street-level camera sits.`}>
          <Fader value={num("camera_follow_distance_m")} min={6} max={40} step={1} unit=" m" label={t`Camera distance`} onChange={set("camera_follow_distance_m")} />
        </Row>
        <Row title={t`Camera tilt`}>
          <Fader value={num("res_follow_pitch")} min={0} max={60} step={5} unit="°" label={t`Camera tilt`} onChange={set("res_follow_pitch")} />
        </Row>
        <Row title={t`Turn smoothing`} description={t`Lower turns the camera more gently.`}>
          <Fader value={num("bearing_smoothing")} min={0.05} max={0.5} step={0.05} label={t`Turn smoothing`} onChange={set("bearing_smoothing")} />
        </Row>
      </Section>

      <Section title={t`Photos at stops`}>
        <Row title={t`Full-screen photos`} description={t`Photos grow to fill the frame when the traveler arrives.`}>
          <Switch checked={on("enable_fullscreen_popups")} onChange={set("enable_fullscreen_popups")} label={t`Full-screen photos`} />
        </Row>
        <Row title={t`Hide the route behind photos`}>
          <Switch checked={on("hide_route_on_popup")} onChange={set("hide_route_on_popup")} label={t`Hide the route behind photos`} />
        </Row>
        <Row title={t`Sharpen photos`} description={t`Upscales photos before they are shown. Needs a GPU and takes longer.`}>
          <Switch checked={on("upscale_popup_images")} onChange={set("upscale_popup_images")} label={t`Sharpen photos`} />
        </Row>
        <Row title={t`Pause on the stop map`}>
          <Fader value={num("waypoint_intro_freeze")} min={0} max={5} step={0.5} unit=" s" label={t`Pause on the stop map`} onChange={set("waypoint_intro_freeze")} />
        </Row>
      </Section>

      <Section title={t`Overview`}>
        <Row title={t`Title on the overview`} description={t`Unset, the project name.`}>
          <input
            type="text"
            value={options.overview_title ?? ""}
            onChange={(e) => onChange({ overview_title: e.target.value || undefined })}
            className={`${inputClass} w-44`}
          />
        </Row>
        <Row title={t`Intro card size`}>
          <Fader value={num("overview_intro_card_scale")} min={0.8} max={1.6} step={0.1} unit="x" label={t`Intro card size`} onChange={set("overview_intro_card_scale")} />
        </Row>
        <Row title={t`Clean map before the card`} description={t`Seconds the overview shows the bare map first.`}>
          <Fader value={num("overview_intro_clean_hold_seconds")} min={0} max={4} step={0.5} unit=" s" label={t`Clean map before the card`} onChange={set("overview_intro_clean_hold_seconds")} />
        </Row>
        <Row title={t`Zoom to the start at the end`} description={t`The closing close-up of the first stop.`}>
          <Switch checked={on("enable_ending_highlight")} onChange={set("enable_ending_highlight")} label={t`Zoom to the start at the end`} />
        </Row>
      </Section>

      <Section title={t`Outro`}>
        <Row title={t`Add an outro`} description={t`The places-visited clip at the end of the video.`}>
          <Switch checked={on("enable_outro")} onChange={set("enable_outro")} label={t`Add an outro`} />
        </Row>
        {on("enable_outro") && (
          <>
            <Row title={t`Outro style`}>
              <Segmented<"scroll" | "grid">
                compact
                value={options.outro_style ?? d.outro_style}
                onChange={set("outro_style")}
                options={[
                  { id: "scroll", label: t`Scrolling` },
                  { id: "grid", label: t`Grid` },
                ]}
              />
            </Row>
            <Row title={t`Route facts`} description={t`Distance, time and mode on each card.`}>
              <Switch checked={on("outro_route_info")} onChange={set("outro_route_info")} label={t`Route facts`} />
            </Row>
          </>
        )}
      </Section>
    </div>
  );
}
