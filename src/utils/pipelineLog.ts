export type PipelineLineKind =
  | "stage" // first tracker line of a "[n/N]" stage (tracker.stage)
  | "status" // any other tracker line (tracker.show / show_item)
  | "info"
  | "warning"
  | "error"
  | "system"; // messages from the app itself, not the pipeline

export interface PipelineLine {
  id: string;
  time: string;
  kind: PipelineLineKind;
  text: string;
  raw: string;
  elapsed?: string;
  stage?: number;
  updates: number;
  tool?: string;
  key?: string;
  details?: string;
  fromApp?: boolean;
}

export interface PipelineStage {
  index: number;
  title: string;
  startedAt: number;
  lastSeenAt: number;
  detail: string;
  notes: PipelineLine[];
}

export interface PipelineLogState {
  lines: PipelineLine[];
  stages: PipelineStage[];
  stageTotal: number;
  current: string;
  progress: number;
  inTraceback: boolean;
  resultBuffer: string[] | null;
}

export const MAX_PIPELINE_LINES = 1500;

export const emptyPipelineLog = (): PipelineLogState => ({
  lines: [],
  stages: [],
  stageTotal: 0,
  current: "",
  progress: 0,
  inTraceback: false,
  resultBuffer: null,
});

const TRACKER_RE = /^\[(\d{2,}):(\d{2})\](?:\s*\[(\d+)\/(\d+)\])?\s*(.*)$/;
const FFMPEG_STATS_RE = /^\s*(?:frame|size)=\s*\S/;
const FFMPEG_BANNER_RE =
  /ffmpeg version|built with gcc|configuration:|^\s*lib[a-z]+\s+\d+\.|Guessed Channel Layout/;
const ETA_RE = /\s+—\s+ETA\s+~\d{2}:\d{2}\s*$/;
const WARNING_RE = /\[WARNING\]|\bwarning\b|low ram/i;
const ERROR_RE = /\[ERROR\]|\[CRITICAL\]|traceback \(most recent call last\)|\b\w*(?:error|exception)\b/i;

const clock = () => new Date().toLocaleTimeString([], { hour12: false });

const toSeconds = (mm: string, ss: string) => parseInt(mm, 10) * 60 + parseInt(ss, 10);

const statusKey = (text: string) => text.replace(ETA_RE, "").replace(/\d+/g, "#");

function stageFraction(text: string): number {
  const m = text.match(/(\d+)\s*\/\s*(\d+)/);
  if (!m) return 0;
  const done = parseInt(m[1], 10);
  const of = parseInt(m[2], 10);
  return of > 0 ? Math.min(1, Math.max(0, done / of)) : 0;
}

const newId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);

function withLine(state: PipelineLogState, line: PipelineLine): PipelineLogState {
  const lines = [...state.lines, line];
  if (lines.length > MAX_PIPELINE_LINES) lines.splice(0, lines.length - MAX_PIPELINE_LINES);
  return { ...state, lines };
}

function replaceLast(state: PipelineLogState, line: PipelineLine): PipelineLogState {
  const lines = state.lines.slice();
  lines[lines.length - 1] = line;
  return { ...state, lines };
}

function noteOnStage(state: PipelineLogState, line: PipelineLine): PipelineLogState {
  if (state.stages.length === 0) return state;
  const stages = state.stages.slice();
  const last = stages[stages.length - 1];
  stages[stages.length - 1] = { ...last, notes: [...last.notes, line].slice(-20) };
  return { ...state, stages };
}

function finishResult(state: PipelineLogState, rawJson: string): PipelineLogState {
  let result: { success?: boolean; error?: string; error_type?: string; traceback?: string } | null = null;
  try {
    result = JSON.parse(rawJson);
  } catch {
    return rawJson.split("\n").reduce(
      (s, l) => withLine(s, { id: newId(), time: clock(), kind: "info", text: l, raw: l, updates: 1 }),
      state,
    );
  }
  if (!result || result.success !== false) return state;
  const text = result.error_type ? `${result.error_type}: ${result.error ?? ""}` : (result.error ?? "");
  const line: PipelineLine = {
    id: newId(),
    time: clock(),
    kind: "error",
    text,
    raw: text,
    updates: 1,
    details: result.traceback,
  };
  return noteOnStage(withLine(state, line), line);
}

function appendSegment(state: PipelineLogState, raw: string): PipelineLogState {
  const text = raw.replace(/\s+$/, "");

  if (state.resultBuffer) {
    const resultBuffer = [...state.resultBuffer, text];
    if (text === "}") return finishResult({ ...state, resultBuffer: null }, resultBuffer.join("\n"));
    return { ...state, resultBuffer };
  }
  if (text === "{") return { ...state, resultBuffer: [text] };

  if (!text.trim() || FFMPEG_BANNER_RE.test(text)) return state;

  if (FFMPEG_STATS_RE.test(text)) {
    const tool = text.trim().replace(/\s+/g, " ");
    const last = state.lines[state.lines.length - 1];
    if (!last) return state;
    return replaceLast(state, { ...last, tool });
  }

  const tracker = text.match(TRACKER_RE);
  if (tracker) {
    const [, mm, ss, n, total, body] = tracker;
    const seconds = toSeconds(mm, ss);
    const elapsed = `${mm}:${ss}`;
    const stageNum = n ? parseInt(n, 10) : undefined;
    const stageTotal = total ? parseInt(total, 10) : state.stageTotal;
    let next: PipelineLogState = { ...state, stageTotal, current: body, inTraceback: false };

    const lastStage = next.stages[next.stages.length - 1];
    const opensStage = stageNum !== undefined && (!lastStage || stageNum > lastStage.index);
    if (opensStage) {
      next = {
        ...next,
        stages: [
          ...next.stages,
          { index: stageNum, title: body, startedAt: seconds, lastSeenAt: seconds, detail: "", notes: [] },
        ],
      };
    } else if (lastStage) {
      const stages = next.stages.slice();
      stages[stages.length - 1] = { ...lastStage, lastSeenAt: seconds, detail: body };
      next = { ...next, stages };
    }

    if (stageNum !== undefined && stageTotal > 0) {
      const pct = ((stageNum - 1 + stageFraction(opensStage ? "" : body)) / stageTotal) * 100;
      next = { ...next, progress: Math.max(next.progress, Math.min(99, Math.floor(pct))) };
    }

    const key = statusKey(body);
    const line: PipelineLine = {
      id: newId(),
      time: clock(),
      kind: opensStage ? "stage" : "status",
      text: body,
      raw: text,
      elapsed,
      stage: stageNum,
      updates: 1,
      key,
    };
    const prev = next.lines[next.lines.length - 1];
    if (!opensStage && prev?.kind === "status" && prev.key === key) {
      return replaceLast(next, { ...line, id: prev.id, updates: prev.updates + 1, tool: prev.tool });
    }
    return withLine(next, line);
  }

  let kind: PipelineLineKind = "info";
  let inTraceback = state.inTraceback;
  if (/traceback \(most recent call last\)/i.test(text)) inTraceback = true;
  if (WARNING_RE.test(text) && !/\[ERROR\]/.test(text)) kind = "warning";
  else if (inTraceback || ERROR_RE.test(text)) kind = "error";

  const prev = state.lines[state.lines.length - 1];
  if (prev && prev.raw === text && prev.kind === kind) {
    return replaceLast({ ...state, inTraceback }, { ...prev, time: clock(), updates: prev.updates + 1 });
  }
  const line: PipelineLine = { id: newId(), time: clock(), kind, text, raw: text, updates: 1 };
  let next = withLine({ ...state, inTraceback }, line);
  if (kind === "warning" || kind === "error") next = noteOnStage(next, line);
  return next;
}

export function appendPipelineOutput(state: PipelineLogState, chunk: string): PipelineLogState {
  return chunk.split(/\r\n|\r|\n/).reduce(appendSegment, state);
}

export function appendSystemMessage(
  state: PipelineLogState,
  text: string,
  kind: "system" | "error" = "system",
): PipelineLogState {
  const line: PipelineLine = {
    id: newId(),
    time: clock(),
    kind,
    text,
    raw: text,
    updates: 1,
    fromApp: true,
  };
  return withLine(state, line);
}

export function lastPipelineError(state: PipelineLogState): string | null {
  const errors = state.lines.filter(
    (l) => l.kind === "error" && !/^\s+File "|^Traceback \(most recent/.test(l.raw),
  );
  const hit = [...errors].reverse().find((l) => !l.fromApp) ?? errors[errors.length - 1];
  return hit ? hit.text.replace(/^.*?\[ERROR\]\s*/, "") : null;
}

export function pipelineLogToText(state: PipelineLogState): string {
  return state.lines
    .map((l) =>
      [l.raw, l.tool && `    ${l.tool}`, l.details?.trimEnd()].filter(Boolean).join("\n"),
    )
    .join("\n");
}
