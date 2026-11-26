# Intro and ending: how they work today (audit)

Branch `chore/pipeline-recap`, 2026-11-26. Read from the code. A few rules were checked with small calculations; **no clip was rendered**.
Index: [PIPELINE_RULES.md](PIPELINE_RULES.md). The overview's own ending is in [OVERVIEW_RULES.md](OVERVIEW_RULES.md).

## 1. Order at the start and end of the film

intro → overview → walking and attraction videos → **finale** → sub course (if any) → **outro**

## 2. Intro

| Topic | Rule |
|---|---|
| On or off | `enable_intro` (on) |
| Styles | `slideshow` (default), `cinematic`, `documentary` |
| Text | Timeline text items, not burned in: location line, title, subtitle with "· N places" |
| Logo | A "Powered by" badge |
| Voice | The opening of the overview script, up to `{start}` |
| Photo movement | `intro_photo_motion` (on) |

### Length

| Case | Length |
|---|---|
| Voice, opening in its own file | 0.5 s + voice + 0.4 s, at least 4 s, **no maximum** |
| Voice, older one-file script | Until just before `{start}`, kept within 4–26 s |
| No voice, slideshow | About 9 s |
| No voice, cinematic / documentary | About 15 s |

### Storyboard

| Style | On screen |
|---|---|
| Slideshow | **Random** stop photos (3; up to 5 with voice), slow zoom, 0.8 s crossfades, heading on top |
| Cinematic / documentary | 3 scenes from attraction videos (stations, piers, start and end left out), else photos. One text line per scene |

### Cues in the opening

| Cue | Effect |
|---|---|
| `{photo:Name}`, `{photo:Name#3}` | Show that stop's photo (or its 3rd) from here |
| `{scene}` | Cut to the next scene (cinematic, documentary) |
| `{open}`, `{close}` | Slideshow heading appears and leaves |

## 3. Finale

The camera pulls back from the last stop to the whole route.

| Topic | Rule |
|---|---|
| On or off | `enable_finale` and `enable_outro` both on (default) |
| Needs | The track, 2 or more stops, a photo for the last stop. Otherwise skipped |
| Fails | Skipped with a warning; the outro follows directly |
| Voice | `finale_narration`, from the start of the clip |

| # | On screen | Time |
|---|---|---|
| 1 | Last stop's photo | 1 s |
| 2 | Pull back on real map tiles; the route and badges come in; totals count up | 2.5 s |
| 3 | Whole route held | at least 3 s, longer so the voice ends 0.8 s before the clip |

## 4. Outro

| Topic | Rule |
|---|---|
| On or off | `enable_outro` (on) |
| Styles | `scrapbook` (the renderer's default), `scroll`, `grid`. An unknown name gives `scroll` |
| Needs | A stop with a photo (scroll can also show route facts alone) |
| Route facts | `outro_route_info` (on) |
| Size | Same as the walking videos |
| Entry | Cut from the finale. Without a finale: 1 s dissolve |

| Style | On screen |
|---|---|
| Scrapbook | Photo cards on paper, a stamp with title, distance and time, held 2 s, then logos |
| Scroll | Cards and legs scroll upward, then logos |
| Grid | One still page of up to 20 cards, 5 s |

## 5. Rules that do not match

1. **Outro style:** the settings screen shows "Scrolling" when you never chose one, but the renderer makes a **Scrapbook**.
2. **Sub course comes after the finale**, so the film says goodbye to the route and then shows another route.
3. **The intro has no maximum length** with a separate opening file, but 26 s in the older path.
4. **The slideshow picks random photos each time**, so a new render changes the intro.

## 6. Decisions for the redesign

1. The film has three closing moments (overview ending, finale, outro). Keep all three?
2. Where should the sub course go?
3. Which outro style is the real default?
