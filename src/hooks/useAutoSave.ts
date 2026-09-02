import { useEffect, useRef } from "react";
import { useWorkspace } from "./useWorkspace";
import { useUI } from "./useUI";

export function useAutoSave() {
    const { settings, metadata, isDirty, setIsDirty, saveProject } = useWorkspace();
    const { showToast } = useUI();
    const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
            try {
                await saveProject();
                setIsDirty(false);
            } catch (error) {
                console.error("Auto-save failed:", error);
                showToast("Auto-save failed. Please check your disk.", "error");
            }
        }, intervalSeconds * 1000);
        return () => {
            if (timeoutRef.current) clearTimeout(timeoutRef.current);
        };
    }, [isDirty, setIsDirty, saveProject, settings.auto_save_interval, showToast]);
}