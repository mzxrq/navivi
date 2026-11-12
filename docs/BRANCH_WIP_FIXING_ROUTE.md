# Branch summary: `WIP/fixing-route`

What this branch changes compared with `main`: 93 commits from 2026-10-29 to 2026-11-12, plus the work not yet
committed on 2026-11-12. In total 236 files change (+13,279 / −8,193 lines). About a fifth of that is the two
translation catalogs (`src/locales/{en,ja}`), which are re-extracted with almost every UI change.

Each item names its commit (short hash) so `git show <hash>` takes you to the code. Parts of the app are named the way
the app names them: a **leg** is the walking clip between two stops, an **attraction clip** is a stop's photo clip, and
a **cue** is a `{tag}` in a narration script that is never spoken but tells the video where the voice is.

Contents

1. [Where the lines went](#1-where-the-lines-went)
2. [Code structure (refactors)](#2-code-structure-refactors)
3. [Script cues added or changed](#3-script-cues-added-or-changed)
4. [Overview video](#4-overview-video)
5. [Walking legs](#5-walking-legs)
6. [Kinds of stop: stop-bys, return stops, closed places, street views](#6-kinds-of-stop)
7. [Attraction clips and photos](#7-attraction-clips-and-photos)
8. [Intro](#8-intro)
9. [Finale and outro](#9-finale-and-outro)
10. [Voice (TTS) and pronunciation](#10-voice-tts-and-pronunciation)
11. [Subtitles](#11-subtitles)
12. [Timeline editor and "Make again"](#12-timeline-editor-and-make-again)
13. [Map editor, project files and the Rust shell](#13-map-editor-project-files-and-the-rust-shell)
14. [Reliability fixes](#14-reliability-fixes)
15. [Code removed](#15-code-removed)
16. [New settings](#16-new-settings)
17. [New and deleted files](#17-new-and-deleted-files)
18. [Tests](#18-tests)
19. [Uncommitted work (2026-11-12)](#19-uncommitted-work-2026-11-12)
20. [Open ends](#20-open-ends)

---

## 1. Where the lines went

| Area | Share of changed lines |
|---|---|
| `pydeckrecorder/` (leg and 3D renders) | 17% |
| `videopipeline/` (pipeline stages) | 16% |
| Translation catalogs (en + ja) | 20% |
| Python tests | 9.5% |
| Other `vdoprocessing/` (outro, intro, img2vdo, route2vdo) | 7.5% |
| `services/` top level (mostly `tuning.py`) | 6.7% |
| `tts/` | 3.3% |
| `spatial_renderer/` (2D overview) | 2.5% |
| Frontend `src/` without locales | ~8% |
| Rust `src-tauri/src/` | 0.5% |

---

## 2. Code structure (refactors)

The two biggest files were split before any feature work started.

**`21ff863` — split `pedestrian.py`, `render_step.py` and `tuning.py`** (28 files, +2,382 / −2,961)

- `pydeckrecorder/pedestrian.py` lost about 1,400 lines into new modules:
  - `leg_camera.py`: leg camera framing and moves
  - `leg_hud.py`: the leg's on-screen HUD (compass, headline, summary card)
  - `overview_pydeck.py`: the 3D (pydeck) overview render
  - `pin_icons.py`: pin glyphs and place-name labels
  - `stopby_pause.py`: the pause at a stop-by and its photo card
- `videopipeline/render_step.py` lost its "look" helpers to `render_look.py`: `_project_color`, `overview_pin_glyphs`,
  `_is_return_stop`, `_leg_pin`, `_arrived_marker_color`, `_project_rgb`, `_mode_line_color_overrides`, `look_options`.
  Its framing went to `overview_framing.py` and its "is this output still current" checks to `render_checkpoint.py`.
- `tuning.py` was reorganised (−1,000 net lines).
- 15 test files only had their imports updated.

**`274d310` — `render_step.py` split further** (+1,001 / −832)

- `animator_config.py`: builds the animator's settings from the job config.
- `leg_sequence.py` (593 lines): works out the order of legs, stops and stop-bys (`build_leg_sequence`,
  `inject_waypoint_popups`).
- `frame_sink.py`: the frame → ffmpeg pipe used by leg renders.
- `render_checkpoint.reuse_render_manifest`: one function decides whether a rendered clip can be reused.

**`dac3d4a` — audit clean-up:** one regex for leg file names instead of four; one `same_place()` rule (~30 m) for
return stops in both legs and the overview; `app.log` rolls over to `app.log.1` past 5 MB.

**Lint and dead code:** `896f40b` extends ruff to flag mutable default arguments, unused loop variables and implicit
`Optional`, and fixes what it found in 17 files. `0bc0880` removes about 1,000 lines of unused Python
([§15](#15-code-removed)). `488e564` turns on `noUnusedLocals` in `tsconfig.json` and removes unused frontend code.
`503e319` makes the Rust code clippy-clean.

---

## 3. Script cues added or changed

| Cue | Where | What it does | Commit |
|---|---|---|---|
| `{photo:X}` | Intro / course opening | From that word on, show the photo of the stop named X (exact name preferred). The slideshow crossfades it in; documentary/cinematic styles play that stop's clip for the scene. | `6f69899`, `dac3d4a` |
| `{photo:X#3}` | Intro | Shows stop X's 3rd photo | `39fbd88` |
| `{closed}` | Overview (course and walk) | After the stop-bys, closed places are told and their red × pins appear | `60f8704`, `23d150d` |
| `{next}` | Attraction narration | One per photo after the first: each photo comes in when the voice reaches it, and its credit follows | `747c23c` |
| `{view}` … `{/view}` | Leg narration | The n-th pair pops the n-th street view card in and out with the voice (without a cue it shows for ~1.2 s at its spot) | `b93228b` |
| `{view wait}` | Leg narration | Also stops the walker at the street view until `{/view}`; the clip keeps its length | `123217b` |
| `{view:X}`, `{view wait:X}` | Leg narration | Picks the street view named X instead of the n-th one | `c553cc1` |
| `{turn}` … `{/turn}`, `{turn wait}` | Leg narration | The same timing for the automatic turn photos | `c553cc1` |
| `{n}` check | Overview script | The editor lists each `{n}` that isn't followed by stop n's name, and the render log warns about it | `a6619b7` |
| `{go}` | Course overview | The walker reaches a `{go}` stop when its name is spoken and waits there until `{go}` | `1fd1284` |

`c553cc1` also fixed `{view wait}` timing so it counts from the `{start}` cue; before, the waits were dropped on legs
that had one.

---

## 4. Overview video

### Course overview (2D, `spatial_renderer/course.py`)
- `1fd1284`: a stretch slower than `COURSE_MIN_PACE_SHARE` of the average pace waits where it starts, then walks on,
  still arriving on its cue (the walker no longer crawls).
- `c943410`: stops are placed in route order on the drawn path and the travel mode is pinned to them (the boat stays
  on the sea, the walker on the island). Every stop-by, connected or not, pops up at `{extras}` without a number.
  Overview render version 9.
- `56be92f`: scene timing and cue handling refined (intro and course).
- `fd9f8da`: the headline names the stretch being traced ("A → B"). A new render version re-renders overviews.
- `3fac501`: the final stop sits on the route's last point, so the E pin and the 3D ending zoom come back.

### Walk overview
- `630b58b`: a one-line script fits the walk between `{start}` and `{end}`. Stop-bys and closed places pop up as
  they're passed (closed places with their own banner) and again with the summary. Cards keep off closed pins. A quicker
  ending zoom with correct pin numbers.
- `f482296`: **"Cards stay up"** (on by default). A stop's card stays on the map once it pops up. The ending summary's
  layout (no overlaps, short leader lines that don't cross) is worked out before the walk, so each card pops straight
  into its final spot and nothing jumps at the end.

### Route map overview (a new style, `e545c9d`)
Moved here from the outro (`0135a38` first built it as an outro). Each stop's photo pops up large off the line and
slides to its leg card (from → to, distance, time, mode, climb), and the walker holds while it's read. Pop-up fades are
faster. `spatial_renderer/map_style.py` is new for this.

### All overview styles
- `bc3a2fe`: the overview narration editor splits every style into an **Opening** box and a route overview box.
- `f96f718`: **one stop-numbering rule** for overview pins, the ending zoom, scrapbook cards and Route map cards
  (`route_inputs.py`). A change to one leg no longer re-renders the overview. Route map slides reset on each render.
- `8315100`: intro cards fade out, the static ending zoom aims at the stop, and pop-ups drop an unused wait budget.
  Overview render version 10.
- `315804a`: more room at the top: the route is framed below a top band and cards stay 150 px down. Shorter
  ending-card hold and pop. 10% of the height is kept free at the bottom (`60441cf` had first set it to 5%).
- `c553cc1`: the summary is held 1 s before a quicker zoom, and the photo after it carries the rest of the voice.
- `dac3d4a`: card shadows are blurred on a small canvas and the stop-by notice is drawn once. A course overview
  render went from ~665 s to ~316 s.

---

## 5. Walking legs

### Following the route
- `c943410`: stops are matched to the GPS track where it first passes them, so an off-track stop-by no longer pushes
  later stops ahead (island legs used to end on the pier). A stop without a voice keeps the leg's narration plan
  instead of one slow pace for the whole leg.
- `4fd97c8`: a start or end point on the first or last stop no longer adds an extra leg (玉手駅 → 玉手駅).

### Photo cards and fullscreen photos
- `bc5ef44`: leg photos grow to fullscreen and shrink back in 0.4 s; a leg's opening/arrival card sits off the route line.
- `28e6290`: the fullscreen photo shrinks in 0.25 s.
- `b13f0dd`: a card keeps off the route line first, and keeps its leader short only after that.
- `f274788`: the arrival photo is handled differently and the leg render version is bumped.

### Labels, HUD and camera
- `0e74333`: place names sit below, above or beside their point, wherever they hide the least of the route line
  (`pin_icons.py`).
- `8a1ffcc`: the compass uses the video's language (北 東 南 西 in Japanese).
- `c553cc1`: a quicker leg zoom, and labels keep off the route line.

### Joining legs together
- `4d27ade`: legs that meet at a return stop dissolve into each other over their shared camera view.
- `e60960d`: a stop with **no attraction narration** gets no attraction clip. Its photo pops up as a card and the next
  leg continues from the same frame, without a dissolve.
- `9c719ad`: new project setting **"At a stop with no attraction script"**: *Slide* (default) or *Zoom out and in*.
  With Slide, the stop's card stays up and rides along its pin while the camera slides into the next leg, then fades.
  **Bug fixed:** a leg's end view (`endview.json`) was deleted by the clean-up right after it was written, so the next
  leg couldn't continue from it and opened zoomed out.
- `c553cc1`: a leg after a stop with no narration slides on from the leg before and keeps its walked line.

### Re-rendering the right legs
- `85a4459` / `dac3d4a`: a reused leg's `_padded` copies are no longer counted as pieces; before, every narration
  shifted by one. Pieces sort by number (`_cont10` used to come before `_cont2`). A `_padded` copy is reused when it's
  newer than its piece and long enough (it used to be re-encoded on every run).
- `212bb17`: a leg with one piece deleted (to remake it) is rendered again instead of skipped as already done.
- `bd9062a`: a new leg version, or a changed leg voice (cue times, length), re-renders the leg. The render stage used
  to skip it.

---

## 6. Kinds of stop

### Stop-bys
- `7c3e812`: an off-route stop-by pops up at the stop before it in waypoint order (after the connected stop-by before
  it, or at the departure stop), not at the leg's start. The leg's pieces are cut in that order.
- `4572c64`: a leg walks to a stop-by near the route before showing its photo; a far one gets a camera fly-out and back.
- `a32e20b`: a course stop-by along a leg is walked to, not popped at the start while the walker stands still. A stop-by
  shown at the start no longer narrows the leg's frame.
- `f4d09b7`: a stop-by pause without a photo returns its frame index (it used to break).

### Return stops (coming back to a place already visited)
- `de9debf`: they show the first visit's pin, pop their photo up as a card (no fullscreen, no clip of their own) and
  join the next leg on the same frame. The last stop and stop-bys are never return stops.
- `6f717d3`: the outro leaves them out, and a round trip shows its start once.

### Closed places (new stop type)
- `3ec9267` (editor): a **Closed** stop type in the stop editor and stop menu, with a red × marker and a "Why it's
  closed" box. Saved as `inaccessible` in `job_config.json`. `3f6eed9` fixes reopening a project, which used to drop it.
- `60f8704` (script): closed places are never visited. They're told after the stop-bys at `{closed}`, with their own
  narration as the reason.
- `23d150d` (video): red × pins at `{closed}` in the course and walk overviews, a red × in leg pop-ups, their own outro
  section.
- `76d7188`: on legs they get a fullscreen photo and their own attraction video (reading their narration). They're
  left out of the leg's "A → B" headline. Legs that pass one are re-rendered. The reason no longer repeats the place's
  name.
- `0163d81`: the `inaccessible` field goes through `route_inputs.py`, the render overlay and auto readings.

### Street views (new stop type, `b93228b`)
- A street-view waypoint is saved in `job_config` as `street_views: [{id, lat, lng, label, image}]`, not in
  `waypoints`, so nothing routes through it.
- `street_photos.street_view_landmarks` puts each one on the leg that passes nearest and shows it as a passing card,
  timed by `{view}` cues ([§3](#3-script-cues-added-or-changed)).
- `ab25423`: street photo cards are 440 px wide.
- `123217b`: cards keep off the HUD, with a longer leader when needed. A passing card never freezes the walker.
- `ae153ea`: no automatic turn photo within 50 m of a street view the user placed.
- `28e6290`: a named street view's card shows its name on a strip. Views are matched to the route *line*, not only its
  points (a view midway along a long straight used to be dropped).
- `c553cc1`: street views count up to 200 m off the route.
- Frontend: `MapArea.tsx`, `WaypointEditor.tsx`, `useStopMenus.ts`, `utils/streetView` (+ `tests/utils/streetView.test.ts`).

---

## 7. Attraction clips and photos

### Camera moves
- `7fa44c4`: a short clip ends on its still photo instead of playing backwards. Walk In keeps its closer second shot.
- `0b6ffcd`: clips no longer end on the whole original photo (a slow drift instead). Pan left/right slides the photo
  flat, without 3D warp.
- `707574a`: zoom in/out also move the photo flat (CPU clips remade).
- `47d98ab`: the hand-held shake (`handheld.py`) was removed.

### "AI photo clips" project setting (`ab57457`)
`photo_clip_engine`: `"cpu"` makes every attraction use the CPU 3D photo (`img2vdo._cpu_only` → `_parallax_clip`), so
ComfyUI never starts. Its raw clips get their own cache key, so switching remakes them. Default `"ai"`. The UI is in
Project settings > Rendering.

### Photo credits (`da8d301`, `7d8cb66`, `747c23c`)
- Typed per photo in the stop editor and shown bottom-left or bottom-right over that photo in its attraction clip.
- Credits have their own timeline lane with adjustable size and box (`TimelinePane.tsx`, `Inspector.tsx`,
  `CaptionStyleFields.tsx`).
- Python: new `photo_credit.py`, drawn by `vdoexporter.py`, placed by `timeline_step.py`.
- Photos copied into a project are named `place-stop-photo` (stop-bys `s1`, closed places `c1`) (`utils/fileNames.ts`).
- **Find source** (Rust, `lib.rs`) reads where a downloaded photo came from and pre-fills its credit.
- With `{next}` cues, each credit follows its photo's time window.
- Reopening a project used to drop the credits; now it keeps them.

### `{next}` photo timing (`747c23c`)
`audio_step._write_photo_cuts` saves the cue times next to the audio (`<wav>.photos.json`). `img2vdo.photo_shares`
gives each photo the time between cues (equal split without them). A changed cue only refits from the kept raw clips.

---

## 8. Intro

- `6f69899`, `39fbd88`: `{photo:X}` / `{photo:X#3}` choose the intro's photos ([§3](#3-script-cues-added-or-changed)).
- `a747cb1`: **Intro photo motion** switch in the Intro panel: photos can be held still instead of zoomed and panned.
- `dfad750`: a place with several photos plays one photo per shot (from its kept raw clips), and no shot is shorter
  than 2.5 s.
- `744304d`: the photo zoom is smooth (sub-pixel crop instead of whole-pixel steps).
- `cd592cc`: photo cuts accept a stop saved without a photo, and titles strip ASS braces themselves.

---

## 9. Finale and outro

### Finale: new clip `98_finale.mp4` (`0b35c93`, `23bfa2b`)
- New stage file `videopipeline/finale_step.py` (237 lines). The last stop's photo is shown fullscreen, shrinks onto
  its pin, the camera pulls back over real map tiles to the whole route (line and stop badges, nothing walking), then
  the overview's summary card appears. It cuts to the outro.
- **"Ending narration"** box in the last stop's editor, voiced in the TTS step as `98_finale_narration.wav`. The clip
  stretches to fit it, and the timeline plays it from the moment the photo shrinks.
- Project setting **"Whole route before the outro"** (on by default).
- Subtitles: `98_finale_narration.srt`, placed on the finale in the timeline.
- **Bug fixed:** clips after the stops went into the timeline by file name only, so the finale's voice was never found.

### Outro styles
- `6f717d3`: route cards start with S, number each stop and end with E. `7035fcb`: the place count includes start and end.
- `5abf252`: card names wrap to a second line, and the outro title no longer animates like the intro.
- `86097c4`: **Scrapbook outro** (new style). Photos drop onto paper as polaroids (S, 1, 2 … E, long names on two
  lines), then a stamp with the subtitle, distance and travel time, then the logos close in like barn doors.
- `0135a38`: **Route map outro**, later moved to the overview (`e545c9d`). Scrapbook badges use the project's pin color.
- `7e58ad9`: scrapbook title and subtitle on top as an **editable text item**, smaller cards, and long names never
  break inside a number (葛城 / 第二十三経塚).
- `510a85b`: **scrapbook redesign** (`outrocard.py` largely rewritten):
  - footprints walk from card to card and each polaroid pops up as they arrive, then walk on to the stamp
  - masking tape on the cards, rows that snake left-right-left, darker paper corners, a rule under the title
  - mountains, sun, torii, a pine sprig and a red seal around the title
  - project setting **"Photos position"** (`outro_content_position`) moves the cards up or down under the title
  - right-click the outro clip in the timeline → **Make the outro again**
- `5a15990`: the scrapbook title is **drawn into the outro video** with the export's own text renderer
  (`outro_step.title_layer`: ffmpeg renders the ASS text on black and on white, and the difference gives the alpha), in
  the style the timeline gives it, so the end card's doors close over it. It stays on the text track for editing,
  marked `burned_in` so the preview and the export don't draw it twice.
- `f96f718`: the scrapbook leaves room for an enlarged title.

---

## 10. Voice (TTS) and pronunciation

### Re-voicing only some sentences
- `0308c3c`: overview narration keeps its sentences in the project (new `tts/voice_pieces.py`, which writes
  `<project>/.navivi/voice_pieces/<stem>/pieces.json`). Only edited or picked sentences are voiced again.
  `VoicePiecesDialog.tsx` lets you listen to each sentence and pick which to redo.
- `e1d83e4`: the same for English leg and attraction narration (`--retake=<i,j>`), plus a **lock** per sentence. A
  locked sentence keeps its take even through a forced full pipeline run, until its text or voice changes. A kana
  reading is no longer put into an English line. There's also **Listen** for a dictionary word.
- `c553cc1`: Japanese stop narration also keeps its sentences.

### Take quality
- `d7c66ef`: removing stray TTS bursts needs true silence around the burst, so a short syllable before a devoiced one
  (セキヒョウ) is kept.
- `b8d272e`: more tests and tuning for burst detection.
- `09652d3`: shorter pauses between sentences. Each take's own leading and trailing silence is trimmed, and the gap is
  0.2–0.35 s.

### Pronunciation dictionary
- `9963920`: full renders use the app-wide dictionary as well as the project's.
- `86c8ef1`: search bar, a **High/low** pitch pattern per word (checked against the reading's morae), script syntax
  `葛城(かつらぎ:LHHH)`, and a switch to turn the auto dictionary off (which drops its automatic entries). New
  `tts/pitch_accent.py` measures a word's high/low in a take.
- `c8e8e7a`: the patterns reach the voice. A line is retaken until the word's pitch matches (kana morae, or English
  syllables), up to `TTS_PITCH_RETAKES`.

### Servers
- `9963920`: the TTS idle watchdog tells a reused PID apart from its own server by start time (psutil).
- `a882e6b`: voice previews (dictionary Listen, Voice tab) no longer stop a running "Make again" job.

---

## 11. Subtitles

- `123217b`: subtitles break only at sentence ends and at commas between clauses (never inside a number like 1,200),
  one line each. The **"Long subtitles"** setting was removed (`subtitle.py` −50 lines).
- `23bfa2b`: the finale gets subtitles.

---

## 12. Timeline editor and "Make again"

- `76e6fda`: **one app-wide queue** for "Make again" requests (the sidecar runs one stage at a time), with new combined
  jobs "Narration and video" / "Voice and photo clip" (`hooks/useStopRegen.ts`).
- `feff45f`: the queue is a corner card in the timeline editor (`RegenQueueCard.tsx`): the running job plus waiting
  jobs you can move up or down or remove, stop this one, or clear the queue.
- `63c3e8d`: **Watch preview** shows the last timeline in the editor while assets generate (`RenderOverlay.tsx`).
- `c553cc1`: **Make again for one walking clip** (`main.py … leg NN`). Every leg is worked out but only that one is
  rendered. The editor takes its new length and voice start, and only the clip being remade shows a spinner. Also: no
  audio fade between clips (`vdoexporter.py`, `test_crossfade_sound.py`).
- `f92ebb9`: the editor loads remade clips at once. Clip URLs change with every new render (`player.ts`, `mediaVersion`).
- `510a85b`, `5a15990`: "Make the outro again", and `stopRegen.withOutroBurnedIn` moves an older outro title over to
  the burned-in form.

---

## 13. Map editor, project files and the Rust shell

- `47d98ab`: **`@mapbox/mapbox-gl-draw` removed** (native DOM markers instead). Asset import renames instead of
  copying and no longer compares files.
- `2592a39`: saving keeps photos that are already in the project (by name) and retries the project file rename on
  Windows.
- `a6619b7`: the overview narration panel shows wrong `{n}` cues.
- `bc3a2fe`: separate Opening and Overview boxes.
- `9963920` (Rust `project_files.rs`): export work folders live beside the output (renames across drives) and `.nvv`
  archives skip them.
- `7d8cb66` (Rust `lib.rs`): **Find source** for photos.
- `503e319`: the render-log readers skip unreadable lines.
- `a882e6b`: `npm run e2e` runs the Playwright tests in the installed Edge (new `playwright.config.ts`). The "Pause at
  Location" switch says what it does.
- `4696247`: the "Pause at Location" switch shows the video's real default.

---

## 14. Reliability fixes

| Commit | Fix |
|---|---|
| `f4d09b7` | `FrameSink.finalize` raises when ffmpeg fails, and `abort()` removes the temp clip, so an old clip is never kept as the new render. The overview encode kills ffmpeg on error. Tile cache files are written aside and renamed, so a cut-off tile is never served. Route keys with a drawn line or via points resolve. |
| `cd592cc` | Outro thumbnails and the upscale check honor EXIF orientation. Fullscreen pop-up videos stream instead of loading every frame. The image cache keeps the last 16 images. Pop-up cards composite on their own patch. Leg maps are centered on the box they were fetched for. |
| `9963920` | The auto overview script is written into a freshly read `job_config.json` (race fixed). GPS rows that are only moving are renumbered. Stay detection uses a scalar haversine. The Mapillary token goes in a header, not the logged URL. |
| `f5b718b` | The ComfyUI idle watchdog no longer kills a job running past 10 minutes, and a dead server ends the wait after 1 minute. |
| `dac3d4a` | The log rolls over at 5 MB. |

---

## 15. Code removed

- `0bc0880`: old card, sprite, `vdoeditor` and TTS assembly helpers, `build_pydeck_map`, `visit_all_stopbys`, the
  outpaint-and-pan clip generator (`local_pan_generator.py` −230 lines), unused constants and the `Route2VDO` alias:
  about 1,060 lines, none of them referenced.
- `47d98ab`: `handheld.py` and its test, plus mapbox-gl-draw.
- `488e564`: `SubtitleSample.tsx`, unused `assColor` writers, unused imports and state.
- `123217b`: the "Long subtitles" setting.

---

## 16. New settings

| Setting (UI name) | Where | Default | Commit |
|---|---|---|---|
| AI photo clips (`photo_clip_engine`) | Project settings > Rendering | AI | `ab57457` |
| Intro photo motion | Intro panel | on | `a747cb1` |
| Closed (stop type) + "Why it's closed" | Stop editor | — | `3ec9267` |
| Photo credit (per photo) | Stop editor | — | `da8d301` |
| Ending narration | Last stop's editor | empty | `0b35c93` |
| Whole route before the outro | Video look | on | `0b35c93` |
| Cards stay up (Walk the route) | Video look | on | `f482296` |
| At a stop with no attraction script | Video look | Slide | `9c719ad` |
| Outro style: Scrapbook | Video look | — | `86097c4` |
| Overview style: Route map | Video look | — | `e545c9d` |
| Photos position (scrapbook, `outro_content_position`) | Video look | middle | `510a85b` |
| Auto dictionary on/off, High/low per word, search | App settings > Dictionary | on | `86c8ef1` |
| Long subtitles | — | **removed** | `123217b` |

---

## 17. New and deleted files

**New Python modules:** `tts/pitch_accent.py`, `tts/voice_pieces.py`, `vdoprocessing/photo_credit.py`,
`pydeckrecorder/{frame_sink,leg_camera,leg_hud,overview_pydeck,pin_icons,stopby_pause}.py`,
`spatial_renderer/map_style.py`,
`videopipeline/{animator_config,finale_step,leg_sequence,overview_framing,render_checkpoint,render_look}.py`.

**New frontend files:** `features/editor/RegenQueueCard.tsx`, `features/editor/VoicePiecesDialog.tsx`, `playwright.config.ts`.

**Deleted:** `vdoprocessing/handheld.py`, `tests/test_handheld.py`, `components/ui/SubtitleSample.tsx`
(and, uncommitted, `tests/test_subtitle_freshness.py`).

---

## 18. Tests

**26 new Python test files:** `test_cli_test_all`, `test_comfyui_wait`, `test_crossfade_sound`,
`test_ending_highlight_zoom`, `test_finale`, `test_frame_sink`, `test_fullscreen_video`, `test_gps_index`,
`test_idle_watchdog`, `test_image_cache`, `test_intro_photo_cuts`, `test_label_placement`, `test_no_narration_stop`,
`test_outro_route_cards`, `test_outro_scrapbook`, `test_overview_map_style`, `test_overview_narration_race`,
`test_photo_clip_engine`, `test_photo_credit`, `test_photo_cues`, `test_pipeline_dictionary`, `test_pitch_accent`,
`test_stop_numbering`, `test_stopby_missing_photo`, `test_street_view`, `test_trim_edge_silence` (and more tests added
to existing files, e.g. `test_course_overview`, `test_waypoint_toggles`, `test_cues`, `test_course_script`).

**New frontend tests:** `tests/features/editor/player.test.ts`, `tests/hooks/stopRegenQueue.test.ts`,
`tests/utils/{photoCredit,photoFileNames,streetView}.test.ts`, plus `tests/services/fileSystemSafeWrite.test.ts`
(uncommitted).

---

## 19. Uncommitted work (2026-11-12)

Not in any commit yet (17 files, +154 / −90):

1. **Live outro title in the timeline preview.** `outrocard._write_scrapbook_clip` now also saves
   `99_outro.title_bg.png`: the paper heading band without the title (written to a temp file, then swapped in).
   `Preview.tsx` lays it over the clip to hide the burned-in title and draws the current title from the text item, so
   size, font and color edits show at once. Without the PNG (outros made earlier), nothing extra is drawn. The export
   still needs "Make the outro again". New test in `test_outro_scrapbook.py`; CODEMAP updated.
2. **Finale reuse.** `render_finale_clip(…, force=False)` fingerprints its inputs (settings, stops, size, voice length,
   GPS csv, photo, voice file, code) with `clip_cache`, and an unchanged finale is no longer captured again.
   `pipeline.py` passes `force_regenerate`. Test: `test_an_unchanged_finale_is_reused_not_captured_again`.
3. **TTS: name fix kept through pitch retakes.** `IrodoriTTSClient._names_spelled` remembers the spelling whose retake
   fixed a misread place name (for example ミワ神社 for 三輪神社), and the high/low retakes reuse it instead of the
   original kanji. The line cache now maps only the first take and the last retake to the kept take. Test in
   `test_name_check.py`.
4. **Safe writes in the frontend.** `fileSystem.writeFileSafely` (write `.tmp`, rename, 5 tries 200 ms apart on
   Windows) is now used for both `job_config.json` and `timeline.json` (the timeline used to be written in place).
   Test: `tests/services/fileSystemSafeWrite.test.ts`.
5. **Dead code removed:** `sentence_split.split_sentences` (moved into its only test), `introclip._crop_rect`,
   `route2vdo._stored_fingerprint`, `helpers.is_newer_than` and its test file `test_subtitle_freshness.py`, plus
   their tests.

---

## 20. Open ends

Things the commit messages and project notes leave unfinished:

- The live outro title preview only redraws the text. The seal beside the title and the card positions only update
  after "Make the outro again".
- The course overview's walker isn't yet timed to each turn in the leg scripts.
- Route map overview script voicing and montage/ticket outros are still to do.
