"""
videoeditor.py (OOP)
---------------------------------------------------------------------------
Handles the concatenation and merging of video and audio files using FFmpeg.
Integrates with the JobConfigManager to automatically route outputs to the 
correct centralized assets directories.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Final, List, Optional

from services.job_config import JobConfigManager

logger = logging.getLogger(__name__)

# =============================================================================
# FFMPEG EXECUTION ENGINE
# =============================================================================

class FFmpegEngine:
    """Manages the discovery and execution of the FFmpeg binary."""

    FFMPEG_BIN: Final[Path] = (
        Path(__file__).resolve().parent.parent / "bin" / "FFmpeg" / "bin" / "ffmpeg.exe"
    )
    TIMEOUT_SECONDS: Final[int] = 300  # 5 minutes should be plenty for stream copying

    def __init__(self, binary_path: Optional[Path] = None):
        self.binary_path = binary_path if binary_path else self.FFMPEG_BIN

    def resolve_binary(self) -> str:
        """Locates the bundled FFmpeg binary or falls back to system PATH."""
        if self.binary_path.exists():
            return str(self.binary_path)

        system_binary = shutil.which("ffmpeg")
        if system_binary is None:
            raise FileNotFoundError(
                f"FFmpeg not found. Expected bundled binary at '{self.binary_path}' or a PATH install."
            )
        return system_binary

    def run_command(self, cmd: List[str]) -> None:
        """Executes a subprocess command securely with timeout handling."""
        logger.info("Executing FFmpeg command: %s", " ".join(cmd))
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"FFmpeg process timed out after {self.TIMEOUT_SECONDS}s.") from exc

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed (exit {result.returncode}):\n{result.stderr.strip()}")


# =============================================================================
# FILE SYSTEM & MANIFEST MANAGER
# =============================================================================

class ConcatListManager:
    """Handles the creation and cleanup of FFmpeg concat demuxer manifest files."""

    @staticmethod
    def create_manifest(input_paths: List[str]) -> Path:
        """
        Creates a temporary text file listing the inputs for FFmpeg's concat demuxer.
        Format requires: file 'absolute/path/to/file.mp4'
        """
        if not input_paths:
            raise ValueError("Input paths list cannot be empty.")

        # Create a temp file that won't be deleted immediately upon closing
        fd, temp_path_str = tempfile.mkstemp(suffix=".txt", prefix="ffmpeg_concat_")
        temp_path = Path(temp_path_str)
        
        with open(fd, 'w', encoding='utf-8') as f:
            for path in input_paths:
                clean_path = Path(path).resolve()
                if not clean_path.exists():
                    raise FileNotFoundError(f"Cannot concatenate missing file: {clean_path}")
                
                # FFmpeg requires single quotes around the path, and escaping internal single quotes
                safe_path = str(clean_path).replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")
                
        return temp_path

    @staticmethod
    def cleanup_manifest(manifest_path: Path) -> None:
        """Safely removes the temporary manifest file."""
        if manifest_path.exists():
            try:
                manifest_path.unlink()
            except OSError as e:
                logger.warning(f"Failed to clean up temporary manifest {manifest_path}: {e}")


# =============================================================================
# FACADE & ORCHESTRATOR
# =============================================================================

class VideoEditor:
    """High-level API for editing, combining, and exporting media files."""

    def __init__(self, job_config=None):
        self.config = job_config or JobConfigManager()
        self.engine = FFmpegEngine()

    def _resolve_output_path(self, filename: str, subfolder: str) -> Path:
        """Dynamically routes outputs to the centralized assets directory."""
        base_path = Path(self.config.get("directory_path", "assets"))
        target_dir = (base_path / subfolder).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / filename

    def concatenate_media(self, input_paths: List[str], output_filename: str, media_type: str = "video") -> str:
        """
        Concatenates multiple media files (audio or video) sequentially.
        Note: Files must share the same codecs, resolutions, and framerates 
        for a safe stream copy.
        """
        if len(input_paths) < 2:
            raise ValueError("At least two files are required for concatenation.")

        # Determine subfolder based on media type (e.g., assets/video vs assets/audio)
        subfolder = "video" if media_type.lower() == "video" else "audio"
        output_path = self._resolve_output_path(output_filename, subfolder)
        
        # If output file already exists, remove it to prevent FFmpeg prompt hangs
        if output_path.exists():
            output_path.unlink()

        ffmpeg_cmd = self.engine.resolve_binary()
        manifest_path = None

        try:
            # 1. Build the list.txt manifest
            manifest_path = ConcatListManager.create_manifest(input_paths)

            # 2. Build the command: -f concat -safe 0 -i manifest.txt -c copy output.mp4
            cmd = [
                ffmpeg_cmd,
                "-y",                   # Overwrite output
                "-f", "concat",         # Use the concat demuxer
                "-safe", "0",           # Allow absolute paths in the text file
                "-i", str(manifest_path),
                "-c", "copy",           # Stream copy (no re-encoding, extremely fast)
                str(output_path)
            ]

            # 3. Execute
            self.engine.run_command(cmd)
            logger.info("Successfully concatenated %d %s files into: %s", len(input_paths), media_type, output_path)

        finally:
            # 4. Ensure cleanup happens even if FFmpeg throws an error
            if manifest_path:
                ConcatListManager.cleanup_manifest(manifest_path)

        return str(output_path)

    # --- Convenience Wrappers ---

    def concatenate_videos(self, input_paths: List[str], output_filename: str) -> str:
        """Joins multiple video clips (e.g., .mp4) together."""
        return self.concatenate_media(input_paths, output_filename, media_type="video")

    def concatenate_audios(self, input_paths: List[str], output_filename: str) -> str:
        """Joins multiple audio files (e.g., .mp3, .wav) together."""
        return self.concatenate_media(input_paths, output_filename, media_type="audio")

    def mux_audio_to_video(self, video_path: str, audio_path: str, output_filename: str) -> str:
        """
        Merges an audio track into a video segment, pinning sample rates 
        and channels to prevent pitch-shifting or desync issues.
        """
        vid_p = Path(video_path)
        aud_p = Path(audio_path)
        
        if not vid_p.exists():
            raise FileNotFoundError(f"Video file not found for muxing: {vid_p}")
        if not aud_p.exists():
            raise FileNotFoundError(f"Audio file not found for muxing: {aud_p}")

        output_path = self._resolve_output_path(output_filename, "video")
        if output_path.exists():
            output_path.unlink()

        ffmpeg_cmd = self.engine.resolve_binary()

        # Query source audio format to lock down -ar and -ac (prevents chipmunk bugs)
        probe_cmd = [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,channels", 
            "-of", "default=noprint_wrappers=1:nokey=1", str(aud_p)
        ]
        try:
            probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=5)
            lines = probe_res.stdout.strip().splitlines()
            src_rate = lines[0] if len(lines) > 0 else "44100"
            src_channels = lines[1] if len(lines) > 1 else "2"
        except Exception:
            src_rate, src_channels = "44100", "2"

        cmd = [
            ffmpeg_cmd, "-y", 
            "-i", str(vid_p), 
            "-i", str(aud_p),
            "-c:v", "copy", 
            "-c:a", "aac", 
            "-ar", str(src_rate), 
            "-ac", str(src_channels),
            "-map", "0:v:0", 
            "-map", "1:a:0",
            "-shortest", 
            str(output_path)
        ]

        self.engine.run_command(cmd)
        logger.info("Successfully muxed audio into video: %s", output_path)
        return str(output_path)