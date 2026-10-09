import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { i18n } from "@lingui/core";
import { resolveNarrationLanguage } from "../utils/narrationLanguage";
import { t } from "@lingui/core/macro";
import { aiEngine } from "../services/ai/engine";
import { EMPTY_BRIEF, mergeBrief, missingForBuild, ProjectBrief } from "../services/assistant/brief";
import { buildProject, BuildProgress } from "../services/assistant/buildProject";
import { emptyChat, hasContent, loadChat, saveChat, serializeChat, StoredChat } from "../services/assistant/chatStore";
import { ChatMessage, converse, Source } from "../services/assistant/converse";
import { isSupportedDocument, readSource } from "../services/assistant/sources";
import { isPhoto } from "../services/imageImport";
import { downloadPhotos, findPlacePhotos } from "../services/placePhotos";
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
  findPhotos: boolean; // look up photos of each place on Wikimedia Commons while building
  setFindPhotos: (on: boolean) => void;
  send: (text: string, paths: string[]) => Promise<void>;
  build: () => Promise<void>;
  stop: () => void;
  reset: () => void;
}

const AssistantContext = createContext<AssistantContextType | null>(null);

const asNote = (text: string): ChatMessage => ({ role: "assistant", text });

const WRITE_DELAY_MS = 300;
const PHOTOS_KEY = "navivi.assistant.findPhotos";
const PHOTOS_PER_STOP = 2; // leaves a slot for the user's own photo

const readPhotosChoice = () => {
  try {
    return localStorage.getItem(PHOTOS_KEY) !== "0";
  } catch {
    return true;
  }
};

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
  const [findPhotos, setFindPhotosState] = useState(readPhotosChoice);
  const setFindPhotos = useCallback((on: boolean) => {
    setFindPhotosState(on);
    try {
      localStorage.setItem(PHOTOS_KEY, on ? "1" : "0");
    } catch {
      // the choice then lasts until the app closes
    }
  }, []);
  const abort = useRef<AbortController | null>(null);

  // Whose chat this is: the folder of the open project, or "" on the start screen and in a project that has no folder yet
  // (a chat there is only in memory until the project's first save). `generation` changes whenever the owner does, so an
  // answer that arrives after the user moved on is dropped instead of landing in the wrong project.
  const owner = useRef("");
  const generation = useRef(0);
  const chat = useRef<StoredChat>(emptyChat());
  chat.current = { messages, brief, sources, attachments };
  const written = useRef(new Map<string, string>());
  const pending = useRef<{ dir: string; snapshot: StoredChat; timer: ReturnType<typeof setTimeout> } | null>(null);
  const queue = useRef<Promise<void>>(Promise.resolve());

  const write = useCallback((dir: string, snapshot: StoredChat) => {
    const text = serializeChat(snapshot);
    if (written.current.get(dir) === text || (!hasContent(snapshot) && !written.current.has(dir))) return;
    written.current.set(dir, text);
    queue.current = queue.current.then(() => saveChat(dir, snapshot)).catch((e) => console.error("Could not save the assistant chat:", e));
  }, []);

  const flush = useCallback(() => {
    const p = pending.current;
    if (!p) return;
    clearTimeout(p.timer);
    pending.current = null;
    write(p.dir, p.snapshot);
  }, [write]);

  const applyChat = useCallback((next: StoredChat) => {
    setMessages(next.messages);
    setBrief(next.brief);
    setSources(next.sources);
    setAttachments(next.attachments);
  }, []);

  // With no places in the brief yet, the builder finds them in an attached document itself.
  const ready = missingForBuild(brief).length === 0 || attachments.gpx !== null || sources.length > 0;

  const reset = useCallback(() => {
    abort.current?.abort();
    generation.current += 1;
    flush();
    if (owner.current) write(owner.current, emptyChat());
    setMessages([]);
    setBrief(EMPTY_BRIEF);
    setSources([]);
    setAttachments({ gpx: null, photos: [] });
    setPhase("idle");
    setProgress(null);
  }, [flush, write]);

  // Another project was opened (or the project was closed): its own chat replaces this one.
  const directory = metadata.directory_path || "";
  useEffect(() => {
    if (directory === owner.current) return;
    flush();
    abort.current?.abort();
    generation.current += 1;
    const mine = generation.current;
    owner.current = directory;
    setPhase("idle");
    setProgress(null);
    applyChat(emptyChat());
    if (!directory) return;
    loadChat(directory).then((stored) => {
      if (generation.current !== mine || hasContent(chat.current)) return; // already typing in it: keep that
      const next = stored ?? emptyChat();
      written.current.set(directory, serializeChat(next));
      applyChat(next);
    });
  }, [directory, flush, applyChat]);

  // A save gives an unsaved project its folder, and Save As makes a second project: the conversation moves along with it.
  useEffect(() => {
    const onSaved = (e: Event) => {
      const { dir, saveAs } = (e as CustomEvent<{ dir: string; saveAs?: boolean }>).detail;
      if (!dir || (dir === owner.current && !saveAs)) return;
      owner.current = dir;
      flush();
      write(dir, chat.current);
    };
    window.addEventListener("project-saved", onSaved);
    return () => window.removeEventListener("project-saved", onSaved);
  }, [flush, write]);

  // Saved shortly after each change, into the folder that owned the chat when the change was made.
  useEffect(() => {
    const dir = owner.current;
    if (!dir) return;
    if (pending.current && pending.current.dir !== dir) flush();
    if (pending.current) clearTimeout(pending.current.timer);
    const snapshot = { messages, brief, sources, attachments };
    pending.current = { dir, snapshot, timer: setTimeout(flush, WRITE_DELAY_MS) };
  }, [messages, brief, sources, attachments, flush]);
  useEffect(() => flush, [flush]);

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
      const mine = generation.current;
      const live = () => generation.current === mine;

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
        if (!live()) return;
        setSources(nextSources);
        setAttachments(nextAttachments);
        if (notes.length) setMessages([...history, ...notes]);

        const result = await converse({ history, brief, sources: nextSources, engine: aiEngine(settings), signal });
        if (!live()) return;
        setBrief((b) => mergeBrief(b, result.patch));
        const canBuild = result.ready || nextSources.length > 0 || nextAttachments.gpx !== null;
        setMessages([...history, ...notes, asNote(result.reply || (canBuild ? t`Done. Tell me more, or press Create project.` : t`Which places should the video visit?`))]);
      } catch (e: any) {
        if (!live()) return;
        if (signal.aborted) setMessages([...history, asNote(t`Stopped.`)]);
        else setMessages([...history, asNote(t`I could not reach the AI: ${e?.message ?? e}. Check Settings > AI models.`)]);
      } finally {
        if (live()) setPhase("idle");
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
    const mine = generation.current;
    const live = () => generation.current === mine;
    try {
      // A language named in the chat wins; else the narration language setting, else what the sources are written in.
      const sourceText = sources.map((s) => `${s.name}\n${s.text}`).join("\n\n").slice(0, MAX_SOURCE_CHARS);
      const languages = brief.languages.length ? brief.languages : [resolveNarrationLanguage(settings.narration_language, [sourceText, brief.scope, brief.purpose], i18n.locale)];
      const built = await buildProject({
        brief: { ...brief, languages },
        sourceText,
        engine,
        mapboxToken: settings.mapbox_api_key || import.meta.env.VITE_MAPBOX_TOKEN,
        signal: abort.current.signal,
        onProgress: setProgress,
        photos: findPhotos
          ? async (stop) => downloadPhotos(await findPlacePhotos(stop, { limit: PHOTOS_PER_STOP, signal: abort.current?.signal }), abort.current?.signal)
          : undefined,
      });
      if (!live()) return;
      const first = built.waypoints[0];
      if (!first) throw new Error(t`No places could be found in your sources`);
      enterEditor({ start_coords: [first.lat, first.lng] });
      setWaypoints(built.waypoints);
      if (files.length) setPendingImport({ kind: "files", paths: files });
      const missed =
        (built.failedPlaces.length ? t` I could not find: ${built.failedPlaces.join(", ")}.` : "") +
        (built.uncertainPlaces.length ? t` I am not sure where these are, so check them on the map: ${built.uncertainPlaces.join(", ")}.` : "") +
        (built.photosAdded ? t` I added ${built.photosAdded} photos from Wikimedia Commons; check that they show the right place. Their credits are listed when you export the video.` : "");
      setMessages((m) => [...m, asNote(t`Created "${built.name}" with ${built.waypoints.length} stops and their scripts.${missed} Review them, then press Generate Assets.`)]);
      setPanelOpen(inEditor);
    } catch (e: any) {
      if (!live()) return;
      if (abort.current?.signal.aborted) setMessages((m) => [...m, asNote(t`Stopped.`)]);
      else {
        setMessages((m) => [...m, asNote(t`I could not finish building: ${e?.message ?? e}`)]);
        showToast(t`The assistant could not build the project`, "error");
      }
    } finally {
      if (live()) {
        setPhase("idle");
        setProgress(null);
      }
    }
  }, [brief, sources, attachments, settings, findPhotos, currentView, waypoints, metadata, resetWorkspace, updateMetadata, updateSettings, setWaypoints, setIsDirty, setCurrentView, showToast]);

  const value = useMemo(
    () => ({ messages, brief, sources, attachments, phase, progress, ready, panelOpen, setPanelOpen, findPhotos, setFindPhotos, send, build, stop, reset }),
    [messages, brief, sources, attachments, phase, progress, ready, panelOpen, findPhotos, setFindPhotos, send, build, stop, reset],
  );

  return <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>;
}

export function useAssistant() {
  const context = useContext(AssistantContext);
  if (!context) throw new Error("useAssistant must be used within AssistantProvider");
  return context;
}
