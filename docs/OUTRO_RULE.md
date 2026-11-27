# Outro rules

The outro is the closing clip (`99_outro.mp4`) at the end of the film: the project title, a card for each stop with a photo, the route's facts, and the logos. Code: `services/vdoprocessing/outrocard.py` (drawing) and `services/vdoprocessing/videopipeline/outro_step.py` (settings and placement). Related: [FINALE_RULE.md](FINALE_RULE.md), [INTRO_ENDING_RULES.md](INTRO_ENDING_RULES.md) (audit of the current behaviour).

## 1. When it runs

| Rule | Value |
|---|---|
| Settings | `enable_outro` (default on). Off = no outro clip at all |
| Needs | At least one stop with a photo. `scroll` can also show route facts alone |
| Otherwise | Skipped and logged |
| Failure | Any exception is logged and the outro is skipped (it never fails the render) |
| Partial file | Rendered to a `.partial.mp4` and swapped in when complete, so a cancelled run never leaves a cut-off outro |

## 2. Styles

`settings.outro_style` takes `scroll`, `grid` or `scrapbook`. An unknown value falls back to `scroll`.

| Style | On screen | Length |
|---|---|---|
| `scrapbook` | Photos drop onto paper as polaroids, one by one with footprints between them, then a round stamp with the title, distance and time. Then the logos | Walk time per card (0.55 s, shorter with many stops, about 6 s in all), then 2 s hold |
| `scroll` | Cards three to a row in a column that scrolls up under the pinned title, credits-style. Then the logos | Scroll speed 100 px/s, 1 s start hold, 0.5 s end hold, capped at 30 s |
| `grid` | One still page of up to 20 cards on one screen | 5 s |

Other limits: `grid` and `scrapbook` show at most 20 cards (`OUTRO_MAX_CARDS`); `scroll` has no cap, since scrolling is what fits a long list. Cards are 4:3 thumbnails.

### Default style: check before you rely on it

The app's settings default is `scroll` (`src/config/constants.ts`). The renderer's own default, used when a project has no `outro_style` key, is `scrapbook` (`tuning.DEFAULT_OUTRO_STYLE`). Both are real, so a project saved without the key renders differently from a new one. See [INTRO_ENDING_RULES.md](INTRO_ENDING_RULES.md) §5.

## 3. Route facts

| Rule | Value |
|---|---|
| Setting | `outro_route_info` (default on) |
| On | Each leg as a row (its start, mode, distance and time chips), then a summary (totals per travel mode) |
| Off | Cards only, the grid as before |

## 4. Title and heading

- The title, subtitle and kicker come from the same heading as the intro (`_outro_heading`).
- The title is a text-track item on the timeline (`outro_text_item`), so it can be edited there.
- Title colour, font sizes and the "Powered by" logo follow `tuning.py` (the `OUTRO_*` block, around line 1320).

## 5. Placement

- **After the finale:** a cut, no transition. See [FINALE_RULE.md](FINALE_RULE.md).
- **Without a finale:** a 1 s dissolve.
- **Size:** the same as the walking videos (the frame size most route clips share).
- A sub course, if any, plays between the finale and the outro. Read [INTRO_ENDING_RULES.md](INTRO_ENDING_RULES.md) §5 before changing this.

## 6. Cards and names

- A card uses the stop's photo, its numbered badge, and its name. Long names wrap at word boundaries (`_word_edges`) and shrink before they are cut with "…".
- A stop with no photo gets no card. Its route row still shows in the route facts.
- Badge colours match the stop's numbered pin.

## 7. Themed scroll (one place per screen)

Code: `services/vdoprocessing/outro_themed.py`, look: `services/hudtheme/designs/outro/default.html`.

| Rule | Value |
|---|---|
| Used when | `outro_style` is `scroll` and `<project>/hud.json` names a theme. Otherwise, or if it fails, the plain scroll |
| Screens | Every stop, described or not, in route order; stop-bys and closed places as `storyboards/outro.json` says. A place come back to gets one screen (the visit with the description). No limit, no 30 s cap |
| Storyboard | `services/vdoprocessing/storyboards/outro.json`: `include_stopby_waypoint` (stop-bys and stops skipped in video export) and `include_closed_waypoint`, both `true`. It applies to every project |
| No description | The screen shows the picture and the facts, with no description box |
| On a screen | Photo (the theme's picture without one), description, badge as on the map pins, name, the distance and time of the leg arriving there (`--.-` when no leg does), and the next place |
| Banner | The intro's place (kicker), title and subtitle |
| Timing | First screen 2.5 s, others 1.5 s, 0.6 s scroll between them, then the logos over the same background |
| Scroll | The next screen follows right behind. The down arrow and the line to it stay put, and fade as the last place arrives |
| Description | `outroDescription` on the waypoint (stop editor; the box shows only while the outro style is scroll). Its size never changes: the box grows from 3 lines up to 7 (the most that fits the screen), then the text is cut with "…" |
| Title | Drawn into the clip. `99_outro.themed.json` beside the clip says so: no outro text item on the timeline |
| Not shown | Trip summary, stop-by and closed-place lists (`outro_route_info` has no effect) |

Frames are captured from headless Chromium on the CPU: the page's CSS animation is paused and set to each frame's time; a held screen is captured once.

## 8. Tuning

All numbers live in `services/tuning.py` (the `OUTRO_*` block, lines ~1320–1400). Change them there, not in `outrocard.py`.

## 9. Checks

- `tests/test_outrocard.py` and `tests/test_look_options.py` cover the outro's options and layout.
- `tests/test_stop_numbering.py` covers the badge numbers.
- `tests/test_outro_themed.py` covers the themed scroll.
