import React, { createContext, useContext, useState } from "react";

export type AppView = "title_screen" | "editor" | "new_project";
export type EditorMode = "map" | "timeline";

export type AppTheme = "light" | "dark" | "system";

export interface AppNotification {
  id: string;
  message: string;
  type: "success" | "error" | "warning" | "info";
  timestamp: Date;
}

// define global ui state
interface UIState {
  // nav
  currentView: AppView;
  setCurrentView: (view: AppView) => void;
  editorMode: EditorMode;
  setEditorMode: (mode: EditorMode) => void;
  // render overlay
  isRendering: boolean;
  setIsRendering: (isRendering: boolean) => void;
  renderLogs: string;
  setRenderLogs: (logs: string) => void;
  // global modal
  isSettingsOpen: boolean;
  setIsSettingsOpen: (isOpen: boolean) => void;
  showToast: (
    message: string,
    type?: "success" | "error" | "warning" | "info",
  ) => void;
  showAppSettings: boolean;
  setShowAppSettings: (show: boolean) => void;
  showProjectSettings: boolean;
  setShowProjectSettings: (show: boolean) => void;
  notifications: AppNotification[];
  clearNotifications: () => void;
  hideToast: (id: string) => void;
  activeToasts: AppNotification[];
  // render collapse & session state
  isRenderCollapsed: boolean;
  setIsRenderCollapsed: (collapsed: boolean) => void;
  // The pipeline keeps running behind a small pill while the user works in the timeline editor.
  isBackgroundRender: boolean;
  setIsBackgroundRender: (background: boolean) => void;
  // True only while that background run is still working (not once it has finished or failed).
  isBackgroundBusy: boolean;
  setIsBackgroundBusy: (busy: boolean) => void;
  markedWaypointIds: string[];
  setMarkedWaypointIds: React.Dispatch<React.SetStateAction<string[]>>;
  generationSessionInfo: { activeLeg?: string; waypointId?: string; message?: string } | null;
  setGenerationSessionInfo: (info: { activeLeg?: string; waypointId?: string; message?: string } | null) => void;
  // auto-director
  autoDirectorData: any;
  setAutoDirectorData: (data: any) => void;
}

// create context
const UIContext = createContext<UIState | undefined>(undefined);

// create provider wrapper
export const UIProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [currentView, setCurrentView] = useState<AppView>("title_screen");
  const [editorMode, setEditorMode] = useState<EditorMode>("map");
  const [activeToasts, setActiveToasts] = useState<AppNotification[]>([]);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [showAppSettings, setShowAppSettings] = useState(false);
  const [showProjectSettings, setShowProjectSettings] = useState(false);
  const [isRendering, setIsRendering] = useState(false);
  const [renderLogs, setRenderLogs] = useState("");
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isRenderCollapsed, setIsRenderCollapsed] = useState(false);
  const [isBackgroundRender, setIsBackgroundRender] = useState(false);
  const [isBackgroundBusy, setIsBackgroundBusy] = useState(false);
  const [markedWaypointIds, setMarkedWaypointIds] = useState<string[]>([]);
  const [generationSessionInfo, setGenerationSessionInfo] = useState<{
    activeLeg?: string;
    waypointId?: string;
    message?: string;
  } | null>(null);
  const [autoDirectorData, setAutoDirectorData] = useState<any>(null);

  // han
  const clearNotifications = () => {
    setNotifications([]);
  };
  const showToast = (
    message: string,
    type: "success" | "error" | "warning" | "info" = "info",
  ) => {
    const id = crypto.randomUUID();
    const newNotif: AppNotification = {
      id,
      message,
      type,
      timestamp: new Date(),
    };
    setNotifications((prev) => [newNotif, ...prev].slice(0, 50));
    setActiveToasts((prev) => [...prev, newNotif]);
  };

  const hideToast = (id: string) => {
    setActiveToasts((prev) => prev.filter((t) => t.id !== id));
  };

  return (
    <UIContext.Provider
      value={{
        currentView,
        setCurrentView,
        editorMode,
        setEditorMode,
        isRendering,
        setIsRendering,
        renderLogs,
        setRenderLogs,
        isSettingsOpen,
        setIsSettingsOpen,
        activeToasts,
        showToast,
        hideToast,
        showAppSettings,
        setShowAppSettings,
        showProjectSettings,
        setShowProjectSettings,
        notifications,
        clearNotifications,
        isRenderCollapsed,
        setIsRenderCollapsed,
        isBackgroundRender,
        setIsBackgroundRender,
        isBackgroundBusy,
        setIsBackgroundBusy,
        markedWaypointIds,
        setMarkedWaypointIds,
        generationSessionInfo,
        setGenerationSessionInfo,
        autoDirectorData,
        setAutoDirectorData,
      }}
    >
      {children}
    </UIContext.Provider>
  );
};

// create hook
export const useUI = () => {
  const context = useContext(UIContext);
  if (context === undefined) {
    throw new Error("useUI must be used within an UIProvider");
  }
  return context;
};
