# TTS voices: backend API for the UI

The backend lets users pick a narration voice per project, clone a new voice by uploading a short reference recording, and preview any voice. This note is everything the UI needs. No Rust changes are needed.

## Calling it

Use the existing `run_python_blueprint` command, which returns one line of JSON on stdout:

```ts
import { invoke } from "@tauri-apps/api/core";

async function voiceAction<T>(action: string, payload: object = {}): Promise<T> {
  const res = await invoke<string>("run_python_blueprint", {
    action,
    payload: JSON.stringify(payload),
  });
  return JSON.parse(res);
}
```

Every response has `success: boolean`. On failure it is `{ success: false, error: string }`, a message you can show the user as-is. The process still exits normally, so `invoke` does not throw on these errors.

> ⚠️ `run_python_blueprint` kills any blueprint process that is already running when a new one starts. Disable the voice buttons while a call is in flight, or a Preview can kill an Upload (and the other way round).

## Actions

### `tts_voices_list`: payload `{}`

```json
{
  "success": true,
  "voices_dir": "C:\\...\\bin\\Irodori-TTS-Server\\voices",
  "voices": [
    { "id": "none",  "filename": null,        "bytes": 0,       "duration_seconds": null, "builtin": true },
    { "id": "test1", "filename": "test1.wav", "bytes": 2572846, "duration_seconds": 53.6, "builtin": false }
  ]
}
```

- `none` is always first. It uses no reference audio (the model's own default voice). Label it something like "No reference (model default)". It can't be deleted.
- `duration_seconds` can be `null` if ffprobe isn't available.

### `tts_voice_add`: payload `{ path, id?, replace? }`

- `path`: absolute path from the file picker. Accepted types: `.wav .flac .mp3 .m4a .ogg .opus .aac .webm`.
- `id`: optional. Only ASCII letters, digits, `_` and `-` are allowed, and `none` is reserved. If omitted, the filename is used, so Japanese filenames will fail. Pre-fill an ASCII id and let the user edit it.
- `replace`: optional. Set it to `true` to overwrite an existing voice with the same id. Without it, adding a duplicate id fails with `"Voice 'x' already exists."`.

```json
{ "success": true,
  "voice": { "id": "alice", "filename": "alice.wav", "bytes": 160044,
             "duration_seconds": 12.3, "warning": null } }
```

`warning` is a string when the clip is under 3 s (the voice may not clone well) or over 30 s (every narration gets slower). Show it, but the voice is saved anyway.

**File picker:**

```ts
import { open } from "@tauri-apps/plugin-dialog";
const path = await open({ multiple: false, filters: [{ name: "Audio",
  extensions: ["wav", "flac", "mp3", "m4a", "ogg", "opus", "aac", "webm"] }] });
```

**Hint text for users:** 5–20 seconds of clear speech from one person, with no music or background noise.

### `tts_voice_delete`: payload `{ id }`

Returns `{ "success": true, "id": "alice" }`, or an error if the voice doesn't exist or is `none`.

### `tts_voice_preview`: payload `{ voice, speed?, text?, hardware? }`

- `voice`: a voice id from the list.
- `speed`: 0.25–4.0. Pass the project's current speed so the preview sounds like the real narration. Defaults to 1.25.
- `text`: optional. The default is a short Japanese greeting.
- `hardware`: optional, `"low"` or `"high"`. Pass the project's `hardware_spec_override`.

```json
{ "success": true, "voice": "alice", "speed": 1.25, "text": "...",
  "path": "C:\\...\\voices\\.preview\\alice.wav" }
```

Play it with `convertFileSrc(path)` in an `<audio>` element. Add a cache-busting query string (`?t=Date.now()`), because the same path is reused for each voice.

⏳ **Slow the first time:** the first preview starts the TTS server and loads the model, which can take a minute or more (much longer on the very first run, when it downloads the model). After that it's a few seconds. Show a spinner. The server shuts itself down after 10 minutes idle.

## The project setting

Save the choice in the project settings (the `ProjectSettings` type in `src/types/index.ts`, saved into `job_config.json`):

```ts
tts?: {
  voice?: string;   // a voice id from tts_voices_list; missing = "test1"
  speed?: number;   // 0.25–4.0; missing = 1.25
};
```

The type doesn't have this field yet, so please add it. Save it with `updateSettings({ tts: { ...settings.tts, voice } })` and `setIsDirty(true)`, like the other settings.

**Behaviour the UI should explain:**

- **Changing voice or speed regenerates the narration** on the next TTS or full-pipeline run. Clips made with a different voice or speed are remade automatically, and so are clips from a voice whose reference file was replaced. A short note next to the picker helps.
- **If the project's voice was deleted from the library**, the backend falls back to `test1` and logs a warning. Show a "missing" badge when `settings.tts.voice` isn't in the list.
- **The library is shared by all projects.** Deleting a voice affects every project that uses it.
