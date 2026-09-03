import React, { useState } from 'react';
import { Search, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react';

export default function DecisionLogFeed({ decisions, loading }) {
  const [filterLayer, setFilterLayer] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedIds, setExpandedIds] = useState({});

  const toggleExpand = (id) => {
    setExpandedIds((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const filteredDecisions = (decisions || []).filter((d) => {
    const matchesLayer = filterLayer === 'all' || d.layer === filterLayer;
    const matchesSearch =
      searchQuery === '' ||
      d.action_taken?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      d.reasoning?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      d.layer?.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesLayer && matchesSearch;
  });

  const getLayerName = (layer) => {
    switch (layer) {
      case 'theme':
        return 'Theme & Portfolio';
      case 'overlay':
        return 'Derivatives Overlay';
      case 'watchdog':
        return 'Expiration Watchdog';
      case 'assistant_reasoning':
        return 'Assistant Reasoning';
      case 'system':
        return 'System Control';
      default:
        return layer?.toUpperCase() || 'Agent Layer';
    }
  };

  const isWarningEntry = (item) => {
    const layer = item.layer?.toLowerCase() || '';
    const action = item.action_taken?.toLowerCase() || '';
    const reasoning = item.reasoning?.toLowerCase() || '';
    
    return (
      (layer === 'watchdog' && (action.includes('roll') || action.includes('close') || action.includes('threshold'))) ||
      action.includes('near-expiry') ||
      action.includes('expiry alert') ||
      action.includes('downside') ||
      action.includes('paused') ||
      reasoning.includes('dte') ||
      reasoning.includes('divergence')
    );
  };

  const formatTimestamp = (isoString) => {
    if (!isoString) return '';
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
    <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-sm flex flex-col gap-5 h-full">
      {/* Header & Filter Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-4">
        <div>
          <h2 className="text-sm font-semibold tracking-tight text-neutral-900 uppercase">
            Decision Audit Trail
          </h2>
          <p className="text-xs text-neutral-500 mt-0.5">
            Transparent chronological record of autonomous reasoning and executions
          </p>
        </div>

        {/* Filters and Search */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-neutral-400" />
            <input
              type="text"
              placeholder="Search audit trail..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="bg-neutral-50 border border-neutral-200 rounded-lg pl-8 pr-3 py-1.5 text-xs text-neutral-900 placeholder-neutral-400 focus:outline-none focus:border-neutral-900 focus:bg-white w-40 transition-all"
            />
          </div>

          <div className="flex items-center gap-1 bg-neutral-100 p-1 rounded-lg border border-neutral-200 text-xs">
            {['all', 'theme', 'overlay', 'watchdog', 'assistant_reasoning', 'system'].map((l) => (
              <button
                key={l}
                onClick={() => setFilterLayer(l)}
                className={`px-2.5 py-1 rounded-md capitalize font-medium transition-colors ${
                  filterLayer === l
                    ? 'bg-neutral-900 text-white shadow-xs'
                    : 'text-neutral-600 hover:text-neutral-900 hover:bg-neutral-200/60'
                }`}
              >
                {l === 'all' ? 'All' : l.replace('_', ' ')}
              </button>
            ))}
          </div>
        </div>
      </div>


      {/* Decision Feed List */}
      <div className="flex flex-col gap-3.5 overflow-y-auto pr-1 flex-1 max-h-[640px]">
        {loading && (!decisions || decisions.length === 0) ? (
          <div className="flex flex-col gap-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-28 bg-neutral-50 border border-neutral-200/60 rounded-xl animate-pulse"></div>
            ))}
          </div>
        ) : filteredDecisions.length === 0 ? (
          <div className="text-center py-16 text-neutral-400 text-xs bg-neutral-50 rounded-xl border border-dashed border-neutral-200">
            No audit log entries matching the selected criteria.
          </div>
        ) : (
          filteredDecisions.map((item) => {
            const isWarning = isWarningEntry(item);
            const isExpanded = !!expandedIds[item.id];
            const hasInputSummary = item.input_summary && Object.keys(item.input_summary).length > 0;

            return (
              <div
                key={item.id}
                className={`rounded-xl p-4.5 border transition-all flex flex-col gap-2.5 ${
                  isWarning
                    ? 'bg-amber-50/75 border-amber-200/90 shadow-xs'
                    : 'bg-white border-neutral-200/80 hover:border-neutral-300 shadow-xs'
                }`}
              >
                {/* Meta Top Bar */}
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span
                      className={`font-semibold text-[11px] px-2 py-0.5 rounded-md border ${
                        isWarning
                          ? 'bg-amber-100/90 text-amber-900 border-amber-300'
                          : 'bg-neutral-100 text-neutral-800 border-neutral-200'
                      }`}
                    >
                      {getLayerName(item.layer)}
                    </span>

                    {isWarning && (
                      <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-amber-800">
                        <AlertTriangle className="w-3 h-3 text-[#F5A623]" />
                        Risk/Watchdog Event
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2 font-mono text-neutral-400 text-[11px]">
                    <span>{formatTimestamp(item.timestamp)}</span>
                    <span>•</span>
                    <span>#LOG-{item.id}</span>
                  </div>
                </div>

                {/* Action Taken Headline */}
                <div
                  className={`text-sm font-semibold leading-snug tracking-tight ${
                    isWarning ? 'text-amber-950' : 'text-neutral-900'
                  }`}
                >
                  {item.action_taken}
                </div>

                {/* Plain-Language Reasoning */}
                <div
                  className={`text-xs leading-relaxed p-3 rounded-lg border whitespace-pre-line ${
                    isWarning
                      ? 'bg-amber-100/40 border-amber-200/80 text-amber-950'
                      : 'bg-neutral-50/90 border-neutral-200/60 text-neutral-700'
                  }`}
                >
                  <span className="font-semibold text-neutral-900 block mb-0.5 text-[11px] uppercase tracking-wider">
                    Agent Rationale:
                  </span>
                  {item.reasoning}
                </div>

                {/* Collapsible Inputs Context */}
                {hasInputSummary && (
                  <div className="pt-0.5">
                    <button
                      onClick={() => toggleExpand(item.id)}
                      className="text-[11px] text-neutral-500 hover:text-neutral-900 flex items-center gap-1 transition-colors font-medium cursor-pointer"
                    >
                      {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                      {isExpanded ? 'Hide Catalyst & Risk Inputs' : 'Inspect Underlying Inputs'}
                    </button>

                    {isExpanded && (
                      <div className="mt-2 p-3 bg-neutral-900 text-neutral-100 border border-neutral-800 rounded-lg font-mono text-[11px] overflow-x-auto">
                        <pre>{JSON.stringify(item.input_summary, null, 2)}</pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
