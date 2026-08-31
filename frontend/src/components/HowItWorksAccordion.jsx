import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Layers, ShieldCheck, Clock, Cpu, Server } from 'lucide-react';

export default function HowItWorksAccordion({ statusData }) {
  const [isOpen, setIsOpen] = useState(false);

  const layers = statusData?.layers || {};
  const themeLayer = layers.theme_portfolio || {};
  const overlayLayer = layers.derivatives_overlay || {};
  const watchdogLayer = layers.expiration_watchdog || {};

  const formatRunTime = (isoString) => {
    if (!isoString) return 'Pending First Run';
    try {
      const dt = new Date(isoString);
      return (
        dt.toLocaleTimeString('en-US', {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        }) + ' UTC'
      );
    } catch {
      return isoString;
    }
  };

  return (
    <div className="bg-white border border-slate-200/80 rounded-2xl shadow-xs overflow-hidden transition-all">
      {/* Accordion Trigger */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-neutral-50/80 transition-colors text-left cursor-pointer"
      >
        <div className="flex items-center gap-3">
          <div className="p-1.5 rounded-lg bg-neutral-100 text-neutral-800 border border-neutral-200">
            <Layers className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-neutral-900">How It Works: 3-Layer Agent Architecture</h3>
            <p className="text-xs text-neutral-500">
              Technical execution rules, cadences, risk gates, and LLM orchestration details
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-neutral-500 text-xs font-medium">
          <span>{isOpen ? 'Collapse Details' : 'View Architecture'}</span>
          {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </div>
      </button>

      {/* Accordion Content */}
      {isOpen && (
        <div className="px-6 pb-6 pt-2 border-t border-slate-100 flex flex-col gap-6">
          {/* Three Layers Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
            {/* Layer 1 */}
            <div className="bg-neutral-50 border border-neutral-200/70 rounded-xl p-4 flex flex-col justify-between gap-3">
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-bold uppercase tracking-wider text-neutral-900">
                    1. Theme & Portfolio
                  </span>
                  <span className="text-[10px] font-mono font-medium px-2 py-0.5 rounded bg-neutral-200/70 text-neutral-700">
                    Daily
                  </span>
                </div>
                <p className="text-xs text-neutral-600 leading-relaxed">
                  Fetches financial news via Alpaca $\rightarrow$ Prompts Groq LLM to cluster emerging macro themes $\rightarrow$
                  Maps to liquid equities $\rightarrow$ Equal-weight portfolio rebalancing.
                </p>
              </div>
              <div className="text-[11px] font-mono text-neutral-500 border-t border-neutral-200/60 pt-2 flex justify-between">
                <span>Last execution:</span>
                <span className="font-semibold text-neutral-800">{formatRunTime(themeLayer.last_run)}</span>
              </div>
            </div>

            {/* Layer 2 */}
            <div className="bg-neutral-50 border border-neutral-200/70 rounded-xl p-4 flex flex-col justify-between gap-3">
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-bold uppercase tracking-wider text-neutral-900">
                    2. Derivatives Overlay
                  </span>
                  <span className="text-[10px] font-mono font-medium px-2 py-0.5 rounded bg-neutral-200/70 text-neutral-700">
                    Hourly
                  </span>
                </div>
                <p className="text-xs text-neutral-600 leading-relaxed">
                  Evaluates delta of held stocks $\rightarrow$ News-gated $\rightarrow$ Confirmed by VWAP/volume divergence $\rightarrow$
                  Deploys protective puts, zero-cost collars, covered calls, or vertical spreads.
                </p>
              </div>
              <div className="text-[11px] font-mono text-neutral-500 border-t border-neutral-200/60 pt-2 flex justify-between">
                <span>Last execution:</span>
                <span className="font-semibold text-neutral-800">{formatRunTime(overlayLayer.last_run)}</span>
              </div>
            </div>

            {/* Layer 3 */}
            <div className="bg-neutral-50 border border-neutral-200/70 rounded-xl p-4 flex flex-col justify-between gap-3">
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-bold uppercase tracking-wider text-neutral-900">
                    3. Expiration Watchdog
                  </span>
                  <span className="text-[10px] font-mono font-medium px-2 py-0.5 rounded bg-neutral-200/70 text-neutral-700">
                    Hourly
                  </span>
                </div>
                <p className="text-xs text-neutral-600 leading-relaxed">
                  Monitors active options DTE $\rightarrow$ Enforces strict close-or-roll mandate for any hedge $\le 5$ trading days.
                  Guarantees no positions cross into final week unmanaged.
                </p>
              </div>
              <div className="text-[11px] font-mono text-neutral-500 border-t border-neutral-200/60 pt-2 flex justify-between">
                <span>Last execution:</span>
                <span className="font-semibold text-neutral-800">{formatRunTime(watchdogLayer.last_run)}</span>
              </div>
            </div>
          </div>

          {/* System Specs Bar */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs bg-neutral-100/70 p-3.5 rounded-xl border border-neutral-200 text-neutral-700">
            <div className="flex items-center gap-2">
              <Cpu className="w-4 h-4 text-neutral-700 shrink-0" />
              <span>
                LLM Provider: <strong className="text-neutral-900">Groq ({statusData?.llm_model || 'openai/gpt-oss-120b'})</strong>
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Server className="w-4 h-4 text-neutral-700 shrink-0" />
              <span>
                Backend Stack: <strong className="text-neutral-900">FastAPI • APScheduler • SQLite</strong>
              </span>
            </div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-neutral-700 shrink-0" />
              <span>
                Broker Interface: <strong className="text-neutral-900">{statusData?.trading_mode || 'Alpaca Paper'}</strong>
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
