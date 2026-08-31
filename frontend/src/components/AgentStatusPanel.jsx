import React, { useState } from 'react';
import { Activity, Play, Zap, Clock, Server, CheckCircle, ShieldAlert, Cpu } from 'lucide-react';

export default function AgentStatusPanel({ statusData, onTriggerLayer, triggering }) {
  const layers = statusData?.layers || {};
  const themeLayer = layers.theme_portfolio || {};
  const overlayLayer = layers.derivatives_overlay || {};
  const watchdogLayer = layers.expiration_watchdog || {};

  const formatRunTime = (isoString) => {
    if (!isoString) return 'Pending First Run';
    try {
      const dt = new Date(isoString);
      return dt.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      }) + ' UTC';
    } catch {
      return isoString;
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl flex flex-col gap-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-emerald-400" />
            <h2 className="text-lg font-bold text-slate-100">Agent Architecture & Cadence Health</h2>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Three asynchronous cadences operating against Alpaca Paper Trading & Groq LLM.
          </p>
        </div>

        {/* Global Agent Status Badge */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/20 px-3 py-1.5 rounded-lg">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
            </span>
            <span className="text-xs font-bold text-emerald-400 uppercase tracking-wider">
              {statusData?.status || 'Online'}
            </span>
          </div>

          <div className="text-xs font-mono bg-slate-950 px-3 py-1.5 rounded-lg border border-slate-800 text-slate-300">
            {statusData?.trading_mode || 'Alpaca Paper Trading'}
          </div>
        </div>
      </div>

      {/* Layer Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* 1. Daily Theme Portfolio Layer */}
        <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-4 flex flex-col justify-between gap-3">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-bold text-indigo-400 uppercase tracking-wider">
                Layer 1: Theme & Portfolio
              </span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                Daily
              </span>
            </div>
            <p className="text-xs text-slate-400 mb-3">
              News catalyst clustering → Thematic discovery → Target weighting & equity rebalance.
            </p>
            <div className="text-[11px] font-mono text-slate-300 flex flex-col gap-1 border-t border-slate-800/60 pt-2">
              <div className="flex justify-between">
                <span className="text-slate-500">Cadence:</span>
                <span>{themeLayer.cadence || 'Every 24 hours'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Last Execution:</span>
                <span className="text-indigo-300">{formatRunTime(themeLayer.last_run)}</span>
              </div>
            </div>
          </div>

          <button
            onClick={() => onTriggerLayer('theme')}
            disabled={triggering}
            className="w-full flex items-center justify-center gap-1.5 text-xs font-semibold py-2 px-3 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white transition-colors"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            Trigger Theme Rebalance
          </button>
        </div>

        {/* 2. Hourly Derivatives Overlay Layer */}
        <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-4 flex flex-col justify-between gap-3">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-bold text-purple-400 uppercase tracking-wider">
                Layer 2: Derivatives Overlay
              </span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-purple-500/10 text-purple-300 border border-purple-500/20">
                Hourly
              </span>
            </div>
            <p className="text-xs text-slate-400 mb-3">
              News-gate → VWAP/Volume confirmation → Protective Puts / Collars / Vertical Spreads.
            </p>
            <div className="text-[11px] font-mono text-slate-300 flex flex-col gap-1 border-t border-slate-800/60 pt-2">
              <div className="flex justify-between">
                <span className="text-slate-500">Cadence:</span>
                <span>{overlayLayer.cadence || 'Every 60 minutes'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Last Execution:</span>
                <span className="text-purple-300">{formatRunTime(overlayLayer.last_run)}</span>
              </div>
            </div>
          </div>

          <button
            onClick={() => onTriggerLayer('overlay')}
            disabled={triggering}
            className="w-full flex items-center justify-center gap-1.5 text-xs font-semibold py-2 px-3 rounded-lg bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white transition-colors"
          >
            <Zap className="w-3.5 h-3.5" />
            Trigger Overlay Risk Check
          </button>
        </div>

        {/* 3. Expiration Watchdog Layer */}
        <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-4 flex flex-col justify-between gap-3">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-bold text-amber-400 uppercase tracking-wider">
                Layer 3: Expiration Watchdog
              </span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20">
                Hourly
              </span>
            </div>
            <p className="text-xs text-slate-400 mb-3">
              Monitors option DTE → Enforces zero-tolerance roll/close rule at ≤ 5 DTE threshold.
            </p>
            <div className="text-[11px] font-mono text-slate-300 flex flex-col gap-1 border-t border-slate-800/60 pt-2">
              <div className="flex justify-between">
                <span className="text-slate-500">Threshold:</span>
                <span className="text-amber-400 font-bold">≤ 5 Trading Days</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Last Execution:</span>
                <span className="text-amber-300">{formatRunTime(watchdogLayer.last_run)}</span>
              </div>
            </div>
          </div>

          <button
            onClick={() => onTriggerLayer('watchdog')}
            disabled={triggering}
            className="w-full flex items-center justify-center gap-1.5 text-xs font-semibold py-2 px-3 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white transition-colors"
          >
            <ShieldAlert className="w-3.5 h-3.5" />
            Trigger Watchdog Scan
          </button>
        </div>
      </div>

      {/* Provider Details Footer */}
      <div className="flex flex-wrap items-center justify-between text-xs font-mono text-slate-400 bg-slate-950/60 p-3 rounded-lg border border-slate-800">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-cyan-400" />
          <span>
            LLM Provider: <strong className="text-slate-200">Groq ({statusData?.llm_model || 'openai/gpt-oss-120b'})</strong>
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Server className="w-4 h-4 text-indigo-400" />
          <span>
            Backend Engine: <strong className="text-slate-200">FastAPI + APScheduler + SQLite</strong>
          </span>
        </div>
      </div>
    </div>
  );
}
