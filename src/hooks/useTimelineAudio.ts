import { useEffect, useRef, useState, useMemo } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { TimelineData, TimelineTrack, ClipData } from "../types";

export interface UseTimelineAudioOptions {
  timeline: TimelineData;
  currentTime: number;
  isPlaying: boolean;
  isScrubbing?: boolean;
}

export interface UseTimelineAudioResult {
  isDuckingActive: boolean;
  duckingFactor: number;
  activeAudioClipsCount: number;
}

/**
 * useTimelineAudio: Professional Web Audio / HTMLAudio synchronization and mixing engine.
 * - Plays audio clips accurately aligned with playhead `currentTime` and `isPlaying`.
 * - Calculates fade-in and fade-out volume envelopes.
 * - Auto-Ducking: Dynamically attenuates music/BGM tracks when voice/narration clips are active,
 *   featuring smooth 300ms attack and 400ms release ramps.
 */
export function useTimelineAudio({
  timeline,
  currentTime,
  isPlaying,
  isScrubbing = false,
}: UseTimelineAudioOptions): UseTimelineAudioResult {
  const audioElementsRef = useRef<Map<string, HTMLAudioElement>>(new Map());
  const [isDuckingActive, setIsDuckingActive] = useState(false);
  const [currentDuckingFactor, setCurrentDuckingFactor] = useState(1.0);

  // Map tracks by ID for fast lookup
  const trackMap = useMemo(() => {
    const map = new Map<string, TimelineTrack>();
    timeline.tracks.forEach((t) => map.set(t.id, t));
    return map;
  }, [timeline.tracks]);

  // Audio clips list
  const audioClips: ClipData[] = useMemo(() => {
    return timeline.clips.filter(
      (c) => c.type === "audio" && Boolean(c.source),
    );
  }, [timeline.clips]);

  // Identify Voice clips for Auto-Ducking
  const voiceClips = useMemo(() => {
    return audioClips.filter((c) => {
      const track = trackMap.get(c.trackId);
      if (!track) return false;
      const isVoiceTrack =
        track.audioRole === "voice" ||
        track.id === "track-audio-1" ||
        track.name.toLowerCase().includes("voice") ||
        track.name.toLowerCase().includes("narration") ||
        track.name.toLowerCase().includes("dialogue");
      const isVoiceClip = c.audioRole === "voice";
      return (isVoiceTrack || isVoiceClip) && !track.isMuted && !c.isMuted;
    });
  }, [audioClips, trackMap]);

  // Compute live ducking factor with smooth attack (0.3s) and release (0.4s) ramps
  const { duckingFactor, duckingActive } = useMemo(() => {
    if (voiceClips.length === 0) {
      return { duckingFactor: 1.0, duckingActive: false };
    }

    const ATTACK_SECS = 0.3;
    const RELEASE_SECS = 0.4;
    let minFactor = 1.0;
    let anyVoicePlaying = false;

    for (const vClip of voiceClips) {
      const start = vClip.startTime;
      const end = vClip.startTime + vClip.duration;
      const targetDuck = 0.25; // Standard -12dB attenuation

      if (currentTime >= start && currentTime <= end) {
        minFactor = Math.min(minFactor, targetDuck);
        anyVoicePlaying = true;
      } else if (
        currentTime >= start - ATTACK_SECS &&
        currentTime < start
      ) {
        // Attack phase: smoothly ramp down from 1.0 to targetDuck
        const progress = (currentTime - (start - ATTACK_SECS)) / ATTACK_SECS;
        const factor = 1.0 - progress * (1.0 - targetDuck);
        minFactor = Math.min(minFactor, factor);
        anyVoicePlaying = true;
      } else if (currentTime > end && currentTime <= end + RELEASE_SECS) {
        // Release phase: smoothly ramp up from targetDuck to 1.0
        const progress = (currentTime - end) / RELEASE_SECS;
        const factor = targetDuck + progress * (1.0 - targetDuck);
        minFactor = Math.min(minFactor, factor);
        anyVoicePlaying = true;
      }
    }

    return { duckingFactor: minFactor, duckingActive: anyVoicePlaying };
  }, [voiceClips, currentTime]);

  useEffect(() => {
    setIsDuckingActive(duckingActive);
    setCurrentDuckingFactor(duckingFactor);
  }, [duckingActive, duckingFactor]);

  // Manage HTMLAudioElement lifecycle for audio clips
  useEffect(() => {
    const audioMap = audioElementsRef.current;
    const currentClipIds = new Set(audioClips.map((c) => c.id));

    // Remove deleted clips
    for (const [clipId, audio] of audioMap.entries()) {
      if (!currentClipIds.has(clipId)) {
        audio.pause();
        audio.src = "";
        audioMap.delete(clipId);
      }
    }

    // Instantiate or update audio elements
    audioClips.forEach((clip) => {
      if (!clip.source) return;
      const safeUrl = convertFileSrc(clip.source);
      let audio = audioMap.get(clip.id);

      if (!audio) {
        audio = new Audio();
        audio.preload = "auto";
        audio.crossOrigin = "anonymous";
        audioMap.set(clip.id, audio);
      }

      if (audio.src !== safeUrl && safeUrl) {
        audio.src = safeUrl;
      }
    });
  }, [audioClips]);

  // Clean up all audio elements on unmount
  useEffect(() => {
    return () => {
      audioElementsRef.current.forEach((audio) => {
        audio.pause();
        audio.src = "";
      });
      audioElementsRef.current.clear();
    };
  }, []);

  // Main synchronization and volume mixing loop
  useEffect(() => {
    const audioMap = audioElementsRef.current;
    let activeCount = 0;

    audioClips.forEach((clip) => {
      const audio = audioMap.get(clip.id);
      if (!audio) return;

      const track = trackMap.get(clip.trackId);
      const isClipActive =
        currentTime >= clip.startTime &&
        currentTime < clip.startTime + clip.duration;

      // If track is hidden or invalid, treat as inactive
      if (!track || track.isHidden) {
        if (!audio.paused) audio.pause();
        return;
      }

      if (isClipActive) {
        activeCount++;

        // 1. Base gain from clip and track volume settings
        const clipVol = clip.volume !== undefined ? clip.volume : 1.0;
        const trackVol = track.volume !== undefined ? track.volume : 1.0;
        const isMuted = Boolean(track.isMuted || clip.isMuted);

        // 2. Fade envelope calculation
        let fadeFactor = 1.0;
        const clipElapsed = currentTime - clip.startTime;
        const clipRemaining = clip.startTime + clip.duration - currentTime;

        if (clip.fadeIn && clip.fadeIn > 0 && clipElapsed < clip.fadeIn) {
          fadeFactor = Math.min(fadeFactor, Math.max(0, clipElapsed / clip.fadeIn));
        }
        if (
          clip.fadeOut &&
          clip.fadeOut > 0 &&
          clipRemaining < clip.fadeOut
        ) {
          fadeFactor = Math.min(
            fadeFactor,
            Math.max(0, clipRemaining / clip.fadeOut),
          );
        }

        // 3. Auto-Ducking attenuation
        const isDuckable =
          track.duckingEnabled ||
          clip.ducking ||
          track.audioRole === "music" ||
          clip.audioRole === "music" ||
          track.id === "track-audio-2" ||
          track.name.toLowerCase().includes("music") ||
          track.name.toLowerCase().includes("bgm");

        const clipDuckAmount =
          clip.duckingAmount ?? track.duckingAmount ?? 0.25;
        let appliedDucking = 1.0;

        if (isDuckable && duckingActive) {
          // Interpolate between 1.0 and user-configured duckingAmount using calculated duckingFactor
          const normalizedProgress = (1.0 - duckingFactor) / (1.0 - 0.25); // 0 -> 1
          appliedDucking = 1.0 - normalizedProgress * (1.0 - clipDuckAmount);
        }

        // 4. Compute final effective gain and clamp to [0, 1]
        const effectiveGain = isMuted
          ? 0
          : Math.max(0, Math.min(1, clipVol * trackVol * fadeFactor * appliedDucking));

        audio.volume = effectiveGain;

        // 5. Align audio timeline position
        const desiredAudioTime = Math.max(
          0,
          clipElapsed + (clip.sourceOffset || 0),
        );

        if (isPlaying && !isScrubbing) {
          // Re-sync if playhead drift exceeds 120ms
          if (Math.abs(audio.currentTime - desiredAudioTime) > 0.12) {
            audio.currentTime = desiredAudioTime;
          }
          if (audio.paused) {
            audio.play().catch(() => {});
          }
        } else {
          // Scrubbing or paused
          if (!audio.paused) {
            audio.pause();
          }
          if (Math.abs(audio.currentTime - desiredAudioTime) > 0.05) {
            audio.currentTime = desiredAudioTime;
          }
        }
      } else {
        // Clip is not active at this playhead position
        if (!audio.paused) {
          audio.pause();
        }
      }
    });
  }, [
    audioClips,
    trackMap,
    currentTime,
    isPlaying,
    isScrubbing,
    duckingActive,
    duckingFactor,
  ]);

  return {
    isDuckingActive,
    duckingFactor: currentDuckingFactor,
    activeAudioClipsCount: audioClips.filter(
      (c) =>
        currentTime >= c.startTime &&
        currentTime < c.startTime + c.duration,
    ).length,
  };
}
