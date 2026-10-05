import { createContext, ReactNode, useCallback, useContext, useMemo, useRef, useState } from "react";
import { t } from "@lingui/core/macro";
import { aiEngine } from "../services/ai/engine";
import { EMPTY_BRIEF, mergeBrief, missingForBuild, ProjectBrief } from "../services/assistant/brief";
import { buildProject, BuildProgress } from "../services/assistant/buildProject";
import { ChatMessage, converse, Source } from "../services/assistant/converse";
import { isSupportedDocument, readSource } from "../services/assistant/sources";
import { isPhoto } from "../services/imageImport";
import { setPendingImport } from "../utils/pendingImport";
import { useUI } from "./useUI";
import { useWorkspace } from "./useWorkspace";

const URL_PATTERN = /https?:\/\/[^\s<>"'）)」]+/g;
const MAX_SOURCE_CHARS = 60000;

type Phase = "idle" | "thinking" | "building";

interface Attachments {
  gpx: string | null;
  photos: string[];
}

interface AssistantContextType {
  messages: ChatMessage[];
  brief: ProjectBrief;
  sources: Source[];
  attachments: Attachments;
  phase: Phase;
  progress: BuildProgress | null;
  ready: boolean;
  panelOpen: boolean;
  setPanelOpen: (open: boolean) => void;
  send: (text: string, paths: string[]) => Promise<void>;
  build: () => Promise<void>;
  stop: () => void;
  reset: () => void;
}

const AssistantContext = createContext<AssistantContextType | null>(null);

const asNote = (text: string): ChatMessage => ({ role: "assistant", text });

export function AssistantProvider({ children }: { children: ReactNode }) {
  const { setCurrentView, showToast, currentView } = useUI();
  const { settings, waypoints, setWaypoints, resetWorkspace, updateMetadata, updateSettings, setIsDirty, metadata } = useWorkspace();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [brief, setBrief] = useState<ProjectBrief>(EMPTY_BRIEF);
  const [sources, setSources] = useState<Source[]>([]);
  const [attachments, setAttachments] = useState<Attachments>({ gpx: null, photos: [] });
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState<BuildProgress | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const abort = useRef<AbortController | null>(null);

  // With no places in the brief yet, the builder finds them in an attached document itself.
  const ready = missingForBuild(brief).length === 0 || attachments.gpx !== null || sources.length > 0;

  const reset = useCallback(() => {
    abort.current?.abort();
    setMessages([]);
    setBrief(EMPTY_BRIEF);
    setSources([]);
    setAttachments({ gpx: null, photos: [] });
    setPhase("idle");
    setProgress(null);
  }, []);

  const stop = useCallback(() => abort.current?.abort(), []);

  const send = useCallback(
    async (text: string, paths: string[]) => {
      const typed = text.trim();
      const urls = typed.match(URL_PATTERN) ?? [];
      const names = paths.map((p) => p.split(/[\\/]/).pop() ?? p);
      if (!typed && paths.length === 0) return;

      const user: ChatMessage = { role: "user", text: typed, files: [...names, ...urls] };
      const history = [...messages, user];
      setMessages(history);
      setPhase("thinking");
      abort.current = new AbortController();
      const { signal } = abort.current;

      try {
        const nextSources = [...sources];
        const notes: ChatMessage[] = [];
        const nextAttachments = { ...attachments };
        for (const input of [...paths.filter(isSupportedDocument), ...urls]) {
          try {
            const read = await readSource(input, signal);
            nextSources.push({ name: read.name, text: read.text });
          } catch (e: any) {
            if (signal.aborted) throw e;
            notes.push(asNote(e?.message ?? t`Could not read ${input}.`));
          }
        }
        const gpx = paths.find((p) => p.toLowerCase().endsWith(".gpx"));
        if (gpx) nextAttachments.gpx = gpx;
        nextAttachments.photos = [...nextAttachments.photos, ...paths.filter(isPhoto)];
        setSources(nextSources);
        setAttachments(nextAttachments);
        if (notes.length) setMessages([...history, ...notes]);

        const result = await converse({ history, brief, sources: nextSources, engine: aiEngine(settings), signal });
        setBrief((b) => mergeBrief(b, result.patch));
        const canBuild = result.ready || nextSources.length > 0 || nextAttachments.gpx !== null;
        setMessages([...history, ...notes, asNote(result.reply || (canBuild ? t`Done. Tell me more, or press Create project.` : t`Which places should the video visit?`))]);
      } catch (e: any) {
        if (signal.aborted) setMessages([...history, asNote(t`Stopped.`)]);
        else setMessages([...history, asNote(t`I could not reach the AI: ${e?.message ?? e}. Check Settings > AI models.`)]);
      } finally {
        setPhase("idle");
      }
    },
    [messages, brief, sources, attachments, settings],
  );

  const build = useCallback(async () => {
    const inEditor = currentView === "editor";
    const replacing = inEditor && waypoints.length > 0;
    if (replacing && !window.confirm(t`Replace the stops in this project with the new ones?`)) return;

    const engine = aiEngine(settings);
    const name = brief.name.trim() || t`Untitled Project`;

    // Files the user attached go through the normal importers once the editor is open.
    const files = [...(attachments.gpx ? [] : []), ...attachments.photos];
    const enterEditor = (settingsPatch: Parameters<typeof updateSettings>[0]) => {
      if (!inEditor) resetWorkspace();
      updateMetadata({
        ...(inEditor && metadata.project_name !== t`Untitled Project` ? {} : { project_name: name }),
        project_id: inEditor ? metadata.project_id : "",
        status: "initialized",
        enable_intro: true,
        video_title: brief.name.trim(),
      });
      updateSettings({ fps: 30, ...settingsPatch });
      setIsDirty(true);
      setCurrentView("editor");
    };

    if (attachments.gpx) {
      enterEditor({});
      setPendingImport({ kind: "route", path: attachments.gpx });
      setMessages((m) => [...m, asNote(t`Created "${name}" from your GPX file. Write the stop scripts with the script button on each stop.`)]);
      return;
    }

    setPhase("building");
    abort.current = new AbortController();
    try {
      const built = await buildProject({
        brief,
        sourceText: sources.map((s) => `${s.name}\n${s.text}`).join("\n\n").slice(0, MAX_SOURCE_CHARS),
        engine,
        mapboxToken: settings.mapbox_api_key || import.meta.env.VITE_MAPBOX_TOKEN,
        signal: abort.current.signal,
        onProgress: setProgress,
      });
      const first = built.waypoints[0];
      if (!first) throw new Error(t`No places could be found in your sources`);
      enterEditor({ start_coords: [first.lat, first.lng] });
      setWaypoints(built.waypoints);
      if (files.length) setPendingImport({ kind: "files", paths: files });
      const missed =
        (built.failedPlaces.length ? t` I could not find: ${built.failedPlaces.join(", ")}.` : "") +
        (built.uncertainPlaces.length ? t` I am not sure where these are, so check them on the map: ${built.uncertainPlaces.join(", ")}.` : "");
      setMessages((m) => [...m, asNote(t`Created "${built.name}" with ${built.waypoints.length} stops and their scripts.${missed} Review them, then press Generate Assets.`)]);
      setPanelOpen(inEditor);
    } catch (e: any) {
      if (abort.current?.signal.aborted) setMessages((m) => [...m, asNote(t`Stopped.`)]);
      else {
        setMessages((m) => [...m, asNote(t`I could not finish building: ${e?.message ?? e}`)]);
        showToast(t`The assistant could not build the project`, "error");
      }
    } finally {
      setPhase("idle");
      setProgress(null);
    }
  }, [brief, sources, attachments, settings, currentView, waypoints, metadata, resetWorkspace, updateMetadata, updateSettings, setWaypoints, setIsDirty, setCurrentView, showToast]);

  const value = useMemo(
    () => ({ messages, brief, sources, attachments, phase, progress, ready, panelOpen, setPanelOpen, send, build, stop, reset }),
    [messages, brief, sources, attachments, phase, progress, ready, panelOpen, send, build, stop, reset],
  );

  return <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>;
}

export function useAssistant() {
  const context = useContext(AssistantContext);
  if (!context) throw new Error("useAssistant must be used within AssistantProvider");
  return context;
}
