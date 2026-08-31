import React, { useState } from 'react';
import { Shield, AlertTriangle, CheckCircle2, RefreshCw, Calendar, ArrowRight } from 'lucide-react';

export default function ActiveHedges({ hedgesData, loading }) {
  const [filter, setFilter] = useState('all');

  const hedges = hedgesData?.hedges || [];
  const openCount = hedgesData?.open_count || 0;
  const nearExpiryCount = hedgesData?.near_expiry_count || 0;

  const filteredHedges = hedges.filter((h) => {
    if (filter === 'open') return h.status === 'open';
    if (filter === 'near_expiry') return h.is_near_expiry;
    if (filter === 'history') return h.status !== 'open';
    return true;
  });

  const getStructureBadge = (type) => {
    switch (type) {
      case 'protective_put':
        return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
      case 'collar':
        return 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30';
      case 'covered_call':
        return 'bg-purple-500/10 text-purple-400 border-purple-500/30';
      case 'vertical_spread':
        return 'bg-blue-500/10 text-blue-400 border-blue-500/30';
      default:
        return 'bg-slate-700/30 text-slate-300 border-slate-600/30';
    }
  };

  const formatStructureName = (type) => {
    return (type || '')
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ');
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl flex flex-col gap-5">
      {/* Header & Tabs */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-emerald-400" />
          <h2 className="text-lg font-bold text-slate-100">Derivatives Overlay & Active Hedges</h2>
          {nearExpiryCount > 0 && (
            <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse">
              <AlertTriangle className="w-3.5 h-3.5" />
              {nearExpiryCount} Near Expiry
            </span>
          )}
        </div>

        {/* Filter Buttons */}
        <div className="flex items-center gap-1 bg-slate-950/80 p-1 rounded-lg border border-slate-800 text-xs">
          <button
            onClick={() => setFilter('all')}
            className={`px-3 py-1 rounded transition-colors ${
              filter === 'all' ? 'bg-indigo-600 text-white font-semibold' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            All ({hedges.length})
          </button>
          <button
            onClick={() => setFilter('open')}
            className={`px-3 py-1 rounded transition-colors ${
              filter === 'open' ? 'bg-emerald-600 text-white font-semibold' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Open ({openCount})
          </button>
          <button
            onClick={() => setFilter('near_expiry')}
            className={`px-3 py-1 rounded transition-colors ${
              filter === 'near_expiry' ? 'bg-amber-600 text-white font-semibold' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Critical DTE ({nearExpiryCount})
          </button>
          <button
            onClick={() => setFilter('history')}
            className={`px-3 py-1 rounded transition-colors ${
              filter === 'history' ? 'bg-slate-700 text-white font-semibold' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Closed / Rolled
          </button>
        </div>
      </div>

      {/* Expiration Watchdog Policy Alert */}
      <div className="text-xs bg-slate-950/60 border border-slate-800/80 rounded-lg p-3 text-slate-300 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-400"></span>
          <span>
            <strong className="text-slate-100">Watchdog Mandate:</strong> Automatic close or roll triggered at{' '}
            <span className="font-mono font-bold text-amber-400">≤ {hedges[0]?.threshold_days || 5} DTE</span>. Zero positions cross into final week.
          </span>
        </div>
        <span className="font-mono text-slate-400 text-[11px]">Strict Risk Overlay Mode</span>
      </div>

      {/* Hedges Table */}
      <div className="overflow-x-auto border border-slate-800 rounded-lg">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-950/80 text-slate-400 uppercase font-semibold border-b border-slate-800">
            <tr>
              <th className="py-2.5 px-3">Underlying</th>
              <th className="py-2.5 px-3">Structure</th>
              <th className="py-2.5 px-3">Legs Specification</th>
              <th className="py-2.5 px-3">Expiration Date</th>
              <th className="py-2.5 px-3 text-center">DTE Status</th>
              <th className="py-2.5 px-3 text-center">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono">
            {filteredHedges.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-8 text-center text-slate-500 font-sans">
                  No hedge positions match current filter.
                </td>
              </tr>
            ) : (
              filteredHedges.map((h) => {
                const isCritical = h.is_near_expiry;
                const isClosed = h.status === 'closed';
                const isRolled = h.status === 'rolled';

                return (
                  <tr
                    key={h.id}
                    className={`transition-colors ${
                      isCritical
                        ? 'bg-amber-950/20 hover:bg-amber-950/30'
                        : 'hover:bg-slate-800/40'
                    }`}
                  >
                    <td className="py-3 px-3 font-bold text-slate-100 font-mono text-sm">
                      {h.underlying_ticker}
                    </td>

                    <td className="py-3 px-3">
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-[11px] font-sans font-semibold border ${getStructureBadge(
                          h.structure_type
                        )}`}
                      >
                        {formatStructureName(h.structure_type)}
                      </span>
                    </td>

                    <td className="py-3 px-3">
                      <div className="flex flex-col gap-1 text-[11px]">
                        {h.legs?.map((leg, idx) => (
                          <div key={idx} className="flex items-center gap-1.5 text-slate-300">
                            <span
                              className={`uppercase text-[10px] font-bold px-1 rounded ${
                                leg.side === 'buy' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'
                              }`}
                            >
                              {leg.side}
                            </span>
                            <span>
                              {leg.qty || 1}x {leg.strike ? `$${leg.strike}` : ''} {leg.type?.toUpperCase()}
                            </span>
                            <span className="text-slate-500 font-sans text-[10px]">({leg.symbol})</span>
                          </div>
                        ))}
                      </div>
                    </td>

                    <td className="py-3 px-3 text-slate-300">
                      <div className="flex items-center gap-1.5">
                        <Calendar className="w-3.5 h-3.5 text-slate-400" />
                        <span>{h.expires_at?.split('T')[0]}</span>
                      </div>
                    </td>

                    <td className="py-3 px-3 text-center">
                      {isCritical ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                          <AlertTriangle className="w-3 h-3" />
                          {h.days_to_expiry} Days (Roll Alert)
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono bg-slate-800 text-slate-300">
                          {h.days_to_expiry} DTE
                        </span>
                      )}
                    </td>

                    <td className="py-3 px-3 text-center">
                      <span
                        className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-sans uppercase font-bold ${
                          h.status === 'open'
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                            : isRolled
                            ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                            : 'bg-slate-800 text-slate-400 border border-slate-700'
                        }`}
                      >
                        {h.status}
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
