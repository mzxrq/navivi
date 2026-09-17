import re
import json

path = r'src\components\ui\AppSettings.tsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    '  Key,\n} from "./icons";',
    '  Key,\n  Film,\n} from "./icons";'
)

content = content.replace(
    'type SettingsTab = "general" | "appearance" | "api";',
    'type SettingsTab = "general" | "appearance" | "api" | "video";'
)

tab_btn = """            <TabButton
              active={activeTab === "api"}
              onClick={() => setActiveTab("api")}
              icon={Key}
              label="API Keys"
            />"""
tab_btn_new = """            <TabButton
              active={activeTab === "api"}
              onClick={() => setActiveTab("api")}
              icon={Key}
              label="API Keys"
            />
            <TabButton
              active={activeTab === "video"}
              onClick={() => setActiveTab("video")}
              icon={Film}
              label="Video Editor"
            />"""
content = content.replace(tab_btn, tab_btn_new)

video_tab = """            {/* VIDEO EDITOR TAB */}
            {activeTab === "video" && (
              <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-300">
                <div className="space-y-3">
                  <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
                    <Film className="w-3.5 h-3.5" /> Video Editor Settings
                  </label>
                  
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Target FPS</label>
                      <input
                        type="number"
                        value={settings.fps || 60}
                        onChange={(e) => updateSettings({ fps: Number(e.target.value) })}
                        className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                      />
                    </div>
                    
                    <div className="space-y-2">
                      <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Duration (seconds)</label>
                      <input
                        type="number"
                        value={settings.duration_seconds || 15}
                        onChange={(e) => updateSettings({ duration_seconds: Number(e.target.value) })}
                        className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                      />
                    </div>
                    
                    <div className="space-y-2">
                      <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Residential Duration</label>
                      <input
                        type="number"
                        value={settings.res_duration || 5}
                        onChange={(e) => updateSettings({ res_duration: Number(e.target.value) })}
                        className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                      />
                    </div>
                  </div>
                  
                  <div className="space-y-2 pt-4 border-t border-zinc-100 dark:border-navidark-700">
                    <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">Subtitle Format</label>
                    
                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Font</label>
                        <input
                          type="text"
                          value={settings.subtitle_font || "Calibri"}
                          onChange={(e) => updateSettings({ subtitle_font: e.target.value })}
                          className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Font Size</label>
                        <input
                          type="number"
                          value={settings.subtitle_font_size || 30}
                          onChange={(e) => updateSettings({ subtitle_font_size: Number(e.target.value) })}
                          className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Primary Color (ASS)</label>
                        <input
                          type="text"
                          value={settings.subtitle_color || "&H00FFFFFF"}
                          onChange={(e) => updateSettings({ subtitle_color: e.target.value })}
                          className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Outline Color (ASS)</label>
                        <input
                          type="text"
                          value={settings.subtitle_outline_color || "&H00000000"}
                          onChange={(e) => updateSettings({ subtitle_outline_color: e.target.value })}
                          className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>"""

# Replace the specific closing tag at the end of the `api` tab
content = re.sub(
    r'(?s)(activeTab === "api" && \(.*?)\n          </div>\n        </div>',
    r'\1\n' + video_tab,
    content
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("done AppSettings again")
