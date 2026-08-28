"""
Video Editor Service (vdoeditor.py)
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
from services.logger import setup_logger

# Logging configuration
logger = setup_logger("VideoEditor")


# [Core] FFmpegEngine : Manages discovery and execution of the FFmpeg binary.
class FFmpegEngine:
    """Manages the discovery and execution of the FFmpeg binary."""

    # [Config] Default bundled FFmpeg binary path and execution timeout
    FFMPEG_BIN: Final[Path] = (
        Path(__file__).resolve().parent.parent / "bin" / "FFmpeg" / "bin" / "ffmpeg.exe"
    )

    TIMEOUT_SECONDS: Final[int] = 300  # 5 minutes should be plenty for stream copying

    # [Config] Initialize with optional binary path
    def __init__(self, binary_path: Optional[Path] = None):
        self.binary_path = binary_path if binary_path else self.FFMPEG_BIN

    # [Validation] Resolve the FFmpeg binary path, checking both bundled and system PATH
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

    # [Core] Executes a subprocess command securely with timeout handling
    def run_command(self, cmd: List[str]) -> None:
        """Executes a subprocess command securely with timeout handling."""
        logger.info("Executing FFmpeg command: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"FFmpeg process timed out after {self.TIMEOUT_SECONDS}s."
            ) from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg failed (exit {result.returncode}):\n{result.stderr.strip()}"
            )


# [Util] ConcatListManager : Handles creation and cleanup of FFmpeg concat demuxer manifest files.
class ConcatListManager:
    """Handles the creation and cleanup of FFmpeg concat demuxer manifest files."""

    # [Util/IO] Creates a temporary text file listing the inputs for FFmpeg's concat demuxer
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

        with open(fd, "w", encoding="utf-8") as f:
            for path in input_paths:
                clean_path = Path(path).resolve()
                if not clean_path.exists():
                    raise FileNotFoundError(
                        f"Cannot concatenate missing file: {clean_path}"
                    )

                # FFmpeg requires single quotes around the path, and escaping internal single quotes
                safe_path = str(clean_path).replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        return temp_path

    # [Util/IO] Cleans up the temporary manifest file after FFmpeg has used it
    @staticmethod
    def cleanup_manifest(manifest_path: Path) -> None:
        """Safely removes the temporary manifest file."""
        if manifest_path.exists():
            try:
                manifest_path.unlink()
            except OSError as e:
                logger.warning(
                    f"Failed to clean up temporary manifest {manifest_path}: {e}"
                )


# [Core] VideoEditor : High-level API for editing, combining, and exporting media files.
class VideoEditor:
    """High-level API for editing, combining, and exporting media files."""

    # [Config] Initialize with optional job configuration and FFmpeg engine
    def __init__(self, job_config=None):
        self.config = job_config or JobConfigManager()
        self.engine = FFmpegEngine()

    # [Validate] Resolves output paths dynamically based on the job configuration and subfolder
    def _resolve_output_path(self, filename: str, subfolder: str) -> Path:
        """Dynamically routes outputs to the centralized assets directory."""
        base_path = Path(self.config.get("directory_path", "assets"))
        target_dir = (base_path / subfolder).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / filename

    # [Core/Util] Concatenates multiple media files (audio or video) sequentially using FFmpeg's concat demuxer.
    def concatenate_media(
        self, input_paths: List[str], output_filename: str, media_type: str = "video"
    ) -> str:
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
                "-y",  # Overwrite output
                "-f",
                "concat",  # Use the concat demuxer
                "-safe",
                "0",  # Allow absolute paths in the text file
                "-i",
                str(manifest_path),
                "-c",
                "copy",  # Stream copy (no re-encoding, extremely fast)
                str(output_path),
            ]

            # 3. Execute
            self.engine.run_command(cmd)
            logger.info(
                "Successfully concatenated %d %s files into: %s",
                len(input_paths),
                media_type,
                output_path,
            )

        finally:
            # 4. Ensure cleanup happens even if FFmpeg throws an error
            if manifest_path:
                ConcatListManager.cleanup_manifest(manifest_path)

        return str(output_path)

    # [Core/Util] Muxes an audio track into a video segment, preserving sample rates and channels to avoid pitch-shifting or desync issues.
    def concatenate_videos(self, input_paths: List[str], output_filename: str) -> str:
        """Joins multiple video clips (e.g., .mp4) together."""
        return self.concatenate_media(input_paths, output_filename, media_type="video")

    # [Core/Util] Muxes an audio track into a video segment, preserving sample rates and channels to avoid pitch-shifting or desync issues.
    def concatenate_audios(self, input_paths: List[str], output_filename: str) -> str:
        """Joins multiple audio files (e.g., .mp3, .wav) together."""
        return self.concatenate_media(input_paths, output_filename, media_type="audio")

    # [Core/Util] Muxes an audio track into a video segment, preserving sample rates and channels to avoid pitch-shifting or desync issues.
    def mux_audio_to_video(
        self, video_path: str, audio_path: str, output_filename: str
    ) -> str:
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
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,channels",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(aud_p),
        ]
        try:
            probe_res = subprocess.run(
                probe_cmd, capture_output=True, text=True, timeout=5
            )
            lines = probe_res.stdout.strip().splitlines()
            src_rate = lines[0] if len(lines) > 0 else "44100"
            src_channels = lines[1] if len(lines) > 1 else "2"
        except Exception:
            src_rate, src_channels = "44100", "2"

        cmd = [
            ffmpeg_cmd,
            "-y",
            "-i",
            str(vid_p),
            "-i",
            str(aud_p),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-ar",
            str(src_rate),
            "-ac",
            str(src_channels),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-shortest",
            str(output_path),
        ]

        self.engine.run_command(cmd)
        logger.info("Successfully muxed audio into video: %s", output_path)
        return str(output_path)

    # [Core/Util] Adjusts the playback duration of a video clip to match a target duration, using PTS scaling without frame interpolation.
    def adjust_video_duration(
        self, video_path: str, target_duration: float, output_filename: str
    ) -> str:
        """
        Adjusts the playback duration of a video clip to match a target duration.
        Uses PTS scaling without frame interpolation, which may result in
        """
        vid_p = Path(video_path)
        if not vid_p.exists():
            raise FileNotFoundError(
                f"Video file not found for duration adjust: {vid_p}"
            )

        if target_duration <= 0:
            raise ValueError(
                f"target_duration must be positive, got {target_duration!r}."
            )

        # --- Probe current duration -----------------------------------------
        # Reused as its own ffprobe call (not FFmpegEngine, which only wraps
        # ffmpeg itself) so this method has no dependency on any other
        # module's probing utility — keeps VideoEditor self-contained.
        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(vid_p),
        ]
        try:
            probe_res = subprocess.run(
                probe_cmd, capture_output=True, text=True, timeout=10
            )
            current_duration = float(probe_res.stdout.strip())
        except (subprocess.TimeoutExpired, ValueError) as exc:
            raise RuntimeError(
                f"Could not determine source duration for '{vid_p}' via ffprobe: {exc}"
            ) from exc

        if current_duration <= 0:
            raise RuntimeError(
                f"ffprobe reported non-positive duration for '{vid_p}': {current_duration}"
            )

        # --- Derive the PTS scale factor --------------------------------------
        # setpts=N*PTS yields output_duration = input_duration * N.
        # To go FROM current_duration TO target_duration:
        #   N = target_duration / current_duration
        # (N > 1 -> stretched/slower; N < 1 -> compressed/faster.)
        pts_factor = target_duration / current_duration

        output_path = self._resolve_output_path(output_filename, "video")
        if output_path.exists():
            output_path.unlink()

        ffmpeg_cmd = self.engine.resolve_binary()
        cmd = [
            ffmpeg_cmd,
            "-y",
            "-i",
            str(vid_p),
            "-vf",
            f"setpts={pts_factor:.6f}*PTS",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-an",  # audio deliberately dropped — muxed in later from narration
            str(output_path),
        ]

        self.engine.run_command(cmd)
        logger.info(
            "Adjusted duration of '%s' from %.3fs to %.3fs (pts_factor=%.4f): %s",
            vid_p,
            current_duration,
            target_duration,
            pts_factor,
            output_path,
        )
        return str(output_path)

    # [Core/Util] Stitches an image sequence into an MP4 video using libx264.
    def stitch_images_to_video(
        self,
        images_dir: str,
        output_filename: str,
        fps: int = 30,
        image_pattern: str = "frame_%04d.png",
    ) -> str:
        """
        Stitches a sequence of identically formatted images into a video file.
        Expects images named sequentially (e.g., frame_0000.png, frame_0001.png).
        """
        img_dir_path = Path(images_dir)
        if not img_dir_path.exists():
            raise FileNotFoundError(f"Images directory not found: {img_dir_path}")

        # Route output to the centralized assets/video directory
        output_path = self._resolve_output_path(output_filename, "video")
        if output_path.exists():
            output_path.unlink()

        # Build the FFmpeg input string (e.g., "images/frame_%04d.png")
        input_pattern = str(img_dir_path / image_pattern)
        ffmpeg_cmd = self.engine.resolve_binary()

        cmd = [
            ffmpeg_cmd,
            "-y",
            "-framerate",
            str(fps),
            "-i",
            input_pattern,
            "-c:v",
            "libx264",  # Standard H.264 encoding
            "-pix_fmt",
            "yuv420p",  # Ensures playback compatibility across standard video players
            str(output_path),
        ]

        self.engine.run_command(cmd)
        logger.info(
            "Successfully stitched images from '%s' into video: %s",
            images_dir,
            output_path,
        )
        return str(output_path)
