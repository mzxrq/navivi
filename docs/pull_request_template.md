<!--
Title: start with feat:, fix:, chore: or docs: (the same words as the commit subjects), for example "feat: assistant chat is saved in each project".
Delete any line below that does not apply. Do not add Co-Authored-By or "Generated with" lines.
-->

## What
<!-- One to five bullets: what changed, in plain words. -->
-

## Why
<!-- The problem or request behind it. One or two sentences. -->

## How to check it
<!-- Steps to see it work in the app (npm run tauri dev), or the tests that cover it. -->
1.

## Checks
- [ ] `npm run typecheck`
- [ ] `npm test`
- [ ] `python -m pytest -q` (from `src-tauri/src-python`), if Python changed
- [ ] `cargo test` (from `src-tauri`), if Rust changed
- [ ] `npm run extract` and the Japanese translations, if UI text changed
- [ ] Tried in the real app

## Not tested or not finished
<!-- Anything you did not run, did not finish, or want a second look at. Write "Nothing" if there is none. -->

## Notes for merging
<!-- Rebuild needed (Rust changes), new downloads, changed file formats, anything a user or teammate must know. -->
- [ ] Nothing special
