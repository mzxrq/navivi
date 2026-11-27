# Attraction videos: how they work today (audit)

Branch `chore/pipeline-recap`, 2026-11-26. Read from the code. **Nothing was generated** (it uses the GPU).
Index: [PIPELINE_RULES.md](PIPELINE_RULES.md).

An *attraction video* shows one stop's photos while the voice tells about that place.

## 1. Global rules

| Topic | Rule |
|---|---|
| On or off | `enable_attraction_videos` (on). Off too when `skip_rich_media` is on |
| Voice | Its own file, from the stop's attraction text |
| Picture | 1920×1080, silent. Voice is added at export |
| Place name and photo credits | Text items on the timeline, so you can edit them |
| Photos | `upscale_popup_images` (on) uses a sharpened copy |
| Signs | The photo's real signs are pasted over generated ones |

## 2. Which stops get one

| Stop | Video? |
|---|---|
| Stop with a photo or its own footage | Yes |
| Attraction text left empty and no footage | No |
| Stop-by not connected to the route | No. **Yes in Whole route first** if it has a photo |
| Connected stop-by | Yes |
| Closed place with a photo | Yes |
| Skipped in video export | No |
| Return stop | No |

## 3. What the video is made from

- A stop's own footage replaces its first photos, one photo per video, and plays first.
- Footage with no photos is used alone.
- Several photos make one video.

## 4. Camera move per photo

| Choice in the app | What makes it |
|---|---|
| None | The photo held still |
| Pan Left / Right / Up / Down | LTXV (ComfyUI, GPU) |
| Dolly In / Out | LTXV |
| Walk In | LTXV, checked for quality, 2 tries, then Dolly In |
| Walk Back | A Walk In played backwards |

- LTXV gets 2 tries. If both fail: the **3D photo move on the CPU**.
- After the chosen move, a **second, closer shot** of the same photo is picked automatically and dissolved in.
- A new photo starts as **None** in the app. In an old project with no choice saved: Pan Right (a stop-by: None).

### GPU or CPU

| Setting | Result |
|---|---|
| `photo_clip_engine: "ai"` (default) | Every moving photo uses ComfyUI |
| `"cpu"` | Every moving photo uses the CPU 3D move; ComfyUI does not start |
| `"cpu"` + "AI clip for this photo" ticked | Only that photo uses ComfyUI |

## 5. Length

| Rule | Value |
|---|---|
| With voice | Voice + 1 s |
| Several photos | Equal shares, or cut at `{next}` cues (each share at least 1.5 s, else equal) |
| Footage mixed with photos | Always equal shares |
| Move longer than its share | Trimmed |
| Move shorter by more than 1 s | A slow drift on the photo fills the rest |
| Shorter by 1 s or less, or a still | Last frame held |
| No voice, still photo | About 3.7 s per photo |

## 6. Storyboard

| # | On screen |
|---|---|
| 1 | Dissolve from the walking video's fullscreen arrival photo (0.8 s) |
| 2 | Photo 1: chosen move, then the closer shot |
| 3 | Next photos, each for its share |
| 4 | Place name at the top left, photo credit |

## 7. Reuse

- Each photo's raw clip is kept. It is reused while the photo, move and engine stay the same.
- A changed script only **refits** the kept clips on the CPU. Nothing is generated again.
- `--force` makes everything again.

## 8. Rules that do not match

1. **Old notes and comments say these videos use Wan.** Every move the app offers now uses LTXV. The Wan path is only reached by input that is not one of those moves.
2. **Two defaults for an unset camera move:** the app saves None, the renderer assumes Pan Right.
3. **Old notes say the filler is a zoom-out.** The code uses a drift.
4. **A code comment says several photos wait for your approval.** They are combined automatically.

## 9. Decisions for the redesign

1. One default camera move?
2. Is the automatic second shot wanted on every photo?
3. Remove the unused Wan path?
