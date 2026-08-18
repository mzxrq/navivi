import React, { createContext, useContext, useState } from "react";

export type AppView = "title_screen" | "editor" | "new_project";

export type AppTheme = "light" | "dark" | "system";
export type MapTheme = "light" | "dark" | "sync";

// define global ui state
interface UIState {
  // nav
  currentView: AppView;
  setCurrentView: (view: AppView) => void;
  showVideoPanel: boolean;
  setShowVideoPanel: (show: boolean) => void;
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
    type: "success" | "error" | "info";
    visible: boolean;
  };
  showToast: (message: string, type?: "success" | "error" | "info") => void;
  showAppSettings: boolean;
  setShowAppSettings: (show: boolean) => void;
}

// create context
const UIContext = createContext<UIState | undefined>(undefined);

// create provider wrapper
export const UIProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [currentView, setCurrentView] = useState<AppView>("title_screen");
  const [showVideoPanel, setShowVideoPanel] = useState(false);
  const [toast, setToast] = useState<{
    message: string;
    type: "success" | "error" | "info";
    visible: boolean;
  }>({
    message: "",
    type: "info",
    visible: false,
  });

  const [showAppSettings, setShowAppSettings] = useState(false);
  const [isRendering, setIsRendering] = useState(false);
  const [renderLogs, setRenderLogs] = useState("");
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  // han

  const showToast = (
    message: string,
    type: "success" | "error" | "info" = "info",
  ) => {
    setToast({ message, type, visible: true });
    setTimeout(() => {
      setToast((prev) => ({ ...prev, visible: false }));
    }, 4000);
  };

  return (
    <UIContext.Provider
      value={{
        currentView,
        setCurrentView,
        showVideoPanel,
        setShowVideoPanel,
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
