# Backend features the frontend cannot reach yet

Audit date: 2026-10-06. Four reviewers read the Python pipeline (`src-tauri/src-python/`) against the frontend (`src/`) and the Rust shell,
each looking at one area: command-line modes, project settings and config keys, voice/text/AI features, and video/map/GPS features.
Nothing was changed by the audit.

How much to trust this: every row comes from a reviewer's reading of the code with file and line evidence. I re-checked the claims marked
**(checked)** myself with a search of the repository; the rest are the reviewers' findings, and rows say "unsure" where they were.
Treat line numbers as pointers: they move.

> **Read this first: editing `job_config.json` by hand is not a workaround.**
> The app keeps each project's settings in its database. When a project is opened the database copy wins (unless the file is newer),
> and every save rewrites `job_config.json` from the database. A key you add by hand is likely to be lost.
> Also, any new key you write through `updateSettings(...)` already reaches the Python side; no schema change is needed (settings are free-form JSON).
> Besides that, some keys never reach the renderer at all (see part 3).

---

## Status after the wrap2 push (2026-10-07)

The tables below are the audit as it was written. What has been done on branch `wrap2` (details in `.agents/CODEMAP.md`, "wrap2 additions"):

| Item | State |
|---|---|
| Bugs 1, 2, 8, 9 (imageTransitions), 12 | fixed (Fly alias, overview model, marker radius, dead field, docs) |
| Bug 3, custom pin icons in the video | done (drawn in the overview and every leg's start/end pins; built-in preset icons and 3D models still teardrops) |
| Bugs 4, 11 and V2, V3 (map style, export options) | done |
| Bug 5 (Mapbox key) | done as app-wide keys: never inside projects or archives |
| Bugs 6, 7, 10 and V1, V4 to V10, V13 (overview panel, look settings, outro) | done; per-stop `freeze_seconds`, `mode_speeds_kmh` and `animation_speeds_kmh` deliberately not exposed |
| V11 (on-video language) | done: `video_text_language` auto/en/ja |
| T1 to T3, T5, T6 (voice) | done; T4 (romaji labels) not offered: it only reaches the waypoint chips |
| G1, G2 (force, per-stop regeneration) | done for voice, subtitles and photo clip; no leg video; G3 obsolete (multi-photo clips combine automatically) |
| T7, G4, G5 | second wave: translated subtitles and stay detection in progress; G5 previews are inside the overview panel |
| Section 5 dead code | removed (all but the legacy 3D renderer, which is not dead, and `local_pan_generator.py`, which `jump_cut.py` now uses) |
| Elevation heatmap (reported by the user, not in this audit) | fixed: see CODEMAP |

## 1. Bugs and broken promises (fix these before building anything new)

These are places where the UI says one thing and the pipeline does another. They are small and worth doing first.

| # | What is wrong | Evidence | Fix | Size |
|---|---|---|---|---|
| 1 | **Fly legs get the wrong look.** The frontend saves Fly as `routeMode: "curve"`; Python's pipeline knows the mode `airplane` (HUD label "飛行機", speed, flat 2D fallback). `MODE_ALIASES` only maps `direct` and `draw`, so a Fly leg is treated as walking: walking HUD, no airplane speed. **(checked)** | `src/components/ui/NewProject.tsx:184`; `services/tuning.py:197, 210, 157` | add `"curve": "airplane"` to `MODE_ALIASES` in `tuning.py`, then test a Fly leg end to end | small |
| 2 | **The local AI model you pick does nothing for the overview narration.** Settings > AI models writes `ai_model`; the overview writer reads `overview_script_model`, which nothing sets, so it always uses the default Gemma 2 model. Online providers do work. **(checked)** | `localization/script_engine.py:22`; `AppSettings.tsx` | make `script_engine.py` read `ai_model` (or write both keys) | small |
| 3 | **Custom pin icons are drawn only in the editor.** Settings > route marker, project settings and the stop editor all let you choose an image; the video renderer never reads `routeMarker` or `customMarker` (it only resolves their file paths). Video pins are always the built-in teardrops and the 3D model. **(checked)** | `services/config/job_config.py:83`; `spatial_renderer/pins.py`, `sprites.py` | either draw them in the renderer, or hide the controls and say so | medium (build) or small (hide) |
| 4 | **The map style you pick in the editor is not what the video uses.** The editor keeps its style in the browser's local storage only; the render uses fixed styles (`outdoors-v12` for legs). **(checked)** | `MapArea.tsx:219-230`; `pedestrian.py:1115`; `maptile.py:150` | save `mapbox_style_id` in settings and pass it on (the pedestrian and overview calls already accept `map_style`) | medium |
| 5 | **The Mapbox key typed in Settings reaches only part of the render.** Legs and overview still use `.env` / `VITE_MAPBOX_TOKEN`; the Settings key (`mapbox_api_key`) reaches only the ending zoom and the legacy 3D renderer. An installed app has no `.env`, so check this with a clean install. | `route2vdo.py:638-663`; `maptile.py:135`; `pydeckrecorder/common.py:44` | pass `settings.mapbox_api_key` into leg and overview calls and let `maptile.py` fall back to it | small |
| 6 | **Review step points to an editor that does not exist.** It says "The overview script is edited in the Intro panel on the map"; that panel has no script editing. **(checked)** | `components/ui/ReviewStep.tsx:250`; `OverviewPanel.tsx` | build the overview script panel (part 2, item V1) or change the sentence | medium or tiny |
| 7 | **Ten renderer options are read but never delivered.** `render_step.py` builds the renderer's config from a fixed list of keys; these are read downstream but not on the list, so even a hand edit does nothing: `show_compass`, `waypoint_map_border`, `waypoint_intro_freeze`, `show_leg_wide_intro`, `res_follow_pitch`, `overview_max_leg_seconds`, `overview_intro_card_scale`, `overview_intro_clean_hold_seconds`, `overview_title`, `enable_ending_highlight` (the last one disagrees between two readers) | `render_step.py:1303-1425` | add them to the list, then expose the ones worth having | small |
| 8 | **Marker size default is clamped.** The frontend writes `marker_radius: 10`, which always beats Python's own default 24, and the renderer clamps it to 16 | `config/constants.ts:44`; `spatial_renderer/base.py:149` | remove the frontend default or raise the clamp | tiny |
| 9 | **Photo "card" look can never happen.** The frontend always writes `image_display: "pip"`; Python's default is `"cover"` and has a boxed-card variant nobody can select. `imageTransitions` is always empty and no Python code reads it either | `fileSystem.ts:205, 212`; `mapfetcher.py:225` | add a per-stop choice, or delete the dead fields | small |
| 10 | **The outro cannot be turned off.** `enable_intro` switches only the intro | `videopipeline/outro_step.py:45-48` | add `enable_outro` | small |
| 11 | **Export is stuck at 1920x1080, 30 fps, captions burned in.** The exporter reads `resolution`, `fps` and `burn_subtitles` from `timeline.json`; the editor never writes the first two and hard-codes the third. `default_export_resolution` is written by one dialog and read by nothing | `vdoexporter.py:757, 863, 964`; `features/editor/model.ts:395-447`; `AutoDirectorModal.tsx:73` | write them in `toManifest` from an Export dialog control | medium |
| 12 | **Docs that are out of date.** `.agents/CLAUDE.md` listed a `zip_project` command (fixed; the real ones are `export_project_archive` and `unzip_project`). CODEMAP and CLAUDE.md say the photo-clip fallback is `local_pan_generator.py`; the real fallback is the depth parallax in `parallax_generator.py` and `local_pan_generator.py` is imported only by a test **(checked)** | `img2vdo.py:309-311` | update the notes; decide whether to delete `local_pan_generator.py` | tiny |

---

## 2. Features that exist in Python and deserve a screen

Ordered by how much a user would notice. "Host" is the file where the control should live. Sizes: small = an afternoon, medium = a day or two, large = a week.

### Video look and feel

| # | Feature | Python side | Size | Host |
|---|---|---|---|---|
| V1 | **Overview script panel**: show, edit, regenerate and re-time the auto-written overview narration, with a length readout (Python already returns `script`, `target_seconds`, `estimated_seconds`, `within_60_90s`, `pieces`) and the `{n}` cue markers. The review step already promises this | `localization/overview_script.py`, `narration_step.py`, CLI mode `overview-script` (no `--no-llm` UI either) | medium | `features/map/components/OverviewPanel.tsx` |
| V2 | **Video map style** (streets, outdoors, satellite, dark) and a sharper-tiles (`mapbox_retina`) switch | `maptile.py`, `maplanguage.py` | medium | `RouteStyling.tsx` or `ProjectSettingsModal.tsx` |
| V3 | **Export options**: resolution, fps, burn captions on/off (or a separate `.srt`) | `vdoexporter.py` | medium | `features/editor/ExportDialog.tsx` |
| V4 | **Outro**: on/off, scroll or grid style, route info | `outro_step.py`, `outrocard.py` | small | `OverviewPanel.tsx` |
| V5 | **Overlay look**: summary card style (glass, taskbar, stacked, columns) and its labels, HUD theme light or dark, card border colour and thickness, map label size | `render_step.py:1353-1425`, `tuning.py:354-358` | small | `ProjectSettingsModal.tsx` (Rendering) |
| V6 | **Pin colours by role** (start, end, stop-by, arrived, drawn) and per-mode line colours | `render_step.py:128, 157, 1385-1393` | small | `MapLayers/RouteStyling.tsx` |
| V7 | **Travel pace**: speed per mode, overview speed multiplier, average and maximum seconds per leg | `render_step.py:629, 655, 868, 875, 1283` | small-medium | `AppSettings.tsx` Video tab |
| V8 | **Popup behaviour per stop**: card look (cover or box), hold time (`freeze_seconds`, capped at 1 s by `POPUP_FREEZE_SECONDS_MAX`), "highlight this stop in the overview" (`overviewHighlight`) | `mapfetcher.py:216-225`, `overview_script.py:592` | small | `WaypointEditor.tsx` |
| V9 | **Camera feel and engines**: follow distance, bearing smoothing, pydeck overview on/off, fullscreen popups on/off, hide route on popup, trigger radius | `pydeckrecorder/recorder.py:102-239`, `render_step.py:1335-1395` | small | `AppSettings.tsx` Video tab (advanced) |
| V10 | **Intro and outro text styles as project defaults** (kicker, title, subtitle). Today only the timeline Inspector styles the clip, with no saved default | `intro_step.py:81-83` | medium | `OverviewPanel.tsx`, reuse `CaptionStyleFields` |
| V11 | **On-video text language.** The HUD and summary strings are Japanese only ("まもなく", "歩く時間", "出発:"); `map_language` already follows the UI language but the HUD does not. Needs an English text catalog and a setting | `tuning.py:155-165`, `pedestrian.py:982-1073` | medium | `tuning.py` + `ProjectSettingsModal.tsx` |
| V12 | **Photo upscale switch** (`upscale_popup_images`, default on, GPU heavy) | `config/upscaled_images.py:26` | small | `AppSettings.tsx` beside fast render |
| V13 | **Moving photo clips choices**: second shot, generator (`shots`, `parallax`, `chain`), colour match, sign locking. Today only the seven camera presets and the on/off switch are reachable | `tuning.py:987-1382` | small each | `WaypointEditor.tsx` / `ProjectSettingsModal.tsx` |

### Voice and text

| # | Feature | Size | Host |
|---|---|---|---|
| T1 | **Speaking style for the Natural voice** (`settings.tts.caption`, default "明るく元気で…"). Add a text box with presets (calm, energetic) for the Irodori engine and add `caption` to the `tts` type | small | `VoiceSettings.tsx`, `types/index.ts:142` |
| T2 | **Caption look extras**: shadow, shadow colour, letter spacing, text opacity. The editor preview already draws them; only the controls are missing | small | `components/ui/CaptionStyleFields.tsx` |
| T3 | **Narration cue helpers**: buttons that insert `{start}`, `{arrive}`, `{end}` markers, and the `auto_overview_cues` / `auto_narration_cues` switches | medium | `ScriptInput.tsx`, `WaypointEditor.tsx` |
| T4 | **Romaji map labels** (`subtitle_language: "romaji"`) for viewers who cannot read Japanese | small | `OverviewPanel.tsx` or `ProjectSettingsModal.tsx` |
| T5 | **Voice cache size and a Clear button** (500 MB shared cache) | small | `VoiceSettings.tsx` or Storage in `AppSettings.tsx` |
| T6 | **Wider speed range**: the slider stops at 0.5-2x, the engine accepts 0.25-4x | tiny | `VoiceSettings.tsx` |
| T7 | **Translated subtitles.** Python has no translator at all (`translator.py` was planned and never written), so this is a build, not wiring | large | new `services/translator.py` + `Inspector.tsx` |

### Generating and editing

| # | Feature | Size | Host |
|---|---|---|---|
| G1 | **"Regenerate everything" (force)**. `start_render` already accepts `force`; the UI never sends it | small | `GenerateDialog.tsx` / `RenderOverlay.tsx:241` |
| G2 | **Per-stop regeneration**: redo one stop's voice, subtitles, photo clip or leg without rerunning the pipeline (modes `tts N`, `attraction N`, `subtitle N`, `residential N` exist). Today a redo deletes files and reruns everything | medium | `WaypointEditor.tsx`, `ReviewStep.tsx` |
| G3 | **Review and approve multi-photo clips**, then call `attraction-finalize` (its docstring says the frontend should) | medium-large | `WaypointEditor.tsx` |
| G4 | **GPS import with stay detection**: `import_gps_track` returns the places a track stopped at (`gpsparser/stays.py`) and nothing calls it; the import is done in TypeScript instead. Could create stops from dwell points with radius and minimum-stay controls. Check first whether the TypeScript `stopsAlongTrack` already covers part of this | medium | `useFileActions.ts`, `NewProject.tsx` |
| G5 | **Previews**: `map` (the overview framing, seconds long), `overview-tts` (hear the overview voice) | small | `OverviewPanel.tsx` |

---

## 3. Settings Python reads that nothing sets

Not exposed by any screen (so they stay at their defaults). Use as a menu when building V5-V9.

- **Map and tiles:** `mapbox_style_id`, `mapbox_style_id_<lang>`, `mapbox_retina`, `tile_cache_dir`, `subtitle_language`
- **Pace:** `mode_speeds_kmh`, `animation_speeds_kmh`, `overview_speed_multiplier`, `overview_target_seconds`, `overview_chars_per_second`, `overview_cue_wait_seconds`, `max_early_arrival_seconds`, `post_arrival_hold_seconds`, `res_duration`, `res_target_avg_seconds`, `res_max_segment_seconds`, `duration`, `speed_kmh`
- **Cards and HUD:** `summary_card_style`, `summary_card_labels`, `theme` (HUD light/dark), `card_border_color`, `card_border_thickness`, `map_font_size`, `clip_summary_hold`, `show_segment_summary`, `outro_style`, `outro_route_info`
- **Pins:** `arrived_marker_color`, `start_pin_color`, `end_pin_color`, `drawn_pin_color`, `stopby_pin_color`, `mode_line_colors`, `history_color`, `marker_filename`
- **Camera and engines:** `camera_follow_distance_m`, `bearing_smoothing`, `use_pydeck_overview`, `use_pydeck_pedestrian`, `enable_gl_ending_zoom`, `overview_background`, `use_3d_res`, `merge_stopby_waypoints`, `overview_describe_stops`, `min_free_ram_gb`
- **Popups:** `fullscreen_transition`, `trigger_radius_padding`, `hide_route_on_popup`, `enable_fullscreen_popups`, `hide_upcoming_pins_on_popup`
- **Voice and text:** `tts.caption`, `auto_overview_cues`, `auto_narration_cues`, `upscale_popup_images`, `intro_title_style`, `intro_subtitle_style`, `intro_kicker_style`, legacy `subtitle_font` / `subtitle_font_size` / `subtitle_color` / `subtitle_outline_color` / `subtitle_bold` (still read, although a type comment says they are not)
- **Per stop:** `freeze_seconds`, `overviewHighlight`
- **In `timeline.json`:** `resolution`, `fps`

**Written by the frontend, never read by Python (dead):** `routeMarker`, `customMarker` (see bug 3), `default_export_resolution`, `quick_export`
(frontend only, that one is fine), `show_route_heatmap`, `ors_api_key`, `start_coords`, `default_route_mode`, `auto_save_interval`,
`intro_location_manual`, `intro_location_at`, `imageTransitions`, `curveOffset`, `timestamp`, `imageCredits`, and `imagePans` (Python uses the derived `camera_pans`).
Most are frontend-only on purpose. Only the marker, export-resolution and image-transition ones are broken promises.

**Hard-coded in `tuning.py` with no override at all:** x264 quality (CRF 18) and preset, popup fade and minimum display times, ending highlight timing,
leg shot holds, intro image count and timing, outro duration, background colour and scroll speed, TTS pause lengths and chunk size.
Make a constant a setting only when a user asks; the file is the right home for tuning knobs.

---

## 4. Command-line modes and who calls them

| Mode | Status | Note |
|---|---|---|
| `full_pipeline`, `render_timeline`, `estimate`, `tts-all`, `subtitle-all`, `concat` | wired | `full_pipeline` is called without `--force` (G1) |
| `get_furigana`, `extract_words`, `read_document`, `system_info`, `convert_images`, `list_fonts`, `google_fonts_catalog`, `install_google_font` | wired | |
| `tts_voices_list`, `tts_voice_add`, `tts_voice_delete`, `tts_voice_preview`, `tts_engines` | wired | |
| `tts_install_kokoro`, `tts_install_qwen3`, `tts_install_irodori`, `comfyui_install` | wired | built from a variable in `VoiceSettings.tsx` and `ComponentsChecklist.tsx` |
| `import_gps_track` | **unwired (checked)** | zero hits in `src/`; import is done in TypeScript (G4) |
| `overview-script`, `overview-tts` | unwired | V1, G5 |
| `upscale-images` | unwired | runs inside `full_pipeline`; no switch (V12) |
| `attraction`, `attraction-all`, `attraction-finalize`, `attraction-tts`, `attraction-tts-all`, `tts N`, `subtitle N` | unwired | G2, G3 |
| `map`, `residential`, `intro`, `outro`, `transition`, `mux`, `gps`, `all`, default overview | internal | developer and test hooks. `map`, `intro`, `outro`, `residential N` could become previews |

Rust and TypeScript side: `cancel_python_blueprint` has one caller. These database commands have wrappers in `db.ts` that nothing uses:
`project_create`, `project_get_by_dir`, `project_delete`, `project_restore`, `project_purge`, `settings_delete`, `version_delete_all`,
`route_cache_get`, `route_cache_put`, `route_cache_put_many`, `route_cache_delete`, `route_cache_prune`, `route_cache_clear`, `app_setting_delete`, `app_setting_list`.
They look like groundwork for a trash view and a cache cleaner; keep them or build those features. No frontend `invoke` name lacks a Rust command.

---

## 5. Dead or legacy code

Checked by searching for imports across `src-tauri`, `src`, `e2e`, `setup`. Delete only after reading the file once more and running the tests.

| File | Finding |
|---|---|
| `vdoprocessing/framesink.py` | nothing mentions it **(checked)** |
| `vdoprocessing/local_pan_generator.py` | imported only by `tests/test_local_pan_without_torch.py`; production code only mentions it in comments **(checked)** |
| `services/model/` (`classic_pan`, `depth_parallax_pan`, `zoom_out_pan`, `outpaint_pan`, `outpaint_sd15`, `outpaint_test`) | nothing imports the package; they reference each other and `local_pan_generator.py` **(checked)** |
| `localization/llmscript.py` | only tests import it |
| `tts/tts.py` | no importers (duplicate subtitle classes) |
| `use_leg_storyboard` flag | raises `NotImplementedError` (`route2vdo.py:783`) |
| `hooks/useTransition.ts` | no importer found (not checked carefully) |
| legacy 3D vehicle renderer (`use_3d_res`, `coinprop.py`, `renderer.py`) | no UI; **not dead**: `recorder.py` is still imported by `pedestrian.py` |

---

## 6. Suggested order of work

1. **Bugs 1, 2, 5, 8** (one afternoon): Fly mode, local model key, Mapbox key for legs, marker radius.
2. **Bug 3 decision**: build custom pins in the renderer, or hide the three controls. Do not leave a promise the video breaks.
3. **V3 + bug 11** (export options) and **V2 + bug 4** (video map style): the two things people compare between editor and result.
4. **V1** (overview script panel): fixes bug 6 and gives the editor the review step already advertises.
5. **G1 + G2** (force, per-stop redo): saves the most waiting time.
6. **V4-V9** as one "look of the video" settings page.
7. **T1-T6** in one pass through the Voice and caption controls.
8. **G4** (stay detection) and **V11** (English on-video text) when the product wants new users abroad.
9. **T7** (translations) is a separate project.
10. Clean up section 5 and the stale notes (bug 12).

Add a test with every change (see recipe 12.9 in the developer guide) and update `docs/FEATURES.md` and the manual when a feature ships.
