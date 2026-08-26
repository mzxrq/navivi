"""
TTS Pipeline Manager (tts.py)
---------------------------------------------------------------------------
TTS pipeline orchestrator and facade.
Imports core media processing classes from tts_engine.py.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, List, Dict, Any

from services.tts_engine import (
    FFmpegManager,
    IrodoriTTSClient,
    AudioProcessor,
    VideoProcessor,
)
from services.subtitle import SubtitleStyle
from services.logger import setup_logger

# Logging configuration
logger = setup_logger("TTSPipelineManager")


# [Core] TTSPipelineManager Class
class TTSPipelineManager:
    """Facade orchestrating TTS execution, pause inspections, and final asset assembly."""

    # [Config] Initialize with optional output directory for audio files
    def __init__(self, output_audio_dir: Path = Path("data/outputs/audio")):
        self.tts_client = IrodoriTTSClient(output_dir=output_audio_dir)
        self.audio_processor = AudioProcessor(output_dir=output_audio_dir)
        self.video_processor = VideoProcessor()

    # [TTS] Generates speech from text using the Irodori TTS client
    async def get_speech(self, text: str) -> str:
        return await self.tts_client.generate_speech(text)

    # [TTS/Util] Analyzes a WAV file for pauses based on silence threshold and minimum pause duration
    def analyze_pauses(
        self,
        wav_path: str,
        silence_threshold: int = 500,
        min_pause_duration: float = 0.2,
    ) -> Dict[str, Any]:
        return self.audio_processor.analyze_pauses(
            wav_path, silence_threshold, min_pause_duration
        )

    # [TTS/Util] Concatenates multiple audio files into a single output file
    def concatenate_audio(
        self,
        audio_paths: List[str],
        final_output_path: str = "outputs/master_narration.wav",
    ) -> str:
        return self.audio_processor.concatenate_files(audio_paths, final_output_path)

    # [TTS/Animation] Assembles the final deliverable by combining video segments and audio tracks
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


# [Config] Default TTSPipelineManager instance for convenience
_default_manager = TTSPipelineManager()


# [TTS/Util] Convenience functions for external use without needing to instantiate TTSPipelineManager
async def get_irodori_speech(text: str) -> str:
    return await _default_manager.get_speech(text)


# [TTS/Util] Convenience function to analyze pauses in a WAV file
def analyze_wav_pauses(
    wav_path: str, silence_threshold: int = 500, min_pause_duration: float = 0.2
) -> dict:
    return _default_manager.analyze_pauses(
        wav_path, silence_threshold, min_pause_duration
    )


# [TTS/Util] Convenience function to concatenate multiple audio files into one
def concatenate_audio_files(
    audio_paths: list[str], final_output_path: str = "outputs/master_narration.wav"
) -> str:
    return _default_manager.concatenate_audio(audio_paths, final_output_path)


# [Validate] Convenience function to assemble the final deliverable
def resolve_ffmpeg_bin() -> str:
    return FFmpegManager.resolve_ffmpeg_bin()


# [TTS/Util] Convenience function to get audio format (sample rate and channels) from a file
def get_audio_format(path: str) -> tuple[int, int]:
    return FFmpegManager.get_audio_format(path)


# [TTS/Animation] Convenience function to assemble the final deliverable
def assemble_final_deliverable(
    video_segment_paths: List[str],
    segment_has_narration: List[bool],
    segment_durations: List[float],
    segment_narration_audio: List[Optional[str]],
    output_dir: str = "outputs",
    subtitle_path: Optional[str] = None,
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

    correct_audio_path = str(
        Path(output_dir).parent / "audio" / "master_full_timeline_audio.wav"
    )

    full_audio_path = _default_manager.audio_processor.build_full_narration_master(
        segment_durations=segment_durations,
        segment_narration_audio=segment_narration_audio,
        final_output_path=correct_audio_path,
    )

    # Pass the subtitle path into combine_video_and_audio so FFmpeg burns it
    final_combined_path = _default_manager.video_processor.combine_video_and_audio(
        video_path=full_video_path,
        audio_path=full_audio_path,
        final_output_path=f"{output_dir}/final_output_with_audio.mp4",
        subtitle_path=subtitle_path,
        style=style,
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


# [Core] TTSService Class for use in legacy tests and external scripts
class TTSService:
    """Backwards-compatibility facade wrapper for legacy tests."""

    # [Config] Initialize with optional audio and output directories
    def __init__(
        self,
        audio_dir: Optional[Path | str] = None,
        output_dir: Optional[Path | str] = None,
        *args,
        **kwargs,
    ):
        audio_path = Path(audio_dir) if audio_dir else Path("data/outputs/audio")
        self.manager = TTSPipelineManager(output_audio_dir=audio_path, *args, **kwargs)

    # [TTS] Generates speech from text using the Irodori TTS client
    async def get_speech(self, text: str) -> str:
        return await self.manager.get_speech(text)

    # [TTS/Util] Analyzes a WAV file for pauses based on silence threshold and minimum pause duration
    def analyze_pauses(
        self,
        wav_path: str,
        silence_threshold: int = 500,
        min_pause_duration: float = 0.2,
    ) -> dict:
        return self.manager.analyze_pauses(
            wav_path, silence_threshold, min_pause_duration
        )

    # [TTS/Util] Concatenates multiple audio files into a single output file
    def concatenate_audio(
        self,
        audio_paths: list[str],
        final_output_path: str = "outputs/master_narration.wav",
    ) -> str:
        return self.manager.concatenate_audio(audio_paths, final_output_path)
