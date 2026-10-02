import { useEffect, useRef } from "react";
import { useWorkspace } from "./useWorkspace";
import { useUI } from "./useUI";
import { t } from "@lingui/core/macro";
export function useAutoSave() {
    const { settings, metadata, isDirty, dirtyRevision, saveProject } = useWorkspace();
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

        const save = async () => {
            // An edit made during a save restarts this effect; wait for that save instead of dropping the new one.
            if (savingRef.current) {
                timeoutRef.current = setTimeout(save, 500);
                return;
            }
            savingRef.current = true;
            try {
                await saveProjectRef.current(undefined, undefined, undefined, false);
            } catch (error) {
                console.error("Auto-save failed:", error);
                showToastRef.current(t`Auto-save failed`, "error");
            } finally {
                savingRef.current = false;
            }
        };
        // each new edit restarts the wait
        timeoutRef.current = setTimeout(save, intervalSeconds * 1000);
        return () => {
            if (timeoutRef.current) clearTimeout(timeoutRef.current);
        };
    }, [isDirty, dirtyRevision, metadata?.directory_path, settings.auto_save_interval]);
}
