import React from 'react';
import { X, Play, Zap, ShieldAlert, Layers } from 'lucide-react';

export default function DevControlsModal({ isOpen, onClose, onTriggerLayer, triggering }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-neutral-900/40 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="bg-white border border-neutral-200 rounded-2xl p-6 shadow-2xl max-w-md w-full flex flex-col gap-5">
        <div className="flex items-center justify-between border-b border-neutral-100 pb-3">
          <div>
            <h3 className="text-sm font-bold text-neutral-900">Developer & Judge Manual Controls</h3>
            <p className="text-xs text-neutral-500">
              Trigger autonomous layer executions on demand
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-neutral-400 hover:text-neutral-700 hover:bg-neutral-100 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex flex-col gap-2.5">
          <button
            onClick={() => onTriggerLayer('theme')}
            disabled={triggering}
            className="flex items-center justify-between p-3 rounded-xl border border-neutral-200 hover:border-neutral-900 hover:bg-neutral-50 text-left transition-all text-xs font-semibold text-neutral-900 disabled:opacity-50 cursor-pointer"
          >
            <div className="flex items-center gap-2.5">
              <div className="p-1.5 rounded-lg bg-neutral-100 text-neutral-800">
                <Play className="w-3.5 h-3.5 fill-current" />
              </div>
              <div>
                <span className="block">Trigger Layer 1: Theme & Portfolio</span>
                <span className="text-[11px] font-normal text-neutral-500">
                  Runs news clustering & rebalancing
                </span>
              </div>
            </div>
            <span className="text-neutral-400 font-mono text-[10px]">Daily</span>
          </button>

          <button
            onClick={() => onTriggerLayer('overlay')}
            disabled={triggering}
            className="flex items-center justify-between p-3 rounded-xl border border-neutral-200 hover:border-neutral-900 hover:bg-neutral-50 text-left transition-all text-xs font-semibold text-neutral-900 disabled:opacity-50 cursor-pointer"
          >
            <div className="flex items-center gap-2.5">
              <div className="p-1.5 rounded-lg bg-neutral-100 text-neutral-800">
                <Zap className="w-3.5 h-3.5" />
              </div>
              <div>
                <span className="block">Trigger Layer 2: Derivatives Overlay</span>
                <span className="text-[11px] font-normal text-neutral-500">
                  Runs VWAP risk-check & options hedging
                </span>
              </div>
            </div>
            <span className="text-neutral-400 font-mono text-[10px]">Hourly</span>
          </button>

          <button
            onClick={() => onTriggerLayer('watchdog')}
            disabled={triggering}
            className="flex items-center justify-between p-3 rounded-xl border border-neutral-200 hover:border-neutral-900 hover:bg-neutral-50 text-left transition-all text-xs font-semibold text-neutral-900 disabled:opacity-50 cursor-pointer"
          >
            <div className="flex items-center gap-2.5">
              <div className="p-1.5 rounded-lg bg-neutral-100 text-neutral-800">
                <ShieldAlert className="w-3.5 h-3.5" />
              </div>
              <div>
                <span className="block">Trigger Layer 3: Expiration Watchdog</span>
                <span className="text-[11px] font-normal text-neutral-500">
                  Enforces close/roll on ≤ 5 DTE hedges
                </span>
              </div>
            </div>
            <span className="text-neutral-400 font-mono text-[10px]">Hourly</span>
          </button>

          <button
            onClick={() => onTriggerLayer('all')}
            disabled={triggering}
            className="flex items-center justify-center gap-2 p-3 mt-1 rounded-xl bg-neutral-900 hover:bg-neutral-800 text-white text-xs font-semibold transition-colors disabled:opacity-50 cursor-pointer"
          >
            <Layers className="w-4 h-4" />
            <span>Run Complete Cycle (All 3 Layers)</span>
          </button>
        </div>

        <div className="text-[11px] text-neutral-400 text-center font-mono border-t border-neutral-100 pt-3">
          Autonomous mode continues running via APScheduler in background.
        </div>
      </div>
    </div>
  );
}
