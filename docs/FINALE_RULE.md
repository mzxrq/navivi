# Finale rules

The finale is the clip (`98_finale.mp4`) between the last walking or attraction clip and the outro. The camera pulls back from the last stop's photo to the whole route, and the route's stops and summary card come in. Code: `services/vdoprocessing/videopipeline/finale_step.py`. Related: [OUTRO_RULE.md](OUTRO_RULE.md), [INTRO_ENDING_RULES.md](INTRO_ENDING_RULES.md) (audit of the current behaviour).

## 1. When it runs

| Rule | Value |
|---|---|
| Settings | `enable_finale` (default on) **and** `enable_outro` (default on). Either off = no finale |
| Needs | A GPS track with 2 or more points, 2 or more stops, and a photo for the last stop |
| Otherwise | Skipped and logged. The outro follows the last stop directly |
| Failure | Any exception is logged and the clip is skipped (it never fails the render) |
| Cache | Rendered again only when forced or when its inputs change (`clip_cache`) |

## 2. What it shows, in order

| Beat | Length | On screen |
|---|---|---|
| 1. Photo | `FINALE_PHOTO_SECONDS` = 1.0 s | The last stop's photo, full frame (skipped for an end stop without narration, §8) |
| 2. Pull-back | `FINALE_ZOOM_SECONDS` = 2.5 s | The photo shrinks onto its pin (without beat 1, its card starts there) while the camera pulls back on real map tiles from `FINALE_ZOOM_BOOST` = 3.5 zoom levels closer than the whole route. The route unspools backwards from the last stop, each stop's card lands as the line reaches it, and the summary card's distance and time count up over 1.1 s |
| 3. Hold | At least `FINALE_HOLD_SECONDS` = 3.0 s | The whole route with its summary card |

The route finishes drawing at 70% of the pull-back (`_ROUTE_DRAW_FRACTION`).

## 3. Voice

| Rule | Value |
|---|---|
| Source | `finale_narration` in the project, only when its voice was made for the current words |
| Start | From the first frame |
| Length | The hold is stretched so the voice ends `FINALE_VOICE_TAIL_SECONDS` = 0.8 s before the clip ends |
| No voice | The hold stays at 3.0 s |

## 4. Stop pins and cards

- Each stop's card is set by `card_style` (§8): `pill` (default) is the slim pill layout the overview recap uses, with no leader lines (`_recap_badges`). `popup` is the overview recap's pop-up card (`_layout_ring_cards`): small cards (at most `FINALE_POPUP_CARD_SCALE` = 0.55) arced round each group of pins, with straight leader lines in the pin's colour that run under the pins.
- Each stop's pin is set by `pin_shape` (§8): `teardrop` (default, the numbered map pin) or `dot`.
- Stop-bys and closed places are left out unless `include_stopby_waypoint` / `include_closed_waypoint` (§8) are on. When shown, a stop-by is `+N` and a closed place `×`; only stops are numbered.
- Stop numbering follows the one rule in `CLAUDE.md` (S, 1, 2 … E, return stops share their first visit's number).
- Colours come from the project's own settings, read through `render_look` (`_stop_colors`).

## 5. Hand-offs

- **Into the finale:** the last walking or attraction clip.
- **Out of the finale:** the outro cuts in directly, unless a sub course plays first (see [OUTRO_RULE.md](OUTRO_RULE.md)).
- **Sub course:** currently placed after the finale. See [INTRO_ENDING_RULES.md](INTRO_ENDING_RULES.md) §5.
- The finale reads `job_config.json` from the folders above the output directory. A test render outside the project has no finale.

## 6. Tuning

All numbers live in `services/tuning.py` (the `FINALE_*` block, around line 1327). Change them there, not in `finale_step.py`.

## 7. Checks

- `tests/test_finale.py` covers the clip and the storyboard settings; stop numbering is in `tests/test_stop_numbering.py`.
- To preview a finale frame without a full render, use the recap shoot script (`.agents/scratch/recap-layout/shoot.py`) on a copy of the project.

## 8. Storyboard settings

The finale's look is set in `services/vdoprocessing/storyboards/finale.json`, next to the overview's `walk.json`, `map.json` and `course.json`. Without a key, the default below applies.

| Key | Values | Default | What it does |
|---|---|---|---|
| `pin_shape` | `teardrop`, `dot` | `teardrop` | The stop's pin on the whole-route map: the numbered map pin, or a plain dot (as the overview's `ending_pin_shape`) |
| `card_style` | `pill`, `popup` | `pill` | The stop's card: the slim pill badge, or the overview's pop-up card |
| `hud` | `overview`, `summary` | `overview` | `overview`: the overview recap's title card, totals, travel modes and route strip, from the project's `hud.json`; the route is framed between them and the cards keep clear. A project without a `hud.json` shows the plain totals card, as `summary` does |
| `include_stopby_waypoint` | `true`, `false` | `false` | `true`: every stop-by (`+N`), on the route or off it, gets its pin and card |
| `include_closed_waypoint` | `true`, `false` | `false` | `true`: every closed place (`×`), on the route or off it, gets its pin and card |
| `shrink_without_voice` | `true`, `false` | `true` | Only when the **end stop** has no attraction narration (and no video of its own). `true`: the photo shrinks onto its pin, as in §2. `false`: no full-frame photo; the first frame is the map with the photo's pop-up card on its pin, and the camera zooms out while the card fades |

Rules:
- A project setting `finale_` plus any key above (for example `finale_include_stopby_waypoint`) (in `job_config.json` `settings`) wins over the file. A value not listed above is ignored.
- The finale's own narration (§3) does not change the opening.

Editing the file or a setting renders the finale again. The settings have no control in the app yet.
