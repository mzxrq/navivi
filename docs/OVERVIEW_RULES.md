# Overview video: how it works today (audit)

Branch `chore/pipeline-recap` (`main` plus the walking-leg changes in `c14ef49`), 2026-11-26.
Read from the code. All three styles render in a tiny CPU test with made-up data (`tests/test_overview_styles_render.py`). No real project was rendered.
The walking videos are in [LEG_RULES.md](LEG_RULES.md).

## 0. State

"Whole route first" could not render after merge `f959dec`. **Fixed**, here and on `main` (section 7).

## 1. Global rules (all styles)

| Topic | Rule |
|---|---|
| Styles | `settings.overview_style`: `walk` (Walk the route, default), `map` (Route map), `course` (Whole route first). Each has its own script. |
| Driven by | The voice. Cue tags in the script say when things happen. |
| Length | Script target: 20 s + 7 s per numbered stop, kept within 60–120 s (`overview_target_seconds` overrides). Walk and Route map log a warning if video and voice differ by more than 3 s. |
| Sound | The clip is silent. The voice is added at export. |
| Intro | The script's opening (before `{start}`) plays over the intro clip: 0.5 s + voice + 0.4 s, at least 4 s. The rest of the voice starts 1.2 s into the overview. |
| Missing cues | Added automatically to a hand-written script (`auto_overview_cues`). Never spoken. |
| Map framing | Route plus padding (more for short routes and many stops). Room kept at the top and bottom. |
| Pins | `S` start, `1, 2, 3 …` stops, `E` end, `・` stop-by or stop skipped in export, `×` closed. A return stop shows the first visit's number. |
| One badge per place | Return stops and a loop's end get no second badge. |
| Which places get a card | Any place with a photo. Stop-bys and closed places get a badge even without one. |
| Renderer | 2D, on the CPU. The optional 3D overview (`use_pydeck_overview`) ignores all cues and is never used for Whole route first. |
| Reuse | The finished clip is kept until its own inputs change. |

## 2. Cues

| Cue | Walk / Route map | Whole route first |
|---|---|---|
| `{start}` | Walker sets off | Opening ends |
| `{route}` | not used | Line starts drawing (without it: 2.5 s after `{start}`) |
| `{n}` | Walker reaches stop n | Stop n's pin lights up and its photo appears |
| `{go}` | Walker leaves the stop (waits from `{n}` until here) | The line waits at that stop until here |
| `{end}` | Walker finishes the route | Line finished, totals card slides in |
| `{distance}` | Ending stays up at least until here | **ignored** |
| `{extras}` | not used | Stop-bys appear (without it: 4 s after `{end}`) |
| `{closed}` | Nothing new on screen. Only with the ending zoom off: holds the last frame longer | Closed places appear |
| `{goPreN}` | **no visible effect** (see 6) | not used |

## 3. The styles side by side

| | Walk the route | Route map | Whole route first |
|---|---|---|---|
| Route and pins | All pins in the intro; then each pin returns when reached | Same | Whole route and route-stop pins from the start, then traced |
| At a numbered stop | Waits if cued; photo card | Waits at least 3.5 s; big photo turns into a leg card | Line passes or waits; photo pops, shrinks to a badge |
| Cards stay on screen | Yes (`overview_cards_stay`) | No, one at a time | Badges stay |
| Stop-bys | Pop up as the walker passes | Same | All together after the route |
| Closed places | Pop up as the walker passes | Same | After the stop-bys |
| Top of frame (not in the ending) | Title, mode times, remaining distance and time, stop count, next stop | Same | Changing headline and "A → B" (left), totals (right) |
| Bottom of frame | Stop-by / closed notice | Same | Progress strip and notices |
| Totals card | Bottom right, at the end | Same | Top right, at `{end}` |
| Camera | Still | Still | Eases out at the start; zooms into groups of 3+ close stops |
| Sub course | Shown after the totals | Same | **Not shown** |

## 4. Storyboards

### 4.1 Walk the route

| # | On screen | Timing |
|---|---|---|
| 1 | Clean map with all pins | up to 1.5 s |
| 2 | Start photo card (and end card, if it has a photo and the route is not a loop) slides in, holds, slides out | until `{start}` |
| 3 | Walker moves. A stop shows its card only once reached | A leg lasts at most 10 s (`overview_max_leg_seconds`), then speeds to meet each `{n}` |
| 4 | Arrival: pin pops, photo card appears | Waits 2 s if `{n}` starts a sentence, or until `{go}`. No wait if "Pause at Location" is off |
| 5 | Stop-by or closed place passed: card pops, notice shows | No stop. Each notice once per video, 5 s |
| 6 | All cards held | 1 s |
| 7 | Recap: map fades back, cards become badges, totals card fades in | 0.5 s fade, 1 s hold |
| 8 | Sub course drawn from its branch stop, with its own totals | only if the project has one |
| 9 | Zoom into the start point, start photo, fullscreen, blur out | `enable_ending_highlight` (on). With a Mapbox key the zoom is rendered in Chromium (`enable_gl_ending_zoom`); otherwise a still close-up map |

With step 9 off: the recap stays until the voice ends, reaching `{distance}`.

### 4.2 Route map

Same as Walk the route, except:

- Each main stop's photo pops up 2.6 times bigger for 0.8 s, then slides (0.5 s) to a leg card: from → to, distance, time, mode, climb.
- The walker stands at least 3.5 s. The card closes when it walks on.
- The script reads the leg's numbers at each stop.

### 4.3 Whole route first

| # | On screen | Timing |
|---|---|---|
| 1 | Map opens slightly zoomed in, eases out. Route and route-stop pins visible | 1.2 s |
| 2 | Line traces the route with a travel-mode icon. Headline and "A → B" change. Progress strip fills | from `{route}` |
| 3 | Each stop: big photo card beside the pin, then it shrinks into a badge | about 2.5 s (at least 1.8 s) |
| 4 | Camera zooms into close groups of stops | while the line is there |
| 5 | Totals card slides in | `{end}` |
| 6 | Stop-bys pop one by one, notice shows, earlier badges dim | `{extras}` |
| 7 | Closed places pop, closed notice shows | `{closed}` |
| 8 | Zoom into the start point and its photo | after the voice, if the ending highlight is on |

Script shape: opening `{start}` これが全体のルートです。`{route}` route sentences (at most 4 stops each) `{end}` totals `{distance}` goal `{extras}` stop-bys `{closed}` closed places.

Walk / Route map script shape: opening `{start}` walk to 1 `{1}` about stop 1 `{go}` … `{end}` closing.

### 4.4 Recap badges

| Rule | Detail |
|---|---|
| Look | Pill badge: number, name, photo. `pop_up_card` gives the older wide photo card |
| Lines | Pill badges have no leader lines: the badge and its pin share a number and a color |
| Place | Beside its pin where there is room, on rows and columns, never overlapping each other |
| Keeps clear of | Route, pin heads, top panels, notices. A badge pushed far away brings back the pin's number |
| Order | Start, numbered stops, stop-bys, closed places, each in walked order |
| Start | Gets the free spot nearest its pin |
| Whole route first | Same badges, up during the whole video. A big photo card shows first, then shrinks into the badge |

Preview one frame without a full render: `.agents/scratch/recap-layout/shoot.py` (local script; use a copy of a project).

## 5. Settings that change the overview

| Setting | Default |
|---|---|
| `overview_style` | `walk` |
| `overview_recap_style` | `pill_badge` (or `pop_up_card`) |
| `overview_target_seconds` | automatic |
| `overview_describe_stops` | on |
| `overview_intro` | automatic opening text |
| `overview_voice_over_intro` | on |
| `auto_overview_cues` | on |
| `overview_cue_wait_seconds` | 2.0 |
| `overview_max_leg_seconds` | 10 |
| `overview_cards_stay` | on (Walk the route only) |
| `enable_ending_highlight` | on |
| `enable_gl_ending_zoom` | on |
| `use_pydeck_overview` | off |
| `course_trace_color` | orange |

## 6. Rules that do not match each other

1. **Script and video disagree about stop-bys (Walk, Route map).** The script still plans a freeze at the stop before a group of stop-bys: about 3.5 s of talk for that stop, no extra spare time, a line "…が見えてきます" and `{goPreN}`. The video no longer freezes; it passes every stop-by. Checked with a small example.
2. **Old stop-by freeze code is unused** in the overview (`_play_stopby_batch`, `{goPreN}` timing).
3. **Cues mean different things per style:** `{distance}` and `{closed}` (section 2).
4. **Sub course** is framed on the map in every style but never drawn in Whole route first.
5. **Old comments** say closed places come in at `{closed}` in the Walk style, and that the ending photo follows `image_display`. Neither is true.

## 7. What merge `f959dec` dropped, now restored

The merge joined the newer overview work (`aa82b9f`) with GitHub `main` (`04597c5`, which held nothing the newer side lacked). In several files the older code won. 13 tests were removed with it, so the test run stayed green.

| Was lost on `main` | Effect on `main` |
|---|---|
| End of the course renderer | Video not saved |
| `total_points` argument of the badge layout | Course render crashes; pins do not take their badge's color |
| Badge placement improvements | Badges may cover the route or pins, or sit far from their pin |
| Start badge kept near its pin | Not done |
| Closing video's badges without leader lines | Leader lines are asked for again |
| Leg "stop N of total" ignoring return stops | Return stops are counted |
| Removal of the next-stop preview badge | The badge is back |
| Course recap preview | Draws the Walk layout |

All of it is restored from `aa82b9f` (`1dc61fe`). The overview render version is now 74, so overviews made with the merged code render again. A second crash, on an ending map with no room for any badge, is fixed in `e8310d2`.

## 8. Decisions for the redesign

1. Should the three styles share one cue meaning?
2. Should stop-bys ever freeze the Walk overview again? If not, the script planning should drop it.
3. Should Whole route first show the sub course?
4. Is the 60–120 s length rule still right?
