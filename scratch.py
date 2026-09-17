import re
import json

path = r'src\components\view\ProjectManager.tsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'import { convertFileSrc } from "@tauri-apps/api/core";',
    'import { convertFileSrc, invoke } from "@tauri-apps/api/core";\nimport { readTextFile, writeTextFile } from "@tauri-apps/plugin-fs";'
)

content = content.replace(
    'AlertTriangle,\n} from "../ui/icons";',
    'AlertTriangle,\n  Film,\n} from "../ui/icons";'
)

content = content.replace(
    'type ModalActionType = "rename" | "duplicate" | "remove" | null;',
    'type ModalActionType = "rename" | "duplicate" | "remove" | "settings" | null;'
)

quick_render_code = """
  const handleQuickRender = async (project: any) => {
    showToast("Quick Render started for " + project.name, "info");
    try {
      await invoke("run_python_blueprint", {
        action: project.path,
        payload: "concat"
      });
      showToast("Quick Render complete for " + project.name, "success");
    } catch (err: any) {
      showToast("Quick Render failed: " + String(err), "error");
    }
  };
"""
content = content.replace('  const handleOpenProject = async (path?: string) => {', quick_render_code + '\n  const handleOpenProject = async (path?: string) => {')

open_modal_code = """  const openModal = async (type: ModalActionType, project: any, e?: MouseEvent) => {
    if (e) e.stopPropagation();
    setModalState({ type, project });
    
    if (type === "settings") {
      try {
        const fileContent = await readTextFile(project.path);
        const data = JSON.parse(fileContent);
        setModalInput(data.settings?.routeMarker || "");
      } catch (err) {
        showToast("Failed to load project settings", "error");
        setModalInput("");
      }
    } else {
      setModalInput(
        type === "duplicate" ? `${project.name} (Copy)` : project.name,
      );
    }
    setActiveMenu(null);
  };"""
content = re.sub(r'  const openModal = \(type: ModalActionType, project: any, e\?: MouseEvent\) => \{.*?\n  \};', open_modal_code, content, flags=re.DOTALL)

execute_code = """
      } else if (type === "settings") {
        const fileContent = await readTextFile(project.path);
        const data = JSON.parse(fileContent);
        if (!data.settings) data.settings = {};
        data.settings.routeMarker = modalInput;
        await writeTextFile(project.path, JSON.stringify(data, null, 2));
        showToast("Project settings updated.", "success");
"""
content = content.replace('      } else if (type === "duplicate") {', execute_code.strip() + '\n      } else if (type === "duplicate") {')

menu1 = """                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            showToast(
                              "To change settings, open the project first.",
                              "info",
                            );
                            setActiveMenu(null);
                          }}
                          className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 flex items-center gap-2"
                        >
                          <Settings2 className="w-3.5 h-3.5" /> Advanced
                          Settings
                        </button>"""
menu1_new = """                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleQuickRender(project);
                            setActiveMenu(null);
                          }}
                          className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 flex items-center gap-2"
                        >
                          <Film className="w-3.5 h-3.5" /> Quick Render
                        </button>
                        <button
                          onClick={(e) => openModal("settings", project, e as any)}
                          className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 flex items-center gap-2"
                        >
                          <Settings2 className="w-3.5 h-3.5" /> Advanced Settings
                        </button>"""
content = content.replace(menu1, menu1_new)

menu2 = """onSettings: () =>
              showToast("To change settings, open the project first.", "info"),"""
menu2_new = """onSettings: () => openModal("settings", project),
            onQuickRender: () => handleQuickRender(project),"""
content = content.replace(menu2, menu2_new)

list_view_menu = """                      <button
                        onClick={(e) => openModal("duplicate", project, e)}
                        className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 flex items-center gap-2"
                      >
                        <Copy className="w-3.5 h-3.5" /> Duplicate
                      </button>"""
list_view_menu_new = """                      <button
                        onClick={(e) => openModal("duplicate", project, e)}
                        className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 flex items-center gap-2"
                      >
                        <Copy className="w-3.5 h-3.5" /> Duplicate
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleQuickRender(project);
                          setActiveMenu(null);
                        }}
                        className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 flex items-center gap-2"
                      >
                        <Film className="w-3.5 h-3.5" /> Quick Render
                      </button>
                      <button
                        onClick={(e) => openModal("settings", project, e as any)}
                        className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 flex items-center gap-2"
                      >
                        <Settings2 className="w-3.5 h-3.5" /> Advanced Settings
                      </button>"""
content = content.replace(list_view_menu, list_view_menu_new)

modal_ui = """                  {modalState.type === "duplicate" && (
                    <>
                      <Copy className="w-4 h-4 text-navi-500" /> Duplicate
                      Project
                    </>
                  )}
                </h3>"""
modal_ui_new = """                  {modalState.type === "duplicate" && (
                    <>
                      <Copy className="w-4 h-4 text-navi-500" /> Duplicate
                      Project
                    </>
                  )}
                  {modalState.type === "settings" && (
                    <>
                      <Settings2 className="w-4 h-4 text-navi-500" /> Advanced Settings
                    </>
                  )}
                </h3>"""
content = content.replace(modal_ui, modal_ui_new)

modal_label = """                    <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                      {modalState.type === "rename"
                        ? "New Project Name"
                        : "Duplicate Project Name"}
                    </label>"""
modal_label_new = """                    <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                      {modalState.type === "rename"
                        ? "New Project Name"
                        : modalState.type === "settings"
                        ? "Global Custom Marker"
                        : "Duplicate Project Name"}
                    </label>"""
content = content.replace(modal_label, modal_label_new)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("done")
