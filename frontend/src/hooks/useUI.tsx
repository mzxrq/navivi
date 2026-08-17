import { message } from '@tauri-apps/plugin-dialog';
import React, { createContext, useContext, useState } from 'react';

type AppView = 'title_screen' | 'editor';

// define global ui state
export interface UIState {
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

    toast: { message: string; type: 'success' | 'error' | 'info'; visible: boolean };
    showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

// create context
const UIContext = createContext<UIState | undefined>(undefined);

// create provider wrapper
export const UIProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    // make ui to start on editor for now
    // ****
    // change default to title screen later
    const [currentView, setCurrentView] = useState<AppView>('title_screen');
    const [showVideoPanel, setShowVideoPanel] = useState(false);
    const [isRendering, setIsRendering] = useState(false);
    const [renderLogs, setRenderLogs] = useState("");
    const [isSettingsOpen, setIsSettingsOpen] = useState(false);
    const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info'; visible: boolean }>({
        message: '', type: 'info', visible: false
    });

    const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
        setToast({ message, type, visible: true });
        setTimeout(() => {
            setToast(prev => ({ ...prev, visible: false }));
        }, 4000);
    }

    return (
        <UIContext.Provider value={{
            currentView, setCurrentView,
            showVideoPanel, setShowVideoPanel,
            isRendering, setIsRendering,
            renderLogs, setRenderLogs,
            isSettingsOpen, setIsSettingsOpen,
            toast, showToast,
        }}>
            {children}
        </UIContext.Provider>
    );
};

// create hook
export const useUI = () => {
    const context = useContext(UIContext);
    if (context === undefined) {
        throw new Error('useUI must be used within an UIProvider');
    }
    return context;
};

