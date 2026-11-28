# Themed video cards: themes, layout and your own styles

Themed cards are used by the "whole route first" (course) overview and the walking legs. A project without
`hud.json` renders in the classic look.

## Turn it on: `<project>/hud.json`

The app rewrites `job_config.json` on every save, so these settings live in their own file.

```json
{
  "theme": "mine",
  "layout": {
    "title":    { "anchor": "top-left", "x": 16, "y": 14 },
    "modes":    { "show": false },
    "strip":    { "scale": 0.9 },
    "totals":   { "style": "ticket" }
  }
}
```

`theme`: a folder name in `services/hudtheme/themes/` (`sea`, `mine`), `auto`, or `classic`. Dark colors follow
the project's own light/dark setting. Only `theme` is required.

### Cards

| Name | Where | Style folder | Default place |
|---|---|---|---|
| `title` | overview | `title` | top-left |
| `totals` | overview | `totals` | top-right |
| `modes` | overview | `modes` | top-right, under the totals |
| `strip` | overview | `strip` | bottom-right |
| `notices` | overview | (drawn by the app) | bottom-left |
| `next` | leg | `next` | top-left |
| `leg_banner` | leg | `totals` | top-right |
| `compass` | leg | `compass` | top-right, under the banner |
| `leg_rail` | leg | `leg_rail` | bottom-left |
| `remaining` | leg | `totals` | bottom-right |
| `outro` | outro | `outro` | the whole frame (no `hud.json` layout entry) |
| `place` | attraction clip | `place` | top-left (600-high frame, like the legs) |

On attraction clips the `place` card replaces the plain place name, in the editor and the export, from the next
render. Renaming the item in the editor shows the new words as plain text until the render after.

### Settings per card

| Field | Value |
|---|---|
| `show` | `true` / `false` |
| `anchor` | `top`, `middle` or `bottom`, then `-left`, `-center` or `-right` |
| `x`, `y` | distance from the anchored edge (from the middle for `center` / `middle`), on a frame 568 high for the overview and 600 high for legs |
| `scale` | 0.5 to 2 |
| `style` | a style file's name without its extension |

`notices` takes `show`, `anchor`, `x` and `y` only. A card never leaves the frame. The strip and the rail shrink
when they would run into the banners or the remaining card. Overview stop badges and map name pills keep clear of
the cards wherever you put them. A theme can set its own defaults with a `"layout"` object in `theme.json`.

A bad value is ignored with a warning in the render log; an unreadable file gives the classic look.

## Your own styles

Put a file in `Documents\Navivi\Styles\<style folder>\<name>.html` (or `.svg`), then set `"style": "<name>"`.
Names may use letters, digits, `-` and `_`. A file named `default.html` there replaces the built-in default.
`NAVIVI_STYLES_DIR` points at another folder.

Start by copying the built-in file from `services/hudtheme/designs/<style folder>/default.html`.

Files are [Jinja2](https://jinja.palletsprojects.com/) templates. Place names are escaped for you. Scripts do not
run and nothing but the bundled fonts is loaded (no web or local pictures; draw with HTML, CSS or inline SVG, or
embed a `data:` URI). A file that fails falls back to the built-in style, with a warning.

### Rules

- One element must have `class="card"`; its box is the card's size.
- `class="fit"`: the text shrinks to its box. `class="card grow"` with a `flow` child: the card grows with its text.
- `strip` must have `data-line="x0 x1 y"`: the line the video draws the progress and traveller on, in card px.
- `compass` must keep the ids `hud-compass-pointer`, `hud-compass-letter`, `hud-compass-label`.

### What a file can use

Every card: `theme` (the colors of `theme.json`, plus `theme.pins`, `theme.mode_colors`), `width`, `height`,
`scene` (the theme's picture), `pattern(name, pale, [[left, right]], height)`, `pin(glyph)` (the map pin's color).
Filters: `words` (break only between words), `units` (small units beside numbers), `g`, `f1`. Built-in artwork:
`{% include "parts/ferry.svg" %}` (also `driving`, `airplane`, `medallion`); macros in `parts/macros.html`.

| Style folder | Variables |
|---|---|
| `title` | `title`, `loop`, `start`, `end`, `stamp` (loop / one way), `route` (the line under the title) |
| `totals` | `distance`, `distance_km`, `time`, `distance_label`, `time_label`, `leg` (the compact banner), `clock_large`, `clock_end` |
| `modes` | `modes`: list of `mode`, `color`, `distance`, `time`, `walker` |
| `strip` | `segments`: list of `mode`, `color`, `glyphs`, `place`, `start`, `end` (shares 0 to 1 of the line); `start`, `end` |
| `next` | `glyph`, `name`, `heading`, `previous_label`, `previous_glyph`, `previous` |
| `place` | `glyph`, `name` |
| `compass` | `degrees`, `name` |
| `leg_rail` | `from_glyph`, `to_glyph`, `share` (0 to 1), `vias`: list of (share, glyph), `color`, `icon` |
| `outro` | `screens`: list of `badge`, `name`, `description`, `photo` (a data URI or ""), `known`, `km`, `time`, `next` (`badge`, `name`, `photo`, or none); `kicker`, `title`, `subtitle`; `distance_label`, `time_label`, `unknown_km`, `unknown_time`; `left` (photo column width), `rolls` (for each of six boxes, in rolling order: (percent, screen) at each end of every hold), `keyframes` (the same for the whole step), `seconds` |

The outro file is a whole animated page, 600 high: it is animated by CSS animations lasting `seconds` that follow `rolls` and `keyframes` (the video code pauses them all and sets their time). Each `class="desc"` text must sit in an element with `data-screen="N"` inside an element with `class="about"`: the video code grows the text from three lines up to seven and sets `--h-N` (the box's height for screen N) on `.about`. `body.bare` must hide everything but the background.

## Your own picture

The picture on the totals card and the outro comes with the theme. A project can show another one:

```json
{ "theme": "sea", "scene": "katsuragi" }
```

`katsuragi` is built in. For your own, put `<name>.svg` in `Documents\Navivi\Styles\scene\` and name it in
`hud.json`; a file there wins over a built-in one of the same name. Draw on a 110 x 76 canvas: either bare SVG shapes,
or a whole `<svg width="110" height="76" viewBox="0 0 110 76">`. The totals card rounds off the left side and covers
everything right of about 95 with its panel. Light and dark projects show the same picture. A missing file gives the
theme's own picture, with a warning in the render log.

## Names on the strip

Each stretch of the strip is labelled with one of its stops. Give your own words, or `""` for none, by the numbers
in its circle:

```json
{ "theme": "mine", "names": { "1-3": "", "4-11": "友ヶ島" } }
```

## A new theme

Copy a folder in `services/hudtheme/themes/`: `theme.json` (colors, optional `layout`), `scene.svg`,
`scene_dark.svg`, `pattern.svg`.
