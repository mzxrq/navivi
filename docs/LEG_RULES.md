# Walking leg videos: how they work today (audit)

Branch `chore/pipeline-audit` (commit `2661bcc` plus the restore listed in [OVERVIEW_RULES.md](OVERVIEW_RULES.md), not committed yet), 2026-11-26.
Read from the code. Only the timing rules were tried, as small calculations. **No leg was rendered** (that uses Chromium and the GPU).

A *leg* is the video of the way from one stop to the next. This covers the default renderer (`pydeckrecorder/pedestrian.py`). The 2D renderer is used for airplane legs, or for all legs with `use_pydeck_pedestrian: false`; its rules are not covered here.

## 1. Global rules

| Topic | Rule |
|---|---|
| Voice | A leg speaks the narration of the stop it walks **toward**. |
| What it speaks | Attraction videos on: only the arriving text, if that stop has its own attraction video. Otherwise arriving text plus attraction text. |
| Sound | The clip is silent. The voice is added at export. `<clip>.timing.json` stores the voice delay. |
| Where legs start and end | Normal stops, plus the trip's start and end. Stop-bys are merged into the leg around them (`merge_stopby_waypoints`, on). A stop skipped in export never ends a leg. |
| Pieces | A pause at a stop-by cuts the leg into more files (`_cont1`, `_cont2` …). Each piece speaks its own target's narration. |
| Voice longer than a piece | The last frame is frozen until the voice fits. |
| Camera | North up, flat, still. It frames the whole leg (up to the first connected stop-by), zoom at most 17.5. |
| Transport | Each leg has one mode. A ferry leg uses the routed ferry line, else a straight line. |
| Reuse | A leg renders again only when its own inputs change. |

## 2. Timing

The voice decides how long the walk takes.

| Rule | Value |
|---|---|
| Deadline to arrive | `{end}`, else `{arrive}`, else the end of the voice |
| Late arrival | Never |
| Early arrival | At most 3 s before the deadline (`max_early_arrival_seconds`). The walker waits until the voice ends |
| Shortest walk | 4 s |
| Narrated stop without cues | Walks at its natural pace, limited to the window above |
| Stop with no voice | Natural pace, silent |
| Leg with no voice at all | One pace for the whole leg |
| Natural pace | Paced from distance: about 14 s on average (`res_target_avg_seconds`), at most 16 s |

Examples with a 20 s voice and a 12 s natural walk:

| Script | Walk | Wait after arriving |
|---|---|---|
| no cue | 17 s | 3 s |
| `{end}` at 15 s | 12 s | 8 s |
| `{walk on 5}` | 22 s | none |

## 3. Cues in a leg script

| Cue | Effect |
|---|---|
| `{start}` | The walk starts here. The opening's last frame is held until then; if the opening is longer, the voice starts later |
| `{end}`, `{arrive}` | The walker must have arrived |
| `{walk on N}` | Arrives up to N s after the voice ends. It may be up to 3 s sooner than N |
| `{slow}…{/slow}` | Slower (0.2 times). `pace_slow_factor` changes it |
| `{fast}…{/fast}` | Faster (1.6 times) |
| `{stop}…{/stop}` | Stands still (ignored under 0.8 s) |
| `{at N}`, `{at N%}` | At turn N, or N% of the way, when the voice gets there |
| `{view}…{/view}` | Street view card up during these words |
| `{view wait}` | Same, and the walker stops there. `slow` also eases in |
| `{turn}`, `{turn wait}` | The same for automatic turn photos |

- A leg with `{view wait}` **ignores** `{slow}`, `{fast}` and `{stop}`.
- A cue that does not fit its piece is skipped.
- **Automatic cues** (`auto_narration_cues`) are only added to a script that has none: `{start}` after the first arriving sentence (if there are two or more), `{end}` where the attraction text begins.

## 4. Storyboard of one leg

| # | On screen | Timing |
|---|---|---|
| 1 | First frame: a slightly wider view of the start, or the last view of the leg before | |
| 2 | Departure photo fullscreen, shrinks to a card on the start pin (the destination photo if there is no departure photo) | card held 1 s |
| 3 | Camera eases into the leg's framing | 0.6 s, or 1 s when continuing from the leg before |
| 4 | Hold until `{start}` | if needed |
| 5 | Walk: dot moves, walked line is colored, panels update | planned time |
| 6 | Stop-bys, street views and closed places on the way (section 5) | |
| 7 | Arrived: counters show 0 | 1 s (with a destination photo) |
| 8 | Camera slides the destination to the middle, a little low | 1 s |
| 9 | Small photo card, waits for the voice, grows fullscreen | grows in 0.4 s |
| 10 | Clip ends on the full photo and dissolves into the attraction video | 0.8 s (`attraction_fade_seconds`) |

Without a destination photo: after step 6 the map holds until the voice ends, then zooms out (unless the next leg continues from this view).

### Panels

| Place | Panel |
|---|---|
| Top left | Places on this leg: A → stop-by → B |
| Top center | Stop N of total (return stops are not counted) |
| Top right | "Heading to X", then "soon" under 60 m |
| Under it | Compass |
| Bottom right | Distance and time left for the leg and the trip |
| Bottom left | Elevation profile, only with the heatmap on |

## 5. What happens at each kind of place

| Place | In the leg |
|---|---|
| Numbered stop (destination) | Steps 7 to 10 |
| Stop with an empty attraction text and no video | Photo stays a small card, never fullscreen. No attraction video. At a leg's end the next leg slides on with the card; a visited stop-by still cuts the leg |
| Return stop | Small card only. The leg to or from it does not open on a fullscreen photo |
| Connected stop-by with photo | Walk pauses: card, fullscreen, cut. The new piece shrinks the photo back and walks on |
| Unconnected stop-by with photo | Card pops while the walker keeps moving. No cut |
| Same, in **Whole route first** | Visited. Within 100 m of the line, or visible in the frame: pause at the nearest point. Farther: the camera flies there and back |
| Closed place with photo | Pauses like a visited stop-by (same near / far rule as the row above), with a `×` marker |
| Stop skipped in export | Card only |
| Street view | Card at its spot, or timed by `{view}` |
| Turn photo | With `street_photos_at_turns` (off) and a Mapillary key, walking legs only |

## 6. Between legs

| Situation | What happens |
|---|---|
| Next leg starts within 100 m of this one's end (not airplane) | It opens on this leg's last view and glides to its own. The walked line stays |
| `quiet_stop_transition: "zoom"` | No sliding: each leg opens and closes on its own (return stops still join) |
| Clip order in the film | Each leg or piece, then the attraction video of the place it walked to |
| First stop (no leg arrives there) | Its attraction video plays before the leg that leaves it |

## 7. Differences for Whole route first

- The walker slows down over the last 3 s before each stop.
- Every stop-by with a photo is visited, narrated and gets its own attraction video.

## 8. Settings

| Setting | Default |
|---|---|
| `use_narration_cues` | on |
| `auto_narration_cues` | on |
| `max_early_arrival_seconds` | 3 |
| `res_target_avg_seconds` | 14 |
| `res_max_segment_seconds` | 16 |
| `merge_stopby_waypoints` | on |
| `quiet_stop_transition` | `slide` |
| `pace_slow_factor` / `pace_fast_factor` | 0.2 / 1.6 |
| `attraction_fade_seconds` | 0.8 |
| `street_photos_at_turns` | off |
| `show_route_heatmap` | off |
| `res_follow_pitch` | 0 (flat) |
| `use_pydeck_pedestrian` | on |

## 9. Rules that do not match

1. **A stop's photo hold time is ignored.** The opening card is always held 1 s: the code applies a 2 s minimum and then a 1 s maximum. The app has no control for `freeze_seconds`.
2. **"Photo card: Boxed / Full photo" does nothing in these legs.** The arrival photo always goes fullscreen, except at return stops and stops with nothing to tell. A code comment still says the setting decides it.
3. **With attraction videos on, automatic cues add no `{end}`** for a stop that has its own video, so the walker only has to arrive by the end of the voice.
4. **Closed places differ by video:** the leg pauses on them fullscreen, the Walk overview just passes.
5. **Old notes:** the project guide says `{slow}` is 0.5 times (it is 0.2). Code comments still say only the first leg shows a departure photo.

## 10. Decisions for the redesign

1. One shared rule for photo cards (fullscreen or boxed, and for how long) in overview and legs?
2. Should closed places pause a leg?
3. Should a leg always have an arrival deadline at the place's name?
