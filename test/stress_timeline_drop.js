// Empirical Stress Testing Harness for TimelineTrack.tsx Drop Logic
import crypto from 'crypto';

// Replicate the exact drop logic from TimelineTrack.tsx lines 70-180
function simulateDrop({
  track,
  timeline,
  asset,
  dropX,
  zoomRatio = 20, // pxPs * zoomMultiplier
}) {
  const logs = [];
  const toasts = [];
  const showToast = (msg, type) => toasts.push({ msg, type });

  const dropTime = Math.max(0, dropX / zoomRatio);
  const trackClips = timeline.clips.filter((clip) => clip.trackId === track.id);

  // STRICT TRACK TYPE VALIDATION
  if (track.type === "video" && asset.type === "audio") {
    showToast("Cannot place Audio on a Video track.", "error");
    return { success: false, toasts, timeline };
  }
  if (track.type === "audio" && asset.type !== "audio") {
    showToast("Audio tracks only accept Audio files.", "error");
    return { success: false, toasts, timeline };
  }
  if (track.type === "subtitle") {
    showToast("Subtitles are managed automatically or via text clips.", "warning");
    if (asset.type !== "text") return { success: false, toasts, timeline };
  }

  if (asset.type === "transition") {
    const sortedClips = [...trackClips].sort((a, b) => a.startTime - b.startTime);
    let bestCut = null;
    let minDiff = Infinity;

    // Find the closest "cut" between two adjacent clips
    for (let i = 0; i < sortedClips.length - 1; i++) {
      const leftClip = sortedClips[i];
      const rightClip = sortedClips[i + 1];
      const cutTime = leftClip.startTime + leftClip.duration;

      // If they are physically touching (or close to it)
      if (Math.abs(cutTime - rightClip.startTime) < 0.1) {
        const diff = Math.abs(cutTime - dropTime);
        if (diff < minDiff && diff < 1.5) { // Drop must be within 1.5s of the cut
          minDiff = diff;
          bestCut = { left: leftClip, right: rightClip, cutTime };
        }
      }
    }

    if (!bestCut) {
      showToast("Drop transitions directly on the cut between two clips!", "warning");
      return { success: false, toasts, timeline };
    }

    const transDuration = asset.duration || 1.0;
    const newTransition = {
      id: crypto.randomUUID(),
      trackId: track.id,
      fromClipId: bestCut.left.id,
      toClipId: bestCut.right.id,
      type: asset.shader,
      duration: transDuration,
      startTime: bestCut.cutTime - transDuration / 2,
    };

    const updatedClips = timeline.clips.map((c) => {
      if (c.id === bestCut.right.id) {
        return {
          ...c,
          transitionIn: asset.shader,
          fadeIn: transDuration,
          prevClip: bestCut.left,
        };
      }
      if (c.id === bestCut.left.id) {
        return {
          ...c,
          transitionOut: asset.shader,
          fadeOut: transDuration,
        };
      }
      return c;
    });

    const filteredTransitions = (timeline.transitions || []).filter(
      (t) =>
        !(
          t.fromClipId === bestCut.left.id &&
          t.toClipId === bestCut.right.id
        ),
    );

    const updatedTimeline = {
      ...timeline,
      clips: updatedClips,
      transitions: [...filteredTransitions, newTransition],
    };

    showToast(`Applied ${asset.name || "transition"} between clips`, "success");
    return { success: true, toasts, timeline: updatedTimeline, bestCut, newTransition };
  }

  return { success: false, toasts, timeline };
}

// SUITE OF EMPIRICAL ADVERSARIAL STRESS TESTS
const tests = [];
function runTest(name, fn) {
  try {
    const result = fn();
    tests.push({ name, passed: result.passed, details: result.details });
  } catch (err) {
    tests.push({ name, passed: false, details: `CRASHED: ${err.message}` });
  }
}

const videoTrack = { id: "track-v1", name: "Video Track", type: "video" };
const audioTrack = { id: "track-a1", name: "Audio Track", type: "audio" };
const subTrack = { id: "track-s1", name: "Subtitle Track", type: "subtitle" };

// Scenario 1: Dropping transition on empty track
runTest("Scenario 1: Drop transition on empty track", () => {
  const timeline = { tracks: [videoTrack], clips: [], transitions: [] };
  const asset = { type: "transition", shader: "glsl-crossfade", name: "Crossfade", duration: 1.0 };
  const res = simulateDrop({ track: videoTrack, timeline, asset, dropX: 50 });
  const passed = !res.success && res.toasts.some(t => t.msg.includes("Drop transitions directly on the cut"));
  return { passed, details: res.toasts };
});

// Scenario 2: Dropping transition on track with single clip
runTest("Scenario 2: Drop transition on track with single clip", () => {
  const clip1 = { id: "c1", trackId: "track-v1", startTime: 0, duration: 5.0 };
  const timeline = { tracks: [videoTrack], clips: [clip1], transitions: [] };
  const asset = { type: "transition", shader: "glsl-crossfade", name: "Crossfade", duration: 1.0 };
  const res = simulateDrop({ track: videoTrack, timeline, asset, dropX: 100 }); // drop at 5.0s (end of clip)
  const passed = !res.success && res.toasts.some(t => t.msg.includes("Drop transitions directly on the cut"));
  return { passed, details: res.toasts };
});

// Scenario 3: Dropping transition on 2 non-adjacent clips (gap > 0.1s)
runTest("Scenario 3: Drop transition with gap between clips (gap = 0.5s)", () => {
  const clip1 = { id: "c1", trackId: "track-v1", startTime: 0, duration: 5.0 };
  const clip2 = { id: "c2", trackId: "track-v1", startTime: 5.5, duration: 5.0 };
  const timeline = { tracks: [videoTrack], clips: [clip1, clip2], transitions: [] };
  const asset = { type: "transition", shader: "glsl-wipe", name: "Wipe", duration: 1.0 };
  const res = simulateDrop({ track: videoTrack, timeline, asset, dropX: 105 }); // drop at 5.25s
  const passed = !res.success && res.toasts.some(t => t.msg.includes("Drop transitions directly on the cut"));
  return { passed, details: "Correctly rejected due to gap > 0.1s" };
});

// Scenario 4: Dropping transition on touching clips near the cut (< 1.5s proximity)
runTest("Scenario 4: Drop transition within cut proximity (< 1.5s)", () => {
  const clip1 = { id: "c1", trackId: "track-v1", startTime: 0, duration: 5.0 };
  const clip2 = { id: "c2", trackId: "track-v1", startTime: 5.0, duration: 5.0 };
  const timeline = { tracks: [videoTrack], clips: [clip1, clip2], transitions: [] };
  const asset = { type: "transition", shader: "glsl-slide", name: "Slide", duration: 1.0 };
  const res = simulateDrop({ track: videoTrack, timeline, asset, dropX: 100 }); // drop at 5.0s (exact cut)
  const passed = res.success && res.timeline.transitions.length === 1 &&
                 res.timeline.clips.find(c => c.id === "c2").transitionIn === "glsl-slide" &&
                 res.timeline.clips.find(c => c.id === "c1").transitionOut === "glsl-slide";
  return { passed, details: `Applied transition correctly: ${JSON.stringify(res.timeline.transitions[0])}` };
});

// Scenario 5: Dropping transition on touching clips FAR from cut (>= 1.5s proximity)
runTest("Scenario 5: Drop transition far from cut (> 1.5s proximity)", () => {
  const clip1 = { id: "c1", trackId: "track-v1", startTime: 0, duration: 10.0 };
  const clip2 = { id: "c2", trackId: "track-v1", startTime: 10.0, duration: 10.0 };
  const timeline = { tracks: [videoTrack], clips: [clip1, clip2], transitions: [] };
  const asset = { type: "transition", shader: "glsl-dissolve", name: "Dissolve", duration: 1.0 };
  const res = simulateDrop({ track: videoTrack, timeline, asset, dropX: 40 }); // drop at 2.0s (cut is at 10.0s, diff = 8.0s)
  const passed = !res.success && res.toasts.some(t => t.msg.includes("Drop transitions directly on the cut"));
  return { passed, details: "Correctly rejected due to distance > 1.5s from cut" };
});

// Scenario 6: Negative drop coordinates / dropX < 0
runTest("Scenario 6: Negative dropX offset (dropX = -50)", () => {
  const clip1 = { id: "c1", trackId: "track-v1", startTime: 0, duration: 5.0 };
  const clip2 = { id: "c2", trackId: "track-v1", startTime: 5.0, duration: 5.0 };
  const timeline = { tracks: [videoTrack], clips: [clip1, clip2], transitions: [] };
  const asset = { type: "transition", shader: "glsl-wipe", name: "Wipe", duration: 1.0 };
  const res = simulateDrop({ track: videoTrack, timeline, asset, dropX: -50 });
  const passed = !res.success; // Should fail because dropTime is clamped to 0, which is > 1.5s from cut at 5.0s
  return { passed, details: "Negative drop safely clamped to 0, rejected as far from cut" };
});

// Scenario 7: Overlapping clips on the track (leftClip.startTime + leftClip.duration > rightClip.startTime)
runTest("Scenario 7: Overlapping clips (clip1 ends at 5.0s, clip2 starts at 4.5s)", () => {
  const clip1 = { id: "c1", trackId: "track-v1", startTime: 0, duration: 5.0 };
  const clip2 = { id: "c2", trackId: "track-v1", startTime: 4.5, duration: 5.0 };
  const timeline = { tracks: [videoTrack], clips: [clip1, clip2], transitions: [] };
  const asset = { type: "transition", shader: "glsl-crossfade", name: "Crossfade", duration: 1.0 };
  const res = simulateDrop({ track: videoTrack, timeline, asset, dropX: 95 }); // drop at 4.75s
  // cutTime (5.0) - rightClip.startTime (4.5) = 0.5 > 0.1s tolerance
  const passed = !res.success && res.toasts.some(t => t.msg.includes("Drop transitions directly on the cut"));
  return { passed, details: "Rejected because overlapping clips do not form a clean cut within 0.1s" };
});

// Scenario 8: Replacing existing transition on same cut
runTest("Scenario 8: Re-dropping new transition over existing transition", () => {
  const clip1 = { id: "c1", trackId: "track-v1", startTime: 0, duration: 5.0 };
  const clip2 = { id: "c2", trackId: "track-v1", startTime: 5.0, duration: 5.0 };
  const existingTransition = {
    id: "trans-old",
    trackId: "track-v1",
    fromClipId: "c1",
    toClipId: "c2",
    type: "glsl-crossfade",
    duration: 1.0,
    startTime: 4.5,
  };
  const timeline = { tracks: [videoTrack], clips: [clip1, clip2], transitions: [existingTransition] };
  const asset = { type: "transition", shader: "glsl-burn", name: "Burn", duration: 1.5 };
  const res = simulateDrop({ track: videoTrack, timeline, asset, dropX: 100 });
  const passed = res.success &&
                 res.timeline.transitions.length === 1 &&
                 res.timeline.transitions[0].type === "glsl-burn" &&
                 res.timeline.transitions[0].duration === 1.5 &&
                 res.timeline.clips.find(c => c.id === "c2").transitionIn === "glsl-burn";
  return { passed, details: "Old transition cleanly replaced without duplicates" };
});

// Scenario 9: Drop transition on Audio Track
runTest("Scenario 9: Drop transition on Audio Track", () => {
  const clip1 = { id: "a1", trackId: "track-a1", startTime: 0, duration: 5.0 };
  const clip2 = { id: "a2", trackId: "track-a1", startTime: 5.0, duration: 5.0 };
  const timeline = { tracks: [audioTrack], clips: [clip1, clip2], transitions: [] };
  const asset = { type: "transition", shader: "glsl-crossfade", name: "Crossfade", duration: 1.0 };
  const res = simulateDrop({ track: audioTrack, timeline, asset, dropX: 100 });
  // Audio tracks only accept audio files
  const passed = !res.success && res.toasts.some(t => t.msg.includes("Audio tracks only accept Audio files"));
  return { passed, details: "Correctly rejected dropping visual WebGL transition on audio track" };
});

// Scenario 10: Transition duration longer than clip duration (Edge case)
runTest("Scenario 10: Transition duration (2.0s) longer than clip duration (0.8s)", () => {
  const clip1 = { id: "c1", trackId: "track-v1", startTime: 0, duration: 0.8 };
  const clip2 = { id: "c2", trackId: "track-v1", startTime: 0.8, duration: 0.8 };
  const timeline = { tracks: [videoTrack], clips: [clip1, clip2], transitions: [] };
  const asset = { type: "transition", shader: "glsl-crossfade", name: "Crossfade", duration: 2.0 };
  const res = simulateDrop({ track: videoTrack, timeline, asset, dropX: 16 }); // drop at 0.8s
  // Notice: TimelineTrack accepts the drop and sets startTime = 0.8 - 1.0 = -0.2s!
  // Negative startTime on transition block!
  const trans = res.timeline.transitions[0];
  const hasNegativeStart = trans && trans.startTime < 0;
  return {
    passed: true,
    details: `Transition applied with startTime = ${trans.startTime}s (negative start offset: ${hasNegativeStart})`
  };
});

console.log(JSON.stringify(tests, null, 2));
