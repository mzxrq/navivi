import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

import { Volume2, Mic, VolumeX, Gauge } from "lucide-react";

interface InspectorAudioPanelProps {
  selectedClip: any;
  updateClip: (updates: any) => void;
}

export function InspectorAudioPanel({
  selectedClip,
  updateClip,
}: InspectorAudioPanelProps) {
  const currentVolPercent = Math.round((selectedClip.volume ?? 1) * 100);
  const volDb =
    currentVolPercent === 0
      ? "-∞"
      : currentVolPercent < 100
        ? `-${(100 - currentVolPercent) / 5}`
        : currentVolPercent > 100
          ? `+${(currentVolPercent - 100) / 5}`
          : "0";
  const duckingAmount =
    selectedClip.duckingAmount !== undefined ? selectedClip.duckingAmount : 50;

  return (
    <div className="space-y-4 pt-3 border-t border-zinc-200 dark:border-navidark-400">
      <div className="flex items-center justify-between">
        <h5 className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
          <Volume2 className="w-3.5 h-3.5 text-[#93C9B2]" />{" "}
          <Trans>Audio & Mixing</Trans>
        </h5>
        <button
          type="button"
          onClick={() => updateClip({ isMuted: !selectedClip.isMuted })}
          className={`px-2 py-1 rounded text-xs font-semibold flex items-center gap-1.5 transition-colors ${
            selectedClip.isMuted
              ? "bg-red-500/20 text-red-400 border border-red-500/40"
              : "bg-zinc-100 dark:bg-navidark-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-navidark-600"
          }`}
          title={selectedClip.isMuted ? t`Unmute Clip` : t`Mute Clip`}
        >
          {selectedClip.isMuted ? (
            <>
              <VolumeX className="w-3 h-3 text-red-400" />
              <Trans>
                <span>Muted</span>
              </Trans>
            </>
          ) : (
            <>
              <Volume2 className="w-3 h-3 text-emerald-400" />
              <Trans>
                <span>Mute</span>
              </Trans>
            </>
          )}
        </button>
      </div>

      {/* Volume Slider with % and dB readout */}
      <div className="space-y-1.5 bg-zinc-50 dark:bg-navidark-900 p-2.5 rounded border border-zinc-200 dark:border-navidark-700">
        <div className="flex justify-between items-center text-xs">
          <span className="font-semibold text-zinc-700 dark:text-zinc-300">
            <Trans>Volume</Trans>
          </span>
          <div className="flex items-center gap-2 font-mono text-[11px]">
            <span className="text-zinc-800 dark:text-zinc-200 font-bold">
              {currentVolPercent}%
            </span>
            <span className="text-zinc-400 text-[10px]">({volDb})</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <input
            type="range"
            min="0"
            max="150"
            step="1"
            value={currentVolPercent}
            onChange={(e) =>
              updateClip({ volume: parseFloat(e.target.value) / 100 })
            }
            className="w-full accent-[#36604C] dark:accent-[#93C9B2] cursor-pointer h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-lg"
          />
          <button
            type="button"
            onClick={() => updateClip({ volume: 1.0 })}
            className="text-[10px] text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 underline shrink-0"
            title={t`Reset to 100% (0 dB)`}
          >
            Reset
          </button>
        </div>
      </div>

      {/* Audio Role Selection */}
      <div className="space-y-1.5">
        <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider flex items-center gap-1.5">
          <Mic className="w-3 h-3" /> <Trans>Audio Role</Trans>
        </label>
        <select
          value={selectedClip.audioRole || ""}
          onChange={(e) =>
            updateClip({
              audioRole: (e.target.value as any) || undefined,
            })
          }
          className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 cursor-pointer"
        >
          <option value="">
            <Trans>Auto</Trans>
          </option>
          <option value="voice">
            <Trans>Narration</Trans>
          </option>
          <option value="music">
            <Trans>Music</Trans>
          </option>
          <option value="sfx">
            <Trans>Sound Effects</Trans>
          </option>
        </select>
      </div>

      {/* Fades: Fade In & Fade Out */}
      <div className="space-y-1.5">
        <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
          <Trans>Fade Transitions</Trans>
        </label>
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1 bg-zinc-50 dark:bg-navidark-900 p-2 rounded border border-zinc-200 dark:border-navidark-700">
            <span className="text-[10px] text-zinc-400">
              <Trans>Fade In (s)</Trans>
            </span>
            <input
              type="number"
              step="0.1"
              min="0"
              max={selectedClip.duration}
              value={(selectedClip.fadeIn || 0).toFixed(1)}
              onChange={(e) =>
                updateClip({
                  fadeIn: Math.max(0, parseFloat(e.target.value) || 0),
                })
              }
              className="w-full bg-transparent text-xs font-mono text-zinc-800 dark:text-zinc-200 outline-none"
            />
          </div>
          <div className="space-y-1 bg-zinc-50 dark:bg-navidark-900 p-2 rounded border border-zinc-200 dark:border-navidark-700">
            <span className="text-[10px] text-zinc-400">
              <Trans>Fade Out (s)</Trans>
            </span>
            <input
              type="number"
              step="0.1"
              min="0"
              max={selectedClip.duration}
              value={(selectedClip.fadeOut || 0).toFixed(1)}
              onChange={(e) =>
                updateClip({
                  fadeOut: Math.max(0, parseFloat(e.target.value) || 0),
                })
              }
              className="w-full bg-transparent text-xs font-mono text-zinc-800 dark:text-zinc-200 outline-none"
            />
          </div>
        </div>
      </div>

      {/* Auto-Ducking Configuration */}
      <div className="space-y-2.5 bg-zinc-50 dark:bg-navidark-900 p-2.5 rounded border border-zinc-200 dark:border-navidark-700">
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-zinc-800 dark:text-zinc-200">
            <input
              type="checkbox"
              checked={Boolean(selectedClip.ducking)}
              onChange={(e) => updateClip({ ducking: e.target.checked })}
              className="accent-amber-500 rounded"
            />
            <span>
              <Trans>Auto-Duck during voice</Trans>
            </span>
          </label>
          <span className="text-[10px] uppercase font-bold text-amber-500">
            {selectedClip.ducking ? t`Active` : t`Off`}
          </span>
        </div>

        {selectedClip.ducking && (
          <div className="space-y-1 pt-1 border-t border-zinc-200 dark:border-navidark-700">
            <div className="flex justify-between items-center text-[11px] text-zinc-500 dark:text-zinc-400">
              <span>
                <Trans>Attenuation</Trans>
              </span>
              <span className="font-mono text-amber-500 font-bold">
                <Trans>
                  {Math.round((1 - duckingAmount) * 100)}% reduction (
                  {(20 * Math.log10(duckingAmount)).toFixed(1)} dB)
                </Trans>
              </span>
            </div>
            <input
              type="range"
              min="0.05"
              max="0.8"
              step="0.05"
              value={duckingAmount}
              onChange={(e) =>
                updateClip({ duckingAmount: parseFloat(e.target.value) })
              }
              className="w-full accent-amber-500 cursor-pointer h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-lg"
            />
          </div>
        )}
      </div>
    </div>
  );
}
