# Navivi refactoring plan

Date: 2026-11-26. Status: **proposal, nothing started**.

This is the roadmap. Each phase gets its own detailed task plan (`docs/superpowers/plans/`) just before it starts,
because the code will have moved by then.

## Goal

Make the code safer and cheaper to change, without changing what the app or the videos do.

**Not goals:** a rewrite, a new framework, OOP for its own sake, new features, visual changes.

## Where it stands (measured 2026-11-26)

| Area | Finding |
|---|---|
| Python `services/` | About 57,000 lines in 174 files; about 600 functions take a raw `dict` |
| Overview card | A dict with 45+ keys, mutated in place across renderer modules |
| Long functions | 10 over 100 lines. `_record_leg` 1,663, `render_residential_leg_pydeck` 483, `_play_leg_photo_card` 448, `_play_stopby_photo_pause` 395 |
| Renderers | `SpatialRenderer` is 9 mixins and `GraphicsEngine` 7, all sharing `self` |
| Largest Python files | `popups.py` 3,000, `pedestrian.py` 2,500, `outrocard.py` 2,000, `cards.py` 1,600, `vdoexporter.py` 1,600 |
| Config | `JobConfigManager` singleton, constructed in 31 places |
| Frontend | About 34,600 lines. `AppSettings.tsx` 1,411, `RenderOverlay.tsx` 1,401, `MapArea.tsx` 1,289, `WaypointEditor.tsx` 1,092, `fileSystem.ts` 902, `useWorkspace.tsx` 801 |
| Rust | About 3,700 lines. `lib.rs` 1,007 |
| Tests | About 1,600 Python tests; 79 frontend test files |

## Rules for every task

1. **Behavior does not change.** A bug found on the way gets its own fix commit, never mixed into a refactor.
2. One task, one commit; it builds and passes on its own.
3. Checks, as they apply: `python -m pytest -q tests` and `python -m ruff check .` (from `src-tauri/src-python`);
   `npx tsc --noEmit` and `npm test`; `cargo test` (from `src-tauri`).
4. Test first where behavior is not already covered: write a test that pins today's output, then move the code.
5. No render version bump: if a frame would change, the task is wrong.
6. Ask before any GPU step. Render only on copies in `Documents/Navivi/RenderTest`.
7. Public contracts stay fixed: `main.py` arguments and JSON output, Tauri command names, `job_config.json`,
   `timeline.json`, the database schema.
8. Don't refactor files another open branch is changing.

## Order

| Phase | What | Risk | Rough size |
|---|---|---|---|
| 0 | Safety net | Low | 1 session |
| 1 | Typed overview data | Medium | 2–3 sessions |
| 2 | Renderers: composition instead of mixins | Medium to high | 3–4 sessions |
| 3 | Leg recorder split | High (needs GPU to verify) | 3–4 sessions |
| 4 | Pipeline settings and config | Low to medium | 2 sessions |
| 5 | Frontend splits | Low to medium | 3–4 sessions |
| 6 | Rust split | Low | 1 session |

Sizes are guesses. Phases 5 and 6 are independent and can run at any time.

**Before Phase 0:** merge `chore/pipeline-recap`. Decide whether `docs/OVERVIEW_RULES.md` Phases 2 and 3 come
first: they edit the same renderer files as Phases 1 and 2 here. Recommended: finish them first.

## Phase 0: safety net

- [ ] Golden frames: `tests/test_golden_frames.py` renders the last overview frame for walk, map and course from a
      small made-up project on a plain background (CPU only, no network), and compares it to a saved image.
- [ ] Golden outputs for the pure planners: timeline JSON, overview script, narration cue plan.
- [ ] Record the test run time, so a slowdown shows.
- [ ] Add a CI step that runs ruff, pytest, tsc and `npm test` if one of them is missing from `ci.yml`.

Done when: a one-pixel layout change or a changed timeline field fails a test.

## Phase 1: typed overview data

New module `spatial_renderer/model.py`, dataclasses grouped by what the keys are for:

| Type | Replaces keys |
|---|---|
| `Place` | `data`, `index`, `order`, `label`, `x`, `y`, `pin_x`, `pin_y` |
| `CardSpot` | `stay_box`, `stay_scale`, `beside_box`, `card_scale`, `no_card`; owns the drawn and layout boxes |
| `PlaceTiming` | `expected_frame`, `cue_frame`, `cue_wait_frames`, `depart_frame`, `pop_frame`, `course_at`, `course_dist`, `leg_display_seconds`, `no_pause` |
| `LeaderStyle` | `leader_*`, `border_color`, `draw_leader_line` |
| `CardState` | `big`, `standing`, `leg_card`, `hud_corner`, `stopby_group`, `stopby_host` |

- [ ] 1.1 Add the types with `from_popup(dict)` / `to_popup()` so old and new code can coexist.
- [ ] 1.2 Move card geometry into `CardSpot` (one place computes a card's box).
- [ ] 1.3 Convert one consumer at a time: layout, then walk, then course, then transitions.
- [ ] 1.4 Delete the pill badge keys with their last user (the ending clip), or give it its own small type.
- [ ] 1.5 Delete `to_popup()` when no caller is left.
- [ ] 1.6 Same method for waypoints: `Waypoint` dataclass read once from `job_config.json`.

Done when: renderer modules read no popup dictionary keys.

## Phase 2: composition instead of mixins

Target shape: `SpatialRenderer` holds collaborators and delegates.

| New object | Takes over |
|---|---|
| `CardLayout` | `popups.py` placement, `card_circles.py`, the ring fallback, the pill lattice |
| `CardPainter` | `popup_box.py` drawing and leader lines |
| `PinPainter` | `pins.py` |
| `HudPainter` | top bar, notices, progress rail from `cards.py` |
| `WalkOverview` | `overview.py`, `overview_animation.py`, `overview_pacing.py` |
| `CourseOverview` | `course.py` |
| `Ending` | `transitions.py` |
| `LegMapRenderer` | `waypoints.py` |

- [ ] 2.1 Extract the leaf objects first (pins, painters): they need little shared state.
- [ ] 2.2 Extract `CardLayout`; split the pill lattice into its own file.
- [ ] 2.3 Extract `Ending`, then `CourseOverview`, then `WalkOverview`.
- [ ] 2.4 Do the same for `GraphicsEngine`, one mixin per commit.
- [ ] 2.5 Replace `self.config` reads with a typed `OverviewSettings` passed in.

Done when: no `_...Mixin` class is left and no module is over about 800 lines.

## Phase 3: leg recorder

`_record_leg` (1,663 lines) mixes planning, browser control and frame writing.

- [ ] 3.1 Map its stages and shared variables; write the map into the detailed plan before moving code.
- [ ] 3.2 Extract pure planning (timing, pace, pop-up schedule) with tests; no browser needed.
- [ ] 3.3 A `LegState` dataclass replaces the closures' shared locals.
- [ ] 3.4 Extract photo-card and stop-by pause playback (also `stopby_pause.py`).
- [ ] 3.5 One browser session class owns Playwright and frame capture, shared with `overview_pydeck.py`.
- [ ] 3.6 With approval: render the same legs before and after and compare frames.

Done when: no function in `pydeckrecorder/` is over about 150 lines.

## Phase 4: pipeline and config

- [ ] 4.1 A typed `JobConfig` loaded once; `run_full_pipeline` passes it in `_Run`.
- [ ] 4.2 Remove `JobConfigManager()` calls from steps and CLI commands, one package at a time; then the singleton.
- [ ] 4.3 One result type per stage instead of loose dictionaries.
- [ ] 4.4 Split `overview_script.py`, `outrocard.py` and `vdoexporter.py` by responsibility.
- [ ] 4.5 Keep pipeline steps as functions.

## Phase 5: frontend

- [ ] 5.1 `AppSettings.tsx`: one file per tab.
- [ ] 5.2 `RenderOverlay.tsx`: render state into a hook; views into components.
- [ ] 5.3 `MapArea.tsx`: draw mode, camera and window events into hooks; keep the map camera uncontrolled.
- [ ] 5.4 `WaypointEditor.tsx`: one component per section.
- [ ] 5.5 `fileSystem.ts`: save/load, GPX, timeline manifest, route cache.
- [ ] 5.6 `useWorkspace.tsx` stays the single state owner; move its logic into pure functions.
- [ ] 5.7 Typed wrappers for every `invoke` command and window event.

Verify visually with the `.agents/scratch/overlay-check` harness. Run `npm run extract && npm run compile` when
strings move.

## Phase 6: Rust

- [ ] 6.1 Split `lib.rs` into `commands/` modules: python process, render, archive, files.
- [ ] 6.2 `lib.rs` keeps only setup and command registration.

## Stop conditions

Stop a task and ask if: a golden test needs its image updated; a public contract (rule 7) would change; or a task
grows past about 500 changed lines of logic.

## Decisions for you

1. Finish the overview rules Phases 2 and 3 first? (Recommended: yes.)
2. Include Phase 3? It has the biggest payoff in risk reduction for legs, and the highest cost to verify.
3. Which first after Phase 0: Python (1) or frontend (5)? (Recommended: Python, where this week's bugs were.)
