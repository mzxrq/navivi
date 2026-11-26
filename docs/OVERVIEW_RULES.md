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
| Length | Script target: 20 s + 7 s per numbered stop, kept within 60–120 s (`overview_target_seconds` overrides). Walk and Route map log a warning if video and voice differ by more than 3 s. (Planned: no 60–120 s window, see 8.2.) |
| Sound | The clip is silent. The voice is added at export. |
| Intro | The script's opening (before `{start}`) plays over the intro clip: 0.5 s + voice + 0.4 s, at least 4 s. The rest of the voice starts 1.2 s into the overview. |
| Missing cues | Added automatically to a hand-written script (`auto_overview_cues`). Never spoken. |
| Map framing | Route plus padding (more for short routes and many stops). Room kept at the top and bottom. |
| Pins | `S` start, `1, 2, 3 …` stops, `E` end, `・` stop-by or stop skipped in export (planned: `+1, +2 …`, see 8.7), `×` closed. A return stop shows the first visit's number. |
| One badge per place | Return stops and a loop's end get no second badge. |
| Which places get a card | Any place with a photo. Stop-bys and closed places get a badge even without one. |
| Renderer | 2D, on the CPU. The optional 3D overview (`use_pydeck_overview`) ignores all cues and is never used for Whole route first. |
| Reuse | The finished clip is kept until its own inputs change. |

## 2. Cues

| Cue | Walk / Route map | Whole route first |
|---|---|---|
| `{start}` | Walker sets off | Opening ends and the line starts tracing the route (planned, see 8.5) |
| `{route}` | not used | Removed. The trace starts at `{start}` (see 8.5) |
| `{n}` | Walker reaches stop n | Stop n's pin lights up and its photo appears |
| `{go}` | Walker leaves the stop (waits from `{n}` until here) | The line waits at that stop until here |
| `{end}` | Walker finishes the route | Line finished, totals card slides in |
| `{distance}` | Ending stays up at least until here | **ignored** (planned: shows the summary card and starts the recap frame, see 8.10) |
| `{extras}` | not used | Stop-bys appear (today: 4 s after `{end}` if the cue is missing; planned: no fallback, see 8.11) |
| `{closed}` | Nothing new on screen. Only with the ending zoom off: holds the last frame longer | Closed places appear (planned: see 8.11) |

## 3. The styles side by side

| | Walk the route | Route map | Whole route first |
|---|---|---|---|
| Route and pins | All pins in the intro; then each pin returns when reached | Same | Whole route and route-stop pins from the start, then traced |
| At a numbered stop | Waits if cued; photo card | Waits at least 3.5 s; big photo turns into a leg card | Line passes or waits; photo pops, shrinks to a badge |
| Cards stay on screen | Yes (`overview_cards_stay`) | No, one at a time | Badges stay |
| Stop-bys | Pop up as the walker passes | Same | All together after the route |
| Closed places | Pop up as the walker passes | Same | After the stop-bys |
| Top of frame (not in the ending) | Title (left); remaining over whole-route distance and time (right), see 8.14 | Same | Same |
| Bottom of frame | Stop-by / closed notice | Same | Progress strip and notices (planned: same as Walk, see 8.15) |
| Totals card | Bottom right, at the end | Same | Top right, at `{end}` |
| Camera | Still | Still | Eases out at the start; zooms into groups of 3+ close stops |
| Sub course | Shown after the totals (planned: at its own storyboard slot, see 8.17) | Same (planned: same slot) | **Not shown** (planned: at its own storyboard slot, see 8.17) |

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
| 2 | Line traces the route with a travel-mode icon. Headline and "A → B" change. Progress strip fills | from `{start}` (planned; today from `{route}`) |
| 3 | Each stop: big photo card beside the pin, then it shrinks into a badge | about 2.5 s (at least 1.8 s) |
| 4 | Camera zooms into close groups of stops | while the line is there |
| 5 | Totals card slides in | `{end}` |
| 6 | Stop-bys pop one by one, notice shows, earlier badges dim | `{extras}` |
| 7 | Closed places pop, closed notice shows | `{closed}` |
| 8 | Zoom into the start point and its photo | after the voice, if the ending highlight is on |

Script shape: opening `{start}` これが全体のルートです。(planned: the trace starts here, so no `{route}`) route sentences (at most 4 stops each) `{end}` totals `{distance}` goal `{extras}` stop-bys `{closed}` closed places.

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
| `overview_passed_stop_look` (planned, see 8.12) | from the storyboard config: `photo_only` (or `badge`) |
| `overview_target_seconds` | automatic |
| `overview_describe_stops` | on |
| `overview_intro` | automatic opening text |
| `overview_voice_over_intro` | on |
| `auto_overview_cues` | on |
| `overview_cue_wait_seconds` | 2.0 |
| `overview_max_leg_seconds` | 10 |
| `overview_cards_stay` | on (every style) |
| `enable_ending_highlight` | on |
| `enable_gl_ending_zoom` | on |
| `use_pydeck_overview` | off (planned: on for all styles, see 8.8) |
| `course_trace_color` | orange |

## 6. Rules that do not match each other

1. **Script and video disagree about stop-bys (Walk, Route map).** The script still plans a freeze at the stop before a group of stop-bys: about 3.5 s of talk for that stop, no extra spare time, and a line "…が見えてきます". The video no longer freezes; it passes every stop-by. Checked with a small example.
2. **Old stop-by freeze code is unused** in the overview (`_play_stopby_batch` timing).
3. **`{goPreN}` is removed.** Planned: delete the cue from the script planning and the auto-tagger, so no script carries it.
4. **Cues mean different things per style:** `{distance}` and `{closed}` (section 2).
5. **Sub course** is framed on the map in every style but never drawn in Whole route first.
6. **Old comments** say closed places come in at `{closed}` in the Walk style, and that the ending photo follows `image_display`. Neither is true.

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

## 8. Planned changes (not yet coded)

Planning only. Nothing below is in the code yet. Code starts after the decisions in 8.0 and 8.4 are confirmed.

### 8.0 Decisions from the reviewer (2026-11-26)

| Section | Question | Decision |
|---|---|---|
| 8.8 | Renderer | the 3D map for all three styles in the real video, viewed straight down |
| 8.12 | Passed stop's card | stays a photo card by default; set in the storyboard config |
| 8.4 | Storyboard | one template file per style, in a folder that code reads (8.1) |
| 8.2 | Length | no limit: no floor, no ceiling |
| 8.7 | Stop-by pins | every stop-by, and every stop skipped in export, shows `+N` |
| 8.10 | Recap frame | held for 3 s, a fixed time set in project settings |
| 8.13 | Cards stay | a passed stop's card pops and stays up until the end; set in the storyboard config |
| 8.14 | Top of frame | a static project name replaces the changing headline |
| 8.17 | Sub course slot | before the stop-by section by default; set in the storyboard config file |
| 8.11 | Missing `{extras}` / `{closed}` | those places are not shown |
| 8.15 | Two notices | side by side; the bar beside them shortens to fit, with a small gap |
| 8.6 | Auto-cue switches | per project only |

Decided in the second round (2026-11-26):
- 8.10: the recap frame holds 3 s.
- 8.4: beat timings go in the storyboard config file.
- 8.7: the editor map does not show `+N`; video only.
- 8.14: distances and times use the same format in every style.
- 8.12: in `photo_only`, the pin keeps its number.
- 8.16: the theme setting controls the totals card's shape and design; `summary_card_style` folds into it.

Still assumed (to check before coding):
- 8.7: `+N` runs across the whole route in visit order.
- 8.10: whether a still is saved as the thumbnail.
- 8.16: the first theme and the registry start with `current` alone.

Any render, in 2D or 3D, still needs approval first (`CLAUDE.md`).

### 8.1 Storyboard control

`settings.overview_style` (`walk`, `map`, `course`) decides the whole storyboard, so each style gets one template.

- New folder `services/vdoprocessing/storyboards/` with one storyboard config file per style: `walk.json`, `map.json`, `course.json`. A small loader (`storyboard.py`) reads them, so code reads the storyboard from the file, not from the style name. An unset or unknown style falls back to `walk`. The files are plain data, so a storyboard can be changed without touching code.
- Today the style is compared at 15 places in 10 files (`spatial_renderer/overview.py:776,781,1150`, `overview_animation.py:810,874`, `popups.py:2853`, `transitions.py:116`, `route2vdo.py:743,899,1100`, `videopipeline/overview_framing.py:142`, `narration_step.py:163`, `pipeline.py:113`, `stopby_visits.py`, `localization/overview_script.py`). Each becomes one field read.
- Fields: `passby_stopbys`, `passby_closed`, `leg_cards`, `traced_route`, `big_stop_card`, `one_card_at_a_time`, `cards_stay` (still ANDed with `overview_cards_stay`), `ending_zoom_after_summary`, `course_brief_legs`, `arrival_slow_seconds`, `pydeck_allowed`, `course_frame`, `script_intro_in_key`, `visit_all_stopbys`.
- Steps: add the module and its test, switch each check one file at a time (rename only), run the 68 overview tests before and after, then the full `pytest -q tests`. Output must not change, so no render version bump. No GPU render. Run `graphify update .` after the change.

### 8.2 Length: any length, the voice decides

Decided: no length limit. No floor and no ceiling. The overview is as long as the voice needs, to the second.

- Remove the clamp: `TARGET_MIN_SECONDS` / `TARGET_MAX_SECONDS` (`localization/overview_script.py:158-159`) and the clamp in `overview_target_seconds()` (`:418-425`). Keep the base-plus-per-stop formula as the starting point.
- Remove `in_overview_range()` (`:412-415`) and the `fits` flag, or narrow `fits` to "voice within 3 s of video".
- Spare time (`:531-534`) fills to the target, not to 60 s.
- Keep: the 3 s audio/video tolerance, the intro and outro shares, the cue logic, and `overview_target_seconds` as a manual override.
- Bump the overview render version, since output changes. Tests: a 1-stop and a 30-stop made-up route, script length within 3 s of the voice.

### 8.3 Open questions for the redesign

1. Should the three styles share one cue meaning? (Section 2 shows they do not.)
2. Should stop-bys ever freeze the Walk overview again? If not, drop that planning from the script.
3. Should Whole route first show the sub course?

### 8.4 Decisions needed before coding

1. Answered: beat timings go in the storyboard config file too (see 8.0).
2. `map`: written as walk plus changes (as in the code), or as an independent template?
3. `course`: keeps its own renderer file, with the template only choosing it?
4. Length: answered in 8.2 (no limit). `overview_target_seconds` keeps overriding.

### 8.5 Intro `{start}` starts the route trace (Whole route first)

Decided: the `{route}` cue is removed. `{start}` is the only cue that starts the trace.

Reading of the request: in the course style, the `{start}` cue that ends the opening is also the moment the line starts tracing the route. The separate `{route}` cue goes.

- Cue table (section 2): `{start}` ends the opening and starts the trace; `{route}` is removed for this style.
- Storyboard step 2 (section 4.3) starts from `{start}`.
- Script shape: opening `{start}`, then the route sentences. No `{route}` tag.
- Check: the opening's voice and the 1.2 s map fly-in must fit before the trace; if the opening is shorter than the fly-in, the trace waits for the fly-in to finish.
- Walk and Route map are not changed.
- Code change when coded: the course script writer and `course.py`'s timing (today it reads `{route}`, or 2.5 s after `{start}` when absent). Auto-cue tagging (`auto_overview_cues`) must add `{start}` only, not `{route}`.
- Render version bump, since the video changes.

### 8.6 Toggle each automatic cue in project settings

Reading of the request: the cues the code adds to a script by itself should each have a switch in project settings, not only the two switches that exist today.

What exists now: `auto_overview_cues` and `auto_narration_cues` (project settings, Voice tab, "Timing cues" section, `VoiceSettings.tsx:555-573`). Both default on. Nothing else is switchable.

Cues added automatically (`localization/overview_cues.py`, `auto_tag_overview` and `add_scene_cues`):

| Cue | Where it goes | Added when |
|---|---|---|
| `{n}` | before the sentence that names stop n | no `{n}` in the script |
| `{go}` | after the stop's opening sentence | no `{go}` in the script |
| `{start}` | before the opening's pivot sentence | no `{start}` |
| `{route}` | removed (8.5) | — |
| `{extras}` | before the stop-bys sentence | stop-bys present |
| `{closed}` | before the closed places sentence | closed places present |
| `{scene}` | in the opening, per intro scene | text-led intro, not slideshow |

Plan:
- Keep the two existing switches as the master switches.
- Add one switch per cue kind above (`{n}`, `{go}`, `{start}`, `{extras}`, `{closed}`, `{scene}`), under the same "Timing cues" section, each default on and off when its master is off.
- Each switch is read in `add_overview_cues` / `auto_tag_overview` / `add_scene_cues`, so a cue left out is not added, and the user's own tags still win.
- Changing a switch re-tags the narration only; the audio stays valid (words are not changed).
- Tests: one per switch, a script with the switch off has no tag of that kind.

Decided: per project only (see 8.0).

### 8.7 Stop-by pins show +1, +2 instead of ・

Decided: every stop-by, and every stop skipped in export, shows `+N` in place of `・`. Stop numbers `1, 2, 3 …` are unchanged.

Plan:
- Numbering: stop-bys are counted in visit order, `+1` for the first stop-by the walk visits, `+2` for the next. Stops skipped in export also get `+N` (decided).
- Where `・` is drawn today (one glyph in each place, so each must change together):
  - `spatial_renderer/pins.py:297` (pin glyph), `pins.py:243`
  - `spatial_renderer/map_style.py:37`, `spatial_renderer/overview.py:399` and `:787`, `spatial_renderer/waypoints.py:643`
  - `spatial_renderer/popups.py:2599` (checks the text `"・"` to decide the card)
  - `mapfetcher/graphicengine/cards.py:317`, `popup_box.py:367`
  - `videopipeline/render_look.py:53-107` (checks the text `"・"` to decide the look)
  - `videopipeline/finale_step.py:72` and `:134` (colour map and check keyed on `"・"`)
  - `videopipeline/leg_sequence.py:689` (comment)
  - `outrocard.py:1770` and `:1782`
  - Frontend: `src/utils/stopLabel.ts` and the map's pin code (not yet traced).
- Risk: three places test the glyph text itself (`popups.py:2599`, `render_look.py:101/107`, `finale_step.py:134`). With `+1` those tests would stop matching. Change them to test the pin's kind (`is_stopby`), not the text, before changing the glyph.
- Tests: `tests/test_stop_numbering.py` covers the numbering rule; add a check that stop-bys get `+1`, `+2` in visit order, and that stop numbers are unchanged. Update any test that asserts `・`.
- Render version bump, since the pins change.

Open questions:
1. Is the count across the whole route (`+1` is the first stop-by on the route), or per stop (each stop's stop-bys count from `+1`)? Plan assumes across the whole route.
2. Answered: stops skipped in export get `+N`.
3. Answered: video only; the editor map keeps its own numbering.

### 8.8 Renderer: 3D for all overview styles

Reading of the request: every overview video uses the 3D renderer (pydeck, `pydeckrecorder/overview_pydeck.py`), not the 2D one.

What the 3D renderer does today (`route2vdo.py:1096-1100`, `overview_pydeck.py`):
- It runs when `use_pydeck_overview` is on (default off), and never for the course style (`!= "course"`).
- It renders in headless Chromium on the GPU. It ignores every cue (`{start}`, `{n}`, `{go}`, `{end}`, `{extras}`, `{closed}`).
- It has no pop-up cards, no badges, no photo-card timing, no course trace, no stop-by or closed-place pop-ups.

Consequence: "3D for all" cannot keep the cue-driven storyboard. The three styles depend on cues (sections 2–4), and the course style needs the trace. So the change is one of these:

1. **3D for Walk and Route map only**, default on. The course style stays 2D. Cards and cue timing are lost in 3D, so these styles would need the 2D look rebuilt in 3D first. Smallest change, but the 3D video is not the same film.
2. **3D for all three**: the course trace, cards, badges and cue timing are rebuilt in the 3D renderer. Largest change; it is a second renderer.
3. **Keep 2D as the storyboard, use 3D only as the map background** (the 2D overlays drawn over a 3D map). Keeps cues and cards; the map changes look. Medium change.

Safety: every 3D render uses the GPU through Chromium. Per `CLAUDE.md`, ask before any GPU render; the PC has crashed (HYPERVISOR_ERROR) during GPU work. Test renders run on a copy of a project, not a real one.

Render version bump, since the video changes.

Decided: all three styles use the 3D map, viewed straight down (see 8.0). The existing cards, badges, cue timing and course trace are drawn over it (section 9, Phase 3). Nothing is rendered until you approve a GPU run.

### 8.9 Rule: zoom in on clustered pins during the trace (3D)

Rule: when several pins sit in the same place (a cluster), the 3D camera zooms in on that place while the trace passes it, the way an interactive map zooms when you fly to a spot. When the trace leaves the cluster, the camera eases back out.

- **Trigger:** two or more stops (numbered or stop-bys) whose screen distance is inside one pin's width at the current zoom. The same rule as the 2D "zooms into groups of 3+ close stops" (section 4.3, step 4), but measured in the 3D view and applied to any count from 2 up. Threshold is a constant in `tuning.py`, not hard-coded.
- **Motion:** like an interactive map's fly-to: ease in over about 1 s, hold while the walker passes the cluster, ease out over about 1 s. Never a hard cut.
- **Stops inside the cluster:** each stop's `{n}` cue still lights its pin and card, as in 2D. The zoom does not change cue timing.
- **Scope:** applies to the 3D renderer only (option 1, 2 or 3 in 8.8). The 2D course already zooms into groups of 3+ close stops (`course.py` `dense_zooms`); this rule keeps that behaviour and extends the 3D renderer to 2+ stops.
- **Pydeck:** the camera is driven from the pydeck view state per frame (`overview_pydeck.py`), not by a new renderer. Reuse the existing zoom-sequence capture where it fits.
- **Safety:** test on a copy of a project and ask before the GPU render (see 8.8).
- **Tests:** a made-up route with a 3-stop cluster and a 2-stop cluster: the camera zoom is larger during the trace over the cluster than before and after, and returns to the overview frame at the end.

Open question: should the zoom also happen for a cluster that is only near the route (not on it), or only for stops the trace reaches?

### 8.10 `{distance}` shows the summary card, then a recap frame

Reading of the request: the `{distance}` cue is used in every style. When the voice reaches it, the summary card (the totals: distance, time, mode breakdown) appears, and a recap frame is shown, a still of the finished route with that card.

Today: `{distance}` is ignored in Whole route first (section 2), and in Walk it only keeps the ending on screen until that point. The totals card shows at `{end}` (Walk: bottom right; course: top right).

Plan:
- `{distance}` shows the summary card (the same card as today's totals card, moved to that cue in all three styles). `{end}` still ends the trace in course and the route in walk.
- The recap frame: at `{distance}`, the map holds still on the full route with all pins, the summary card, and the route's stop badges. It is held for a fixed time set in project settings (see 8.0). For Walk and Route map this replaces the "map fades back" step (section 4.1 step 7) at that moment; for course it is the frame that is held after the trace.
- Walk and Route map: the recap frame is one still, not the fade. The existing ending zoom (section 4.1 step 9) follows the recap frame if the ending highlight is on.
- Course: `{distance}` comes after `{end}` and before `{extras}`, so the recap frame sits between the totals and the stop-bys. The stop-bys and closed places then pop on top of it.
- Render version bump, since the video changes.

Open questions:
1. Answered: 3 seconds, fixed in project settings (see 8.0).
2. In course, should the stop-bys and closed places pop on top of the recap frame (plan: yes), or after it is cleared?
3. Should the recap frame also be exported as a still image (a thumbnail for the project), or only shown in the video?

### 8.11 Whole route first: `{extras}` shows stop-bys, `{closed}` shows closed places

Reading of the request: in Whole route first, the stop-bys appear only at `{extras}` and the closed places only at `{closed}`. Each cue is the trigger for its own group, with no fallback timing.

Today (`course.py`, cue table section 2): `{extras}` falls back to 4 s after `{end}` when the cue is missing, and `{closed}` has no fallback. Stop-bys and closed places are shown in the order stop-bys, then closed places (section 4.3 steps 6 and 7).

Plan:
- `{extras}`: the stop-by pins and pop-ups appear here and only here. If the script has no `{extras}`, the auto-tagger adds one before the stop-by sentence (`auto_overview_cues`, section 8.6); the 4 s fallback is removed.
- `{closed}`: the closed-place pins and pop-ups appear here and only here, after `{extras}`, with the closed notice.
- Each group pops one by one across its own sentence, as today; the change is only where the group starts.
- Walk and Route map are not changed.
- Render version bump, since the video changes.

Open questions:
1. Answered: those groups are left out of the video.
2. Should the stop-by pins be visible before `{extras}` as dimmed pins (not pop-ups), or stay hidden until the cue?

### 8.12 Numbered stop setting: photo card only, no badge

**Superseded by 8.18:** the `badge` look is dropped, so no setting is needed. A passed stop stays a photo card. The plan below is kept for history.

Reading of the request: a new project setting for what a numbered stop leaves on screen once the walker passes it. The choices: `badge` (today: the stop's pill badge, section 4.4) or `photo_only` (the photo card alone, with no badge).

Plan:
- Setting `passed_stop_look` in the storyboard config: `photo_only` (default) or `badge`. The project setting `overview_passed_stop_look`, shown next to the recap style, overrides it when set.
- `photo_only`: the stop's photo card is shown when the walker reaches the stop and stays as the card, with no badge drawn over it or after it. A stop with no photo shows nothing (no badge either).
- The pin keeps its number, so the card still ties to its stop by the pin (see 4.4, "Lines"). Open question 1 asks whether the pin should be hidden too.
- Applies to Walk and Route map and to Whole route first. In Whole route first, the big photo card still pops and shrinks, but to nothing instead of to a badge.
- Places with no number (stop-bys, closed places) are not changed.
- Render version bump, since the video changes.

Open questions:
1. Answered: the pin keeps its number.
2. Should the setting be per project only (plan: yes), like the recap style?

### 8.13 "Cards stay up" as a project toggle

What exists: the toggle is already in the project's video look settings (`src/components/ui/VideoLookSettings.tsx:208-210`, label "Cards stay up", setting `overview_cards_stay`, default on). It is shown for every style, but the code only uses it for Walk the route. `_cards_stay()` (`spatial_renderer/popups.py:2851-2853`) is `style == "walk" AND overview_cards_stay`, so in Route map and Whole route first the switch does nothing.

Plan:
- The switch stays a project setting in the same place.
- The row's description says which styles it affects, and the switch is greyed out for a style it does not affect, so it is not a switch that silently does nothing.
- Decided: in every style a stop's card pops when the walker or trace passes it and stays up until the end. The default is `cards_stay` in the storyboard config; the project switch can still turn it off.

### 8.14 Top of frame: title, remaining, and whole-route totals only

Reading of the request: the top of the frame shows only three things, in every style:
1. a static project name (not a changing headline),
2. the remaining distance and time,
3. the whole route's distance and time.

Removed from the top of the frame:
- Walk and Route map: mode times, stop count, next stop.
- Whole route first: the changing headline and the "A → B" line. The static project name takes their place.

Plan:
- Walk and Route map: the top bar keeps title, remaining distance and time (left) and whole-route distance and time (right). The mode-time line, stop count and next-stop line are dropped.
- Whole route first: the same bar. The totals that were on the right stay as the whole-route totals.
- The ending (section 4.1 step 9, and the zoom) is not changed.
- Render version bump, since the video changes.

Open questions:
1. Answered: the changing headline goes; the static project name is shown.
2. Answered: yes, the same format in every style.

### 8.15 Bottom of frame: notices on the left, progress beside them

Reading of the request: the bottom bar, in every style, has three things on its left side: the stop-by notice, the closed-place notice, and the progress bar.

Plan:
- Left side of the bottom bar, in order: stop-by notice, closed notice, progress bar. The notices sit at the left edge.
- When a notice pops up, the progress bar shrinks from its left edge so it fits in the room to the right of the notice. Its length is the bar's width minus the notice's width (plus a fixed gap), and it grows back when the notice fades.
- A notice fits its text: its box is as wide as its content, so the progress bar's length follows the notice's real width, not a fixed slot.
- Both notices showing at once: they sit side by side, and the progress bar starts after the second one, with a small gap.
- Course already does this in part (`_course_rail_left` shrinks the progress rail for the stop-by and closed notices). The plan extends the same rule to Walk and Route map.
- Render version bump, since the video changes.

Open questions:
1. Answered: side by side, with the bar beside them.
2. Answered: the bar shortens to fit the room left; no fixed minimum.

### 8.16 Totals card: a design theme, for later

Reading of the request: the totals card (the summary card with distance, time and mode breakdown, section 8.10) is drawn by a design theme that can be swapped. Today there is one design. Future designs are added as more themes, with no change to the cue or layout code.

What exists: `settings.summary_card_style` already picks between several drawings (`glass`, `taskbar`, `columns`, `circles`, `stacked`) in `mapfetcher/graphicengine/cards.py`. That is a partial theme switch for the card's drawing only: it does not change colors, fonts or the card's place in the frame.

Plan:
- A theme is a named set: the card drawing (one of the existing styles or a new one), colors, fonts, and the card's corner in each style.
- New project setting `overview_theme`, default `current` (today's look, unchanged, so no output change for existing projects). Future themes are added to a registry; `current` is the first entry.
- The card reads its drawing, colors and position from the theme, so a new theme is a new entry, not a change to the renderers.
- `summary_card_style` stays as it is; under `current` it keeps working as today. Open question 1 asks whether it folds into the theme.
- Render version bump only when the default look changes (no bump for `current`).

Open questions:
1. Answered: `summary_card_style` becomes part of the theme setting.
2. Answered: the theme setting controls the totals card's shape and design. No new theme is named yet, so the registry starts with `current`.

### 8.17 Sub course: shown at a storyboard slot, to be placed later

Reading of the request: the sub course (the branch drawn from a stop, with its own totals, section 4.1 step 8) appears at a point in the storyboard that you will set later. Until then, the slot exists but its position is a placeholder.

Today: Walk and Route map draw it after the totals (step 8). Whole route first does not draw it at all.

Plan:
- Add a named slot `sub_course` to each style's storyboard (the storyboard template from section 8.1). Its position is set in the style's storyboard config file, not in the renderer, so moving it later is a one-line edit to that file (decided, see 8.0).
- Default position: before the stop-by section in Whole route first, which now draws the sub course. Walk and Route map have no separate stop-by section, so theirs stays after the totals card.
- The sub course shows for the length of its own card (`SUB_COURSE_OVERVIEW_SECONDS`) and then fades. Its totals card follows the theme (section 8.16).
- If the project has no sub course, the slot is skipped (no time is spent).
- Render version bump, since the video changes.

Open questions:
1. Answered: the position is set later in the storyboard config file (see 8.0). No position chosen yet.
2. Answered: yes, before the stop-by section.

### 8.18 Global rule: a card has one spot and one size (all styles)

Decided (option A). Done before Phase 2 (section 9, Task 20).

**Why:** a viewer finds a place's card once. It does not move or change size between the walk and the recap.

**Covers** the cards that stay: start, end, numbered stops, stop-bys and closed places.
**Does not cover** the Route map's big photo and leg card, or the ending zoom's photo. Those keep their own size.

| Rule | Detail |
|---|---|
| One spot | A card appears where it stays: the same spot while the video runs and on the recap frame. It does not move, resize or turn into a badge. |
| One size | Every covered card in a video has the same width and the same photo height. |
| Circles | Approved 2026-11-26: cards sit on a circle round each group of pins (`spatial_renderer/card_circles.py`). No card covers the route, a pin, a panel or another card; no leader crosses or lies on another, or passes under a card; leaders may cross the route. |
| Scale | The size is the largest at which a round circle layout exists, up to a maximum in `tuning.py`. Where none exists down to `OVERVIEW_CARD_CIRCLE_MIN_SCALE` (very many pins), cards go to the nearest free spots, shrinking until all fit and keeping leaders clear where they can. |
| No photo | A place without a photo shows its pin only, with no card and no badge. |
| Planned up front | One layout is worked out before the first frame, counting every card that will ever appear, including later stop-bys and closed places. |
| Clear of | Other cards, the route, pin heads, the top and bottom panels, notices and the totals card. |
| Tie to the pin | A card sits beside its pin where there is room; otherwise a leader line joins them. |
| Leader line | One straight line from the pin to the nearest point of its card, in every style. It passes under no other card where the layout allows. |
| Recap look | The recap shows the same photo cards. The pill badge recap and the `overview_recap_style` setting are removed. The ending clip's own badges are not part of the overview and stay. |
| Zoom (every style that zooms) | Cards never slide: while the camera moves in, each fades out at its spot, then fades in beside its zoomed pin (same size). A card whose pin is out of the zoomed view is gone until the camera is back. Once the view is whole, every card is exactly at its recap spot (`popups.zoom_card_alphas`). |

**Approaches**

| Approach | Trade-off |
|---|---|
| **A. One layout before the first frame, searching for the largest shared size** (picked) | Meets both rules by construction; reuses the existing card layout; needs a size search |
| B. Place each card as it appears, then freeze it | Simple, but a later card with no room breaks the shared size or the fixed spot |
| C. Hand-set slots in the storyboard files | Predictable, but every route has different geography |

Open questions:
1. Answered: a place with no photo shows its pin only.
2. Answered: cards scale until all of them fit.
3. Answered: the `badge` look is dropped.
4. Answered: cards stay during a zoom, adjusted to the zoomed view, and end exactly at their recap spots.

## 9. Implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:executing-plans or superpowers:subagent-driven-development, task by task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** make the three overview styles follow the decisions in section 8.

**Architecture:** one JSON storyboard per style, read through `storyboard.py`. The real video uses the 3D (deck.gl) map, viewed straight down; the existing Python code draws pins, trace, cards and panels on top. A straight-down view keeps today's Web Mercator projection, so the Phase 2 drawing changes carry over, and CPU tests keep working with a plain background.

**Tech stack:** Python 3 + OpenCV + pytest (`src-tauri/src-python`), React 19 + TypeScript + Lingui + Vitest (`src/`).

**Spec:** sections 1–8 of this file. Read 8.0 first.

Paths are under `src-tauri/src-python/` unless they start with `src/`, `tests/` (frontend) or `docs/`. Line numbers were read on 2026-11-26; search for the quoted code if they have moved.

### Global constraints

- Ask before any GPU step, including every Chromium render. All checks below run on the CPU.
- Never render into a real project. Use a copy.
- Python: run from `src-tauri/src-python` with the system `python`. `python -m pytest -q tests` and `python -m ruff check .` stay green. Baseline on 2026-11-26: 1,510 passed.
- Frontend: `npx tsc --noEmit` and `npm test` (from a path with an upper-case `C:\`).
- UI text is American English. New or changed strings need `npm run extract && npm run compile` and a `ja` translation.
- A new project setting is wired in all of: `src/types/index.ts`, `src/config/constants.ts` (default), its settings component, `videopipeline/animator_config.py`, and `route_inputs.overview_flags_hash` when it changes the picture, so the overview renders again.
- Old saved scripts keep their old tags. `localization/cues.py` `CUE_RE` and `src/utils/overviewScript.ts` `CUE` keep matching `route` and `goPreN`, so they are never spoken or shown as text.
- A task that changes the picture bumps `OVERVIEW_RENDER_VERSION` (`spatial_renderer/overview.py:78`, now 74), once per release. Task 7 also bumps `LEG_RENDER_VERSION` (`route2vdo.py:61`, now 40).
- Stop numbering is one rule counted in six places (`CLAUDE.md`, "Stop numbering"). Change all of them together.
- Keep UTF-8 without BOM. Edit files directly, no patch scripts. Comment tags follow the existing `# [NOTE] [..]` style.
- Commit only when the user asks. No attribution lines in commits or pull requests. Run `graphify update .` after code changes.

### Review focus

1. A saved script with `{route}` or `{goPreN}`: renders, tags are silent. (Tasks 3, 4)
2. A script missing `{distance}`, `{extras}` or `{closed}` with auto-tagging off: the video renders; the totals card shows at `{end}`; places whose cue is missing are not shown, and no notice appears for them. (Tasks 8, 9)
3. A route with 1 stop, and one with 30: no length clamp, no crash. (Task 5)
4. Ten or more stop-bys: `+10` fits inside the pin and the badge. (Task 7)
5. A very long project name or two notices at once: nothing overlaps, the progress rail never gets a negative length. (Tasks 10, 11)

### Decisions (2026-11-26)

| # | Decision |
|---|---|
| D1 | The real video uses the 3D map. Phase 3 is required before release |
| D2 | A passed stop's card pops and stays up until the end, set by `cards_stay` in the storyboard config |
| D3 | A missing `{extras}` or `{closed}` drops those places; no fallback code |
| D4 | The sub course plays before the stop-by section by default, set by `sub_course_slot` in the storyboard config |
| D5 | Two notices sit side by side; the bar beside them shortens to fit, with a small gap |
| D6 | The camera looks straight down (pitch 0). No tilt setting |
| D7 | A passed stop stays a photo card, also at the recap. The badge look is dropped (8.18) |

### Phase 1: carries over to 3D

#### Task 1: Finish the storyboard config (8.1)

Already done and passing: `services/vdoprocessing/storyboard.py`, `storyboards/{walk,map,course}.json`, and the call sites in `spatial_renderer/overview.py`, `overview_animation.py`, `popups.py`, `transitions.py` (uncommitted).

**Files:** modify `route2vdo.py` (`_course_brief_legs`, the `arrival_slow_seconds` block, the pydeck condition), `videopipeline/overview_framing.py` (`_overview_bbox`), `videopipeline/narration_step.py` (source-ids key), `videopipeline/pipeline.py` (`set_visit_all_stopbys`), `localization/overview_script.py` (`plan_budget`, `_TourWriter.stop_piece`); create `tests/test_storyboard.py`.

**Interfaces (produces):** `storyboard.of(style: Optional[str]) -> Storyboard`, `storyboard.for_config(config: dict) -> Storyboard`.

- [ ] Write `tests/test_storyboard.py`:

```python
def test_each_style_reads_its_own_file():
    assert [of(s).name for s in ("walk", "map", "course")] == ["walk", "map", "course"]
    assert of("map").leg_cards and not of("walk").leg_cards
    assert of("course").traced_route and not of("course").pydeck_allowed
    assert of("course").arrival_slow_seconds == 3.0

def test_unset_or_unknown_style_is_walk():
    assert of(None) is not None and of(None).name == of("nope").name == "walk"
```

- [ ] Replace each remaining style comparison with the field: `course_brief_legs`, `arrival_slow_seconds`, `pydeck_allowed`, `course_frame`, `script_intro_in_key`, `visit_all_stopbys`; in `overview_script.py`, `traced_route` for the course budget and `leg_cards` for the leg facts line.
- [ ] Check no comparison is left: search `services` for `== "course"`, `!= "course"`, `== "map"`. Only `overview_framing._course_config`'s data check and `overview_style()` itself may remain.
- [ ] Run pytest and ruff. Expected: all pass, with no change to any existing test. No version bump.

#### Task 2: Beat timings in the storyboard files (8.4)

**Interfaces (produces):** `Storyboard.timings: Mapping[str, float]`; callers read `sb.timings["name"]`. A project setting, where one exists, still wins.

| Key | Replaces in `tuning.py` | walk | map | course |
|---|---|---|---|---|
| `sub_course_seconds` | `SUB_COURSE_OVERVIEW_SECONDS` | 8.0 | 8.0 | 8.0 |
| `cue_wait_seconds`, `max_leg_seconds`, `intro_clean_hold_seconds` | the defaults behind the `overview_*` settings of those names (2.0 and 10 for the first two; copy the current value of the third) | yes | yes | no |
| `map_photo_seconds`, `map_slide_seconds`, `map_min_stop_seconds` | `OVERVIEW_MAP_PHOTO_SECONDS`, `_SLIDE_`, `_MIN_STOP_` | no | 0.8, 0.5, 3.5 | no |
| `open_zoom_seconds`, `pass_card_seconds`, `pass_card_min_seconds`, `stats_slide_seconds` | `COURSE_OPEN_ZOOM_SECONDS`, `COURSE_PASS_CARD_SECONDS`, `COURSE_PASS_CARD_MIN_SECONDS`, `COURSE_STATS_SLIDE_SECONDS` | no | no | 1.2, 2.5, 1.8, 0.6 |

- [ ] Test: `of("course").timings["open_zoom_seconds"] == 1.2`; `of("map").timings["map_min_stop_seconds"] == 3.5`.
- [ ] Move the values, delete the replaced constants, and update every use (search each name, tests included). Store `arrival_slow_seconds` as the number 3.0 and remove the constant-name lookup in `_load`.
- [ ] pytest and ruff pass. No version bump.

#### Task 3: Remove `{route}`; the trace starts at `{start}` (8.5)

**Files:** `spatial_renderer/course.py` (`_course_timing`, module docstring), `localization/overview_cues.py` (`_sentence_marks`, docstring), `localization/overview_script.py` (`build_course_script`, near line 1031), `tuning.py` (delete `COURSE_PIVOT_HOLD_SECONDS`), `tests/test_course_script.py:159`.

- [ ] Tests: `_course_timing({"start": 0.0}, ...).route_at == 1.2`; `_course_timing({"start": 4.0, "route": 9.0}, ...).route_at == 4.0`; with no cues, `route_at == 1.2`; the tagged script reads `{start}これが全体のルートです。加太駅から`.
- [ ] `route_at = max(cues.get("start", 0.0), open_zoom_seconds)`. A `route` cue is ignored. The script writer and auto-tagger no longer add it.
- [ ] pytest passes. Version bump.

#### Task 4: Delete `{goPreN}` (section 6, rule 3)

**Files:** `localization/overview_script.py` (`_via_batch_lines`), `localization/cues.py` (docstring only), `spatial_renderer/overview.py` (the `goPre` reads near lines 195, 420, 510–522, 667–671), `overview_animation.py` (near line 499), `tests/test_route_brief.py:358-370`.

- [ ] Tests: the built script contains the "見えてきます" line and no `goPre`; `strip_cues("見えてきます。{goPre4}")` leaves no tag in the text.
- [ ] Remove the tag writer and the renderer's `goPre` reads. A stop-by batch uses the same hold it uses today when the cue is missing.
- [ ] pytest passes. Version bump.

#### Task 5: No length limit (8.2)

**Files:** `localization/overview_script.py` (lines 155–159, 412–425, 509, 531, 587), `services/cli/script_commands.py:14-40`, `tests/test_route_brief.py:298,414-420`, `src/utils/overviewScript.ts`, `src/features/map/components/OverviewNarration.tsx:145-149`, `tests/utils/overviewScript.test.ts`, `tests/features/map/components/OverviewNarration.test.tsx`.

**Interfaces (produces):** `overview_target_seconds(project, stops)` returns the setting, else `20 + 7 * stops`. The length command no longer returns `within_60_90s`, `min_seconds`, `max_seconds`. `OverviewLength` is `{ chars_per_second, target_seconds }`.

- [ ] Tests: target for 1 stop is 27.0, for 30 stops 230.0, with `overview_target_seconds: 45` it is 45.0; `plan_budget` has no `fits` key.
- [ ] Delete `TARGET_MIN_SECONDS`, `TARGET_MAX_SECONDS`, `in_overview_range`, `fits` and `lengthVerdict`. The editor readout becomes `About {seconds} s spoken (aim {target} s)`.
- [ ] Keep the 3 s audio/video tolerance. pytest, tsc and `npm test` pass; Lingui extract and compile.

#### Task 6: A switch for each automatic cue (8.6)

**Settings (all default true, per project):** `auto_cue_n`, `auto_cue_go`, `auto_cue_start`, `auto_cue_extras`, `auto_cue_closed`, `auto_cue_scene`. `auto_overview_cues` stays the master.

**Files:** `localization/overview_cues.py`, `videopipeline/narration_step.py` (`add_overview_cues`, `CueStore`), `src/components/ui/VoiceSettings.tsx` ("Timing cues" section), `src/types/index.ts`, `tests/test_overview_cues.py`, `tests/components/ui/VoiceSettings.test.tsx`.

**Interfaces (produces):** `auto_tag_overview(script, labels, skip: frozenset[str] = frozenset())`, with kinds `"n" "go" "start" "extras" "closed"`. `CueStore.put_text` / `cued_text` also store and compare the skip set, because a stored tagged script is reused today.

- [ ] Tests: each kind in `skip` leaves no such tag; a tag the user typed stays; run with `auto_cue_go` off, then on again, and `{go}` is back; with the master off nothing is added.
- [ ] UI: six switches under the master, disabled when it is off.
- [ ] pytest, tsc, `npm test`, Lingui.

#### Task 7: Stop-by pins show `+N` (8.7)

**Files:** `services/vdoprocessing/route_inputs.py`, then every `・` pin site listed in 8.7 (video only), `tests/test_stop_numbering.py`, `test_leg_pin_glyphs.py`, `test_waypoint_toggles.py`, `test_look_options.py`, `test_pinimage.py`.

**Interfaces (produces):** `stopby_labels(waypoints: list) -> dict[int, str]` (waypoint index to `"+1"`, counted in route order over stop-bys and skipped stops; start, end and closed places excluded; a return stop reuses the first visit's label) and `is_stopby_label(label: str) -> bool`.

- [ ] Tests: the existing badge list becomes `["S", "1", "+1", "+2", "×", "3", "E"]`; the leg glyphs become `["S", "+1", "+2", "1", "2", "+3", "E"]`; a 12-stop-by route ends at `+12`.
- [ ] First change the three text checks (`popups.py:2599`, `render_look.py:101,107`, `finale_step.py:72,134`) to `is_stopby_label`, then change the glyph sources. `video_text.py` and Japanese text separators keep `・`.
- [ ] Render one pin and one badge with `+12` in a test and assert the text box is inside the badge.
- [ ] `src/utils/stopLabel.ts` is not changed. pytest passes. Bump both render versions.

### Before Phase 2

#### Task 20: One spot and one size for cards (8.18)

**Files:** `spatial_renderer/popups.py` (`_layout_ring_cards`, `_hud_card` / `_card_box_beside_badge`, the pill badge recap), `spatial_renderer/overview.py` (`_ov_layout_stay_cards`, `_ov_write_recap_preview`), `overview_animation.py`, `course.py` (`_course_pass_cards`), `tuning.py` (`OVERVIEW_CARD_MAX_SCALE`), `videopipeline/render_look.py`, `src/components/ui/VideoLookSettings.tsx`, `src/types/index.ts`.

- [x] One layout pass before the first frame returns each covered place's box and the shared scale; the walk and the recap both read it.
- [x] Tests: every covered card has the same size; each card's box on the frame it appears equals its box on the recap frame; 24 places do not overlap; 5 places come out larger than 24; the scale never passes the maximum.
- [x] Tests: 60 places all get a card (no minimum size, none dropped); a place without a photo gets no card and no badge.
- [x] Tests: stop-bys that appear last have their spots reserved from the start; Route map's big photo and the ending zoom keep their size.
- [x] Remove the overview's pill badge recap and `overview_recap_style`. The ending clip's badges (`finale_step`) stay. (The badge recap code remains only for a storyboard with `cards_stay` off; none ships that way.)
- [x] Walk first; Route map and Whole route first take the same layout when their cards stay up (Task 12). Whole route first: cards stay during a zoom and are exactly at their recap spots once the view is whole again. Version bump.

### Phase 2: drawing changes

These draw in screen space, over whatever map is underneath, so Phase 3 does not redo them (it only changes where points land).

#### Task 8: `{distance}` shows the totals card and holds the recap (8.10)

**Setting:** `overview_recap_hold_seconds`, default 3.0. **Files:** `course.py` (`_course_timing`), `spatial_renderer/overview.py` (`_ov_hold_summary`, `_ov_play_ending_highlight`, `_ov_write_ending`), settings files.

- [ ] Course tests: `stats_at` equals the `distance` cue; without it, the `end` cue; stop-bys may pop on top of the card.
- [ ] Walk and map tests: with a `distance` cue the totals card appears at it and the ending zoom starts no sooner than cue + hold; without it, behavior is as today; a voice shorter than the hold still gets the full hold.
- [ ] No thumbnail export. Version bump.

#### Task 9: `{extras}` and `{closed}` start their own groups (8.11, D3)

**Files:** `course.py` (`_course_timing`; delete `_EXTRAS_AFTER_SECONDS`).

- [ ] Tests: each group starts at its cue; with no `extras` cue `extras_at is None`, no stop-by pin, card or notice is drawn, and `end_at` is not extended for it; the same for `closed`.
- [ ] Remove both fallbacks. pytest passes. Version bump.

#### Task 10: Top of frame (8.14)

**Files:** `mapfetcher/graphicengine/cards.py` (`render_overview_hud`), `overview_animation.py` (`_apply_hud`), `spatial_renderer/overview.py` (`_ov_reset_hud`), `course.py` (`_course_panels`, `_composite_course_panels`), `services/video_text.py` (new `overview_total_hud`, `en` and `ja`), `videopipeline/overview_framing.py` (drop `overview_taglines`).

**Interfaces (produces):** `render_overview_hud(frame, title=None, remaining_km=None, remaining_seconds=None, total_km=None, total_seconds=None, alpha=1.0, top_margin=20, side_margin=32)`.

- [x] Left: title (`overview_title`, else `project_name`). Right: remaining, then whole route, in one format. No mode times, stop count, next stop, progress bar, headline or "A → B".
- [x] Course computes remaining as total × (1 − traced share).
- [x] Tests: a 60-character Japanese name stays inside its panel and clear of the right panel; missing totals draw the title only. Version bump.

#### Task 11: Bottom of frame (8.15, D5)

**Files:** `cards.py` (`render_stopby_notice`, `render_route_progress_rail`), `course.py` (`_course_rail_left`, `_reserve_notices`), `overview_animation.py` (notice writer), `tuning.py` (`NOTICE_RAIL_GAP`, frame pixels).

- [ ] Walk and map draw the same rail as course. Each notice is as wide as its text. Two notices sit side by side at bottom left (course does this today).
- [ ] Rail left edge = right edge of the last visible notice + `NOTICE_RAIL_GAP`; its right edge stays put; the change eases with the notice fade. With too little room for its markers the rail is not drawn.
- [ ] Tests: no notice gives the margin; one and two notices put the rail after them; very long notices never give a negative length; the badge layout still keeps clear of the notices. Version bump.

#### Task 12: A passed stop's card stays up (8.13, D2)

**Files:** `storyboards/{map,course}.json` (`"cards_stay": true`), `popups._cards_stay` (already `cards_stay and overview_cards_stay`), `overview_animation.py` (map style), `course.py` (`_course_pass_cards`), `VideoLookSettings.tsx:208-210` (description names every style).

- [x] Map: the big photo and leg card play as today; after the walker leaves, the stop's photo card stays, as in Walk.
- [x] Course: the card that pops on pass stays at card size and does not shrink into a badge; cards do not overlap (reuse the card lattice).
- [x] Kept cards take their spot and size from Task 20's layout (8.18).
- [x] Tests: one per style for on (the card is on the last route frame) and off (today's behavior). Version bump. (Course off: a card closes when the next pops, up at least 1.8 s, and all return when the trace ends.)

#### Task 13: Passed stop look: photo card by default (8.12, D7)

**Dropped (8.18):** with the `badge` look gone there is only one look, so there is no setting. Task 20 covers it: cards stay photo cards, also on the recap frame, the pin keeps its number, and a place without a photo shows its pin only.

#### Task 14: Theme setting (8.16)

**Setting:** `overview_theme`, default `"current"`. **Interfaces:** `tuning.OVERVIEW_THEMES = {"current": {}}`; a theme may set `card_style`. Card style = theme's `card_style`, else the project's `summary_card_style`, else the default. Course keeps its circles card under `current`.

- [ ] Tests: `current` gives today's card for each `summary_card_style`; an unknown theme behaves as `current`. No selector in the UI until a second theme exists. No version bump.

#### Task 15: Sub course slot (8.17, D4)

**Files:** the storyboard files (`"sub_course_slot"`: `"after_totals"` in walk and map, `"before_stopbys"` in course), `storyboard.py`, `spatial_renderer/overview.py` (`_render_sub_course_part`), `course.py`.

- [ ] Course, `before_stopbys`: the sub course draws between the totals card (after the recap hold) and `{extras}`, for `sub_course_seconds`. If the voice leaves less time, the stop-by pops wait until it finishes. No new cue.
- [ ] Course with no `{extras}` cue, or `after_totals`: it draws after the totals card.
- [ ] Tests: course draws it before the first stop-by pop; a short gap delays the stop-bys; no sub course changes no frame count; walk and map are unchanged. Version bump.

### Phase 3: the 3D map, straight down (8.8, 8.9, D1, D6). Required before release

What exists already (read on 2026-11-26): `MapFetcher.fetch_image` draws the overview background through the deck.gl page, top-down, for Whole route first whenever there is a Mapbox key, and for the other styles only for a non-default map language or `overview_background: "pydeck"`. `compute_pydeck_view` returns an extent that the existing projection uses unchanged. `course.py` already captures zoomed GL views (`_course_gl_frames`).

Every browser capture uses the GPU: ask first, and use a copy of a project. Automatic tests replace the capture with a fake, so they stay on the CPU.

#### Task 16: Every style on the 3D map

**Files:** `services/mapfetcher/mapfetcher.py` (`fetch_image`), `tests/test_mapfetcher_overview_background.py` (create, or extend the existing `fetch_image` test if one exists).

- [ ] The overview background is the deck.gl capture for every style. A missing Mapbox key or a failed capture raises an error that says which; no silent raster fallback.
- [ ] Check every other caller of `fetch_image` (`popups.py:3173`, `services/cli/gps_commands.py:132`) still wants this, and keep the raster path only for a caller that is not the video.
- [ ] Tests: each style calls `fetch_overview_image_pydeck`; no key raises; a capture error raises.

#### Task 17: Cluster zoom, Whole route first (8.9)

**Files:** `spatial_renderer/course.py` (`dense_zooms`), course storyboard (`"cluster_min_stops": 2`), `storyboard.py`, `tuning.py` (replace `COURSE_DENSE_MIN_STOPS`).

- [ ] A run of 2 or more stops within one pin width zooms in, easing in and out over about 1 s, for stops the trace reaches. Cue timing is unchanged.
- [ ] Tests: 2-stop and 3-stop clusters zoom; spread stops do not; the view returns to the whole map. Version bump.

#### Task 18: Cluster zoom, Walk and Route map (8.9)

**Files:** `spatial_renderer/overview_animation.py`, walk and map storyboards (`"cluster_min_stops": 2`).

- [ ] Reuse `zoom_view`, `dense_zooms` and the GL view capture from `course.py`; move any shared function out of the course module rather than copying it. Cards that stay up follow 8.18's zoom rule (`popups.zoom_card_alphas`): cross-fade, no sliding, off-view cards hidden, recap spots once the view is whole.
- [ ] Same tests as Task 17, for walk and map. Version bump.

#### Task 19: Remove the old flat overview

**Files:** `route2vdo.py` (pydeck branch near line 1096), delete `pydeckrecorder/overview_pydeck.py`, `tuning.DEFAULT_USE_PYDECK_OVERVIEW`, `animator_config.py`, storyboard `pydeck_allowed`, and every `use_pydeck_overview` use.

- [ ] That path ignores all cues; remove it and its setting. Old projects that carry the setting render normally.
- [ ] pytest, ruff, `npx tsc --noEmit` and `npm test` pass. Bump `OVERVIEW_RENDER_VERSION`.
- [ ] Approved GPU run of all three styles on a copy of a project; check the frames at every cue.
