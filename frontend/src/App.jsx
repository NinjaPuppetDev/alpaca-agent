import React, { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Settings, CheckCircle2, AlertCircle, Power } from 'lucide-react';
import PortfolioOverview from './components/PortfolioOverview.jsx';
import TradingControlDashboard from './components/TradingControlDashboard.jsx';
import DecisionLogFeed from './components/DecisionLogFeed.jsx';
import HowItWorksAccordion from './components/HowItWorksAccordion.jsx';
import DevControlsModal from './components/DevControlsModal.jsx';

export default function App() {
  const [portfolioData, setPortfolioData] = useState(null);
  const [hedgesData, setHedgesData] = useState(null);
  const [decisions, setDecisions] = useState([]);
  const [statusData, setStatusData] = useState(null);
  const [autonomousMode, setAutonomousMode] = useState(true);
  const [loading, setLoading] = useState(true);
  const [togglingMode, setTogglingMode] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState(new Date());
  const [toastMessage, setToastMessage] = useState(null);
  const [devModalOpen, setDevModalOpen] = useState(false);

  // Check URL query param ?dev=true to auto-open dev controls if requested
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('dev') === 'true') {
      setDevModalOpen(true);
    }
  }, []);

  const showToast = (msg, type = 'success') => {
    setToastMessage({ text: msg, type });
    setTimeout(() => setToastMessage(null), 4000);
  };

  const fetchAllData = useCallback(async () => {
    try {
      const [portfolioRes, hedgesRes, decisionsRes, statusRes] = await Promise.all([
        fetch('/api/portfolio').then((r) => (r.ok ? r.json() : null)),
        fetch('/api/hedges').then((r) => (r.ok ? r.json() : null)),
        fetch('/api/decisions?limit=50').then((r) => (r.ok ? r.json() : [])),
        fetch('/api/status').then((r) => (r.ok ? r.json() : null)),
      ]);

      if (portfolioRes) setPortfolioData(portfolioRes);
      if (hedgesRes) setHedgesData(hedgesRes);
      if (decisionsRes) setDecisions(decisionsRes);
      if (statusRes) {
        setStatusData(statusRes);
        if (typeof statusRes.autonomous_mode === 'boolean') {
          setAutonomousMode(statusRes.autonomous_mode);
        }
      }

      setLastRefreshed(new Date());
    } catch (err) {
      console.error('Error fetching dashboard state:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Poll dashboard data at 8s intervals
  useEffect(() => {
    fetchAllData();
    const interval = setInterval(fetchAllData, 8000);
    return () => clearInterval(interval);
  }, [fetchAllData]);

  // Kill Switch handler
  const handleToggleAutonomousMode = async () => {
    const nextState = !autonomousMode;
    setTogglingMode(true);
    try {
      const res = await fetch('/api/autonomous-mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: nextState }),
      });
      const data = await res.json();
      if (res.ok) {
        setAutonomousMode(data.autonomous_mode);
        showToast(
          data.autonomous_mode
            ? 'Autonomous Mode RESUMED — Scheduled cadences active'
            : 'Autonomous Mode PAUSED (Kill Switch Active) — Order execution suspended',
          data.autonomous_mode ? 'success' : 'error'
        );
        await fetchAllData();
      } else {
        showToast(`Failed: ${data.detail || 'Could not toggle mode'}`, 'error');
      }
    } catch (err) {
      showToast(`Error: ${err.message}`, 'error');
    } finally {
      setTogglingMode(false);
    }
  };

  const handleTriggerLayer = async (layerName) => {
    setTriggering(true);
    try {
      const res = await fetch(`/api/trigger/${layerName}`, { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        showToast(`Triggered ${layerName} layer execution!`, 'success');
        await fetchAllData();
      } else {
        showToast(`Execution failed: ${data.detail || 'Error'}`, 'error');
      }
    } catch (err) {
      showToast(`Error triggering layer: ${err.message}`, 'error');
    } finally {
      setTriggering(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F8F9FA] text-neutral-900 flex flex-col font-sans antialiased">
      {/* Clean Financial Header */}
      <header className="sticky top-0 z-40 bg-white/95 backdrop-blur-md border-b border-neutral-200/80 px-6 py-3.5 flex items-center justify-between shadow-xs">
        {/* Brand & Title */}
        <div className="flex items-center gap-3">
          {/* Alpaca Yellow Logo Mark */}
          <div className="w-8 h-8 rounded-lg bg-[#FFD400] flex items-center justify-center font-black text-neutral-950 text-base shadow-xs select-none">
            🦙
          </div>

          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-bold text-neutral-950 tracking-tight">
                Alpaca Options Overlay Agent
              </h1>
            </div>
            <p className="text-[11px] text-neutral-500 hidden sm:block">
              Thematic Equity Portfolios & Risk-Managed Options Overlay
            </p>
          </div>
        </div>

        {/* Right Status Pill, Kill Switch & Controls */}
        <div className="flex items-center gap-3">
          {/* Autonomous Mode Kill Switch Toggle */}
          <button
            onClick={handleToggleAutonomousMode}
            disabled={togglingMode}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold border transition-all cursor-pointer select-none ${
              autonomousMode
                ? 'bg-neutral-900 text-white border-neutral-900 hover:bg-neutral-800 shadow-xs'
                : 'bg-amber-50 text-amber-900 border-amber-300 hover:bg-amber-100 shadow-xs'
            }`}
            title="Toggle autonomous scheduling on or off"
          >
            <Power className={`w-3.5 h-3.5 ${autonomousMode ? 'text-white' : 'text-[#F5A623]'}`} />
            <span>Autonomous Mode: {autonomousMode ? 'ON' : 'OFF (PAUSED)'}</span>
            <span
              className={`w-2 h-2 rounded-full ${
                autonomousMode ? 'bg-white animate-pulse' : 'bg-[#F5A623]'
              }`}
            ></span>
          </button>

          {/* Single Status Pill */}
          <div
            className={`hidden md:flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-medium ${
              autonomousMode
                ? 'bg-neutral-100 border-neutral-200/80 text-neutral-700'
                : 'bg-amber-50/60 border-amber-200 text-amber-900'
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                autonomousMode ? 'bg-neutral-700' : 'bg-[#F5A623]'
              }`}
            ></span>
            <span className="font-mono text-[11px]">
              {autonomousMode ? 'Autonomous Mode · Running' : 'Autonomous Mode · Paused'}
            </span>
            <span className="text-neutral-300">•</span>
            <span className="font-mono text-[11px] text-neutral-500">
              {lastRefreshed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })} UTC
            </span>
          </div>

          {/* Quick Refresh Button */}
          <button
            onClick={fetchAllData}
            title="Refresh state"
            className="p-1.5 rounded-lg border border-neutral-200 hover:bg-neutral-100 text-neutral-600 transition-colors cursor-pointer"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>

          {/* Dev Controls Toggle (gear icon) */}
          <button
            onClick={() => setDevModalOpen(true)}
            title="Developer & Judge Manual Triggers"
            className="p-1.5 rounded-lg border border-neutral-200 hover:bg-neutral-100 text-neutral-600 transition-colors cursor-pointer"
          >
            <Settings className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 animate-in fade-in slide-in-from-bottom-2 duration-200">
          <div
            className={`flex items-center gap-2 px-4 py-3 rounded-xl shadow-lg border text-xs font-semibold ${
              toastMessage.type === 'error'
                ? 'bg-rose-50 border-rose-200 text-rose-900'
                : toastMessage.type === 'warning'
                ? 'bg-amber-50 border-amber-200 text-amber-900'
                : 'bg-emerald-50 border-emerald-200 text-emerald-900'
            }`}
          >
            {toastMessage.type === 'error' ? (
              <AlertCircle className="w-4 h-4 text-rose-600" />
            ) : toastMessage.type === 'warning' ? (
              <AlertCircle className="w-4 h-4 text-amber-600" />
            ) : (
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
            )}
            <span>{toastMessage.text}</span>
          </div>
        </div>
      )}

      {/* Main Content Layout */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6 flex flex-col gap-6">
        {/* Trading Control Dashboard (Top) */}
        <div className="w-full">
          <TradingControlDashboard
            onLiquidationComplete={fetchAllData}
            showToast={showToast}
            statusData={statusData}
          />
        </div>

        {/* Two-Column Primary View */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Primary Panel 1: Portfolio Overview (Left Column, narrower 5/12) */}
          <div className="lg:col-span-5 flex flex-col gap-6">
            <PortfolioOverview portfolioData={portfolioData} loading={loading} />
          </div>

          {/* Primary Panel 2: Decision Audit Trail (Right Column, wider 7/12 - the centerpiece) */}
          <div className="lg:col-span-7 flex flex-col">
            <DecisionLogFeed decisions={decisions} loading={loading} />
          </div>
        </div>

        {/* Secondary Collapsed Section: How It Works */}
        <div className="w-full mt-2">
          <HowItWorksAccordion statusData={statusData} />
        </div>
      </main>

      {/* Minimal Footer */}
      <footer className="border-t border-neutral-200/80 py-4 px-6 text-center text-xs text-neutral-400 font-mono">
        Alpaca AI Trading Agents Hackathon • Autonomous 3-Layer Derivatives Overlay Engine
      </footer>

      {/* Dev Controls Modal */}
      <DevControlsModal
        isOpen={devModalOpen}
        onClose={() => setDevModalOpen(false)}
        onTriggerLayer={handleTriggerLayer}
        triggering={triggering}
      />
    </div>
  );
}
