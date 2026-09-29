import { useEffect, useRef } from "react";
import { useWorkspace } from "./useWorkspace";
import { useUI } from "./useUI";
import { t } from "@lingui/core/macro";

export function useAutoSave() {
    const { settings, metadata, isDirty, setIsDirty, saveProject, waypoints, routeSegments, timeline } = useWorkspace();
    const { showToast } = useUI();
    const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const saveProjectRef = useRef(saveProject);
    const showToastRef = useRef(showToast);
    const savingRef = useRef(false);

    saveProjectRef.current = saveProject;
    showToastRef.current = showToast;

    useEffect(() => {
        // no unsaved changes, happy life
        if (!isDirty || !metadata?.directory_path) return;
        const intervalSeconds = settings.auto_save_interval ?? 3;
        if (intervalSeconds === 0) return; // if set as 0 = autosave disabled
        
        // clear timeout if new change happens quickly
        if (timeoutRef.current) {
            clearTimeout(timeoutRef.current);
        }
        
        // set a new timeout to save after 3 seconds
        timeoutRef.current = setTimeout(async () => {
            if (savingRef.current) return;
            savingRef.current = true;
            try {
                await saveProjectRef.current(undefined, undefined, undefined, false);
            } catch (error) {
                console.error("Auto-save failed:", error);
                showToastRef.current(t`Auto-save failed`, "error");
            } finally {
                savingRef.current = false;
            }
        }, intervalSeconds * 1000);
        
        return () => {
            if (timeoutRef.current) clearTimeout(timeoutRef.current);
        };
    }, [isDirty, metadata, waypoints, routeSegments, timeline, settings.auto_save_interval]);
}