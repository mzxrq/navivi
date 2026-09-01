import React, { createContext, useContext, useState, useRef } from "react";

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
  toast: {
    message: string;
    type: "success" | "error" | "warning" | "info";
    visible: boolean;
  };
  showToast: (message: string, type?: "success" | "error" | "warning" | "info") => void;
  showAppSettings: boolean;
  setShowAppSettings: (show: boolean) => void;
  notifications: AppNotification[];
}


// create context
const UIContext = createContext<UIState | undefined>(undefined);

// create provider wrapper
export const UIProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [currentView, setCurrentView] = useState<AppView>("title_screen");
  const [editorMode, setEditorMode] = useState<EditorMode>("map");
  const [toast, setToast] = useState<{
    message: string;
    type: "success" | "error" | "warning" | "info";
    visible: boolean;
  }>({
    message: "",
    type: "info",
    visible: false,
  });
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const toastTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [showAppSettings, setShowAppSettings] = useState(false);
  const [isRendering, setIsRendering] = useState(false);
  const [renderLogs, setRenderLogs] = useState("");
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  // han

  const showToast = (message: string, type: "success" | "error" | "warning" | "info" = "info") => {
    const newNotif: AppNotification = {
      id: crypto.randomUUID(),
      message, type, timestamp: new Date(),
    };
    setNotifications((prev) => [newNotif, ...prev].slice(0,50));
    setToast({ message, type, visible: true });
    if (toastTimeoutRef.current) {
      clearTimeout(toastTimeoutRef.current);
    }

    toastTimeoutRef.current = setTimeout(() => {
      setToast((prev) => ({ ...prev, visible: false }));
    }, 4000);
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
        toast,
        showToast,
        showAppSettings,
        setShowAppSettings,
        notifications,
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
