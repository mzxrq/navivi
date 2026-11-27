# The video pipeline today: index (audit)

Branch `chore/pipeline-recap`, 2026-11-26. Read from the code. No real project was rendered.

## 1. Rule files

| Part | File |
|---|---|
| Overview | [OVERVIEW_RULES.md](OVERVIEW_RULES.md) |
| Walking videos | [LEG_RULES.md](LEG_RULES.md) |
| Attraction videos | [ATTRACTION_RULES.md](ATTRACTION_RULES.md) |
| Intro and ending | [INTRO_ENDING_RULES.md](INTRO_ENDING_RULES.md) |
| Voice, subtitles, export | [VOICE_EXPORT_RULES.md](VOICE_EXPORT_RULES.md) |

## 2. Stages of a full render

| # | Stage | Result |
|---|---|---|
| 1 | Read the GPS track | Cleaned route |
| 2 | Voice, with automatic cues | Audio files and cue times |
| 3 | Subtitles | `.srt` files |
| 4 | Sharpen photos | Better copies |
| 5 | Attraction videos | One per stop |
| 6 | Intro, overview, walking videos, sub course | Silent clips |
| 7 | Outro, finale, timeline | `timeline.json` |
| Export | A separate step | The finished film |

## 3. Film order

intro → overview → (walk → attraction) for each place → finale → sub course → outro

## 4. Rules that apply everywhere

| Topic | Rule |
|---|---|
| The voice leads | Cue tags in the scripts set the timing of the pictures |
| Silent clips | Sound and subtitles are added only at export |
| Reuse | A finished output is kept while its inputs are the same. `--force` makes it again |
| Optional parts | A failed intro, finale or outro is skipped, not fatal |
| Settings | `job_config.json` `settings.*`; defaults in `services/tuning.py` |

## 5. Switches

| Setting | Default | Turns off |
|---|---|---|
| `skip_rich_media` | off | Voice, subtitles, photo sharpening, attraction videos |
| `enable_attraction_videos` | on | Attraction videos |
| `upscale_popup_images` | on | Photo sharpening |
| `enable_intro` | on | Intro |
| `enable_finale` | on | Finale |
| `enable_outro` | on | Outro and finale |

## 6. Problems found, most important first

| # | Problem | Where |
|---|---|---|
| 1 | A failed voice or music mix still gives a "successful" export; failed voice clips leave silent parts | [Voice and export](VOICE_EXPORT_RULES.md) |
| 2 | Outro style on screen differs from the one rendered | [Intro and ending](INTRO_ENDING_RULES.md) |
| 3 | The overview script plans a stop-by pause the video does not make | [Overview](OVERVIEW_RULES.md) |
| 4 | Sub course plays after the finale; Whole route first does not draw it in its overview | [Intro and ending](INTRO_ENDING_RULES.md), [Overview](OVERVIEW_RULES.md) |
| 5 | A stop's photo hold time and "Photo card" choice do nothing in walking videos | [Walking videos](LEG_RULES.md) |
| 6 | The same cue means different things in different overview styles | [Overview](OVERVIEW_RULES.md) |
| 7 | Old notes and code comments describe earlier behaviour (Wan, filler zoom, `{slow}` speed) | all |

## 7. Questions to settle before changing the logic

1. One shared meaning for each cue in every video type?
2. One rule for photo cards: size, fullscreen or boxed, how long?
3. Which parts of the ending stay?
4. What should stop a render, and what may be skipped?
