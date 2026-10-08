# Code map (frontend)

What lives where and why, for agents. Kept here instead of long code comments (the user
prefers lean source files). Update it when you move or rewrite something listed here.

## Shell

| File | Role / non-obvious behaviour |
|---|---|
| `components/ui/TitleBar.tsx` | Frameless window bar (h-10, z-9999). App menu (`MenuItem`, `MenuSeparator`), undo/redo, Map/Timeline switch, settings, window buttons. Escape closes the menu. |
| `components/ui/StatusBar.tsx` | Editor-only (h-7). Stats (map vs timeline), saved state, History + System log popovers; both close on outside mousedown / Escape. Opening the log clears the unread dot. Render estimate comes from the Python estimator (see below). |
| `components/ui/Toast.tsx` | Bottom-right above the status bar. 3.7 s, errors 7 s; hover pauses the timer. |
| `components/ui/ErrorBoundary.tsx` | Wraps the whole app in `main.tsx`, so when it shows the TitleBar is gone: it draws its own drag strip with minimize/close. Details = stack + component stack; Copy copies both. |
| `components/ui/Tip.tsx` | Hover label for icon buttons: put inside a `group/tool relative` button, give the button an aria-label (Tip is aria-hidden). 300 ms delay, instant on keyboard focus. `align` start/end for buttons at window edges. |
| `components/ui/Tooltip.tsx` | Wrapper tooltip for longer text (unused so far). |
| `components/ui/Switch.tsx` | On/off switch; stops click propagation so it works inside clickable rows/labels. |
| `components/ui/Dialog.tsx` | Small modal shell (title, subtitle, body, footer). Inset below the TitleBar, Escape + backdrop close. `dialogButton.{secondary,primary,danger}`, `dialogInput`. Used by SaveAs, UnsavedChanges, ProjectManager dialogs, ProjectSettingsModal. |

## Context menus

- `components/ui/menuItems.ts`: `MenuEntry` (item / `separator` / `{type:"label"}` heading), `openContextMenu(event, items)` (prevents default + stops propagation, dispatches `open-context-menu` with `type:"items"`), `tidy()` drops stray separators from conditional items (`false`/`null` entries are filtered).
- `components/ui/ContextMenu.tsx` (mounted once in App):
  - `openedThisEventRef`: the window `contextmenu` listener runs after component handlers; the flag stops it from closing/replacing a menu opened in the same event.
  - Unhandled right-clicks: text fields get Cut/Copy/Paste/Select all (`execCommand`; paste = `navigator.clipboard.readText` + `insertText` so undo history and React onChange work); selected text gets Copy; otherwise no menu (the browser menu is always suppressed).
  - `MenuPanel` measures off-screen, then clamps/flips into the window; submenus are separate portal panels anchored to the item rect (flip left if no room). Panel `onMouseDown` preventDefault keeps focus/selection in the field the menu was opened from.
  - Needs `transition-none`: `duration-100` sets transition-duration and the default transition-property is `all`, so the move from the measuring spot animated (menu "slid in from the top-left").
  - Keyboard: arrows/Home/End/→/←/Escape inside panels; a capture listener routes arrows/Escape into the menu when focus fell outside it.
  - Only `items` menus exist now; the old typed timeline menus were removed with the old editor.
- `features/map/hooks/useStopMenus.ts`: `useModeOptions`, `VIA_MODES` (walk/drive/ferry can take via points), `useLegActions` (`setLegMode` seeds a Draw leg with the routed segment's inner points, then opens draw mode), and the menus `stopMenu`, `legMenu`, `viaMenu`, `mapMenu`.

## Map editor

- `features/map/components/MapArea.tsx`
  - Camera is uncontrolled (`initialViewState`); read it via `mapRef`. A `viewState`+`onMove` setState loop re-rendered everything each frame.
  - Thumbnail: 1.5 s after moveend, copy the canvas inside a `render` event (no preserveDrawingBuffer) into a ≤640 px canvas ref; encoded to PNG only when saving (`registerThumbnailGetter`).
  - `handlePinClick`: select tool only; `pinDraggedRef` swallows the click that follows a drag.
  - `removeAnchor(idx)` keeps the insert point on the same anchor. `fitToLeg` pads top 170 px to clear toolbar + draw bar.
  - Window events handled: `enter-via-mode`, `exit-via-mode`, `enter-draw-mode`, `focus-waypoint` (flyTo), `select-anchor`.
  - On mount consumes `utils/pendingImport.ts` (set by NewProject) and runs `importRouteFile` / `handleDroppedFiles` with the fresh (reset) workspace.
- `MapCompass.tsx`: subscribes to map `rotate`, writes the needle transform to the DOM; keeps an unwrapped angle so the CSS transition always turns the short way across ±180°.
- `MapToolbar.tsx`: V/P/L/E/Escape handler registered once, reads state from a ref (re-subscribing mid-dispatch dropped Escape). Ignores keys with Ctrl/Alt/Meta and in text fields.
- `DrawBar.tsx`: leg picker, Add/Erase, Smooth, points list (synced with MapArea via `select-anchor`), zoom, More (copy path / clear), Done. `useDismiss` closes its popovers.
- `WaypointItem.tsx`: stop row + leg row; right-click = `stopMenu` / `legMenu`. Via chip is informational (clearing lives in the leg menu).
- `WaypointEditor.tsx`: an unlinked stop-by has no attraction clip, so its Attraction section is hidden. Photo cards have a context menu (camera angle, reveal, remove).
- `GenerateDialog.tsx`: confirm before "Generate assets" (Dialog shell). Summary of what will run (route legs, voiceover, photo clips, title card; the last three dim/skip with Fast render), time estimate from the Python `estimate` command (saves the project first, then `run_python_blueprint({action:"estimate", payload: job_config path})`; do not call it while a render runs, a new blueprint call kills the previous process), amber warning listing stops with no narration, switches for `skip_rich_media` / `quick_export`.
- `OverviewPanel.tsx`: intro title card row (text only). My size/color/bold controls (`settings.intro_style`, `introLook.ts`, `introclip.intro_look`) were dropped in the merge with
  origin/main, whose intro title and subtitle are text-track items styled per line (`settings.intro_title_style` / `intro_subtitle_style`, `localization/text_style.py`, `intro_step.intro_text_item`, `burn_text=False`),
  edited in the timeline Inspector.
- Per-leg colour: `Waypoint.lineColor` (RGB, colour of the leg *leaving* that stop; unset = `settings.line_color`).
  Saved to job_config by `fileSystem.ts`. Edited via `LegColorButton.tsx` (leg row dot) and the leg menu's "Line colour"
  submenu (`useStopMenus.ts`); hidden for direct/curve (`legColorable`). `RouteLayer.tsx` maps segment i → i-th routed
  waypoint (stop-bys not on the route skipped) and uses `["coalesce", ["get","color"], routeColour]`; memo keyed on a
  colour string so narration edits don't rebuild the GeoJSON. Swatches/hex helpers: `components/ui/ColorSwatches.tsx`.
  Backend: `helpers._build_point_colors` (BGR per point, same leg rules as `_build_point_modes`) → overview colour
  breakpoints (`overview.py` `self._color_breakpoints`) → `mode_history` entries `(mode, bgr)` → `drawing._segment_color`.
  Each leg's `res_data["line_color"]` (leg colour or project route colour, RGB) → pydeck leg `walker_color`.
  Pydeck *overview* (off by default) still uses its own trail colour.
- `utils/stopLabel.ts`: badge text — S, E, "+n" for the n-th stop-by in a run, else the stop number (stop-bys not counted).

## Screens / dialogs

- `components/view/ProjectManager.tsx`: grid/list (remembered in `navivi_project_view`), relative dates via `Intl.RelativeTimeFormat`, one `projectMenu()` for right-click and the ⋯ button. "Duplicate" is still a stub (toast only).
- `components/ui/NewProject.tsx`: name, Start from (blank / GPS track / photos — files picked here, imported by MapArea after the editor opens), starting point (last choice in `navivi_last_origin`, else localized Osaka), default travel mode, export ratio (`default_export_ratio`, used by ExportModal), title card (`enable_intro`, `video_title` only if typed so it keeps following the project name, `video_subtitle`), fast render.
- `components/ui/AppSettings.tsx`: `Section` / `Row` / `Badge` / `NumberInput` / `MarkerTile`. Project-scoped settings go through `updateProject` (marks dirty). AI tab falls back to General when AI is switched off.
- `components/ui/ScriptInput.tsx`: commits on blur and Ctrl+Enter (Save/scan buttons preventDefault on mousedown so they don't blur first); `漢字(かな)` in text is moved into the pronunciation dictionary on save.

## Render log

- `utils/pipelineLog.ts`: folds piped pipeline output back into terminal behaviour — tracker lines that only advance a counter replace the previous row (`statusKey` = text with counters stripped), ffmpeg `-stats` lines attach to the current row (`tool`), `[n/N]` opens a stage, main.py's final JSON result becomes one error row with the traceback as `details`. `lastPipelineError` prefers the pipeline's own error over the app's generic one.
- `components/ui/PipelineLogPanel.tsx`: `STAGE_MATCHERS` = the 7 stages of `run_full_pipeline` (keep in sync with pipeline.py); sticks to bottom only while the reader is at the bottom; app errors only shown when the pipeline gave none.

## Render time estimate (Python)

- `services/render_estimate.py`: `workload(config)` = units per pipeline stage (voice chars, clips, video seconds), times a cost per unit. Cost = median of the last 6 recorded runs once there are 2+ (`~/Documents/Navivi/render_timings.json`), else a default scaled by `hardware_profile()["speed_factor"]` (cores, nvidia-smi GPU/VRAM, none = 1.8x). `STAGES` order = the 7 `tracker.stage()` calls.
- `StageRecorder` is hooked through `tracker.on_stage` in `run_full_pipeline`; it stores units/seconds per completed stage. Cached clips make samples fast, so estimates drift low after reruns.
- `main.py estimate <job_config.json>` prints the JSON. StatusBar still uses its own 1.5 min/stop guess; RenderOverlay has no live ETA from it yet.

## Export after generation (RenderOverlay)

- Quick export and "Accept assets & export" both run `handleStitchAndExport` -> Rust `export_video` -> `main.py render_timeline <project>/timeline.json`; Rust now returns the exported video's path (shown as "Show Video").
- Do not re-save timeline.json from editor state before this: the pipeline's file carries `audio_path` per clip, the editor's compiled manifest did not, so the export was silent. `toManifest` (editor/model.ts) writes `audio_path` per clip, and `render_from_timeline` calls `recover_narration_paths` for files an older editor saved without it.
- No silent `concat` fallback any more: an export error is shown as is.

## Timeline editor (`features/editor/`)

Rebuilt as a clip sequence, matching what the Python exporter can do (concat of clips, each with its own narration). The old multi-track Konva editor and ExportModal are gone.

- `model.ts`: pure logic, no React. `TimelineData` = `segments` (video, trimIn/trimOut, narration `audio` + `audioOffset`, volume, muted, `fadeIntoNext`), `subtitles` (cues *anchored to a segment*, times relative to it, so reordering/trimming keeps them with their clip), `music`, `burnSubtitles`. `layout()` gives start/length per clip (length = max(trimmed video, audio end)). `autoArrange` (intro, overview, then attraction_i + leg_i+1, outro; adds the leg→attraction fade), SRT parse/format, `autoTimeBlocks` (SRT without timestamps: text spread over the narrated time by length), `cuesFromSegmentFile` (the pipeline's per-narration .srt), `toManifest` / `timelineFromEditorState` / `timelineFromPipeline`.
- timeline.json: `video_tracks` (what Python reads: `trim_in/trim_out/volume/muted/audio_offset/fade_into_next_seconds`), `subtitles` (global times), `burn_subtitles`, `music`, plus `editor` = the full state for reloading. `fileSystem.loadTimelineData` uses `editor` if present, else builds from the pipeline's file (probing media lengths in the webview). `saveTimelineManifest` skips an empty timeline so it can't wipe the pipeline's file.
- `EditorView.tsx`: toolbar (add video/music, subtitles menu, Auto edit, zoom, Export), keyboard (Space, arrows, Del, M), context menus, all import/auto actions. Drags edit a `draft` copy and commit once on release, so undo is one step per gesture.
- `TimelinePane.tsx`: DOM lanes (ruler, video, narration, subtitles, music). Video blocks drag to reorder, edges trim; narration bar drags to shift; cues drag/resize and re-anchor to the clip under them; double-click the subtitle lane to add. Subtitles multi-select: shift/ctrl-click toggles, dragging on empty lane draws a marquee, Ctrl+A selects all; `Selection` cue form carries `ids`, read it with `selectedCueIds`. Dragging one selected cue moves the whole group; Inspector shows `MultiCueSection` (style patches go into every cue's own `style`).
- `player.ts` + `Preview.tsx`: play position lives in an external store (only playhead/timecode/subtitle overlay re-render per frame). Preview runs a rAF clock and slaves one `<video>`, one narration `<audio>` and a music `<audio>` to it.
- `Inspector.tsx`: clip (trim, narration offset/volume/mute, fade), subtitle (text, timing), or project (subtitle list, burn toggle, music).
- Export: `ExportDialog.tsx` saves timeline.json then `export_video`. Python (`VideoExporter.concat_from_timeline`) trims, applies volume/mute, crossfades, then `_finish_timeline_output` mixes the music loop and burns the cues (`cues_to_srt`).
- Not in the editor: splitting a clip, per-clip transitions other than the fade, resolution/aspect settings (size comes from the clips).
- Harness: `scratch/overlay-check/index.html?editor=demo&render=0` (or `editor=media`) opens the editor with a demo timeline; the mocked `convertFileSrc` returns an SVG so real playback can't be tested there.

- `components/ui/VoiceSettings.tsx` (Voice tab of AppSettings): voice library from `tts_voices_list`, picks `settings.tts.voice`, speed slider (`settings.tts.speed`, default 1.25), preview (`tts_voice_preview`, first one is slow: it loads the model), add (`tts_voice_add`, ASCII slug id, replace confirm) and delete (shared by all projects). One blueprint call at a time: `run_python_blueprint` kills the previous process, so every button is disabled while a call runs. Same API doc as the backend note `docs/tts-voices-api.md`.

## Own videos at a stop, music library

- Waypoint `videos` (+ `videoSound[]`, default all false): added in the Videos tab of `WaypointEditor` (`WaypointVideos.tsx`, max 3). `fileSystem` copies them to `assets/video/user/` and writes `videos`/`videoSound` into job_config (`job_config.py` resolves `videos` to absolute). Photos stay in `images`/`popup_image` (popup cards read those as images, so videos must not go there).
- Python: `helpers.has_attraction_media` (photo or videos) gates the attraction step. `user_videos.process_user_videos` replaces the ComfyUI/pan generation: videos are normalised silent, fitted to the narration by the generator's own `_fit_and_finalize` / `_combine_clips` (hold last frame or trim, scale, place label). Re-run only when the files, sound flags, narration length or label change (`<clip>.src.json`). With "keep its sound" the footage audio goes to `<clip>.orig.wav`; `timeline_step` lists it as `extra_audio_path` (+ `extra_audio_volume` 0.5), the editor shows it as `Segment.extraAudio` ("Original sound" slider, played by a 4th `<audio>` in Preview), and `_mux_track_for_concat` amixes it under the narration.
- New Project no longer has a Photos tile; photos with GPS are still imported by dropping them on the map (`useFileActions.handleDroppedFiles`: skips and reports photos without a location).
- `features/editor/MusicPicker.tsx`: the editor's Music button. Library = audio files in `Documents/Navivi/Music/` (created on first open), optional `library.json` (array or `{tracks:[]}`) of `{file, title, tags[], credit, license, url}` adds names/tags/credit. A picked track is copied into the project (`assets/audio/music/`); `MusicBed.credit` is shown in the export dialog. No tracks are bundled: licences must be checked per track first.
- GPX/FIT/TCX/KML import (`useFileActions.importRouteFile`, helpers in `utils/gpxTrack.ts`): stops = the file's named waypoints snapped to the track in track order, plus the track's start/end if no waypoint is near them (150 m); with no waypoints, 5 stops sampled along the track. Each leg between two stops is a `draw` leg whose `customRoute` is the recorded points between them (Douglas-Peucker, 4 m), so the video follows the real track instead of a re-routed one. Names: the file's, minus Google's "日本、〒… " prefix, else Nominatim (1.1 s apart) else Start/End/Stop n. Track points fall back to `<rtept>`.
- Map markers: the name label is `absolute` above the pin and `pointer-events-none`, so the marker's draggable box is only the pin (it used to be as wide as the label, so hovering or dragging beside a pin moved the stop). MapArea resizes the mapbox canvas from a ResizeObserver on its container and once in `handleMapLoad` (a reused map keeps its old size, which left a strip at the bottom).
- Waypoint narration prompt (`services/narrationPrompt.ts`, pure so it can be tested in node; `ollamaApi.generateWaypointScriptStream` fetches the facts, calls the model with temperature 0.4 / repeat_penalty 1.1 and runs `cleanNarration` on every chunk). Rules: use only the given facts, the user's request (top priority), the photo and the real previous/next stop (`RouteContext` from WaypointEditor / AutoDirector); with thin facts stay general instead of inventing history; exact length and TTS-safe output rules; no greeting on "arriving". A/B script: `.agents/scratch/prompt-ab.mts` (needs the local Ollama + gemma model; before, the 2B model invented history for a stop with no facts).
- TTS stray "あ": the Irodori model sometimes emits a 40-80 ms burst, as loud as speech, alone in the middle of a pause (seen at comma pauses; 4 of 11 narration files in the Shirahama project; a fresh take with a plain `、` reproduced it at the pause after "地下には、"). `services/tts/artifacts.py::remove_stray_bursts` finds sounds <= 90 ms with >= 150 ms of silence on both sides (file edges count as silence) and silences them with a 4 ms fade; length and all other samples are untouched. It runs on every new narration (`IrodoriTTSClient.generate_speech`, after any chunk join) and on reused narration files in `audio_step` (so existing projects are repaired on the next generate without regenerating). The cause is the model, not the text: replacing `、` was not shown to help (few takes), so the text is left alone. TTS takes ~80-120 s per sentence on CPU.
- Pronunciation "scan kanji" button (`ScriptInput.handleScanKanji`): calls the Python action `extract_words` (text as the payload) and adds whole words with readings, filling empty readings of existing entries; falls back to plain kanji runs if Python can't be reached. `services/localization/japanese_words.py`: fugashi + unidic-lite tokenise; a verb/adjective keeps its okurigana (透き通る) and a following て/た (透き通った); runs of nouns/prefixes/suffixes join (三段壁, 源平合戦); readings come from UniDic's `kana`. Unknown place names are the weak spot (白良浜 → しろよはま, 三段壁 → さんだんへき, no rendaku): the user fixes those by hand. `get_furigana` (Auto-fill readings) uses the same analyser. Needs `fugashi` and `unidic-lite` (requirements.txt).
- Pronunciation dictionary scopes: project (`settings.pronunciation_dictionary`) and app-wide (app settings DB key `GLOBAL_DICTIONARY_KEY`, edited under Settings → Pronunciation → "All projects"; the only scope shown outside the editor, where Video/Voice tabs are hidden too). `saveProjectData` copies the app-wide list into each job_config as `settings.global_pronunciation_dictionary`; Python merges it (`audio_step.merge_pronunciation`, project entry wins) and replaces longest words first. Editing the shared list in an open project marks it dirty so that copy refreshes on save. Known gap: changing a dictionary entry does not regenerate narration already on disk (the saved-text check compares the script before the dictionary is applied).
- `ProjectSettingsModal.tsx` has one shared `ProjectSettingsForm` (route marker, Rendering options `enable_attraction_videos`, `use_narration_cues`, `attraction_fade_seconds`, look of the video, map style) and two shells. `ProjectSettingsModal` (Project Manager → "Project settings", project closed) writes job_config.json AND patches the DB (`db.settings.patch`): the DB is what the app reads when it opens a project, so the file alone was silently overridden. `OpenProjectSettings` is the "Project" tab of App Settings (editor only; File → "Project settings..." opens App Settings on it via the `open-app-settings-tab` event). It edits the open project's workspace `settings` live (`updateSettings` + `setIsDirty`), so it never touches the files and saves with the project, and it leaves out the route marker (the Video tab has the full picker). There is deliberately no separate title bar button or second dialog.
- Dropdowns are `Select.tsx` everywhere in settings (`disabled`, `placeholder` props); no native `<select>`. The App Settings window is `clamp(46rem,78vw,72rem)` × `clamp(34rem,82vh,52rem)`; the project dialog is `clamp(36rem,52vw,48rem)` wide.

## Project folder layout (2026-10-01)

- `services/projectfiles.py` (Python) and `fileSystem.metaFolder` (TS) name the places: generated files live in `<project>/.navivi/` (`routecache.json`, `narration_cues.json`, `overview_narration.json`, `asset_manifest.json`, `gpsdata/`); `meta_file()` reads the new name and falls back to the old root file, `meta_path()` always writes the new one. Tiles: `tile_cache_dir()` = `Documents/Navivi/Cache/tiles`.
- `src-tauri/src/project_files.rs`: `tidy_project_folder` (one-time migration, idempotent, run by `useWorkspace.loadProject` after `syncProjectOnOpen`: deletes the `<name>.nvv` JSON copy of job_config.json — or promotes it if job_config.json is missing, or parks a differing one in `.navivi/legacy/` — moves the root dot-files into `.navivi/`, moves `cache/` to the shared tile cache (or deletes it if that exists), removes `.history/`) and `export_project_archive` (streamed zip; skips `cache/`, `.history/`, `.navivi/gpsdata`, other `.nvv`; leaves out `assets/video/**` (except `user/`) and `assets/image/map` unless "include rendered").
- Saving no longer writes a `.nvv` or a zip; `projects.archive_path` is cleared on open (patched to "" since the patch can't set NULL) so the Project Manager opens the folder. Opening a shared `.nvv` unzips into `Workspaces/<slug>` (never over an existing folder). UI: `ExportProjectDialog.tsx` (event `export-project`, from the editor menu and the project card menu; the editor's project is saved first).
- On the real Shirahama project (copy): 430 MB -> 108 MB folder, lean archive 17.7 MB (was zipping everything, one old archive is 1.5 GB). Old archives in `Documents/Navivi/Projects` are untouched.

## Startup (Discord-style splash window)

- Two windows in `tauri.conf.json`: `splash` (420x460, no decorations, always on top so it is not lost behind the editor or terminal, loads `splash.html`) is shown at once; `main` (1200x800, min 1000x600) starts hidden. `splash.html` is a second Vite page (see `build.rollupOptions.input` in vite.config.ts) with the logo animation: the route is drawn from the start dot to the waypoint (`.nv-route` / `.nv-start` / `.nv-pin`, one 3.2 s loop; reduced motion shows it static). `capabilities/splash.json` only allows dragging it.
- `main.tsx` calls `revealApp()` (`utils/splash.ts`) after the first render -> Rust `app_ready` waits until 3.6 s after process start (`SPLASH_MIN`; the window itself appears about 1 s in, and the logo needs ~2.6 s after that, so the finished logo is seen briefly), shows and focuses `main`, closes `splash`. It is a no-op if the splash is already gone (dev reload). A thread does the same after 25 s (`SPLASH_GIVE_UP`) if the page never reports in, so a crash while loading can't leave the user on the splash.
- In a plain browser (harness, `npm run dev`) there is no splash and `revealApp` does nothing.
- Waypoint persistence has two hand-written lists that must match: the serializer in `fileSystem.saveProjectData` and the loader map in `useWorkspace.loadProject` (it does NOT keep unknown fields). A new `Waypoint` field has to be added to both, or it silently resets on reopen (that is how `lineColor`, `videos`/`videoSound`, `viaPoints`, `curveOffset` and `timestamp` were lost).
- Route cache keys come from one function, `utils/routeCacheKey.ts` (`from|to|mode|drawnHash` plus `|viaHash` only with via points, so caches from older versions still match). `useMapRouting` looks a leg up by it before calling OpenRouteService / OSRM, and `saveProjectData` uses the same function to prune unused legs. Before 2026-10-01 the hook's key had an extra trailing field the save didn't, so every save pruned the whole cache (the DB rows and `.navivi/routecache.json` ended up empty) and every reopen re-requested every leg.

## Review step (after generation)

- `components/ui/ReviewStep.tsx` is the page shown when generation finishes (unless "Export automatically" is on, which skips it; Fast render has no voices or photo clips to review). One card per clip in video order (title card, overview, each leg, each stop's photo/own-video clip, ending card), each with its player and, if it has narration, a play button and the script. Per clip two toggles: **Redo clip** (legs and stop clips) and **Redo voice**. Selecting a voice opens its text and a pronunciation fixer (word + reading, saved to this project or to all projects). A footer shows what is selected and has Customize in Timeline / Redo selected / Accept and export. State (`reviewRows`, `selection`, `edits`) lives in `RenderOverlay`.
- Row mapping (`buildReviewRows`): leg N = video `02_waypoint_NN_*` + audio of waypoint N-1 (`arrivingNarration`); stop clip = `04_attraction_NN_*` + audio `04_attraction_NN_*` (`attractionNarration`); overview text is read-only here (its script is edited in the Intro panel, and the app's save blanks it in job_config).
- Redo voice: apply the pronunciation fixes, write the edited text into the waypoint, save (`saveAfterRender`: `saveProject` reads the state of its own render, so it runs from an effect after the edit), delete the selected `.wav`s, then `tts-all` (the pipeline's checkpoints make only the missing ones) and `subtitle-all`. Redo clip: delete the clip files + render manifests, then on a high-spec PC open the timeline editor, otherwise mark the stops and open the map editor (Resume Generation redoes only what is missing).
- `main.py` splits a multi-word blueprint payload (`"tts 3 --force"`), since `run_python_blueprint` passes only one argument; before, the old review's "Regenerate Audio" sent `tts 3` / `tts overview` and the CLI never recognised them.

## Existing assets prompt and background redo

- `services/assetCleanup.ts`: `scanAssets(dir)` counts files per group, `clearAssets(dir, groups)` deletes them. Groups: voice (`assets/audio/*`, `.navivi/narration_cues.json`), subtitles (`assets/subtitles/*`), route (`assets/video/route/*` incl. manifest), photo clips (`assets/video/attraction/*`), cards (files directly in `assets/video`). Files only, so `assets/audio/music` and `assets/video/user` are never touched. Voice always takes subtitles with it (`withDependents`). Falls back to the old root `audio/`, `video/`, `subtitles/`.
- Why: the pipeline checkpoints every stage (audio by text + voice, route by a manifest, clips by file), so pressing Generate on a project that already has assets changes nothing. `GenerateDialog` scans on open; if anything exists it shows "This project already has assets" with a tick per group (none ticked = reuse everything, the button stays "Generate assets"; any ticked = "Delete and generate"). `Sidebar.executeGenerate(clear)` deletes, then saves and starts the render.
- Background redo: in the review step, "Redo in the background" (switch next to Redo selected, on by default) deletes the picked voices/clips (`prepareVoices`, `removeClipFiles`), switches to the timeline editor and runs the normal `start_render` (only the missing files are made) with `isBackgroundRender` set in `useUI`. The overlay collapses to a pill (`RenderOverlay`, "BACKGROUND PILL"): progress and stage while running (Cancel, Details), then "Review" (reopens the review step with fresh rows) or Retry/Dismiss on failure. "Keep working" in the expanded header collapses it again.
- While it runs: only the Timeline tab is enabled (TitleBar), the map stays locked, undo works in the timeline, Export is disabled (`isBackgroundBusy`, true only while it works, so it re-enables on finish or failure).
- On finish `finishBackgroundRun`: the pipeline has rewritten `timeline.json`. If the user edited the timeline meanwhile (`canUndoTimeline`), the editor state is saved back (edits kept; the redone files have the same names so they play in place, but a new voice's length is not re-probed), otherwise the timeline is reloaded from the new file.
- Limits: the old files are deleted up front, so a failed run leaves them missing until the next Generate; the project is not editable on the map while it runs.

## Ollama requests (`services/ollamaApi.ts`)

- `streamLLM` sends `think: false` and never uses raw mode (raw mode has no place for photos, which made Gemma 4 answer 400, and the forced thinking mode spent minutes recounting characters on a CPU). Non-thinking models accept `think:false` (checked on Ollama 0.35 with llama3.2 and gemma-2-2b).
- A 400 on a request with photos is retried once without them; the model is remembered as text-only for the session only if Ollama's message mentions images/vision. `modelSeesPhotos` reads `/api/show` capabilities and drives the warning in Settings > AI models.

## Background installs and onboarding (2026-10-08, from the Hyper-V test)

- Engine installs (three voices, ComfyUI, Ollama) run through `services/installs.ts` (`startInstall(id, label, action)`), not inside the dialog that started them, so closing the window keeps them going. One install at a time, but in a Python slot of their own: Rust `run_python_install` / `cancel_python_install` (`BlueprintState.install_process`, whitelist `INSTALL_MODES`, shared body `run_in_slot`), so opening the Voice tab, a preview or a render stage no longer kills a running install and an install no longer kills them.
  `cancelInstall` stops it; the call comes back as cancelled and the job vanishes (installs resume).
  `hooks/useInstalls.ts` reads the store; `ui/InstallToast.tsx` (bottom left) shows one compact box per install and opens a details dialog (steps, output, full error) on click. Failures stay until dismissed; "ready" fades after 5 s.
- Progress: Python installers call `services/install_progress.py` (`begin(total)`, then `step(label)` from `kokoro_setup._run`, shared by qwen3/irodori/comfyui) which prints `[progress] <done>/<total>|<label>` on stderr. Rust forwards every stderr line as an event, `install-log` for installs (`blueprint-log` for the normal slot), and still collects the whole text for the error. It is step-based, not byte-based: the model download inside a step shows as one step. `installs.test.ts` covers the line parser.
- First-run setup screen (`SetupGate`): `setup.ts` `parseDownloadLine` turns Playwright's `|■■■  | 40% of 150 MiB` lines into a second progress bar and keeps them out of the log. The checklist dialog button says "Skip for now" until a voice is ready, then "Done".
- `ComponentsChecklist`: long text moved into `InfoTip` (circled i, `SettingsParts.tsx`; `Row` takes `info`). Only required items (VC++ runtime, one voice) go in the colored box; optional sections get an "Optional" badge (`Section optional=`). `ProviderPicker allowNone` adds "None" (= `ai_features_enabled: false`) and takes children,
  so the Ollama rows sit inside the provider box. The ComfyUI section is greyed out without an NVIDIA card. Voices are named by model (Kokoro-82M, Qwen3-TTS, Irodori-TTS), not Fast/Balanced/Natural.
- Settings: tab order is project / video+voice / pronunciation / the rest, separated by dividers (`tabGroups` in `AppSettings`). The sidebar's slider button opens Settings on the Project tab through the `open-app-settings-tab` event. AI models "Active model" only shows a model that is installed (the unset default `DEFAULT_LOCAL_MODEL` used to be shown even when absent).
  `Segmented` buttons no longer truncate (they were squeezed to "Col…" in the video look rows). Voice tab: with exactly one engine set up, the project's engine switches to it.
- Map: picking a different stop drops Add/Draw back to Select (`MapArea`, `drawTargetRef` keeps the stop that draw mode was opened for). The elevation profile is bottom-left (it overlapped the collapsed WaypointEditor, which made it impossible to expand) and the uphill/downhill key is top-left and smaller.
  Both use `hooks/useMapPanelOpacity.ts` (localStorage, slider in Settings > Appearance) through the `--panel-alpha` variable (`bg-white/(--panel-alpha)`).
- Bundled FFmpeg: `route2vdo._freeze_video_end`, `local_pan_generator` and `vdoeditor`'s ffprobe calls used a bare `ffmpeg`/`ffprobe` and crashed with WinError 2 on a PC without FFmpeg on PATH; they now use `runtime_paths`. `GPSParser.clean_data` no longer fails with "index 0 is out of bounds" when every track point has a name (all points used as the route).

## Installer (2026-10-05)

- Build: `npm run build:installer` (= `tauri build --config src-tauri/tauri.installer.conf.json`, NSIS, per-user install, ja/en). `beforeBuildCommand` runs `scripts/stage-installer.mjs`, which fills
  `src-tauri/installer-staging/` (gitignored; downloads cached in `scripts/.cache`): `src-python/` (code, assets, `requirements-runtime.txt`; no `bin/`, tests, data), `tools/ffmpeg/bin/{ffmpeg,ffprobe}.exe`
  (gyan.dev "essentials": has libass `subtitles` and `xfade`), `tools/gpsbabel/` (CLI only: gpsbabel.exe + Qt5Core + Qt5Xml, 7 MB instead of 161), `tools/uv.exe`. About 290 MB staged, 114 MB installer.
  The installer config is separate so `tauri dev` never copies resources. Python is NOT bundled: it is made on first run (below), so the installer stays small.
- Layout when installed: `<install>/{navivi.exe, src-python/, tools/}` (read-only), `%LOCALAPPDATA%\navivi\runtime\venv` (the pipeline's Python), `%LOCALAPPDATA%\navivi\bin` (engines, recorded voices).
- `src-tauri/src/runtime.rs` decides the layout (`running_from_repo()` is true only for a debug build with `src-python/main.py` beside the cwd: an installed app's cwd also holds that file, which
  fooled the first version). Every Python spawn goes through `lib.rs::python_command()`: `runtime.command()` sets cwd, `NAVIVI_BIN_DIR`, `NAVIVI_TOOLS_DIR`, `NAVIVI_UV`, hides the console window
  (CREATE_NO_WINDOW; a release build would flash one per call) and adds the AI keys. With no venv yet it fails with `SETUP_REQUIRED`, which `services/sidecar.ts` and RenderOverlay turn into the setup dialog.
- First-run setup: `SetupGate.tsx` (mounted in App) asks `runtime_status`; for an installed app without a venv it shows the dialog. `runtime_install` (Rust) runs `uv venv --python 3.12`, then
  `uv pip install -r requirements-runtime.txt`, then `python -m playwright install chromium`, streaming `setup-step` / `setup-log` events. Idempotent. Verified against the real installed exe
  (silent install into a temp folder, WebView2 remote debugging + Playwright CDP): dialog, steps, `system_info`, GPSBabel and a real intro render all worked.
- Python side: `services/runtime_paths.py` is the one place for tool and engine paths (`bin_dir`, `engine_dir`, `ffmpeg_exe`, `gpsbabel_exe`, `uv_exe`); nothing else builds a path to `bin`. Before this,
  `ttsengine`, `vdoeditor` and `vdoexporter` looked for FFmpeg in `services/bin` (wrong), so the bundled one was never found. `requirements-runtime.txt` leaves out torch/diffusers/transformers; the attraction
  fallback (`parallax_generator.py`) imports them lazily. The whole pytest suite passes in a venv made from that file.
- Engines are still set up from Settings > Voice: Fast (Kokoro) and Balanced (Qwen3) as before, and now Natural (Irodori): `tts/irodori_setup.py` downloads the upstream source zip and runs
  `uv sync --extra cu128|cpu` (CUDA when `nvidia-smi` works). Ollama is not bundled or installed by us: Settings > AI models shows "Get Ollama" (opens ollama.com/download) when no model is found.
  ComfyUI (moving attraction videos) is set up from Settings > Setup (`vdoprocessing/comfyui_setup.py`, action `comfyui_install`): pinned ComfyUI release zip + pinned ComfyUI-GGUF commit zip, a uv venv (3.12) with
  torch/torchvision/torchaudio from the cu128 index before the requirements, then the six model files (Wan2.2 5B Turbo GGUF + umt5 + VAE for free-text prompts, LTX-Video 13B GGUF + T5 + VAE for the six camera presets;
  about 26 GB). Refuses without an NVIDIA GPU (`pick_backend`) or under 32 GB free; downloads resume from `.part` files and are sha256-checked (hashes from the HF file listing, 2026-10-06). `tts_engines` reports
  `comfyui: {ready, nvidia}`. NOT run end to end (26 GB, needs a GPU PC); only unit-tested with fakes (`tests/test_comfyui_setup.py`). Without it the pan fallback is used.
- About: `ui/AboutPanel.tsx` (Settings > About): version via Tauri `getVersion`, links, "built with" list, map-data credits, and the verified stock voices' credit lines read from `scripts/stock-voices.json`.
- Ollama calls (`ollamaApi.ts` `ollamaFetch`) send an empty `Origin` (needs `tauri-plugin-http` feature `unsafe-headers`): the installed app's origin `http://tauri.localhost` gets 403 from Ollama otherwise.
- Rounded caption boxes: `background_radius` > 0 makes `write_caption_ass` draw the box as a `\p1` shape (`services/localization/caption_box.py`, widths measured with PIL at libass's cell-height scale) under bare text; if the font can't be measured the square BorderStyle=3 box is used. The `.srt` burn path stays square.
- Assistant (chat that builds a project): `hooks/useAssistant.tsx` (provider mounted in main.tsx: messages, brief, sources, build) -> `features/assistant/AssistantChat.tsx` (start-screen box in ProjectManager, floating `AssistantPanel` in the editor, toggled from the title bar). `services/assistant/`: `brief.ts` (ProjectBrief = the hand-off prompt fields, `cleanBriefPatch`), `converse.ts` (prompt + lenient reply parsing: small local models drop the `<brief>` tag or translate place names, hence `guardPlaces`), `sources.ts` (PDF/Word via Python `read_document`, txt/md, web pages), `buildProject.ts` + `geocode.ts` (places -> geocode -> one script per stop; `AutoDirectorModal` uses the same). GPX/photos attached in chat are queued with `setPendingImport` and imported by MapArea once the editor opens; with a GPX the builder is skipped.
- Geocoding a route (`services/geocode.ts` `geocodeRoute`): Mapbox/OSM match small places by fuzzy name and happily return a namesake on another continent (Mapbox even returns its nearest neighborhood at relevance ~0.5 for any name), so places are searched only inside a box: the shared region ("..., Wakayama") anchors it, each later stop is searched within `hopKm` of its neighbor (15 km when the brief says walking/pilgrimage, else 40), misses retry as `nameVariants` (Sta. -> Station, suffixes cut) and as the local-script name from `localNames` (AI), and anything still unknown is placed between its neighbors and reported as `uncertainPlaces`. Weak Mapbox hits are never trusted. OSM Nominatim is rate-limited to 1 request per second (`geocodeSettings`).
- Assistant chat history is per project (2026-10-06): `<project>/assistant.json` (root, not `.navivi/`: it cannot be rebuilt; Duplicate and "Export for sharing" carry it) via `services/assistant/chatStore.ts`
  (tolerant `parseChat`, 200 messages max, missing attachments dropped on load). `useAssistant` owns it: `owner` = the open project's folder ("" on the start screen / an unsaved project, kept in memory only),
  `generation` changes with the owner so late replies and builds are dropped, writes are debounced 300 ms into the folder that owned the chat when the change happened. Opening another project loads its file;
  `saveProject` fires window event `project-saved {dir, saveAs}`: a first save or Save As makes the current chat that folder's. NewProject and the chat's "Start over" reset it (and delete the file).
- Photos found online (2026-10-06): `services/placePhotos.ts` (Wikimedia only: Wikipedia lead image of an article found by `geosearch` around the stop, then Commons files within 120 m or carrying the stop's name, then a name search;
  an uncertain position uses the name search alone and offers one photo). `imageinfo/extmetadata` gives license + author: only CC0, PD, CC BY, CC BY-SA and "Attribution" pass; maps, logos, SVG, small files are dropped; landscape first;
  one series (same name without digits) does not fill every slot. Requests go one at a time with `User-Agent: Navivi/<version> (github.com/mzxrq/navivi)` (Commons answers 403 without one; plugin-http passes it because of
  `unsafe-headers`); 1920 px thumbnails go to `Documents/Navivi/Imports/photos-<ts>/` and are copied into `assets/image` by the normal save. `Waypoint.imageCredits` (keyed by photo path; `renameCredits` re-keys it on save to
  `assets/image/<name>` and back to absolute on load) -> shown under the photo in the Photos tab and listed in the export dialog (`collectCredits`). Triggers: the assistant build (`buildProject` `photos` option, checkbox
  "Find photos of each place", remembered in localStorage `navivi.assistant.findPhotos`, 2 photos per stop) and the "Find photos online" button in the Photos tab (fills only empty slots). Live-checked against Commons for six
  Shirahama/Kumano stops (all downloads 200); not tried in the real app.
- Saving writes `popup_image` = ALL of a stop's photos (it held only the first, so Python's multi-photo attraction clips never saw the others) and loading prefers `images` (`utils/waypointImages.ts`).
- AI settings are app-wide: `useWorkspace` keeps `ai_features_enabled` (default on), `ai_provider`, `ai_model`, `ai_online_*` in `globalAi` (persisted as app setting `ai_settings`) and merges them over the project's settings, so a project file can no longer switch them.
- Checklist: `ui/ComponentsChecklist.tsx` lists what can be set up after the media tools (the three voices named by model with credit lines from `config/credits.ts`, Ollama / online AI status, ComfyUI install; a summary box lists what is still missing; the same credits are listed in About). It is shown once after first-run
  setup in `SetupGate` (flag `firstRunChecklistDone` in the app-settings table; ignored in `tauri dev`) and always under Settings > Setup. Installs go one at a time (a new blueprint call would cancel the running one),
  statuses come from `tts_engines` (now includes `irodori`), `getLocalModels` and `hasApiKey`.
- Look: `scripts/make-installer-art.mjs` (`npm run art:installer`) draws `src-tauri/installer/sidebar.bmp` (164x314, welcome/finish pages) and `header.bmp` (150x57) from the app's logo with Playwright and
  writes 24-bit BMPs (committed, so a build needs no browser). `tauri.installer.conf.json` points `nsis.sidebarImage` / `headerImage` / `installerIcon` at them. Deeper changes (modern flat pages) would need a
  custom NSIS `template`; not done.
- MSIX "custom App Installer UX" (`MSIXAppInstallerData.xml`: accent/background color, font, logo, buttons) was considered and does not apply: it only styles MSIX packages, which Tauri v2 cannot build
  and which must be signed with a trusted certificate to install on other PCs. A fully custom look needs either a custom NSIS template (native controls, limited) or our own small Tauri/React setup app.
- Not done: code signing, auto-update, a smaller ffmpeg (two 100 MB exes), an Ollama installer.

## Custom setup program (2026-10-05, replaces the NSIS look)

- `setup/` is a separate small Rust crate (wry 0.55 + tao 0.35, the same versions Tauri uses; its own `Cargo.lock` and `target/`): `navivi-setup.exe`, 0.8 MB, a borderless 780x480 WebView2 window rendering `setup/ui/index.html`
  (one file: CSS, JS, ja/en strings; language from the Windows display language). `npm run build:setup` (`scripts/build-setup.mjs`; `-- --skip-app` reuses `src-tauri/target/release/navivi.exe`) builds the app with
  `tauri build --no-bundle`, stages code and tools (`stage-installer.mjs`), zips `navivi.exe + src-python + tools + .navivi-install.json` with Windows bsdtar, builds the crate, and appends `[zip][footer "NAVIVIPL" + zip length]`
  to it: `setup/dist/Navivi-Setup-<version>.exe` (about 140 MB; plain Deflate, so bigger than the NSIS LZMA 114 MB). `setup/payload.zip`, `setup/stage/` and `setup/dist/` are gitignored: GitHub rejects files over 100 MB.
- Code: `payload.rs` (footer, `Section` reader so the zip is read in place, `safe_join` against zip-slip, `extract` with progress), `install.rs` (steps shared by the window and `--silent`, `resolve_dir`: a folder that holds other
  things gets a `Navivi` subfolder, `.navivi-files.txt` lists everything written so the uninstaller removes exactly that, then empty folders), `system.rs` (language, running copies, shortcuts and registry via PowerShell/winreg),
  `main.rs` (tao window, IPC `window.ipc.postMessage` from the page, `window.__emit` back).
- Flags: `--silent`, `--dir X`, `--no-launch`, `--no-shortcuts`, `--log file`; `uninstall.exe --uninstall [--silent] [--remove-data]`. The uninstaller is the setup exe without its payload; it copies itself to %TEMP% and
  runs from there so it can delete its own folder. Apps & features entry: `HKCU\...\Uninstall\Navivi`, the same key the NSIS installer uses, so each removal only touches an entry/shortcut that points at its own folder
  (a test run once deleted a real NSIS install's entry and shortcuts; fixed, and they were restored by re-running that installer).
- Bundled voices: `scripts/stock-voices.json` lists the voices to ship (`verified: true` only after checking the license allows redistributing the audio; `credit` goes into `CREDITS.txt`). `stage-installer.mjs` copies
  them from the developer's own `bin/Irodori-TTS-Server/voices` into `src-python/assets/voices` (so the audio is not in git). `voices.sync_stock_voices()` copies any the user lacks (and has not deleted: `.stock.json`) into the
  voice library on first `list_voices`/`voice_file`, so they are ordinary voices for every engine. Frontend default voice is `test1` (`VoiceSettings.DEFAULT_VOICE`) while Python's CLI default is `jvs004` (`tuning.TTS_VOICE`).
- VC++ runtime (2026-10-06): `setup/.cargo/config.toml` links the C runtime statically, so `navivi-setup.exe` imports no VCRUNTIME140/UCRT and starts on a clean PC (the Tauri app already does this: checked with a PE import dump).
  What does need the Microsoft Visual C++ 2015-2022 x64 redistributable is PyTorch (`c10.dll` imports msvcp140/vcruntime140; the uv Python ships vcruntime140 but not msvcp140) = the three voices and ComfyUI.
  `install.rs` therefore checks `HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64\Installed` as the last step and, if missing, downloads `aka.ms/vs/17/release/vc_redist.x64.exe` and runs it `/install /quiet`
  (UAC prompt); a failure only adds a note on the done screen (`Event::Note`), never fails the install. Not tested on a PC without the redistributable.
- Never packaged: `src-python/.env` (the developer's Mapbox/ORS keys; Python reads a Mapbox token from it, users enter theirs in Settings > API keys) and the empty dev `src-python/.venv`.
- Testing without touching the screen: run the exe with `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=N`, connect Playwright `connectOverCDP`, call `paint()` / `window.__emit(...)` or click page buttons;
  `--silent --dir <temp>` for install and uninstall. Needs WebView2 (shipped with Windows 11; a message with the download link appears if missing). Not done: code signing (SmartScreen will warn), updating over a running copy
  beyond closing it, the NSIS build (`build:installer`) is kept as a fallback.

## Online AI for scripts (2026-10-05)

- Who writes a script is `AiEngine` (`services/ai/engine.ts`): a model name string (local Ollama) or an `OnlineTarget` {provider, model, baseUrl, sendPhotos}. `aiEngine(settings)` builds it from
  `settings.ai_provider` (unset/`ollama` = local `ai_model`), `ai_online_models[provider]`, `ai_online_base_url` (custom only), `ai_online_send_photos`. WaypointEditor, AutoDirectorModal and
  ScriptInput call it; `ollamaApi.streamLLM` branches on `isOnlineEngine` so every generator (`generateWaypointScriptStream`, `extractLocationsFromDocument`, ...) works with either.
- Providers (`services/ai/providers.ts`, pure and unit-tested): Anthropic `/v1/messages`, OpenAI and OpenRouter and "Other" (`/chat/completions`), Gemini `streamGenerateContent?alt=sse`. `buildRequest`,
  `textDelta`, `errorMessage`, `listModelsRequest`/`parseModelList` hold all protocol knowledge. OpenAI official takes `max_completion_tokens` and no temperature (newer models reject both
  `max_tokens` and a non-default temperature); the others get `max_tokens` + temperature. `streamOnline` (`online.ts`) streams through `@tauri-apps/plugin-http` (no CORS; the http scope already allows https) and `sse.ts` parses events.
  The online token cap is 2000 because reasoning models spend part of it thinking. Default models are cheap and fast (Haiku 4.5, gpt-4o-mini, gemini-2.5-flash); the model list is fetched from the provider on demand (Refresh), not hard-coded.
- Keys: OS credential store through the Rust commands `secret_set/get/delete` (`src-tauri/src/secrets.rs`, `keyring` crate, names must be `ai-key:<provider>`). Never in settings, the DB, the project folder or a `.nvv`. The JS side (`ai/keys.ts`) does see the key, to put it in a header.
- Photos: up to 4, shrunk to 1280 px JPEG in the webview (`ai/photos.ts`) because APIs cap an image (Anthropic 5 MB) and bill by size; a Settings switch turns them off. Settings > AI models (`OnlineAiSettings.tsx`) shows a disclosure of what is sent.
  The plugin-opener is registered in `lib.rs` so "Get a key" opens the provider's page (`plugin:opener|open_url`).
- Python side: the overview narration (`narration_step.ensure_overview_narration`, and the `overview-script` mode) picks its model through `services/localization/script_engine.script_generator(settings)`:
  an online provider when `settings.ai_provider` names one, else local Ollama (`overview_script_model`). `localization/online_llm.py` does the non-streaming request (httpx; text only, no photos), mirrors the
  provider defaults of `providers.ts` (keep them in step), retries 429/5xx twice, and after a 400/401/403/404 stops calling for the rest of the run so remaining passages use their templates at once.
  Keys never touch job_config.json: Rust's `secrets::export_keys` sets `NAVIVI_AI_KEY_<PROVIDER>` on the Python child in `run_python_blueprint` and `start_render` only. So a key saved while a render runs applies from the next run.
  Generate Assets therefore also sends stop names and scripts to the provider (the Settings disclosure says so).

## Code-review fixes (2026-10-02)

- Subtitles: `helpers.is_newer_than(srt, audio)`; an `.srt` older than its audio is rebuilt (a re-synthesised voice keeps its filename), checked in all three `subtitle_step` skip paths.
- Autosave (`useAutoSave`): restarts on every edit via `dirtyRevision` (workspace context) and waits out a save in flight instead of dropping the edit.
- Rust: `kill_tree` (`taskkill /T /F` on Windows) for every kill, so ffmpeg, Chromium and the TTS/ComfyUI servers go with python. `run_python_blueprint` only reaps its own child (compared by pid), so a newer call replacing it no longer steals the result.
- Same-named files: `utils/fileNames.ts` `planFileNames` names copies in `assets/image` and `assets/video/user`; files already in the folder keep their name, outside files that share a name get a tag from their source path (stable, order independent).
- `raw_track.gpx` escapes the project name. Return stops reset leg-specific and generated fields. `useHistory` is one state object with pure updaters (StrictMode used to double-record edits).
- Duplicate project: Rust `duplicate_project_folder` (skips `.history`, old `cache`, root archives) + `duplicateProjectFolder` (new id and name in job_config.json) + `projectStore.duplicateProject` (registers it in the DB).
- File drop: the window has `dragDropEnabled:false` on purpose (map markers use HTML5 drag), so `tauri://drag-*` never fired. `MapArea` now handles HTML5 file drops on `<main>`, `useFileActions.handleDroppedBrowserFiles` writes them to `Documents/Navivi/Imports/<time>/` and runs the normal import (photos, GPX, txt/md). Other types are skipped with a toast. Staged files are not cleaned up.

- `components/ui/ComboBox.tsx`: text field + list (type to filter, Up/Down/Enter/Escape, list in a portal that flips above the field near the window edge). `allowCustom` + `validate` accept values outside the list (font size, 8-200); without it only a listed option is accepted and anything else reverts. Used for the subtitle font (common Windows/Japanese fonts, the saved font is always listed, options drawn in their own face) and font size in Settings > Video. The Duration / Residential duration rows and their `duration_seconds` / `res_duration` settings are gone (Python falls back to 8 s / 12 s).

- Voice tab (`VoiceSettings.tsx`): `run_python_blueprint` runs one sidecar call at a time and a newer call kills the running one ("Process was cancelled"). `listVoices()` shares the in-flight `tts_voices_list` request (the mount effect runs twice under StrictMode), and a `cancelled` reply is never shown as an error. The harness mock for `tts_voices_list` now kills the earlier overlapping call like Rust does, so this can be re-checked with `?strict=1`.

## Tests and CI

- Frontend: Vitest + Testing Library (`vitest.config.ts`, same React/Lingui-macro plugins as the app). Tests run in plain Node; a test that renders a hook/component starts with `// @vitest-environment jsdom`. CI uses Node 24 (the Lingui CLI needs it) and v6 of the checkout/setup actions. Tests sit next to the code (`*.test.ts[x]`): `services/sidecar`, `features/editor/model`, `utils/{fileNames,gpxTrack,routeCacheKey}`, `hooks/useHistory`. `npm test`, `npm run typecheck`. Gotcha: a `beforeEach(() => mock.mockReset())` returns the mock and Vitest runs a returned function as cleanup (it called the rejecting mock again); use braces.
- `useHistory.test.tsx` is a behaviour suite: the old StrictMode double-recording bug (reproduced in the browser harness) did not reproduce under jsdom, so the tests would not have caught it.
- Python: `src-tauri/src-python/requirements-test.txt` is the light dependency list CI installs (no diffusers/transformers); 467 tests pass in a clean venv with it.
- `.github/workflows/ci.yml`: frontend (ubuntu: typecheck + vitest), python (windows, 3.12), rust (windows: `kill_tree` test is Windows-only). Not yet run on GitHub. `.gitignore` now lets `.github/workflows/`, `README.md` and `docs/*.md` through; the rest of `.github` and other `*.md` stay ignored. `test-results/` (Playwright output, was tracked) is ignored and untracked.
- Sidecar calls: `services/sidecar.ts` is the only place that calls `run_python_blueprint`. `callSidecar(mode, input)` never throws and returns `{success:false, error, cancelled?}`; `callSidecarShared` joins an identical in-flight call (Rust kills the running blueprint when a new one starts); `runStage(configPath, mode)` runs a pipeline stage and rejects on failure.

## HEIC photos and the checkbox

- iPhone photos are HEIC/HEIF: the webview cannot show them and Pillow/OpenCV in the pipeline cannot read them without a plugin. They are converted to JPEG when imported. `services/imageconvert.py` (`convert_to_jpeg`, `convert_images`; needs `pillow-heif`, in requirements.txt) keeps the EXIF block (GPS), applies the rotation and resets the orientation tag; `services/cli/image_commands.py` is the `main.py convert_images` mode (JSON in, `{images:{src:jpeg}, failed:{src:reason}}` out; `missing_package` is set when pillow-heif is not installed).
- `services/imageImport.ts`: `preparePhotos(paths)` (no sidecar call unless a HEIC is in the list) writes the JPEGs to `Documents/Navivi/Imports/<time>/`. Used by `useFileActions.handleDroppedFiles` (file dialog, drops, folders) and `WaypointEditor.handleImageSelect`. GPS is read from the converted JPEG (exifr could not read the HEIC made by pillow-heif in tests). A failure to convert reports the sidecar's message and the other files are still imported. Marker/logo pickers (svg/png/jpg) were left alone.
- `components/ui/Checkbox.tsx`: custom checkbox over a transparent native input (click, label, Space, focus ring keep working); accent fill with a white tick, used in the Generate dialog's existing-assets list.

## Walking routes: gap closing and GSI paths (2026-10-02)
- `utils/gsiPaths.ts`: reads the road centre lines (ftCode 27xx, narrow paths included) from GSI's `experimental_bvmap` vector tiles
  (z16, CORS open, Japan only), builds a graph for the tiles a leg needs and finds the shortest walk (A* on a binary heap, snapping onto the
  middle of a segment, 60 m snap limit, at most 9 tiles). Both are LRU caches in memory: the last 36 tiles by `x/y` (a failed fetch is not
  cached) and the last 6 graphs by tile set. `closeGaps` also uses the GSI walk through the via points when it is shorter than the
  router's route plus the filled ends.
- `closeGaps(route, stops, bridge)` (`stops` = start, via points, end): routers snap to the nearest mapped way, so a walking route can stop short of its stop. Any end more than
  25 m from its stop is extended with the GSI path between them, or a straight segment when GSI has none. Called from
  `fetchSingleSegment` for `walking` only (not ferry/driving). Cached with the leg, so legs routed before this change are only fixed when
  they are re-routed (change the mode or move a stop).
- Whole-leg alternative: the router may also have gone a long way round to reach the way it snapped to (Kada: 780 m, ending 63 m short,
  then +210 m of GSI fill, against 345 m on GSI alone, which already passes the user's via point). So when a gap exists, the leg is also
  walked on GSI through every stop in order, and the shorter of the two is kept. GSI has no access info, so either result can use a
  private lane; a drawn leg stays the trustworthy option for places the user has walked.
- Limits: it fills the end of a leg, it does not route a whole leg on GSI, and GSI's path is a mapped path, not necessarily the one walked
  (Gyojado: the mapped path loops round the south side, the route the user drew comes from the north where GSI has nothing).
- `MapStyleOption.maxZoom` (constants.ts): GSI Topo is 17. Its 256 px tiles end at level 18, which Mapbox shows at map zoom 17 (tiles of
  256 px are requested one level deeper than the zoom); deeper would only stretch pixels. Others use 20. The GSI source also sets
  `maxzoom: 18` and the layer no longer has its own maxzoom, which used to blank the map past zoom 18.
- Stop names: `utils/placeName.ts` `placeNameOf(reply, fallback)` is the one rule for naming a stop from a Nominatim reverse lookup: the place's name,
  then its street, then the smallest area it sits in (neighbourhood, quarter, suburb, ... city), then the fallback. Used by photo import, GPX
  import, map clicks and the waypoint editor's locate button. (`ollamaApi.fetchLocationContext` keeps its own city lookup for the AI prompt.)
- Map style no longer follows the app theme. The editor opens on the style the user last picked in the Layers panel (localStorage `map-style`,
  per device), else Outdoors. The old `mapTheme` (sync/dark/light) setting is gone; nothing in the UI could change it.
- Subtitle colors (Settings > Video): Text/Outline color use `ColorSwatches` (same picker as route line color). The saved value stays an ASS
  string (`&HAABBGGRR`, what Python hands to libass); `utils/assColor.ts` converts (`assToRgb`, `rgbToAss` which keeps the existing alpha byte,
  `assToCss`) and falls back to white/black for a value it cannot read. `ui/SubtitleSample.tsx` previews font, size, bold, colors on a
  light-to-dark frame; libass sizes against a 288-line frame (measured with the bundled ffmpeg: size 30 on 1080p = capitals ~74 px), so the
  sample uses `cqh` units: font size/288, outline 2/288, margin 10/288 of the frame height.

## Burned-in captions (2026-10-02)
- Until now the Settings subtitle font/size/colors reached no output: `_build_subtitle_style` was never called and both burn paths ran FFmpeg's
  `subtitles` filter with no style. Now `services/localization/subtitle.py::caption_style(settings)` is the one builder, used by
  `VideoExporter.burn_subtitles(..., style=)` from the timeline export (`_finish_timeline_output`, style read from the `subtitle_style` block of
  timeline.json) and from the pipeline's `subtitle_step.burn_subtitles` (style from job_config settings; it is part of the burn checkpoint key,
  so a style change re-burns finished clips).
- Look: a translucent dark box (BorderStyle 3; libass fills the box with the OUTLINE colour, so `subtitle_outline_color` is the box colour and the
  Settings row is "Background color"), narrow (`CAPTION_MAX_WIDTH` 0.5 of the width, via MarginL/MarginR) and centred at the bottom, so it stays clear of
  the walk-time card at the bottom right of route clips. Constants live in `tuning.py` `CAPTION_*`; `src/utils/subtitleLook.ts` `CAPTION` mirrors them.
  Default size 16 (real cues: median 17 characters, so mostly 1-2 lines); FFmpeg's own default look was about size 16 too.
- The editor writes the style into timeline.json (`toManifest(name, timeline, subtitleStyleOf(settings))`; `saveTimelineManifest` takes `settings`) every
  time it saves, so Export always uses the current Settings. `ui/Caption.tsx` draws the same box in the editor Preview and in the Settings sample
  (container-query units, size/288 of the frame height). Not identical: libass boxes each line separately with square corners, the preview is one box.
- Vite/Windows trap seen here: rewriting a file with a shell `cat >` can leave the dev server serving an empty module; `touch` the file.
- Background opacity (Settings > Video): a 0-100% slider (step 5) that edits only the alpha byte of `subtitle_outline_color` (`assOpacity` / `withOpacity` in
  `utils/assColor.ts`); no extra saved field, so the exporter and the burn already honour it. Picking a new background color keeps the opacity.

## Slider (`components/ui/Slider.tsx`, 2026-10-02)
- One slider for the whole app (replaced the four native ranges: subtitle background opacity, narration speed, route line width/border, the timeline Inspector's
  volumes and fade). A "ruler fader": 2px baseline that fills with the accent, tick marks hanging under it (one per step up to 40, else every 5%; taller at the ends
  and middle), a 4x16px bar as the handle (grows on hover/drag/focus), a value tag above it (`format`) while hovered or focused.
- A real `<input type="range">` sits on top, invisible, with a 4px native thumb equal to the drawn one, so dragging, arrow keys, focus and screen readers all work and the
  drawn handle sits exactly where the native thumb is. `onChange` fires on every move; `onCommit` fires once when a drag/key press/blur ends on a different value (the
  Inspector uses it so one drag is one undo step). Give it `label` (aria) and `className` for the width (default `w-full`).

## Faster narration and scripts on a CPU PC (2026-10-02)
- Measured on the user's PC (Ryzen 5 5600GE, 15 GB RAM, no GPU): a short Irodori line took 38-45 s (CPU fp32, 40 steps; fixed ~22 s per request), and the
  Gemma-4-26B script model needs ~17 GB of memory (2 tokens/s, ~55 s to load). Evidence: `bin/Irodori-TTS-Server/server.log`, `%LOCALAPPDATA%\Ollama\server.log`.
- Script requests (`ollamaApi.ts`): `keep_alive: 30m`, `num_predict 400`, `num_ctx 4096` for scripts; `warmUpModel` loads the model when the script box is focused;
  Settings > AI model warns (`utils/modelFit.ts`, model size from `/api/tags`, RAM from the new sidecar mode `system_info`) when a model is over 60% of the PC's memory.
- Irodori (`services/tts/ttsengine.py`): quality presets in `tuning.TTS_QUALITY_PRESETS` (fast 16 / balanced 24 / best 40 steps) chosen by `settings.tts.quality`
  (Voice tab picker). Not in the voice fingerprint, so finished audio stays valid; Redo voice remakes it. Measured (saved latent, 6/14/31 characters): best 40/45/77 s,
  balanced 26/31/51 s, fast 20/25/42 s.
- `ensure_reference_latent` encodes the voice wav once with the server venv (`make_latent.py` -> `voices/.latents/<voice>-<sha12>.pt`) and requests send `ref_latent`
  instead of the wav (saves ~5 s each; the audio is bit-identical, measured with a fixed seed). Any failure falls back to the wav and is not retried.
- `phrase_cache.py`: every spoken line is kept in `~/Documents/Navivi/Cache/tts/<sha256>.wav` (500 MB cap, oldest first), keyed by the request (text, voice, speed,
  caption, sampling options) plus the voice file hash. A repeated line, or regenerating after "delete assets", is served from it.
- Estimate (`render_estimate.py`): without a GPU the first narration estimate is `requests x per-request + chars x per-char` (`tuning.TTS_CPU_COST`, a fit of the
  measurements, scaled by the preset's steps) instead of 0.12 s/char; the median of real runs still takes over after two.
- `ui/Segmented.tsx` is the shared segmented control (was local to NewProject).
- Kokoro spike (Part C, not wired into the app yet): lives in its own venv `src-tauri/src-python/bin/Kokoro-TTS/.venv` (Python 3.10, gitignored), NOT the Irodori venv. Reasons:
  `misaki[ja]` needs `pyopenjtalk`, which has no Windows py3.10 wheel and wants Visual Studio; `pyopenjtalk-prebuilt` works but is built for NumPy 1.x (the Irodori venv has 2.2.6).
  Working install: torch (CPU index) + `uv pip install kokoro "transformers<5" "huggingface_hub<1" "numpy<2" jaconv mojimoji fugashi unidic-lite pyopenjtalk-prebuilt soundfile`
  (without the `transformers`/`huggingface_hub` pins uv resolves transformers 4.12.2). Measured: import 21 s + model load 13 s once per process, then 1.4-4 s per line
  (6/14/31 characters), vs Irodori 20-77 s. Voices heard: jf_alpha, jf_gongitsune, jf_nezumi, jf_tebukuro, jm_kumo; 24 kHz; no cloning.

## Voice engines: Natural (Irodori) and Fast (Kokoro) (2026-10-02)
- `settings.tts.engine` = `irodori` (default) | `kokoro`; `settings.tts.kokoro_voice` (default `jf_tebukuro`) is separate from `settings.tts.voice`, so switching engine keeps both choices.
  `ttsengine.make_tts_client(settings, output_dir)` is the one place a client is made (cli/tts_commands `_prepare`, audio_step, voice preview); `stop_all_tts_servers()` stops both.
- `KokoroTTSClient` subclasses `IrodoriTTSClient`: same chunking, gaps, shared phrase cache and cross-process server reuse. What differs is declared on the class (`_SERVER_DIR`,
  `_PIDFILE`, `_PROCESS_MARKER`, `_spawn_server`, `call_api`); the process handle is per class (`type(self)._server_process`). Kokoro has no reference voice or caption, ignores the
  quality preset, and exits by itself after 600 s idle (`kokoro_server.py --idle-seconds`) instead of using `idle_watchdog.py`.
- `services/tts/kokoro_server.py` (runs in `bin/Kokoro-TTS/.venv`, no Navivi imports): `GET /health` (503 until the model is loaded), `POST /v1/audio/speech {input, voice, speed}` ->
  24 kHz mono WAV, port 8089. Measured here: ~21 s the first time (model load), then 6 s for a 64-character narration (about 13 s of audio), 0 s when repeated.
- `services/tts/kokoro_setup.py` (`tts_install_kokoro`): creates that venv with `uv` (Python 3.10, torch CPU, the pins listed in the Kokoro spike note above), downloads the model and
  the five voices, writes `bin/Kokoro-TTS/.ready` (`KokoroTTSClient.is_ready()`). Idempotent; needs `uv` on the PC (an error says so).
- Voice fingerprint includes the engine (`voices.voice_fingerprint(..., engine)`; a clip without one counts as Irodori), so switching engine marks finished narration stale.
- Voice tab (`VoiceSettings.tsx`): engine picker; Fast shows its five voices (from `tts_engines`) or a "Set up fast voice" box, and hides the Irodori-only voice list, quality picker and
  Add a voice. The two sidecar calls (`tts_voices_list`, then `tts_engines`) are sequential on purpose: the app runs one Python call at a time and a new call kills the running one.
- Render estimate: `render_estimate._narration_estimate` picks Kokoro (`tuning.KOKORO_COST`: 35 s startup + ~1 s/request + 0.09 s/char) or the CPU Irodori model.
- Qwen3-TTS was tried and not added: 0.6B clone mode ran at ~6.5 s of compute per second of audio on this CPU (10/13/31 s for the test lines), uses ~3 GB of RAM, needs Python 3.12 and a
  ~3 GB download; the user judged it "ok" (a short line had odd intonation, a mid line was cut short at the token cap) and wants it only as a possible middle option later.

## Third engine: Balanced voice (Qwen3-TTS), added 2026-10-02
- `settings.tts.engine` is now `irodori` | `qwen3` | `kokoro` (UI: Natural / Balanced / Fast voice). Qwen3 clones from the SAME voice library and `settings.tts.voice` as Irodori, so
  its voice list is the library without "No reference" (a recording is required; config falls back to the default voice, the client says what to do if there is none). Quality presets
  and the style caption are Irodori-only; the voice fingerprint for qwen3 has the file hash and `engine: "qwen3"`.
- `Qwen3TTSClient` and `KokoroTTSClient` both extend `_VenvEngineClient` (own venv `bin/<Engine>-TTS/.venv`, own port/pidfile/marker, server script run by that venv, idle self-exit,
  `.ready` file written by `<engine>_setup.py`). Qwen3: port 8090, `bin/Qwen3-TTS` (Python 3.12, torch CPU, `qwen-tts`), model `Qwen/Qwen3-TTS-12Hz-0.6B-Base` (~2.5 GB).
- `services/tts/qwen3_server.py`: x-vector clone prompt per recording (cached; the recording is cut to its first 15 s), `max_new_tokens = 4 x characters + 40`, text ends with 。 if it
  has no final punctuation, a 0.25 s pause is appended. **Cut-off guard:** Qwen3 sometimes stops a line early depending on the seed (the last syllable is lost). The energy of the
  last 80 ms against the whole clip is ~0.00-0.12 for a clean ending and 0.19-0.31 for a cut-off one (measured on the three test lines, several seeds); above `TAIL_OK` (0.15) the line
  is made again with another seed, up to 3 times, keeping the quietest ending. `non_streaming_mode=True` did NOT help (tested); the full stop helped (6/6 vs 4/6 clean takes).
- Speed: Qwen3 has no speed control, so `apply_speed` runs ffmpeg `atempo` on the finished line (chained for >2x), before it is cached (the cache key includes the speed).
- Measured here (warm, 4 GB free RAM): 10/13/31 s for lines of 6/14/31 characters, ~65 s for a 64-character, 3-line narration (Irodori Best: ~150 s; Fast voice: 6 s); first start ~40-55 s
  (import + model load). ~3 GB of RAM while running. `tuning.QWEN3_COST` and `render_estimate.qwen3_narration_seconds` carry the fit.
- Setup: `tts_install_qwen3` (`qwen3_setup.py`, needs `uv`), button "Set up balanced voice" in the Voice tab (about 4 GB in all).

## Assistant, sign-in and geocoding changes (2026-10-06)

- `features/assistant/AssistantChat.tsx`: the start-screen box (`variant="hero"`) is centered (`ProjectManager` section `mx-auto max-w-3xl`) with no heading: rounded composer (`+` attach, up-arrow send, square stop while busy), starter chips with icons that prefill an editable prompt, user messages as a soft bubble and assistant text plain. The "ready to build" card shows stops / length / narration / tone next to Create project; the build bar names its step. The user disliked an added greeting title: keep it off. The stop button uses the translation context "stop the assistant" because plain "Stop" is the waypoint type (地点) in ja.
- `useAssistant.build`: a build that finds no stops throws before anything is replaced (it used to wipe the project's stops). `readSource(input, signal)` stops retrying a cancelled PDF read when the user presses Stop.
- `services/geocode.ts`: `regionOf` prefers the last two comma parts ("Wakayama, Japan"), then one. The no-region path looks up at most `MAX_ROUGH` (6) spread-out places; each place tries at most `MAX_NAMES` (4) spellings. `buildProject` fetches facts only for the attraction script and not for guessed (interpolated) stops (lat/lng 0 skips it).
- OpenRouter sign-in: `oauth.rs` accepts only `/callback/<nonce>` (nonce made by `openrouterAuth.ts`, passed to `oauth_listen_start`), reports `error=` redirects, and `oauth_listen_cancel` frees the port (Cancel button in `OnlineAiSettings`, and on a failed browser open).
- `ScriptInput`: the footer is a flex row under the textarea (it used to be an absolute overlay covering the scrollbar).
- User manual (English and Japanese .docx, with screenshots from the `.agents/scratch/overlay-check` harness) is generated outside the repo; its source is in the Claude session scratchpad only.

## wrap2 additions (2026-10-07)

- **App-wide map keys.** `utils/apiKeys.ts` (pure helpers: strip, legacy, adopt, patched), `hooks/useAppApiKeys.ts` (app setting `api_keys` {mapbox, ors}; writes wait for the first read; `adoptLegacy` only fills empty keys).
  `useWorkspace` merges the keys into `settings` and strips them from project settings (`setSettings` is a wrapper); keys changes do not set dirty. `syncProjectOnOpen` returns `legacyApiKeys` and removes them from the DB row;
  `saveProjectData`, `versionHistory`, `duplicateProjectFolder` and the `.nvv` archive (`project_files.rs scrub_map_keys`, incl. `.navivi/legacy`) never carry them. Rust `python_command(app)` sets `NAVIVI_MAPBOX_TOKEN`;
  Python `services/mapbox_token.py` order: env `NAVIVI_MAPBOX_TOKEN`, settings keys, `MAPBOX_API_KEY`, `MAPBOX_ACCESS_TOKEN`, `VITE_MAPBOX_TOKEN`. The token is not in the leg fingerprint. The ORS key is read in the frontend only.
- **Elevation heatmap** (`utils/elevation.ts`, `MapLayers/useLegElevations.ts`, `HeatmapLegend.tsx`, `RouteLayer.tsx`). The `RouteLayer` source/layer ids must never change (react-map-gl throws "source id changed" and the error boundary eats the app):
  sources stay mounted, only data changes. Slope is smoothed over ~60 m with a continuous blue/green/red ramp. `Waypoint.customRouteEle` = `[stop, ...customRoute, next stop]`, valid only when its length is `customRoute.length + 2`.
  Legs without elevation are sampled from the map terrain with `queryTerrainElevation({exaggerated:false})` (needs 3D terrain on and the tiles on screen). The video has no heatmap; the setting is editor-only. `raw_track.gpx` still writes a fake `<ele>35.0`.
- **Voice tab** (`ui/VoiceSettings.tsx`, `ui/voiceOptions.ts`, `CaptionStyleFields.tsx`, `ScriptInput.tsx`). `voiceOptions.ts` mirrors `tuning.TTS_CAPTION` and the speed range (0.25-4x; a Python test guards it). `settings.tts.caption`: missing = default, `""` = no style, Reset deletes the key.
  `auto_overview_cues` / `auto_narration_cues` default on (separate from `use_narration_cues`). `ScriptInput` takes a `cues` prop and exports `insertCue()`; cue tags `start arrive end n go`. Voice cache info/clear are `tts_cache_info/clear` actions (`phrase_cache.py`); clearing never touches projects.
- **Overview narration editor** (`OverviewNarration.tsx`, `utils/overviewScript.ts`). Every action saves the project first (Python reads the file) then calls the sidecar: Auto-write = `overview-script`, no-AI = `overview-script --no-llm`, Hear it = `overview-tts`, Preview framing = `map`.
  Saved as `overview_narration` text + `is_auto` + `source_ids` (saver `overviewNarrationFields`); editing sets `is_auto` false; a non-blank text without a flag counts as hand-written. Length verdict 60-120 s (3 s slack) uses `chars_per_second` from `overview_length`.
- **Custom pin images in the video** (`graphicengine/pinimage.py`). `marker_for(wp, settings, base_dir)` gives a sprite or None (None = teardrop: `""`, `/defaults/*`, missing/unreadable file). A stop's `customMarker` wins over `settings.routeMarker`; a stop on a preset never takes the project image.
  Transparent icons get a white halo; opaque pictures become round photo pins. 2D: `draw_marker(image=)`; pydeck: `deck_icon()` (384x512 PNG data URL). The `route.markers` checkpoint part exists only when a pin image is used. 3D `.glb` models and stop-by dots are unchanged.
- **Look of the video** (`ui/VideoLookSettings.tsx`, `utils/videoLook.ts`, `render_step.look_options`). Unset keys show `videoLookDefaults` (= the renderer's fallbacks) and nothing is written until changed; `lookPatch` sends `null` for reset keys (the DB merges JSON).
  `enable_outro:false` makes `render_outro_clip` return None. `settings.theme` is the video HUD theme, not the app theme. Per stop: `imageDisplay` (pip/cover), `overviewHighlight` (false = opt out).
- **Regenerate** (`services/renderOptions.ts`, `services/stopRegen.ts`, `GenerateDialog.tsx`). "Make everything again" sets a one-shot force flag taken at `start_render` (a retry does not force again). Per stop: `regenModes` builds the CLI modes (tts, subtitle, attraction), `runRegen` runs them one at a time (one sidecar call at a time),
  `refreshStopMedia` re-probes lengths and swaps that stop's cues. Fixed with it: `subtitle N` wrote into `assets/video` instead of `assets/subtitles`; `attraction N` did not resolve relative `popup_image`. No leg-video regeneration (needs the merged-leg number).
- **Video text language** (`services/video_text.py`, `assets/config/labels_<lang>.json`, setting `video_text_language` auto/en/ja). Resolution: explicit en/ja, else top-level `map_language` (written from `i18n.locale` on every save; `ja*` = Japanese, else English), else Japanese.
  A new language is one catalog file (layered over ja then en). Cache keys carry `video_text` only when the language is not ja. `tuning.LABELS_JA` and the OUTRO/INTRO/STOPBY constants derive from the ja catalog. An AST test forbids Japanese literals in `vdoprocessing/` and `mapfetcher/`.
- **Export options and map style** (`features/editor/model.ts` `exportOptionsFrom`, `ExportDialog.tsx`, `ProjectSettingsModal.tsx`). The timeline manifest carries `export_height` (not for 1080p), `fps`, `save_srt`, `burn_subtitles` only when set; `VideoExporter._timeline_size` keeps even sizes at the clips' aspect.
  `settings.mapbox_style_id` (`owner/id`, absent = the old look) goes through `resolve_map_style` for every tile/style step; `route.map_style` is in the render checkpoint. The pydeck maps load mapbox-gl 1.13, so Mapbox Standard is excluded. `mapbox_retina` removed = on.
- **Small fixes.** Fly legs (`routeMode: "curve"`) resolve to airplane via `MODE_ALIASES`; overview narration uses `ai_model` (override `overview_script_model`); `marker_radius` is optional (unset = renderer default 16); `main.split_mode_payload` splits only stage calls (argv[1] ends in `.json`).
  Removed as dead: `services/model/`, `llmscript.py`, `framesink.py`, `tts/tts.py`, `useTransition.ts`, the `use_leg_storyboard` flag, `imageTransitions`. `local_pan_generator.py` was on that list but stays: `jump_cut.py` and `ltx_keyframed.py` (added on main) use it. Some tests write model-sized files into pytest's temp dir (pytest keeps three runs): clear `%TEMP%\pytest-of-*` if the disk fills.

## Clean-PC fixes after a Windows Sandbox run (2026-10-07)

- **Setup exe needed VCRUNTIME140_1.dll.** `setup/.cargo/config.toml` (static C runtime) was ignored: cargo reads it from the working directory, and `build-setup.mjs` ran cargo from the repo root. It now runs with `cwd = setup/`; `src-tauri/.cargo/config.toml` does the same for the app (it had no config before, so a plain build imported the runtime). `build-setup.mjs` throws when either exe's real PE import table (`scripts/pe-imports.mjs`; a string scan gives false hits) names vcruntime/msvcp. Rebuild with `npm run build:setup`.
- **Visual C++ runtime check.** `runtime.rs` `vc_runtime_present()` looks for vcruntime140, vcruntime140_1 and msvcp140 in System32 (true off Windows); `RuntimeStatus.vcRuntime`. `start_render` and `convert_gps_to_gpx` fail with `VC_RUNTIME_MISSING` instead of letting gpsbabel.exe show the Windows DLL dialog. `install_vc_runtime` (Rust, PowerShell: downloads aka.ms vc_redist.x64.exe, runs it `-Verb RunAs`) works before any Python exists.
  `VcRuntimeGate.tsx` (mounted in App) asks at startup and when a render / GPS import announces `VC_RUNTIME_MISSING` (`services/setup.ts`). Python side: `services/system_runtime.py` (`vc_runtime_installed` via the registry, `missing_runtime_message`, `import_failure`); `tts_engines` reports `vc_runtime`, and the voice/ComfyUI installers refuse early with a clear message.
- **"Kokoro could not be imported. See the log above."** There was no log: `_imports_work` threw the import's stderr away. The three voice setups now raise `system_runtime.import_failure(...)` = the last 500 chars of the real error, plus the Visual C++ explanation when it is a DLL failure and the runtime is missing.
- **Settings > Setup (`ComponentsChecklist`)**: a Windows row (Visual C++) when missing; Ollama "Install now" asks first, then runs `ollama_setup.install_ollama` (action `ollama_install`: PowerShell `irm https://ollama.com/install.ps1 | iex`, waits up to 60 s for port 11434). Ollama is looked for again every 4 s, on focus and when a key is saved (`getOllamaState` separates "not running" from "no model"); a model picker appears when `ai_model` is not installed. The provider picker and `OnlineProviderSettings` (key, OpenRouter sign-in) are embedded, so first-run setup configures AI too.
- **No usable AI = no assistant.** `services/ai/ready.ts` `aiReady` (features on + key for the online provider, or the chosen/default model installed in Ollama) and `hooks/useAiReady.ts` (re-checks on focus, on `AI_KEYS_CHANGED` from `keys.ts`, every 6 s while not ready) hide the title bar Assistant button, the floating panel and the start-screen chat box.
- **Voice preview** (`VoiceSettings.tsx`): when the selected engine is not set up, Play streams the stock/recorded sample file itself instead of cloning it.
- **tao panic `assertion failed: flush_paint_messages`** (during assistant chat with Ollama): the same assertion is open upstream (tauri-apps/tao#1140, no reliable repro, still in tao master); the tray-icon cause there does not apply (we have tray-icon 0.24.2, which has the revert, and no tray). Mitigation only: commands that block (`wake_up_ollama`, `runtime_status`, `secret_*`, `open_in_explorer`) are now `#[tauri::command(async)]` so they stop running on the main thread. Not verified as a fix.
- **Code signing (optional, 2026-10-07).** Smart App Control blocks unsigned installers on Windows 11 ("アプリケーション制御ポリシーによってこのファイルがブロックされました"; hits the NSIS exe too). `scripts/sign.mjs` signs `navivi.exe` (before it goes into the payload) and the finished `Navivi-Setup-<v>.exe` when `NAVIVI_SIGN_PFX` (+ `NAVIVI_SIGN_PASSWORD`) or `NAVIVI_SIGN_COMMAND` (a command with `{file}`, for cloud signing such as Microsoft Artifact Signing) is set; otherwise the build only prints a note. A self-signed certificate signs but is still blocked: it needs a certificate from a trusted authority.
  A signature sits after the footer, so `payload.rs` `Payload::find` reads the PE security directory (`security_entry`) and looks for the footer just before it (up to 7 padding bytes); `write_uninstaller` clears that entry in its copy, which is then a plain unsigned exe (so `uninstall.exe` is not signed). Tested with a self-signed certificate: signed setup installs and uninstalls silently.
