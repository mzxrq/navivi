import React, { useEffect } from "react";
import ReactDOM from "react-dom/client";
import App from "../../../src/App";
import "../../../src/App.css";
import { ThemeProvider } from "../../../src/hooks/useTheme";
import { WorkspaceProvider, useWorkspace } from "../../../src/hooks/useWorkspace";
import { UIProvider, useUI } from "../../../src/hooks/useUI";
import { AssistantProvider } from "../../../src/hooks/useAssistant";
import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { dynamicActivate } from "../../../src/i18n";
import { ErrorBoundary } from "../../../src/components/ui/ErrorBoundary";

// ?crash=1 throws during render to show the ErrorBoundary.
function Crash(): null {
  throw new Error("Cannot read properties of undefined (reading 'lat')");
}

const params = new URLSearchParams(location.search);

// ?stops=demo loads a realistic route (stop-by, mixed modes, media, via points).
const DEMO_STOPS = [
  { id: "a", lat: 33.6617, lng: 135.3597, name: "白浜バスセンター", routeMode: "walking" },
  { id: "b", lat: 33.6679, lng: 135.3436, name: "三段壁展望台", routeMode: "walking", images: ["x.jpg", "y.jpg"], arrivingNarration: "三段壁展望台に到着しました。断崖絶壁から太平洋を望む絶景です。", viaPoints: [[33.66, 135.35], [33.665, 135.345]] },
  { id: "c", lat: 33.668, lng: 135.344, name: "三段壁洞窟", routeMode: "walking", isStopBy: true, images: ["z.jpg"] },
  { id: "d", lat: 33.6788, lng: 135.3876, name: "白良浜", routeMode: "ferry", attractionNarration: "真っ白な砂浜が広がる白良浜。" },
  { id: "e", lat: 33.6851, lng: 135.3616, name: "熊野三所神社", routeMode: "curve" },
  { id: "f", lat: 33.69, lng: 135.37, name: "とれとれ市場 南紀白浜 — Toretore Ichiba Fish Market", routeMode: "driving" },
];

// ?view=title shows the project manager with a few recent projects.
const DEMO_PROJECTS = [
  { name: "SHIRAHAMA", path: "C:\\Users\\me\\Documents\\Navivi\\Projects\\shirahama.nvv", lastOpened: Date.now() - 2 * 3600e3 },
  { name: "京都 嵐山さんぽ", path: "C:\\Users\\me\\Documents\\Navivi\\Workspaces\\arashiyama", lastOpened: Date.now() - 3 * 86400e3 },
  { name: "Tokyo night drive — Shibuya to Odaiba", path: "C:\\Users\\me\\Documents\\Navivi\\Projects\\tokyo-night.nvv", lastOpened: Date.now() - 40 * 86400e3 },
];

function Driver() {
  const ui = useUI() as any;
  const { setCurrentView, setIsRendering, showToast, setEditorMode, setShowAppSettings } = ui;
  const ws = useWorkspace() as any;
  (window as any).__ws = ws;
  const { setWaypoints, updateMetadata, setRecentProjects, setTimeline } = ws;
  useEffect(() => {
    (window as any).__toast = showToast;
    (window as any).__ui = ui;
    if (params.get("ai") === "1") ws.updateSettings({ ai_features_enabled: true });
    (window as any).__openSettings = (tab: string) => { setShowAppSettings(true); window.dispatchEvent(new CustomEvent("open-app-settings-tab", { detail: tab })); };
    if (params.get("view") === "new") {
      setCurrentView("new_project");
      return;
    }
    if (params.get("view") === "title") {
      setRecentProjects?.(DEMO_PROJECTS);
      setCurrentView("title_screen");
      return;
    }
    setCurrentView("editor");
    if (params.get("stops") === "demo") {
      setWaypoints(DEMO_STOPS);
      if (params.get("review") === "demo") updateMetadata({ directory_path: "C:/p" });
      updateMetadata({ project_name: "SHIRAHAMA", video_title: "南紀白浜 さんぽ", video_subtitle: "和歌山県 白浜町" });
    }
    if (params.get("editor") === "media") {
      const mk = (id: string, video: string, extra: any = {}) => ({ id, label: id, kind: "custom", video, videoDuration: 3, trimIn: 0, trimOut: 3, audioOffset: 0, volume: 1, muted: false, fadeIntoNext: 0, ...extra });
      setTimeline({
        segments: [mk("A", "a.webm", { audio: "v.wav", audioDuration: 2, audioOffset: 0.5 }), mk("B", "b.webm", { trimIn: 1 })],
        subtitles: [{ id: "c1", segmentId: "A", start: 0.5, end: 2, text: "hello cue" }],
        music: null,
        burnSubtitles: true,
      });
      setEditorMode("timeline");
    }
    if (params.get("editor") === "demo") {
      const seg = (id: string, label: string, kind: string, dur: number, extra: any = {}) => ({ id, label, kind, video: `assets/video/${label}.mp4`, videoDuration: dur, trimIn: 0, trimOut: dur, audioOffset: 0, volume: 1, muted: false, fadeIntoNext: 0, ...extra });
      setTimeline({
        segments: [
          seg("s0", "00_intro", "intro", 8),
          seg("s1", "01_overview", "overview", 20, { audio: "a.wav", audioDuration: 18, audioOffset: 1 }),
          seg("s2", "02_waypoint_01_三段壁", "route", 12, { audio: "b.wav", audioDuration: 9, audioOffset: 2, fadeIntoNext: 0.8 }),
          seg("s3", "04_attraction_01_三段壁", "attraction", 10, { audio: "c.wav", audioDuration: 12, trimOut: 8 }),
          seg("s4", "02_waypoint_02_白良浜", "route", 14, { audio: "d.wav", audioDuration: 10, muted: true }),
        ],
        subtitles: [
          { id: "c1", segmentId: "s1", start: 1, end: 5, text: "南紀白浜へようこそ。" },
          { id: "c2", segmentId: "s1", start: 5.2, end: 11, text: "真っ白な砂浜と、断崖絶壁が広がる町です。" },
          { id: "c3", segmentId: "s2", start: 2, end: 8, text: "まずは三段壁へ向かいます。" },
        ],
        texts: [{ id: "t0", segmentId: "s0", start: 0.5, end: 7, kind: "intro", title: { text: "南紀白浜 さんぽ" }, subtitle: { text: "和歌山県 白浜町" } }],
        music: { path: "assets/audio/music/bgm.mp3", label: "bgm", volume: 0.25 },
        burnSubtitles: true,
      });
      setEditorMode("timeline");
    }
    if (params.get("render") !== "0") setTimeout(() => setIsRendering(true), 300);
  }, []);
  return null;
}

dynamicActivate(params.get("locale") || "en").then(() => {
  const Wrap = params.get("strict") === "1" ? React.StrictMode : React.Fragment;
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <Wrap><ThemeProvider defaultTheme={(params.get("theme") as any) || "dark"}>
      <I18nProvider i18n={i18n}>
        <UIProvider>
          <WorkspaceProvider>
            <AssistantProvider>
              <ErrorBoundary>
                <App />
                <Driver />
                {params.get("crash") === "1" && <Crash />}
              </ErrorBoundary>
            </AssistantProvider>
          </WorkspaceProvider>
        </UIProvider>
      </I18nProvider>
    </ThemeProvider></Wrap>,
  );
});
