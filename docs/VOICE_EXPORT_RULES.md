# Voice, subtitles and export: how they work today (audit)

Branch `chore/pipeline-recap`, 2026-11-26. Read from the code. **No voice was made and no film exported.**
Index: [PIPELINE_RULES.md](PIPELINE_RULES.md).

## 1. Voice files

Made in this order: overview, finale, walking videos, attraction videos.

| Voice | Text | Used by |
|---|---|---|
| Overview opening | Overview script before `{start}` | Intro |
| Overview | The rest | Overview |
| Finale | `finale_narration` | Finale |
| Leg | Destination's arriving text (plus attraction text when it has no attraction video) | Walking video |
| Attraction | Attraction text | Attraction video |

| Topic | Rule |
|---|---|
| Engines | `irodori` (default), `qwen3`, `kokoro` |
| Cue tags | Never spoken. Their times are measured from the finished audio |
| Pronunciation | The shared dictionary and the project's dictionary change the spoken text only |
| Reuse | Kept while the spoken text, voice, speed and engine are the same |
| Locked audio | `lockNarrationAudio` keeps a stop's recording |
| Fast render | `skip_rich_media`: no voice, subtitles or attraction videos |
| GPU memory | The voice server is stopped before the next stages |

## 2. When voice fails

| Case | Result |
|---|---|
| The voice is not set up | The run stops with the reason |
| No clip at all, although scripts exist | The run stops |
| Some clips fail | **The run continues; those parts are silent** |

## 3. Subtitles

- Built from the same text the voice speaks, timed by the pauses in the audio.
- One `.srt` per voice file.
- Burned **once**, onto the whole film, at export.

## 4. Timeline

`timeline.json` holds the clip order, each clip's voice, subtitles and text items.

| Topic | Rule |
|---|---|
| Order | Intro, overview, then each walking video or piece followed by the attraction video of the place it walked to, finale, sub course, outro |
| Clip length | The longer of the video and its voice + 0.5 s (the last frame is held) |
| Walk ↔ attraction | Hard cut on the same picture: the leg ends on the attraction clip's first frame, the next opens on its last |
| Dissolve: walk → walk | 0.8 s (`attraction_fade_seconds`; 0 = hard cut) only at some joins, such as a return stop |
| Dissolve: into the outro | 1 s, only without a finale |
| Everything else | Hard cut |

## 5. Export

| Step | What happens |
|---|---|
| 1 | Each clip gets its voice |
| 2 | Dissolves are applied, clips are joined |
| 3 | Voice that has its own start time (the overview voice on the intro, unlinked clips) is mixed in |
| 4 | Music is mixed in, looped, at volume 0.25. **It is not lowered under the voice** |
| 5 | Subtitles and text items are burned in |

| Choice | Default |
|---|---|
| Size | The timeline's, else the size most clips have. The export dialog can set another height |
| Frame rate | The timeline's, else 30 |
| Burn subtitles | On (text items are burned even when off) |
| Save `.srt` beside the video | Off |
| Output | The old video is replaced only when the new one is complete |

## 6. Rules that do not match, and risks

1. **A failed mix does not fail the export.** If adding the separately timed voice, the music or the subtitles fails, you get a video without it and only a log line.
2. **Some failed voice clips do not stop a render.** The film can have silent parts.
3. **Music stays at one volume** under speech.

## 7. Decisions for the redesign

1. Should a missing voice or a failed mix stop the run?
2. Should music be lowered under speech?
