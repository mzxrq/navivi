# The ten engineer tasks (prompts used on 2026-10-06)

Each block below was given, word for word, to a separate sub-agent (Claude Code `Agent` tool, `isolation: "worktree"`,
`run_in_background: true`) after the line "FIRST read `.agents/handover/agent_rules.md` and follow it exactly".
They all died on a session limit before reporting; their unfinished work is in the branches listed in `.agents/HANDOVER.md`.
To resume: re-launch a task (adjust it to say "continue from branch `wrap2-<name>`, see `git log wrap2..wrap2-<name>`")
or finish the branch by hand. Vite ports: heatmap 5201, keys 5202, cleanup 5203, look 5204, pins 5205, render-output 5206,
hudlang 5207, voice 5208, overview 5209, regen 5210. Branch names are `wrap2-<name>`.

---

## 1. heatmap (branch `wrap2-heatmap`)

TASK: the route ELEVATION HEATMAP does not work properly yet. The user (project owner) only said "the route elevation heatmap hasn't been working properly" and did not say how. Settings > Appearance has an "Elevation heatmap" switch (`settings.show_route_heatmap`), the manual says it "colors GPX routes by steepness", and `ElevationProfile.tsx` shows climbs and descents. Find out what is wrong and fix it.

Method:
1. Read how it is built: grep `show_route_heatmap`, `heatmap`, `elevation`, `ElevationProfile`, `ele` in `src/`; `features/map/components/MapLayers/RouteLayer.tsx`, `RouteStyling.tsx`, `ElevationProfile.tsx`, `utils/gpxTrack.ts`, the GPX/FIT/TCX/KML import in `hooks/useFileActions.ts`, `types/index.ts`, and how a stop's leg geometry (`customRoute: [lat,lng][]`) and the routing cache are stored. Find out where elevation data comes from (GPX `<ele>` tags? Mapbox terrain? nothing?), whether it survives import, save and reopen, what happens for legs that were routed (walk/drive) or drawn, how colours are computed, whether turning the switch on/off redraws, and whether there is a legend.
2. Reproduce with a headless harness run: create a small synthetic GPX with real hills (and one flat track and one without `<ele>`), import it the way the app does and take screenshots with the heatmap on and off. List concretely what is wrong (write it in your report), e.g. elevation dropped on import, colour scale unreadable, wrong slope maths, only one leg coloured, switch does nothing, 3D terrain mismatch.
3. Fix it. What "working" means (adjust if you find a better answer, and say so): (a) a route imported from a GPX with elevation is coloured by gradient (steepness) with smooth segments and a small legend; (b) legs without recorded elevation (routed or drawn) either get elevation sampled from the map's terrain (`map.queryTerrainElevation` when terrain is on) or the control explains that no elevation data exists; no silent blank result; (c) the elevation profile and the colours agree; (d) switching it off restores the normal line colours including per-leg colours; (e) the elevation survives save and reopen (if a Waypoint field is needed, follow recipe 12.1: type, saver in `fileSystem.ts`, loader in `useWorkspace.tsx`, absolute paths).
4. Put the slope, smoothing and colour-scale logic in a pure, unit-tested util (for example `src/utils/elevation.ts` + test).

Ownership: `src/features/map/components/MapLayers/*`, `ElevationProfile.tsx`, `src/utils/gpxTrack.ts` (+ tests), new `src/utils/elevation*.ts`, the Appearance "Elevation heatmap" row in `AppSettings.tsx` (only that row), and the Waypoint field plumbing if needed. Python is NOT in scope (the video does not draw the heatmap; say so in the report if that matters).

---

## 2. keys (branch `wrap2-keys`; also run `cargo test` once)

BACKGROUND (the owner asked "why are the Mapbox and OpenRouteService tokens stored in the project settings if they live in the app?"): today `settings.mapbox_api_key` and `settings.ors_api_key` are part of `ProjectSettings` (`src/types/index.ts`, default in `src/config/constants.ts`, edited in `AppSettings.tsx` API-keys tab via `updateProject`). So they are written into every project's `job_config.json`, into the project's database row, and into every shared `.nvv`. The AI provider keys were later done properly (credential store, never in project files). The user manual currently tells people to delete these two keys before sharing: that is a design flaw to fix, not to document.

TASK: make the Mapbox token and the OpenRouteService key APP-WIDE, never part of a project.
1. Storage: an app setting `api_keys` (`{ mapbox?: string, ors?: string }`) in the database `app_settings` table via `db.appSettings`, loaded and saved the way `ai_settings` is (see `GLOBAL_AI_KEY` / `globalAi` / `pickAiSettings` in `src/hooks/useWorkspace.tsx`; reuse that pattern, including the early-write protection). Components keep reading `settings.mapbox_api_key` / `settings.ors_api_key` from the merged `settings` object (MapArea.tsx, useMapRouting.tsx, AutoDirectorModal.tsx, useAssistant.tsx), but the values must come from the app-wide store.
2. They must never be written: `saveProjectData` (`src/services/fileSystem.ts`) must not put them into `job_config.json`; the per-project settings stored in the database (`db.settings`) must not contain them; version snapshots (`services/versionHistory.ts`) must not either.
3. Migration: when a project is opened and its saved settings contain either key: if the app-wide value is empty, adopt it; never overwrite an existing app-wide key; always remove the key from the project's in-memory settings so the next save drops it from the project file.
4. Sharing: `export_project_archive` (`src-tauri/src/project_files.rs`) must scrub `settings.mapbox_api_key` / `settings.ors_api_key` out of the `job_config.json` that goes into the archive even for projects that still have them on disk. Rust test.
5. Python must receive the Mapbox token from the app: Rust sets env `NAVIVI_MAPBOX_TOKEN` (read from the DB app setting) on every Python spawn that renders (look at `python_command()` and `secrets::export_keys` in `src-tauri/src/lib.rs` / `secrets.rs`, which already hands AI keys over as `NAVIVI_AI_KEY_*`). In `services/mapfetcher/maptile.py` and `services/vdoprocessing/pydeckrecorder/common.py` read `NAVIVI_MAPBOX_TOKEN` first, then the legacy `settings.mapbox_api_key`, then the old env vars / `.env`. Also fix the audit finding that the key reaches only the ending zoom: make leg and overview renders use it (`route2vdo.py` passes neither `mapbox_key` nor a style; `mapfetcher.py:75`). pytest.
6. UI: the API keys tab says in one short line that keys are saved on this PC only and never inside projects or shared files.
7. Keep the dev fallback `import.meta.env.VITE_MAPBOX_TOKEN` / `VITE_ORS_API_KEY` working.

Ownership: `AppSettings.tsx` (API keys tab only), `types/index.ts`, `config/constants.ts`, `hooks/useWorkspace.tsx`, `services/fileSystem.ts` (saver), `services/projectStore.ts` / `versionHistory.ts`, the four readers (read-path only), `src-tauri/src/lib.rs`, `project_files.rs`, `db/*` only if needed, Python `maptile.py`, `pydeckrecorder/common.py`, and the few lines in `route2vdo.py` / `mapfetcher.py` that pass the key. Tests for: not written to job_config, migration rules, archive scrub (Rust), env var precedence (pytest).

---

## 3. cleanup (branch `wrap2-cleanup`; may also edit `.agents/CLAUDE.md` for lines about removed code)

TASK A: small bugs from `docs/BACKEND_GAPS.md` section 1. Re-verify each, then fix with a test:
- Bug 1: the frontend saves a Fly leg as `routeMode: "curve"` but the pipeline knows `airplane`. `MODE_ALIASES` in `tuning.py` only maps `direct` and `draw`. Make Fly legs behave as airplane legs (check every place that reads the mode).
- Bug 2: `services/localization/script_engine.py` reads `overview_script_model` which nothing sets; the UI sets `ai_model`. Make the chosen local model be used (keep `overview_script_model` as an override).
- Bug 8: `marker_radius` default 10 in `constants.ts` always beats Python's 24 and is clamped to 16 in `spatial_renderer/base.py`. Decide the intended size by how it renders, stop the fight, without changing how existing projects look unless that was clearly a bug. Say what you chose.
- Bug 9 (part): `imageTransitions` is always written as `[]` and nothing in Python reads it. Check `utils/manifestBuilder.ts` / `.navivi/asset_manifest.json` use before removing the field from `types`, the saver and the loader. Leave `image_display` and `freeze_seconds` alone.
- `main.py`: the `_WHOLE_PAYLOAD` set does not list `import_gps_track` and the voice/image actions; make that robust and correct the help text.

TASK B: dead code removal. Re-verify EACH with repository-wide searches (src-tauri/src-python incl. tests and scripts, `src`, `setup`, `scripts`, `e2e`, installer files, docs, the harness; ignore `installer-staging/` and `bin/`) before deleting, and run the tests that mention the module: `services/vdoprocessing/framesink.py`; `local_pan_generator.py` (+ `tests/test_local_pan_without_torch.py`; the real fallback is `parallax_generator.py`); the whole `services/model/` package (nothing imports it; fix docstrings that mention it); `services/localization/llmscript.py` (+ its tests); `services/tts/tts.py`; the `use_leg_storyboard` flag/branch in `route2vdo.py`; `src/hooks/useTransition.ts` if truly unused. Do NOT remove the database command wrappers in `db.ts`, the legacy 3D renderer (`recorder.py` is imported by `pedestrian.py`), anything in `src-tauri/src/`, or `move_picker.py` / the new attraction-shot code. Report which packages in `requirements.txt` were only needed by deleted modules (do not edit requirements) and which docs mention deleted things. Run the full pytest suite ONCE at the end, and the frontend suite.

---

## 4. look (branch `wrap2-look`; port 5204)

TASK: give the video's look the controls the Python renderer already supports, and make the options actually reach the renderer. Items from `docs/BACKEND_GAPS.md` (re-verify first): bug 7 (ten renderer options read downstream but never forwarded by `render_step.py`'s `animator_config` builder: `show_compass`, `waypoint_map_border`, `waypoint_intro_freeze`, `show_leg_wide_intro`, `res_follow_pitch`, `overview_max_leg_seconds`, `overview_intro_card_scale`, `overview_intro_clean_hold_seconds`, `overview_title`, `enable_ending_highlight` (two readers disagree)); bug 10 / V4 (outro cannot be turned off: add `enable_outro` plus `outro_style` scroll/grid and `outro_route_info`, see `videopipeline/outro_step.py`); V5 (`summary_card_style` glass/taskbar/stacked/columns, HUD theme light/dark `settings.theme`, card border colour/thickness, `map_font_size`); V6 (pin colours by role: `start_pin_color`, `end_pin_color`, `stopby_pin_color`, `arrived_marker_color`, `drawn_pin_color`, per-mode `mode_line_colors`); V7 (pace: `mode_speeds_kmh`, `animation_speeds_kmh`, `overview_speed_multiplier`, `res_target_avg_seconds`, `res_max_segment_seconds`); V8 (per stop: `image_display` cover|pip, `freeze_seconds` capped by `POPUP_FREEZE_SECONDS_MAX`, `overviewHighlight`); V9 (`camera_follow_distance_m`, `bearing_smoothing`, `enable_fullscreen_popups`, `hide_route_on_popup`, `trigger_radius_padding`); V12 (`upscale_popup_images` switch). Skip anything dead or legacy and say so.

DESIGN: one new section group "Look of the video" in `components/view/ProjectSettingsModal.tsx` (keep writing the file AND patching the database), compact, quiet style (Section/Row pattern, Segmented, Slider, Switch, ColorSwatches). Per-stop options go in a small "Popup" group in the `WaypointEditor.tsx` right sidebar (another engineer adds a Regenerate menu to the same file: keep hunks separate). Every new setting: type, default in `constants.ts` that EQUALS the current rendering, Python reads with a fallback to `tuning`. Trace each Python key from `job_config.json` to its use and prove it with a pytest on the config-building function.

Ownership: `ProjectSettingsModal.tsx`, new components under `src/components/ui/`, `WaypointEditor.tsx` (Popup group), `types/index.ts`, `constants.ts`, `fileSystem.ts` / `useWorkspace.tsx` for the per-stop fields only, Python `render_step.py` (animator_config forwarding), `outro_step.py`, `tuning.py` (append constants), and the readers in `spatial_renderer/*` / `route2vdo.py` / `pydeckrecorder/*`. NOT yours: map style / tiles / export options (render-output), on-video text language (hudlang), custom pin icons (pins).

---

## 5. pins (branch `wrap2-pins`; port 5205)

TASK: custom pin icons are a broken promise (`docs/BACKEND_GAPS.md` bug 3, re-verify first). The app lets the user choose an image as the route marker (`settings.routeMarker`: Settings > Appearance, Project settings; default pin / walking figure / car / own image) and as a per-stop custom marker (`Waypoint.customMarker`). The editor map shows them, but the Python video renderer never reads either (`job_config.py:83` only resolves their paths). Video pins are always the built-in teardrops from `spatial_renderer/pins.py` / `graphicengine/sprites.py` and, in the default pydeck pipeline, the 3D models in `assets/*.glb`.

Investigate how pins are drawn in BOTH render paths (2D `spatial_renderer`/`graphicengine` and the default pydeck pedestrian path). Then (a) build it where feasible: draw the user's image as the pin (route marker = moving marker or start/end pins; stop's custom marker = that stop's pin), transparent PNG support, caching, safe fallback to the built-in pin; keep the built-in options exactly as before. (b) If a render path cannot reasonably support image pins, implement the paths that can and make the UI honest for the rest (a short note under the control saying where the image appears). Decide with evidence and report why. Prove it with a pytest that draws a pin with a custom image and checks pixels (no GPU, no network).

Ownership: `spatial_renderer/pins.py`, `graphicengine/sprites.py` and neighbours, `pydeckrecorder/*` for marker handling, `render_step.py` only the few lines that pass the marker, `job_config.py` path handling, the marker help text rows in `AppSettings.tsx` / `ProjectSettingsModal.tsx`, `WaypointEditor.tsx` Custom Marker row.

---

## 6. render-output (branch `wrap2-render-output`; port 5206)

TASK 1 (export options; bug 11 / V3): the exporter `vdoexporter.py` reads `resolution` and `fps` from `timeline.json` and honours `burn_subtitles`, but the editor's `toManifest` (`features/editor/model.ts`) writes neither and hard-codes `burn_subtitles: true`; `default_export_resolution` is written by `AutoDirectorModal.tsx` and read by nothing; `NewProject.tsx` has `default_export_ratio`. Add an options block to `ExportDialog.tsx`: resolution presets (1080p default = current behaviour, 720p, 1440p, 4K; honour the project's ratio), frame rate (24/30/60, default = the project's `fps`), "Burn subtitles" on/off, "Also save subtitles as .srt" if the exporter can. Remember the choices per project and write them in `toManifest`. Make the exporter handle each value (even sizes for x264) and test with a small synthetic clip through the real ffmpeg. Keep the photo and music credits shown in the dialog.

TASK 2 (video map style; bug 4 / V2): the editor's style is only in `localStorage "map-style"` (`MapArea.tsx`); the render uses fixed styles (`outdoors-v12` for legs, `pedestrian.py:1115`). Add a project setting `mapbox_style_id` and a "Map style in the video" control as its own small Section in `ProjectSettingsModal.tsx` (Outdoors, Streets, Satellite Streets, Dark, Light, "Same as the editor" when it is a Mapbox style; non-Mapbox editor styles cannot be used: say so) plus a "Sharper map tiles" switch for `mapbox_retina`. Plumb it through `render_step.py` (only the lines that pass style/retina) to every place that fetches tiles or builds a style URL. Default (setting absent) must equal today's styles exactly. pytest the style resolution.

Ownership: `ExportDialog.tsx`, `model.ts` (+ test), `NewProject.tsx` (export-ratio plumbing), `AutoDirectorModal.tsx` (one line), `vdoexporter.py`, `ProjectSettingsModal.tsx` (own Section), `MapArea.tsx` / `LayerManager.tsx`, `maptile.py` / `maplanguage.py` (style parts; "keys" edits the token lines), style plumbing in `pedestrian.py` / `transitions.py` / `pydeckrecorder/*`, `constants.ts` (style table), `types/index.ts`.

---

## 7. hudlang (branch `wrap2-hudlang`; port 5207)

TASK: the text drawn INTO the video (route HUD "まもなく", "歩く時間", "出発:", summary cards, popup captions, intro/outro labels, mode names such as "乗船"/"飛行機") is Japanese only, although the UI, `map_language` and narration can be English (`docs/BACKEND_GAPS.md` V11 and T4; re-verify first). Find every drawn string: `tuning.py` (label tables ~150-170, `pipeline_labels`/`summary_card_labels`), `pedestrian.py` (~982-1073), `graphicengine/cards.py`, `popup_box.py`, `spatial_renderer/*`, `introclip.py`, `outrocard.py`, any `labels_ja.json`. Then:
1. One label catalog per language (English and Japanese; a third language = another file), one resolver `labels_for(language)`, and every drawn string goes through it. English strings short and natural ("Arriving soon", "Walking time", "Departure:"); check text-fit code and fonts for Latin text.
2. A project setting `video_text_language`: "auto" (default: follow the project's `map_language`, which follows the UI language), "ja", "en". Behaviour change to document: with "auto" an English-UI project now gets English on-video text. Japanese projects must render exactly as before.
3. T4: `subtitle_language: "romaji"` romanizes map place labels (see `localization/localization.py`, `romaji.py`, `render_step.py`). Offer a "Place names on the map: as written / romanized" choice only if it works end to end.
4. UI: one row in the `AppSettings.tsx` Video tab "Language of the text in the video" (Auto / English / 日本語) (+ the romaji choice if it works). Keys in `types/index.ts`, defaults in `constants.ts`.
5. pytest: the resolver, no string bypasses the catalog (only if not flaky), a frame-level check that an English card renders and fits.

Ownership: the label tables in `tuning.py` (that section only), `pedestrian.py` / `cards.py` / `popup_box.py` / `spatial_renderer/*` / `introclip.py` / `outrocard.py` (text lookups), the new catalog files, `localization.py` + `romaji.py`, the one `AppSettings.tsx` row, `types/index.ts`, `constants.ts`; `render_step.py` only the lines that pass the language.

---

## 8. voice (branch `wrap2-voice`; port 5208)

TASK: expose voice and caption features Python supports (`docs/BACKEND_GAPS.md` T1, T2, T3, T5, T6; re-verify first):
- T1: Irodori "speaking style" prompt `settings.tts.caption` (default "明るく元気で…", `ttsengine.py` ~121 / `voices.py` ~213): a text box with presets (calm, energetic, warm, serious) in the Voice tab for the Natural engine only, plus Reset; add `caption` to the `tts` type. Changing it must mark finished narration out of date like changing the voice (check `voices.voice_fingerprint`; do not silently change fingerprints of existing projects: test before/after).
- T2: caption look extras: shadow, shadow colour, letter spacing, text opacity in `CaptionStyleFields.tsx` (Python `text_style.py` and `utils/textStyle.ts` honour them; verify the exported video really does through real ffmpeg; do not expose what libass cannot honour).
- T3: narration cue helpers: "Insert cue" buttons in `ScriptInput.tsx` for `{start}`, `{arrive}`, `{end}`, `{n}` (see `localization/cues.py`, `overview_cues.py`) with short tooltips; the `auto_overview_cues` / `auto_narration_cues` switches (Python `narration_step.py`) in the Voice tab under a "Timing cues" Section.
- T5: Python actions `tts_cache_info` / `tts_cache_clear` in `voice_commands.py` (`VOICE_ACTIONS` + `_HANDLERS`) and a "Voice cache" row (size + Clear with confirm). One Python call at a time.
- T6: widen the speed slider to Python's 0.25-4x (default 1.25 stays; keep it usable).
Ownership: `VoiceSettings.tsx`, `CaptionStyleFields.tsx`, `ScriptInput.tsx`, `types/index.ts`, `constants.ts`, `voice_commands.py`, `services/tts/*`, `text_style.py`. Tests for each.

---

## 9. overview (branch `wrap2-overview`; port 5209)

TASK: build the missing overview-narration editor (`docs/BACKEND_GAPS.md` V1, bug 6, G5; re-verify first). The pipeline writes an auto "overview narration" (voice-over of the whole-route map shot) in `narration_step.py` (`ensure_overview_narration`) using `overview_script.py` (`build_tour_script`) and the AI chosen by `script_engine.py`; CLI mode `overview-script` (+ `--no-llm`) returns script, `target_seconds`, `estimated_seconds`, `within_60_90s`, `stopped_at`, `pieces`; `ReviewStep.tsx:250` says "The overview script is edited in the Intro panel on the map" but `OverviewPanel.tsx` has no script UI; the frontend keeps `metadata.overview_narration` (saver writes `overview_narration: ""` ~288 of `fileSystem.ts`; `projectStore.ts` reads `overview_narration_is_auto`, `overview_narration_source_ids`); `ollamaApi.ts` has an unused `generateOverviewScriptStream`. First work out how it is stored, regenerated and protected from overwriting, then:
1. Add an "Overview narration" section to `OverviewPanel.tsx`: editable text (same commit behaviour as `ScriptInput`), "Auto-write" (calls `overview-script` via the sidecar; one call at a time) with a "Write without AI" fallback (`--no-llm`), a length readout (estimated vs target seconds, in-range / too long / too short), hear it (`overview-tts`), revert to auto. Persist edits so the pipeline respects them (`overview_narration_is_auto` false when edited) and survive save/reopen (find out why the saver blanks it; keep a user-written overview, keep regenerating an auto one).
2. Fix `ReviewStep.tsx:250` so it points to the new panel.
3. G5: a small "Preview framing" button running mode `map` if cheap and reliable; otherwise skip and say so.
4. Online models: the key is passed by Rust (`NAVIVI_AI_KEY_*`), so the call must go through `run_python_blueprint`.
Ownership: `OverviewPanel.tsx`, `ReviewStep.tsx` (one sentence), `ollamaApi.ts` (overview helpers), `types` / `fileSystem.ts` / `useWorkspace.tsx` (overview fields), Python `overview_script.py`, `narration_step.py`, `script_commands.py`, `main.py` (overview mode). Tests: Python JSON contract; frontend panel with a mocked sidecar.

---

## 10. regen (branch `wrap2-regen`; port 5210)

TASK: regeneration controls (`docs/BACKEND_GAPS.md` G1, G2, G3; re-verify first).
- G1 "Regenerate everything": Rust `start_render({configPath, force})` accepts `force`; the UI never sends it (`RenderOverlay.tsx` ~241). Add a clear option in `GenerateDialog.tsx` ("Make everything again, ignoring what already exists": careful wording, confirm when assets exist) and pass it through `RenderOverlay`. Make it consistent with the existing "This project already has assets" group ticks (force implies every group; disable the ticks when force is on).
- G2 per-stop regeneration: today "redo" in the review step deletes files and reruns the full pipeline and the editor has no per-stop redo. The CLI has single-stop modes: `tts N`, `attraction-tts N`, `attraction N`, `subtitle N`, `residential N` (payload "job_config path + mode string like `tts 3 --force`", split by main.py; one Python call at a time). First prove which work against a small fixture project and note any broken. Then add a "Regenerate" menu to the stop editor header (`WaypointEditor.tsx`): "Voice", "Subtitles", "Photo clip", "Leg video" (only those that work), each runs the single-stop mode with `--force` through the sidecar with a busy state and toasts; disabled while rendering; saves the project first; the timeline picks up the new files (see the review step's background redo: `autoLoadTimeline`, `finishBackgroundRun`).
- G3: the audit says `attraction-finalize` is unwired, but `tests/test_attraction_multi_image.py` says multi-photo clips are combined automatically. Verify; if obsolete, say so (no UI) and correct the stale docstring in `services/cli/attraction_commands.py`.
Ownership: `GenerateDialog.tsx`, `RenderOverlay.tsx` (start/force wiring and redo helpers only), `ReviewStep.tsx` (redo path only), `WaypointEditor.tsx` (header menu only), `assetCleanup.ts`, `sidecar.ts` only if needed, Python `attraction_commands.py` and single-stop plumbing if broken. Tests required.

---

## Second wave (not started)

- GPS stay detection on import (`import_gps_track`, `stays.py`; check what `useFileActions.importRouteFile` / `stopsAlongTrack` already do) with radius and minimum-stay controls.
- Translated subtitles (a real build: no translator exists in Python).
- Anything left over from the first wave, plus the lead's own jobs listed in `.agents/HANDOVER.md`.
