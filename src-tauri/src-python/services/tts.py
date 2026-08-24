"""
tts.py (OOP Refactored)
---------------------------------------------------------------------------
TTS processor for generating speech audio via the Irodori TTS service,
analyzing pause frames, and handling batch/single-file audio & video assembly.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import httpx
import uuid
from pathlib import Path
import wave
import numpy as np
import subprocess
import os
import shutil
import logging  # PATCH: needed for the loud subtitle-skip warnings below (was missing)
from typing import Final, Optional, Tuple, List, Dict, Any

# PATCH: module-level logger, same pattern used in vdoeditor.py / gpsparser.py.
# Without this, subtitle-burn failures/skips had nowhere to surface — they
# either silently no-op'd or got swallowed by main.py's bare str(e) handler.
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from services.subtitle import SubtitleStyle

# =============================================================================
# FFMPEG & FFPROBE SYSTEM MANAGER
# =============================================================================


class FFmpegManager:
    """Encapsulates binary resolution and direct media probing via FFmpeg/FFprobe."""

    @staticmethod
    def resolve_ffmpeg_bin() -> str:
        """Locates the bundled FFmpeg binary or falls back to system PATH."""
        bundled = (
            Path(__file__).resolve().parent.parent
            / "bin"
            / "FFmpeg"
            / "bin"
            / "ffmpeg.exe"
        )
        if bundled.exists():
            return str(bundled)
        found = shutil.which("ffmpeg")
        if not found:
            raise RuntimeError(
                "ffmpeg not found (bundled path or PATH). Check network/install settings."
            )
        return found

    @staticmethod
    def resolve_ffprobe_bin() -> Optional[str]:
        """Locates ffprobe next to the resolved ffmpeg binary, or on PATH."""
        try:
            ffmpeg_path = Path(FFmpegManager.resolve_ffmpeg_bin())
            candidate = ffmpeg_path.with_name(
                "ffprobe.exe" if os.name == "nt" else "ffprobe"
            )
            if candidate.exists():
                return str(candidate)
        except Exception:
            pass
        return shutil.which("ffprobe")

    @classmethod
    def get_media_duration(cls, path: str) -> float:
        """Queries container duration precisely via ffprobe."""
        ffprobe_cmd = cls.resolve_ffprobe_bin()
        if not ffprobe_cmd:
            raise RuntimeError("ffprobe not found; cannot determine media duration.")

        result = subprocess.run(
            [
                ffprobe_cmd,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(f"ffprobe failed on '{path}': {result.stderr.strip()}")
        return float(result.stdout.strip())

    @classmethod
    def get_audio_format(cls, path: str) -> Tuple[int, int]:
        """Probes a real audio file's sample_rate and channel count via ffprobe."""
        ffprobe_cmd = cls.resolve_ffprobe_bin()
        if not ffprobe_cmd:
            raise RuntimeError(
                "ffprobe not found; cannot detect narration audio's sample rate."
            )

        result = subprocess.run(
            [
                ffprobe_cmd,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate,channels",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(
                f"ffprobe failed to read audio format of '{path}': {result.stderr.strip()}"
            )

        lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
        if len(lines) < 2:
            raise RuntimeError(
                f"Unexpected ffprobe output for '{path}': {result.stdout!r}"
            )
        return int(lines[0]), int(lines[1])


# =============================================================================
# IRODORI TTS API CLIENT
# =============================================================================


class IrodoriTTSClient:
    """Handles communication with the local Irodori TTS service."""

    def __init__(
        self,
        output_dir: Path = Path("data/outputs/audio"),
        base_url: str = "http://127.0.0.1:8088/v1/audio/speech",
    ):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url

    async def call_api(self, text: str) -> bytes:
        """Makes an HTTP POST request to the local Irodori TTS API to generate speech."""
        payload = {"model": "irodori-tts", "input": text, "voice": "string"}

        async with httpx.AsyncClient() as client:
            response = await client.post(self.base_url, json=payload, timeout=300.0)

            if response.status_code != 200:
                print(f"Server returned {response.status_code}: {response.text}")
                raise Exception(
                    f"API request failed with status {response.status_code}"
                )

            return response.content

    async def generate_speech(self, text: str) -> str:
        """Generates speech audio for the given text and saves it to a local WAV file."""
        file_id = str(uuid.uuid4())
        file_path = self.output_dir / f"{file_id}.wav"

        audio_content = await self.call_api(text)

        with open(file_path, "wb") as f:
            f.write(audio_content)

        return str(file_path)


# =============================================================================
# AUDIO PROCESSOR & PAUSE ANALYZER
# =============================================================================


class AudioProcessor:
    """Handles wave pause analysis, silence synthesis, and file concatenations."""

    def __init__(self, output_dir: Path = Path("data/outputs/audio")):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def analyze_pauses(
        self,
        wav_path: str,
        silence_threshold: int = 500,
        min_pause_duration: float = 0.2,
    ) -> Dict[str, Any]:
        """Reads a .wav file, gets its duration, and detects silent pause intervals."""
        with wave.open(wav_path, "rb") as wf:
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
            chunk = audio_np[i : i + chunk_size]
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
                        pauses.append(
                            {
                                "start": round(pause_start, 3),
                                "end": round(pause_end, 3),
                                "duration": round(pause_end - pause_start, 3),
                            }
                        )

        if in_pause:
            pause_end = len(audio_np) / framerate
            if (pause_end - pause_start) >= min_pause_duration:
                pauses.append(
                    {
                        "start": round(pause_start, 3),
                        "end": round(pause_end, 3),
                        "duration": round(pause_end - pause_start, 3),
                    }
                )

        return {"duration_seconds": round(duration, 3), "pauses": pauses}

    def concatenate_files(
        self,
        audio_paths: List[str],
        final_output_path: str = "outputs/master_narration.wav",
    ) -> str:
        """Concatenates multiple WAV audio segments into 1 single master audio file using FFmpeg."""
        out_path_obj = Path(final_output_path)
        out_path_obj.parent.mkdir(parents=True, exist_ok=True)

        concat_list_path = self.output_dir.resolve() / "audio_concat_list.txt"

        with open(concat_list_path, "w", encoding="utf-8") as f:
            for path in audio_paths:
                if path and os.path.exists(path):
                    abs_path = os.path.abspath(path).replace("\\", "/")
                    f.write(f"file '{abs_path}'\n")

        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
        cmd = [
            str(ffmpeg_cmd),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c",
            "copy",
            str(out_path_obj.resolve()),
        ]

        print(f"🔄 Merging audio segments...")
        subprocess.run(cmd, check=True)

        if concat_list_path.exists():
            concat_list_path.unlink()

        print(f"✅ Successfully compiled audio into 1 single file: {final_output_path}")
        return final_output_path

    def make_silent_audio(
        self,
        duration_seconds: float,
        output_path: str,
        sample_rate: int = 44100,
        channels: int = 2,
        as_wav: bool = False,
    ) -> str:
        """Synthesizes a silent audio track via ffmpeg's `anullsrc` filter."""
        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
        codec_args = (
            ["-c:a", "pcm_s16le"] if as_wav else ["-c:a", "aac", "-b:a", "128k"]
        )

        cmd = [
            ffmpeg_cmd,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout={'stereo' if channels >= 2 else 'mono'}:sample_rate={sample_rate}",
            "-t",
            f"{max(duration_seconds, 0.05):.3f}",
            *codec_args,
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to synthesize silent audio '{output_path}': {result.stderr.strip()}"
            )
        return output_path

    def build_full_narration_master(
        self,
        segment_durations: List[float],
        segment_narration_audio: List[Optional[str]],
        final_output_path: str = "outputs/master_full_timeline_audio.wav",
    ) -> str:
        """Builds a timeline-accurate master audio track combining narration and procedural silence."""
        if len(segment_durations) != len(segment_narration_audio):
            raise ValueError(
                "segment_durations and segment_narration_audio must be the same length and order."
            )

        ref_sample_rate, ref_channels = self._detect_reference_audio_format(
            segment_narration_audio
        )
        print(
            f"🔊 Reference audio format for silence padding: {ref_sample_rate}Hz, {ref_channels}ch"
        )

        # ✅ Route temporary audio files into the active project audio directory instead of root outputs
        temp_dir = self.output_dir / "tmp_master_audio"
        temp_dir.mkdir(parents=True, exist_ok=True)
        parts = []

        try:
            for i, (duration, narration_path) in enumerate(
                zip(segment_durations, segment_narration_audio)
            ):
                if narration_path and os.path.exists(narration_path):
                    parts.append(narration_path)
                else:
                    silent_path = str(
                        temp_dir / f"silence_{i:03d}_{uuid.uuid4().hex[:8]}.wav"
                    )
                    self.make_silent_audio(
                        duration,
                        silent_path,
                        sample_rate=ref_sample_rate,
                        channels=ref_channels,
                        as_wav=True,
                    )
                    parts.append(silent_path)

            return self.concatenate_files(parts, final_output_path)
        finally:
            for p in parts:
                if "tmp_master_audio" in p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    @staticmethod
    def _detect_reference_audio_format(
        narration_paths: List[Optional[str]],
        default_sample_rate: int = 44100,
        default_channels: int = 2,
    ) -> Tuple[int, int]:
        """Detects sample rate and channels from the first available narration clip."""
        for path in narration_paths:
            if path and os.path.exists(path):
                return FFmpegManager.get_audio_format(path)
        return default_sample_rate, default_channels


# =============================================================================
# VIDEO PROCESSOR & STREAM CONCATENATOR
# =============================================================================


class VideoProcessor:
    """Manages video segment padding, stream-copy concatenation, and final muxing."""

    @staticmethod
    def normalize_segment_audio(
        video_path: str,
        has_narration: bool,
        sample_rate: int,
        channels: int,
        temp_dir: str = "",
    ) -> str:
        """Ensures a video segment has a matching audio stream (pads with silent AAC if missing)."""
        if has_narration:
            return video_path

        os.makedirs(temp_dir, exist_ok=True)
        duration = FFmpegManager.get_media_duration(video_path)

        silent_aac = str(Path(temp_dir) / f"silence_{uuid.uuid4().hex}.aac")
        audio_proc = AudioProcessor()
        audio_proc.make_silent_audio(
            duration,
            silent_aac,
            sample_rate=sample_rate,
            channels=channels,
            as_wav=False,
        )

        muxed_path = str(Path(temp_dir) / f"{Path(video_path).stem}_padded.mp4")
        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
        cmd = [
            ffmpeg_cmd,
            "-y",
            "-i",
            video_path,
            "-i",
            silent_aac,
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-shortest",
            muxed_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if os.path.exists(silent_aac):
            os.remove(silent_aac)

        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to pad silent segment '{video_path}': {result.stderr.strip()}"
            )
        return muxed_path

    @staticmethod
    def concatenate_segments(
        video_paths: List[str],
        final_output_path: str = "outputs/final_navigation_video.mp4",
    ) -> str:
        """Joins stream-homogeneous video segments via FFmpeg's concat demuxer (-c copy)."""
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

        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
        cmd = [
            ffmpeg_cmd,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c",
            "copy",
            final_output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        concat_list_path.unlink(missing_ok=True)

        if result.returncode != 0:
            raise RuntimeError(f"Video concat failed: {result.stderr.strip()}")

        print(f"✅ Final navigation video assembled: {final_output_path}")
        return final_output_path

    @staticmethod
    def combine_video_and_audio(
        video_path: str,
        audio_path: str,
        final_output_path: str = "outputs/final_output_with_audio.mp4",
        subtitle_path: Optional[str] = None,
        style: Optional["SubtitleStyle"] = None,  # PATCH: new optional style hook
    ) -> str:
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio not found: {audio_path}")

        out_dir = Path(final_output_path).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        ffmpeg_cmd = FFmpegManager.resolve_ffmpeg_bin()
        cmd = [ffmpeg_cmd, "-y", "-i", video_path, "-i", audio_path]

        if subtitle_path and os.path.exists(subtitle_path):
            normalized = os.path.abspath(subtitle_path).replace("\\", "/")
            escaped = normalized.replace(":", r"\:")

            # PATCH: append force_style if a SubtitleStyle was provided. Falls
            # back to libass defaults if style is None, so existing calls
            # without this argument keep working unchanged.
            vf_filter = f"subtitles=filename='{escaped}'"
            if style is not None:
                # force_style's own commas/colons must NOT be escaped the same
                # way as the path — it's a separate sub-argument, appended
                # after the filename clause with its own colon delimiter.
                vf_filter += f":force_style='{style.to_force_style()}'"

            cmd.extend(
                [
                    "-vf",
                    vf_filter,
                    "-c:v",
                    "libx264",
                    "-crf",
                    "18",
                    "-preset",
                    "fast",
                    "-pix_fmt",
                    "yuv420p",
                ]
            )
            logger.info(
                "Burning subtitles from: %s (style=%s)",
                subtitle_path,
                "custom" if style else "default",
            )
        else:
            cmd.extend(["-c:v", "copy"])
            reason = (
                "subtitle_path was None/empty"
                if not subtitle_path
                else f"file not found: {subtitle_path}"
            )
            logger.warning(
                "Skipping subtitle burn-in (%s) — output will have NO captions.", reason
            )

        cmd.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-shortest",
                final_output_path,
            ]
        )

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"Final audio/video/subtitle burn failed: {result.stderr.strip()}"
            )

        if subtitle_path and result.stderr and "error" in result.stderr.lower():
            logger.warning(
                "FFmpeg reported a possible subtitle issue despite exit 0:\n%s",
                result.stderr[-800:],
            )

        print(f"✅ Final combined video with burned subtitles: {final_output_path}")
        return final_output_path


# =============================================================================
# PIPELINE FACADE & ORCHESTRATOR
# =============================================================================


class TTSPipelineManager:
    """Facade orchestrating TTS execution, pause inspections, and final asset assembly."""

    def __init__(self, output_audio_dir: Path = Path("data/outputs/audio")):
        self.tts_client = IrodoriTTSClient(output_dir=output_audio_dir)
        self.audio_processor = AudioProcessor(output_dir=output_audio_dir)
        self.video_processor = VideoProcessor()

    async def get_speech(self, text: str) -> str:
        return await self.tts_client.generate_speech(text)

    def analyze_pauses(
        self,
        wav_path: str,
        silence_threshold: int = 500,
        min_pause_duration: float = 0.2,
    ) -> Dict[str, Any]:
        return self.audio_processor.analyze_pauses(
            wav_path, silence_threshold, min_pause_duration
        )

    def concatenate_audio(
        self,
        audio_paths: List[str],
        final_output_path: str = "outputs/master_narration.wav",
    ) -> str:
        return self.audio_processor.concatenate_files(audio_paths, final_output_path)

    def assemble_final_deliverable(
        self,
        video_segment_paths: List[str],
        segment_has_narration: List[bool],
        segment_durations: List[float],
        segment_narration_audio: List[Optional[str]],
        output_dir: str = "outputs",
        style: Optional["SubtitleStyle"] = None,
    ) -> Dict[str, str]:
        """Executes the 3-step compilation of video segments and master audio tracks."""
        if not (
            len(video_segment_paths)
            == len(segment_has_narration)
            == len(segment_durations)
            == len(segment_narration_audio)
        ):
            raise ValueError(
                "video_segment_paths, segment_has_narration, segment_durations, and "
                "segment_narration_audio must all be the same length."
            )

        ref_sample_rate, ref_channels = AudioProcessor._detect_reference_audio_format(
            segment_narration_audio
        )

        normalized_paths = [
            self.video_processor.normalize_segment_audio(
                path,
                has_narration=has_narr,
                sample_rate=ref_sample_rate,
                channels=ref_channels,
            )
            for path, has_narr in zip(video_segment_paths, segment_has_narration)
        ]

        full_video_path = self.video_processor.concatenate_segments(
            normalized_paths,
            final_output_path=f"{output_dir}/final_navigation_video.mp4",
        )

        full_audio_path = self.audio_processor.build_full_narration_master(
            segment_durations=segment_durations,
            segment_narration_audio=segment_narration_audio,
            final_output_path=f"{output_dir}/master_full_timeline_audio.wav",
        )

        final_combined_path = self.video_processor.combine_video_and_audio(
            video_path=full_video_path,
            audio_path=full_audio_path,
            final_output_path=f"{output_dir}/final_output_with_audio.mp4",
            style=style,
        )

        return {
            "full_video_path": full_video_path,
            "full_audio_path": full_audio_path,
            "final_combined_path": final_combined_path,
        }


# =============================================================================
# BACKWARDS-COMPATIBLE MODULE-LEVEL FUNCTIONS (FACADE WRAPPERS)
# =============================================================================

_default_manager = TTSPipelineManager()


async def get_irodori_speech(text: str) -> str:
    return await _default_manager.get_speech(text)


def analyze_wav_pauses(
    wav_path: str, silence_threshold: int = 500, min_pause_duration: float = 0.2
) -> dict:
    return _default_manager.analyze_pauses(
        wav_path, silence_threshold, min_pause_duration
    )


def concatenate_audio_files(
    audio_paths: list[str], final_output_path: str = "outputs/master_narration.wav"
) -> str:
    return _default_manager.concatenate_audio(audio_paths, final_output_path)


def resolve_ffmpeg_bin() -> str:
    return FFmpegManager.resolve_ffmpeg_bin()


def get_audio_format(path: str) -> tuple[int, int]:
    return FFmpegManager.get_audio_format(path)


def assemble_final_deliverable(
    video_segment_paths: List[str],
    segment_has_narration: List[bool],
    segment_durations: List[float],
    segment_narration_audio: List[Optional[str]],
    output_dir: str = "outputs",
    subtitle_path: Optional[str] = None,  # <-- Added parameter
    style: Optional["SubtitleStyle"] = None,  # <-- Added parameter
) -> Dict[str, str]:
    """Executes the 3-step compilation of video segments and master audio tracks."""
    if not (
        len(video_segment_paths)
        == len(segment_has_narration)
        == len(segment_durations)
        == len(segment_narration_audio)
    ):
        raise ValueError(
            "video_segment_paths, segment_has_narration, segment_durations, and "
            "segment_narration_audio must all be the same length."
        )

    ref_sample_rate, ref_channels = AudioProcessor._detect_reference_audio_format(
        segment_narration_audio
    )

    segment_audio_temp_dir = str(Path(output_dir) / "tmp_segment_audio")

    normalized_paths = [
        _default_manager.video_processor.normalize_segment_audio(
            path,
            has_narration=has_narr,
            sample_rate=ref_sample_rate,
            channels=ref_channels,
            temp_dir=segment_audio_temp_dir,
        )
        for path, has_narr in zip(video_segment_paths, segment_has_narration)
    ]

    full_video_path = _default_manager.video_processor.concatenate_segments(
        normalized_paths, final_output_path=f"{output_dir}/final_navigation_video.mp4"
    )

    full_audio_path = _default_manager.audio_processor.build_full_narration_master(
        segment_durations=segment_durations,
        segment_narration_audio=segment_narration_audio,
        final_output_path=f"{output_dir}/master_full_timeline_audio.wav",
    )

    # Pass the subtitle path into combine_video_and_audio so FFmpeg burns it
    final_combined_path = _default_manager.video_processor.combine_video_and_audio(
        video_path=full_video_path,
        audio_path=full_audio_path,
        final_output_path=f"{output_dir}/final_output_with_audio.mp4",
        subtitle_path=subtitle_path,
        style=style,  # PATCH
    )

    # HYGIENE: clean up temp files
    temp_dir_path = Path(segment_audio_temp_dir)
    if temp_dir_path.exists():
        for leftover in temp_dir_path.glob("*_padded.mp4"):
            try:
                leftover.unlink()
            except OSError:
                pass
        try:
            temp_dir_path.rmdir()
        except OSError:
            pass

    return {
        "full_video_path": full_video_path,
        "full_audio_path": full_audio_path,
        "final_combined_path": final_combined_path,
    }


class TTSService:
    """Backwards-compatibility facade wrapper for legacy tests."""

    def __init__(
        self,
        audio_dir: Optional[Path | str] = None,
        output_dir: Optional[Path | str] = None,
        *args,
        **kwargs,
    ):
        audio_path = Path(audio_dir) if audio_dir else Path("data/outputs/audio")
        self.manager = TTSPipelineManager(output_audio_dir=audio_path, *args, **kwargs)

    async def get_speech(self, text: str) -> str:
        return await self.manager.get_speech(text)

    def analyze_pauses(
        self,
        wav_path: str,
        silence_threshold: int = 500,
        min_pause_duration: float = 0.2,
    ) -> dict:
        return self.manager.analyze_pauses(
            wav_path, silence_threshold, min_pause_duration
        )

    def concatenate_audio(
        self,
        audio_paths: list[str],
        final_output_path: str = "outputs/master_narration.wav",
    ) -> str:
        return self.manager.concatenate_audio(audio_paths, final_output_path)
