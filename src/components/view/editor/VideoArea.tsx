import {
  Film,
  Play,
  SkipBack,
  SkipForward,
  Volume2,
  Maximize,
  Settings2,
  PictureInPicture,
} from "lucide-react";
import { useUI } from "../../../hooks/useUI";
import { useRef, useState } from "react";

export function VideoArea() {
  const { showVideoPanel } = useUI();
  const videoRef = useRef<HTMLVideoElement>(null);

  // This will hold the path to the final rendered video from Rust later
  const [videoSource, setVideoSource] = useState<string | null>(null);

  if (!showVideoPanel) return null;

  const toggleFullscreen = () => {
    if (videoRef.current) {
      if (document.fullscreenElement) {
        document.exitFullscreen();
      } else {
        videoRef.current.requestFullscreen();
      }
    }
  };

  const togglePiP = async () => {
    if (videoRef.current) {
      try {
        if (document.pictureInPictureElement) {
          await document.exitPictureInPicture();
        } else {
          await videoRef.current.requestPictureInPicture();
        }
      } catch (error) {
        console.error("PiP failed:", error);
      }
    }
  };

  return (
    <div className="h-56 border-t border-zinc-200 dark:border-white/5 bg-white dark:bg-zinc-950 flex flex-col relative z-10 transition-colors">
      {/* Top Section: Video Viewport */}
      <div className="flex-1 flex items-center justify-center relative overflow-hidden">
        {" "}
        {!videoSource ? (
          <p className="text-sm font-medium text-zinc-500">
            Engine: Waiting for render...
          </p>
        ) : (
          <video
            ref={videoRef}
            src={videoSource}
            className="w-full h-full object-contain"
            controls={false} // We will use our custom controls below
          />
        )}
      </div>

      {/* Bottom Section: Media Controls */}
      <div className="w-full px-6 pb-5 pt-2">
        {/* Scrubber Bar */}
        <div className="group cursor-pointer py-2 w-full">
          <div className="h-1.5 w-full bg-zinc-200 dark:bg-zinc-800/80 rounded-full overflow-hidden flex items-center border border-zinc-300 dark:border-white/5 relative transition-colors">
            <div className="absolute left-0 top-0 bottom-0 w-0 bg-zinc-800 dark:bg-zinc-200 rounded-full group-hover:bg-zinc-950 dark:group-hover:bg-white transition-colors" />
          </div>
        </div>

        {/* Controls Row */}
        <div className="flex items-center justify-between mt-2">
          <div className="flex flex-col justify-center gap-1 w-1/3">
            <div className="flex items-center gap-1.5 text-[10px] font-bold text-zinc-500 uppercase tracking-widest">
              <Film className="w-3 h-3" />
              <span>Preview</span>
            </div>
            <div className="text-[11px] font-mono font-medium text-zinc-600 dark:text-zinc-400 whitespace-nowrap">
              00:00:00 / 00:00:00
            </div>
          </div>

          <div className="flex items-center justify-center gap-6 w-1/3 text-zinc-500 dark:text-zinc-400">
            <button className="hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors">
              <SkipBack className="w-4 h-4 fill-current" />
            </button>
            <button
              onClick={() => {
                if (videoRef.current) {
                  videoRef.current.paused
                    ? videoRef.current.play()
                    : videoRef.current.pause();
                }
              }}
              className="w-10 h-10 rounded-full bg-zinc-900 dark:bg-zinc-200 text-white dark:text-zinc-950 flex items-center justify-center hover:scale-105 active:scale-95 transition-all shadow-lg"
            >
              <Play className="w-5 h-5 ml-0.5 fill-current" />
            </button>
            <button className="hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors">
              <SkipForward className="w-4 h-4 fill-current" />
            </button>
          </div>

          <div className="flex items-center justify-end gap-4 w-1/3 text-zinc-500 dark:text-zinc-400">
            <button className="hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors">
              <Volume2 className="w-4 h-4" />
            </button>
            <button
              onClick={togglePiP}
              className="hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors"
              title="Picture in Picture"
            >
              <PictureInPicture className="w-4 h-4" />
            </button>
            <div className="h-4 w-px bg-zinc-300 dark:bg-zinc-700/50 mx-1" />
            <button
              onClick={toggleFullscreen}
              className="hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors"
              title="Fullscreen"
            >
              <Maximize className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
