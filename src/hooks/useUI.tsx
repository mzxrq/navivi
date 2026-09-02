import React, { createContext, useContext, useState } from "react";

export type AppView = "title_screen" | "editor" | "new_project";
export type EditorMode = "map" | "timeline";

export type AppTheme = "light" | "dark" | "system";
export type MapTheme = "light" | "dark" | "sync";

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
  notifications: AppNotification[];
  clearNotifications: () => void;
  hideToast: (id: string) => void;
  activeToasts: AppNotification[];
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
  // const [toast, setToast] = useState<{
  //   message: string;
  //   type: "success" | "error" | "warning" | "info";
  //   visible: boolean;
  // }>({
  //   message: "",
  //   type: "info",
  //   visible: false,
  // });
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [showAppSettings, setShowAppSettings] = useState(false);
  const [isRendering, setIsRendering] = useState(false);
  const [renderLogs, setRenderLogs] = useState("");
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

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
        notifications,
        clearNotifications,
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
