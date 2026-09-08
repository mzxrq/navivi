"""Step 5: Burn SRT subtitles permanently onto the finished video files."""

from pathlib import Path

from services.logger.progress import tracker
from services.vdoprocessing.vdoexporter import VideoExporter

from .helpers import logger


def burn_subtitles(
    video_paths: list[str], subtitle_paths: list[str], output_dir: str
) -> list[str]:
    """Step 5: Permanently burns SRT subtitles onto the finished video files."""
    logger.info("Step 5: Burning subtitles into %d video(s).", len(video_paths))

    final_videos = []

    # [NOTE] [Subtitle] Matches subtitle_paths[idx] to video_paths[idx] purely by list position — the two lists must stay in the same order upstream or subtitles land on the wrong clip.
    for idx, video_path in enumerate(video_paths):
        original_file = Path(video_path)

        if idx < len(subtitle_paths) and subtitle_paths[idx]:
            sub_path = subtitle_paths[idx]
            subtitled_output = str(
                Path(output_dir)
                / f"{original_file.stem}_subtitled{original_file.suffix}"
            )

            tracker.show(
                f"Burning subtitle {idx + 1}/{len(video_paths)}: {original_file.name}"
            )

            logger.info(
                "Step 5: [%d/%d] Burning subtitles onto '%s'.",
                idx + 1,
                len(video_paths),
                original_file.name,
            )
            try:
                result = VideoExporter.burn_subtitles(
                    input_video_path=video_path,
                    subtitle_file_path=sub_path,
                    output_video_path=subtitled_output,
                )
                final_videos.append(result)
            except Exception as e:
                logger.error(
                    "Step 5: [%d/%d] Failed to burn subtitle for '%s': %s",
                    idx + 1,
                    len(video_paths),
                    original_file.name,
                    e,
                )
                final_videos.append(video_path)
        else:
            tracker.show(
                f"Passing through video {idx + 1}/{len(video_paths)}: {original_file.name}"
            )

            logger.info(
                "Step 5: [%d/%d] No subtitle file for '%s' — passing through unchanged.",
                idx + 1,
                len(video_paths),
                original_file.name,
            )
            final_videos.append(video_path)

    tracker.clear()
    logger.info("Step 5 complete: %d video(s) processed.", len(final_videos))
    return final_videos
