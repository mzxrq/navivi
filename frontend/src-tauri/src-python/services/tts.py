"""
TTS processor for generating speech audio via the Irodori TTS service,
analyzing pause frames, and handling batch/single-file audio assembly.
"""
import httpx
import uuid
from pathlib import Path
import wave
import numpy as np
import subprocess
import os
import shutil

# Directory to store generated audio files[cite: 6]
OUTPUT_DIR = Path("data/outputs/audio")
OUTPUT_DIR.mkdir(exist_ok=True)

async def call_irodori_api(text: str) -> bytes:
    """
    Makes an HTTP POST request to the local Irodori TTS API to generate speech.
    """
    url = "http://127.0.0.1:8088/v1/audio/speech"
    
    payload = {
        "model": "irodori-tts",
        "input": text,
        "voice": "test1" 
    }
    
    async with httpx.AsyncClient() as client:
        # CHANGE: Increased timeout from 30.0 to 300.0 (5 minutes) just to be safe for the first load!
        response = await client.post(url, json=payload, timeout=300.0)
        
        if response.status_code != 200:
            print(f"Server returned {response.status_code}: {response.text}")
            raise Exception(f"API request failed with status {response.status_code}")
            
        return response.content

async def get_irodori_speech(text: str) -> str:
    """
    Generates speech audio for the given text and saves it to a local WAV file.[cite: 6]
    """
    file_id = str(uuid.uuid4())
    file_path = OUTPUT_DIR / f"{file_id}.wav"
    
    audio_content = await call_irodori_api(text)
    
    with open(file_path, "wb") as f:
        f.write(audio_content)
        
    return str(file_path)

def analyze_wav_pauses(wav_path: str, silence_threshold: int = 500, min_pause_duration: float = 0.2) -> dict:
    """
    Reads a .wav file, gets its duration, and detects silent pause intervals.[cite: 6]
    """
    with wave.open(wav_path, 'rb') as wf:
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        duration = n_frames / framerate
        
        audio_bytes = wf.readframes(n_frames)
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
        
        channels = wf.getnchannels()
        if channels > 1:
            audio_np = audio_np.reshape(-1, channels).mean(axis=1)

    chunk_duration = 0.05 
    chunk_size = int(framerate * chunk_duration)
    
    pauses = []
    in_pause = False
    pause_start = 0.0

    for i in range(0, len(audio_np), chunk_size):
        chunk = audio_np[i:i + chunk_size]
        if len(chunk) == 0:
            continue
        
        peak_amplitude = np.max(np.abs(chunk))
        current_time = i / framerate

        if peak_amplitude < silence_threshold:
            if not in_pause:
                in_pause = True
                pause_start = current_time
        else:
            if in_pause:
                in_pause = False
                pause_end = current_time
                if (pause_end - pause_start) >= min_pause_duration:
                    pauses.append({
                        "start": round(pause_start, 3),
                        "end": round(pause_end, 3),
                        "duration": round(pause_end - pause_start, 3)
                    })

    if in_pause:
        pause_end = len(audio_np) / framerate
        if (pause_end - pause_start) >= min_pause_duration:
            pauses.append({
                "start": round(pause_start, 3),
                "end": round(pause_end, 3),
                "duration": round(pause_end - pause_start, 3)
            })

    return {
        "duration_seconds": round(duration, 3),
        "pauses": pauses
    }

def concatenate_audio_files(audio_paths: list[str], final_output_path: str = "outputs/master_narration.wav") -> str:
    """
    Concatenates multiple WAV audio segments into 1 single master audio file using FFmpeg.
    """
    # 1. FIX: Guarantee the output folder exists before FFmpeg tries to write to it
    out_path_obj = Path(final_output_path)
    out_path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    # 2. FIX: Use absolute paths for everything to prevent FFmpeg from getting lost
    concat_list_path = OUTPUT_DIR.resolve() / "audio_concat_list.txt"
    
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for path in audio_paths:
            if path and os.path.exists(path):
                abs_path = os.path.abspath(path).replace("\\", "/")
                f.write(f"file '{abs_path}'\n")

    # 3. FIX: Try to use your bundled FFmpeg if available, otherwise fallback
    ffmpeg_cmd = "ffmpeg"
    if "resolve_ffmpeg_bin" in globals():
        ffmpeg_cmd = resolve_ffmpeg_bin()

    cmd = [
        str(ffmpeg_cmd), "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list_path),
        "-c", "copy",
        str(out_path_obj.resolve())
    ]
    
    print(f"🔄 Merging audio segments...")
    
    # 4. FIX: Removed DEVNULL hiding so if it crashes, you will see exactly why!
    subprocess.run(cmd, check=True)
    
    if concat_list_path.exists():
        concat_list_path.unlink()

    print(f"✅ Successfully compiled audio into 1 single file: {final_output_path}")
    return final_output_path


# ---------------------------------------------------------------------------
# FINAL ASSEMBLY STAGE
# ---------------------------------------------------------------------------
# Everything below joins the per-phase silent/narrated video segments
# (produced by route2vdo.render_route_animation + the per-leg audio mux in
# main.py) into a SINGLE final video and a SINGLE full-timeline master audio
# track, then combines those two into one final playable file.
#
# Core design constraint: the ffmpeg CONCAT DEMUXER (-f concat -c copy)
# requires every input file to have an IDENTICAL stream layout (same number
# of streams, same codecs). route2vdo's overview/summary segments have NO
# audio stream at all, while waypoint legs do (narration muxed in). Feeding
# that mismatch directly into the concat demuxer produces broken/silently
# dropped audio. So every helper here exists to make streams homogeneous
# BEFORE the join, so the actual join can be a cheap, lossless stream copy
# instead of a full re-encode.
# ---------------------------------------------------------------------------


def resolve_ffmpeg_bin() -> str:
    """
    Small local resolver mirroring route2vdo._resolve_ffmpeg(). Kept as a
    local duplicate (rather than importing from route2vdo) to avoid a
    cross-module import cycle: route2vdo imports from mapfetcher, and
    main.py imports both tts and route2vdo — a one-line duplication here
    is cheaper than restructuring module boundaries for a single path
    lookup.
    """
    bundled = Path(__file__).resolve().parent.parent / "bin" / "FFmpeg" / "bin" / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    found = shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("ffmpeg not found (bundled path or PATH). Check network/install settings.")
    return found


def _resolve_ffprobe_bin() -> str | None:
    """Locates ffprobe next to the resolved ffmpeg binary, or on PATH."""
    ffmpeg_path = Path(resolve_ffmpeg_bin())
    candidate = ffmpeg_path.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if candidate.exists():
        return str(candidate)
    return shutil.which("ffprobe")


def _get_media_duration(path: str) -> float:
    """
    Uses ffprobe to read a media file's exact duration in seconds,
    straight from the container header. Preferred over re-deriving it in
    Python from frame counts / fps (e.g. frame_count / fps) because it
    queries the SAME number ffmpeg itself will use when muxing or
    concatenating this file next — eliminating any chance of a rounding
    drift between "what we computed" and "what ffmpeg thinks", which is
    exactly the kind of off-by-one-frame bug that causes audio/video
    drift to accumulate silently across concat boundaries.
    """
    ffprobe_cmd = _resolve_ffprobe_bin()
    if not ffprobe_cmd:
        raise RuntimeError("ffprobe not found; cannot determine media duration for silence padding.")

    result = subprocess.run(
        [ffprobe_cmd, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"ffprobe failed on '{path}': {result.stderr.strip()}")
    return float(result.stdout.strip())


def get_audio_format(path: str) -> tuple[int, int]:
    """
    Probes a real audio file's sample_rate and channel count via ffprobe.

    This exists to fix the "chipmunk" pitch/speed distortion bug: silence
    generated at a HARDCODED sample rate (e.g. 44100) that doesn't match
    the real narration audio's actual rate (Irodori-TTS commonly emits
    16kHz/22.05kHz/24kHz, not 44.1kHz) causes a rate mismatch once
    stream-copy concatenation joins them. -c copy concatenation does NOT
    resample — it just re-packages existing sample data under one
    declared rate, so any mismatched segment plays back faster/slower
    than intended, which is heard as pitch-shifted, sped-up audio.
    Matching every synthesized silence segment to the REAL source rate
    eliminates the mismatch instead of just guessing a common value.
    """
    ffprobe_cmd = _resolve_ffprobe_bin()
    if not ffprobe_cmd:
        raise RuntimeError("ffprobe not found; cannot detect narration audio's sample rate.")

    result = subprocess.run(
        [ffprobe_cmd, "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"ffprobe failed to read audio format of '{path}': {result.stderr.strip()}")

    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        raise RuntimeError(f"Unexpected ffprobe output for '{path}': {result.stdout!r}")
    sample_rate, channels = int(lines[0]), int(lines[1])
    return sample_rate, channels


def _detect_reference_audio_format(narration_paths: list, default_sample_rate: int = 44100, default_channels: int = 2) -> tuple[int, int]:
    """
    Finds the first real (non-None) narration file in the list and uses
    ITS sample_rate/channels as the reference format for every silence
    segment synthesized elsewhere in the timeline. Falls back to
    44100/stereo only when there is no real narration audio at all
    (e.g. a route with zero waypoint narration), in which case there's
    nothing to mismatch against.
    """
    for path in narration_paths:
        if path and os.path.exists(path):
            return get_audio_format(path)
    return default_sample_rate, default_channels


def _make_silent_audio(duration_seconds: float, output_path: str, sample_rate: int = 44100, channels: int = 2, as_wav: bool = False) -> str:
    """
    Synthesizes a silent audio track via ffmpeg's `anullsrc` filter — a
    pure sample generator (writes zeros procedurally), NOT a decode of an
    actual file. Cost is O(duration * sample_rate) of trivial writes, not
    an I/O- or decode-bound operation like reading a real silent WAV
    would be.

    as_wav=True produces PCM WAV (for standalone master-audio assembly,
    matching the format concatenate_audio_files() already expects).
    as_wav=False produces AAC (for muxing directly into an MP4 container
    alongside video).
    """
    ffmpeg_cmd = resolve_ffmpeg_bin()
    if as_wav:
        codec_args = ["-c:a", "pcm_s16le"]
    else:
        codec_args = ["-c:a", "aac", "-b:a", "128k"]

    cmd = [
        ffmpeg_cmd, "-y",
        "-f", "lavfi", "-i", f"anullsrc=channel_layout={'stereo' if channels >= 2 else 'mono'}:sample_rate={sample_rate}",
        "-t", f"{max(duration_seconds, 0.05):.3f}",  # floor avoids a zero-length ffmpeg edge case
        *codec_args,
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to synthesize silent audio '{output_path}': {result.stderr.strip()}")
    return output_path


def normalize_segment_audio(video_path: str, has_narration: bool, sample_rate: int, channels: int, temp_dir: str = "outputs/tmp_normalized") -> str:
    """
    Ensures ONE rendered video segment has an audio stream, regardless of
    whether narration was already muxed into it upstream.

    - Narrated segments (waypoint legs): passed through untouched, they
      already have audio.
    - Silent segments (overview / summary): get a matching-duration
      silent AAC track muxed in via stream copy (no re-encode of the
      existing video — O(bytes), not O(frames)).

    sample_rate/channels MUST match the real narration audio's format
    (see _detect_reference_audio_format). This silent AAC track ends up
    living inside a video file that later gets joined to narrated
    segments via stream-copy concat in concatenate_video_segments() — if
    its sample rate doesn't match the narrated segments' audio, the
    concat demuxer's -c copy join will produce speed/pitch-distorted
    ("chipmunk") audio across the mismatched boundary, since stream copy
    never resamples.

    Doing this homogenization per-segment (rather than special-casing
    "missing audio" inside the concat step itself) keeps
    concatenate_video_segments() dead simple: by the time it runs, EVERY
    input is guaranteed to be video+audio with matching codecs AND
    matching sample rate/channels.
    """
    if has_narration:
        return video_path

    os.makedirs(temp_dir, exist_ok=True)
    duration = _get_media_duration(video_path)

    silent_aac = str(Path(temp_dir) / f"silence_{uuid.uuid4().hex}.aac")
    _make_silent_audio(duration, silent_aac, sample_rate=sample_rate, channels=channels, as_wav=False)

    muxed_path = str(Path(temp_dir) / f"{Path(video_path).stem}_padded.mp4")
    ffmpeg_cmd = resolve_ffmpeg_bin()
    cmd = [
        ffmpeg_cmd, "-y",
        "-i", video_path, "-i", silent_aac,
        "-c:v", "copy", "-c:a", "copy",   # stream copy: zero re-encode cost
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest", muxed_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Clean up the intermediate silent track regardless of outcome —
    # avoids leaking tmp_normalized/*.aac files on repeated failed runs.
    if os.path.exists(silent_aac):
        os.remove(silent_aac)

    if result.returncode != 0:
        raise RuntimeError(f"Failed to pad silent segment '{video_path}': {result.stderr.strip()}")
    return muxed_path


def concatenate_video_segments(video_paths: list[str], final_output_path: str = "outputs/final_navigation_video.mp4") -> str:
    """
    Joins already-encoded, stream-homogeneous video segments into ONE
    file using the ffmpeg CONCAT DEMUXER with -c copy.

    Why this over -filter_complex concat: filter_complex forces a full
    decode -> filter-graph -> re-encode pass over EVERY frame in the
    timeline — O(total_frames) of libx264 encode work a SECOND time, on
    top of the O(frame_count) encode route2vdo's _FrameSink already
    performed per phase. The concat demuxer instead performs a pure
    container remux: it walks the existing H.264/AAC packet streams and
    re-packages them without touching a single pixel or audio sample —
    O(total_encoded_bytes) of disk I/O, not O(total_frames) of CPU-bound
    encode work. On a multi-minute 1080p route video this is the
    difference between a sub-second join and several minutes of
    redundant encoding.

    PRECONDITION (enforced by the caller via normalize_segment_audio):
    every input must have exactly one video + one audio stream, using
    codecs identical to what _FrameSink emitted (h264/yuv420p + aac).
    Mismatched codecs/resolutions here will surface as an ffmpeg error,
    not a silent corruption, because we check returncode below.
    """
    if not video_paths:
        raise ValueError("No video segments provided to concatenate.")

    for path in video_paths:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Segment missing before concat: {path}")

    out_dir = Path(final_output_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    concat_list_path = out_dir / f"video_concat_list_{uuid.uuid4().hex}.txt"

    with open(concat_list_path, "w", encoding="utf-8") as f:
        for path in video_paths:
            abs_path = os.path.abspath(path).replace("\\", "/")
            f.write(f"file '{abs_path}'\n")

    ffmpeg_cmd = resolve_ffmpeg_bin()
    cmd = [
        ffmpeg_cmd, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list_path),
        "-c", "copy",
        final_output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    concat_list_path.unlink(missing_ok=True)

    if result.returncode != 0:
        # Surface ffmpeg's actual diagnostic instead of failing silently —
        # this is exactly where stream-mismatch errors (mismatched
        # codecs/resolutions/sample-rates across segments) would
        # otherwise vanish into DEVNULL.
        raise RuntimeError(f"Video concat failed: {result.stderr.strip()}")

    print(f"✅ Final navigation video assembled: {final_output_path}")
    return final_output_path


def build_full_narration_master_audio(
    segment_durations: list,
    segment_narration_audio: list,
    final_output_path: str = "outputs/master_full_timeline_audio.wav",
) -> str:
    """
    Builds a TIMELINE-ACCURATE master audio track: real narration where
    it exists, exact-duration synthesized silence everywhere else
    (overview / summary gaps) — unlike the existing
    concatenate_audio_files(), which only stitches narration clips
    back-to-back with no regard for the silent phases between them, and
    is therefore NOT sample-aligned with the final concatenated video.

    segment_durations[i] and segment_narration_audio[i] must correspond
    to the SAME i-th phase of the timeline (overview, each waypoint leg,
    summary) in the same order the video segments will be concatenated.

    Silence is synthesized to match the REAL narration audio's detected
    sample_rate/channels (via _detect_reference_audio_format), not a
    hardcoded value — mismatched rates across a stream-copy concat are
    what cause sped-up/pitch-shifted ("chipmunk") playback.
    """
    if len(segment_durations) != len(segment_narration_audio):
        raise ValueError("segment_durations and segment_narration_audio must be the same length and order.")

    ref_sample_rate, ref_channels = _detect_reference_audio_format(segment_narration_audio)
    print(f"🔊 Reference audio format for silence padding: {ref_sample_rate}Hz, {ref_channels}ch")

    temp_dir = Path("outputs/tmp_master_audio")
    temp_dir.mkdir(parents=True, exist_ok=True)
    parts = []

    try:
        for i, (duration, narration_path) in enumerate(zip(segment_durations, segment_narration_audio)):
            if narration_path and os.path.exists(narration_path):
                parts.append(narration_path)
            else:
                silent_path = str(temp_dir / f"silence_{i:03d}_{uuid.uuid4().hex[:8]}.wav")
                # WAV (not AAC) here since this master track is standalone
                # audio, not something being muxed into an MP4 container —
                # matches the format concatenate_audio_files() expects.
                # sample_rate/channels matched to the REAL narration audio
                # (not a hardcoded default) to avoid the chipmunk bug.
                _make_silent_audio(duration, silent_path, sample_rate=ref_sample_rate, channels=ref_channels, as_wav=True)
                parts.append(silent_path)

        return concatenate_audio_files(parts, final_output_path)
    finally:
        # Best-effort cleanup of synthesized silence WAVs; narration
        # files (paths the caller owns) are never touched or deleted.
        for p in parts:
            if "tmp_master_audio" in p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


def combine_video_and_master_audio(
    video_path: str,
    audio_path: str,
    final_output_path: str = "outputs/final_output_with_audio.mp4",
) -> str:
    """
    Final mux stage: joins the fully-concatenated video (from
    concatenate_video_segments) against a SEPARATE, independently-built
    master audio track (from build_full_narration_master_audio).

    Use this instead of relying solely on each segment's own inline
    audio when you want ONE authoritative audio timeline driving the
    whole video, rather than trusting N independently-muxed segments to
    stay sample-aligned after concatenation.

    -c:v copy: the video stream is never re-touched (it was already
    finalized by concatenate_video_segments).
    -c:a aac: the master audio (currently WAV/PCM) is encoded to AAC
    exactly once here — the single unavoidable encode cost in this
    entire assembly stage, since MP4 containers require compressed
    audio, not raw PCM.
    -shortest: guards against a few-millisecond rounding mismatch
    between independently-built video and audio timelines (frame-count
    rounding via int(duration_seconds * fps) in route2vdo) becoming a
    trailing black/silent tail instead of a hard failure.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    out_dir = Path(final_output_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_cmd = resolve_ffmpeg_bin()
    cmd = [
        ffmpeg_cmd, "-y",
        "-i", video_path, "-i", audio_path,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest", final_output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Final audio/video mux failed: {result.stderr.strip()}")

    print(f"✅ Final combined video+audio: {final_output_path}")
    return final_output_path


def assemble_final_deliverable(
    video_segment_paths: list[str],
    segment_has_narration: list[bool],
    segment_durations: list[float],
    segment_narration_audio: list,
    output_dir: str = "outputs",
) -> dict:
    """
    Top-level orchestrator tying every helper above into the exact
    3-step flow requested:

      1. Generate route animation video segments + narration audio
         (done upstream, by route2vdo + get_irodori_speech — this
         function starts AFTER that).
      2. Combine ALL video segments -> ONE full video file.
         Combine ALL audio (narration + timed silence) -> ONE full
         audio file.
      3. Combine the full video + full audio -> ONE final playable clip.

    All three intermediate artifacts (full video, full audio, final
    combined file) are returned so callers can keep/inspect/reuse any
    of them independently, not just the final muxed result.
    """
    if not (len(video_segment_paths) == len(segment_has_narration) == len(segment_durations) == len(segment_narration_audio)):
        raise ValueError(
            "video_segment_paths, segment_has_narration, segment_durations, and "
            "segment_narration_audio must all be the same length and represent the "
            "SAME ordered list of timeline phases."
        )

    # Detect the REAL narration audio format ONCE and reuse it everywhere
    # silence needs to be synthesized (both the video-embedded silent AAC
    # tracks and the standalone master WAV track). This is the fix for the
    # "chipmunk" sped-up/pitch-shifted audio bug: silence generated at a
    # rate that doesn't match the real narration causes exactly that
    # distortion once stream-copy concatenation joins mismatched segments.
    ref_sample_rate, ref_channels = _detect_reference_audio_format(segment_narration_audio)

    # Step 2a: homogenize + concat -> one full video (kept for consumers
    # who just want a single-file video regardless of audio strategy).
    normalized_paths = [
        normalize_segment_audio(path, has_narration=has_narr, sample_rate=ref_sample_rate, channels=ref_channels)
        for path, has_narr in zip(video_segment_paths, segment_has_narration)
    ]
    full_video_path = concatenate_video_segments(
        normalized_paths, final_output_path=f"{output_dir}/final_navigation_video.mp4"
    )

    # Step 2b: one full, timeline-accurate audio file (narration + timed silence).
    full_audio_path = build_full_narration_master_audio(
        segment_durations=segment_durations,
        segment_narration_audio=segment_narration_audio,
        final_output_path=f"{output_dir}/master_full_timeline_audio.wav",
    )

    # Step 3: combine the two into the single final deliverable.
    final_combined_path = combine_video_and_master_audio(
        video_path=full_video_path,
        audio_path=full_audio_path,
        final_output_path=f"{output_dir}/final_output_with_audio.mp4",
    )

    return {
        "full_video_path": full_video_path,
        "full_audio_path": full_audio_path,
        "final_combined_path": final_combined_path,
    }