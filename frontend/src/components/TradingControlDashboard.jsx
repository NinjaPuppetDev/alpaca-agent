import React, { useState, useEffect } from 'react';
import { AlertTriangle, Zap, AlertCircle, RefreshCw } from 'lucide-react';

export default function TradingControlDashboard({ 
  onLiquidationComplete,
  showToast,
  statusData
}) {
  const [accountSummary, setAccountSummary] = useState(null);
  const [positions, setPositions] = useState([]);
  const [optionPositions, setOptionPositions] = useState([]);
  const [backendConnected, setBackendConnected] = useState(true);
  const [liquidatingMode, setLiquidatingMode] = useState(null); // 'smart' | 'all' | null
  const [optionLiquidatingMode, setOptionLiquidatingMode] = useState(null);
  const [showConfirmationModal, setShowConfirmationModal] = useState(false);
  const [showSmartConfirmationModal, setShowSmartConfirmationModal] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState(new Date());
  const [autoRefreshActive, setAutoRefreshActive] = useState(true);
  const assistantReasoningLayer = statusData?.layers?.assistant_reasoning || {};

  // Poll account data every 3 seconds
  const fetchAccountData = async () => {
    try {
      const [summaryRes, positionsRes] = await Promise.all([
        fetch(`${import.meta.env.VITE_API_URL}/api/account/summary`).then(r => r.json()).catch(() => null),
        fetch(`${import.meta.env.VITE_API_URL}/api/account/positions`).then(r => r.json()).catch(() => null),
      ]);

      if (summaryRes) {
        setAccountSummary(summaryRes);
        setBackendConnected(true);
      }
      if (positionsRes) {
        setPositions(positionsRes.positions || []);
        setOptionPositions(positionsRes.option_positions || []);
      }
      
      setLastRefreshed(new Date());
    } catch (err) {
      console.error('Failed to fetch account data:', err);
      setBackendConnected(false);
    }
  };

  useEffect(() => {
    fetchAccountData();
    
    if (!autoRefreshActive) return;
    
    const interval = setInterval(fetchAccountData, 3000);
    return () => clearInterval(interval);
  }, [autoRefreshActive]);

  // Calculate losing positions
  const losingPositions = positions.filter(p => p.unrealized_pl < 0);
  const winningPositions = positions.filter(p => p.unrealized_pl >= 0);
  const totalPositions = positions.length;
  const optionPositionCount = optionPositions.length;

  const handleSmartLiquidate = async () => {
    setLiquidatingMode('smart');
    try {
      const res = await fetch(`${import.meta.env.VITE_API_URL}/api/positions/liquidate-smart`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      const data = await res.json();
      if (res.ok) {
        showToast(`✓ Smart Liquidate: ${data.closed_count} position(s) closed. Freed $${data.freed_cash.toFixed(2)}`, 'success');
        await fetchAccountData();
        onLiquidationComplete?.();
      } else {
        showToast(`✗ Smart Liquidate Failed: ${data.detail || 'Unknown error'}`, 'error');
      }
    } catch (err) {
      showToast(`✗ Error: ${err.message}`, 'error');
    } finally {
      setLiquidatingMode(null);
      setShowSmartConfirmationModal(false);
    }
  };

  const handleLiquidateAll = async () => {
    setLiquidatingMode('all');
    try {
      const res = await fetch(`${import.meta.env.VITE_API_URL}/api/positions/liquidate-all`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      const data = await res.json();
      if (res.ok) {
        showToast(`🚨 LIQUIDATED ALL: ${data.closed_count} position(s). Freed $${data.freed_cash.toFixed(2)}`, 'warning');
        await fetchAccountData();
        onLiquidationComplete?.();
      } else {
        showToast(`✗ Emergency Liquidation Failed: ${data.detail || 'Unknown error'}`, 'error');
      }
    } catch (err) {
      showToast(`✗ Error: ${err.message}`, 'error');
    } finally {
      setLiquidatingMode(null);
      setShowConfirmationModal(false);
    }
  };

  const handleOptionLiquidation = async (mode) => {
    const isSmart = mode === 'smart';
    const endpoint = isSmart ? '/api/options/liquidate-smart' : '/api/options/liquidate-all';
    setOptionLiquidatingMode(mode);
    try {
      const res = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
      const data = await res.json();
      if (res.ok) {
        showToast(
          `${isSmart ? 'Smart option liquidation' : 'Option liquidation'}: ${data.closed_count} contract position(s) closed.`,
          isSmart ? 'success' : 'warning'
        );
        await fetchAccountData();
        onLiquidationComplete?.();
      } else {
        showToast(`Option liquidation failed: ${data.detail || 'Unknown error'}`, 'error');
      }
    } catch (err) {
      showToast(`Option liquidation error: ${err.message}`, 'error');
    } finally {
      setOptionLiquidatingMode(null);
    }
  };

  if (!backendConnected) {
    return (
      <div className="bg-rose-50 border-2 border-rose-300 rounded-xl p-4 mb-6">
        <div className="flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-rose-600 flex-shrink-0" />
          <div>
            <div className="font-semibold text-rose-900">⚠️ BACKEND DISCONNECTED</div>
            <div className="text-sm text-rose-800">
              Run <code className="bg-rose-100 px-2 py-1 rounded text-xs font-mono">execution_engine.py</code> on http://localhost:8000
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="bg-white border border-neutral-200 rounded-xl p-4 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">Assistant Reasoning Guardrail</div>
            <div className="text-sm font-bold text-neutral-900 mt-1">VWAP + hedge overlay checks before order routing</div>
          </div>
          <div className={`px-2.5 py-1 rounded-full text-[10px] font-semibold ${assistantReasoningLayer.health === 'healthy' ? 'bg-neutral-100 text-neutral-800 border border-neutral-200' : 'bg-amber-100 text-amber-800 border border-amber-200'}`}>
            {assistantReasoningLayer.health === 'healthy' ? 'Enabled' : 'Paused'}
          </div>
        </div>
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs text-neutral-700">
          <div className="bg-neutral-50 border border-neutral-200 rounded-lg p-2.5">
            <div className="text-[10px] uppercase tracking-wider text-neutral-500">Last Approval Check</div>
            <div className="font-mono mt-1">{assistantReasoningLayer.last_run || 'Pending first run'}</div>
          </div>
          <div className="bg-neutral-50 border border-neutral-200 rounded-lg p-2.5">
            <div className="text-[10px] uppercase tracking-wider text-neutral-500">Guardrail Logic</div>
            <div className="font-medium mt-1">VWAP chase gate + 8% partial TP + option hedge confirmation</div>
          </div>
        </div>
      </div>

      {/* Account Summary Panel */}
      <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-bold uppercase tracking-wider text-neutral-900">
            Trading Control Dashboard
          </h3>
          <button
            onClick={fetchAccountData}
            className="text-neutral-500 hover:text-neutral-900 transition"
            title="Refresh account data"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>

        {/* Account Metrics */}
        {accountSummary && (
          <div className="grid grid-cols-3 gap-3 mb-5">
            {/* Equity */}
            <div className="bg-neutral-50 border border-neutral-200 rounded-lg p-3">
              <span className="text-xs text-neutral-600 font-medium">Equity</span>
              <div className="text-lg font-bold font-mono text-neutral-900">
                ${accountSummary.equity?.toFixed(2)}
              </div>
            </div>

            {/* Cash */}
            <div className={`border rounded-lg p-3 ${
              accountSummary.cash <= 0
                ? 'bg-rose-50 border-rose-300'
                : 'bg-neutral-50 border-neutral-200'
            }`}>
              <span className={`text-xs font-medium ${
                accountSummary.cash <= 0 ? 'text-rose-700' : 'text-neutral-600'
              }`}>
                Cash
              </span>
              <div className={`text-lg font-bold font-mono ${
                accountSummary.cash <= 0 ? 'text-rose-900' : 'text-neutral-900'
              }`}>
                ${accountSummary.cash?.toFixed(2)}
              </div>
            </div>

            {/* Buying Power */}
            <div className={`border rounded-lg p-3 ${
              accountSummary.buying_power <= 0
                ? 'bg-amber-50 border-amber-300'
                : 'bg-neutral-50 border-neutral-200'
            }`}>
              <span className={`text-xs font-medium ${
                accountSummary.buying_power <= 0 ? 'text-amber-700' : 'text-neutral-600'
              }`}>
                Buying Power
              </span>
              <div className={`text-lg font-bold font-mono ${
                accountSummary.buying_power <= 0 ? 'text-amber-900' : 'text-neutral-900'
              }`}>
                ${accountSummary.buying_power?.toFixed(2)}
              </div>
            </div>
          </div>
        )}

        {/* Position Summary */}
        <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 mb-5">
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            <div>
              <span className="text-xs text-slate-600 font-medium">Equity Positions</span>
              <div className="text-2xl font-bold text-slate-900">{totalPositions}</div>
            </div>
            <div>
              <span className="text-xs text-neutral-600 font-medium">Option Contracts</span>
              <div className="text-2xl font-bold text-neutral-900">{optionPositionCount}</div>
            </div>
            <div>
              <span className="text-xs text-neutral-600 font-medium">Winning</span>
              <div className="text-2xl font-bold text-neutral-900">{winningPositions.length}</div>
            </div>
            <div>
              <span className="text-xs text-amber-700 font-medium">Losing</span>
              <div className="text-2xl font-bold text-amber-700">{losingPositions.length}</div>
            </div>
            <div>
              <span className="text-xs text-slate-600 font-medium">Last Sync</span>
              <div className="text-sm font-mono text-slate-700">
                {lastRefreshed.toLocaleTimeString()}
              </div>
            </div>
          </div>
        </div>

        {/* Risk Alert */}
        {accountSummary?.cash <= 0 && (
          <div className="bg-rose-100 border border-rose-400 rounded-lg p-3 mb-5 flex items-start gap-2">
            <AlertTriangle className="w-5 h-5 text-rose-600 flex-shrink-0 mt-0.5" />
            <div className="text-sm text-rose-900">
              <div className="font-semibold">Cash Warning:</div>
              <div>Account cash is ${accountSummary.cash?.toFixed(2)}. Use Smart Liquidate to recover cash.</div>
            </div>
          </div>
        )}

        {/* Liquidation Controls */}
        <div className="flex gap-3 pt-2 border-t border-slate-200">
          {/* Smart Liquidate Button */}
          <button
            onClick={() => setShowSmartConfirmationModal(true)}
            disabled={liquidatingMode !== null || losingPositions.length === 0}
            className={`flex-1 py-2.5 px-3 rounded-lg font-medium text-sm transition flex items-center justify-center gap-2 ${
              losingPositions.length === 0
                ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                : liquidatingMode === 'smart'
                ? 'bg-amber-500 text-white animate-pulse'
                : 'bg-amber-400 hover:bg-amber-500 text-white'
            }`}
            title={losingPositions.length === 0 ? 'No losing equity positions to liquidate' : 'Liquidate losing equity positions only'}
          >
            <Zap className="w-4 h-4" />
            Smart Liquidate Equities {losingPositions.length > 0 && `(${losingPositions.length})`}
          </button>

          {/* Liquidate All Button */}
          <button
            onClick={() => setShowConfirmationModal(true)}
            disabled={liquidatingMode !== null || totalPositions === 0}
            className={`flex-1 py-2.5 px-3 rounded-lg font-medium text-sm transition flex items-center justify-center gap-2 ${
              totalPositions === 0
                ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                : liquidatingMode === 'all'
                ? 'bg-rose-600 text-white animate-pulse'
                : 'bg-rose-500 hover:bg-rose-600 text-white'
            }`}
            title={totalPositions === 0 ? 'No equity positions to liquidate' : 'EMERGENCY: Liquidate ALL equity positions'}
          >
            <AlertCircle className="w-4 h-4" />
            Liquidate All Equities {totalPositions > 0 && `(${totalPositions})`}
          </button>
        </div>
        <div className="flex gap-3 pt-3">
          <button
            onClick={() => window.confirm('Close every losing option contract?') && handleOptionLiquidation('smart')}
            disabled={optionLiquidatingMode !== null || !optionPositions.some((p) => p.unrealized_pl < 0)}
            className="flex-1 py-2.5 px-3 rounded-lg font-medium text-sm transition flex items-center justify-center gap-2 bg-violet-100 hover:bg-violet-200 text-violet-800 disabled:bg-slate-100 disabled:text-slate-400"
            title="Close losing option contracts only"
          >
            <Zap className="w-4 h-4" />
            Smart Liquidate Options
          </button>
          <button
            onClick={() => window.confirm('Close every open option contract? Equities will not be affected.') && handleOptionLiquidation('all')}
            disabled={optionLiquidatingMode !== null || optionPositions.length === 0}
            className="flex-1 py-2.5 px-3 rounded-lg font-medium text-sm transition flex items-center justify-center gap-2 bg-fuchsia-100 hover:bg-fuchsia-200 text-fuchsia-800 disabled:bg-slate-100 disabled:text-slate-400"
            title="Close all option contracts without affecting equities"
          >
            <AlertCircle className="w-4 h-4" />
            Liquidate All Options
          </button>
        </div>
        <div className="text-[11px] text-slate-500 pt-1">
          Option controls close contracts directly at Alpaca. Equity liquidation controls do not affect options.
        </div>
      </div>

      {/* Confirmation Modal */}
      {showSmartConfirmationModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 rounded-lg">
          <div className="bg-white rounded-xl shadow-2xl p-6 max-w-sm mx-4">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-12 h-12 rounded-full bg-amber-100 flex items-center justify-center">
                <AlertTriangle className="w-6 h-6 text-amber-600" />
              </div>
              <div>
                <h4 className="font-bold text-neutral-900">SMART LIQUIDATION</h4>
                <p className="text-xs text-neutral-600">This will sell every losing equity position.</p>
              </div>
            </div>
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-6 text-sm text-amber-900">
              You are about to submit market orders for {losingPositions.length} losing position(s). This action cannot be undone.
            </div>
            <div className="flex gap-3">
              <button onClick={() => setShowSmartConfirmationModal(false)} className="flex-1 px-4 py-2 rounded-lg border border-neutral-300 text-neutral-900 font-medium hover:bg-neutral-50 transition">Cancel</button>
              <button onClick={handleSmartLiquidate} className="flex-1 px-4 py-2 rounded-lg bg-amber-500 text-white font-medium hover:bg-amber-600 transition">Confirm</button>
            </div>
          </div>
        </div>
      )}
      {showConfirmationModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 rounded-lg">
          <div className="bg-white rounded-xl shadow-2xl p-6 max-w-sm mx-4">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-12 h-12 rounded-full bg-rose-100 flex items-center justify-center">
                <AlertTriangle className="w-6 h-6 text-rose-600" />
              </div>
              <div>
                <h4 className="font-bold text-neutral-900">EMERGENCY LIQUIDATION</h4>
                <p className="text-xs text-neutral-600">This will close ALL equity positions</p>
              </div>
            </div>

            <div className="bg-rose-50 border border-rose-200 rounded-lg p-3 mb-6 text-sm text-rose-900">
              <div className="font-semibold mb-1">You are about to:</div>
              <ul className="list-disc list-inside space-y-1 text-xs">
                <li>Liquidate {totalPositions} equity position(s) immediately</li>
                <li>Execute at current market prices</li>
                <li>Recover ~${positions.reduce((sum, p) => sum + p.market_value, 0).toFixed(2)} in cash</li>
              </ul>
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => setShowConfirmationModal(false)}
                className="flex-1 px-4 py-2 rounded-lg border border-neutral-300 text-neutral-900 font-medium hover:bg-neutral-50 transition"
              >
                Cancel
              </button>
              <button
                onClick={handleLiquidateAll}
                className="flex-1 px-4 py-2 rounded-lg bg-rose-600 text-white font-medium hover:bg-rose-700 transition"
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
