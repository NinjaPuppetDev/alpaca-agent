import React from 'react';

export default function PortfolioOverview({ portfolioData, loading }) {
  if (loading && !portfolioData) {
    return (
      <div className="bg-white border border-slate-200/90 rounded-2xl p-6 shadow-sm animate-pulse">
        <div className="h-5 bg-slate-100 rounded w-1/3 mb-6"></div>
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="h-20 bg-slate-100 rounded-xl"></div>
          <div className="h-20 bg-slate-100 rounded-xl"></div>
          <div className="h-20 bg-slate-100 rounded-xl"></div>
        </div>
        <div className="h-48 bg-slate-100 rounded-xl"></div>
      </div>
    );
  }

  const account = portfolioData?.account || { equity: 100000, cash: 100000, buying_power: 200000 };
  const themes = portfolioData?.themes || [];
  const positions = portfolioData?.positions || [];

  return (
    <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-sm flex flex-col gap-6">
      {/* 1. Account Metrics - Three numbers only */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold tracking-tight text-neutral-900 uppercase">
            Portfolio Overview
          </h2>
          <span className="text-xs font-mono font-medium text-neutral-500">
            {positions.length} {positions.length === 1 ? 'Position' : 'Positions'}
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
          {/* Total Equity */}
          <div className="bg-neutral-50 border border-neutral-200/70 rounded-xl p-3 min-w-0 flex flex-col justify-center">
            <span className="text-[11px] text-neutral-500 font-medium truncate block">Total Equity</span>
            <div
              className="text-sm sm:text-base font-bold font-mono text-neutral-900 mt-0.5 tracking-tight truncate"
              title={`$${account.equity?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
            >
              ${account.equity?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>

          {/* Cash Buffer */}
          <div className="bg-neutral-50 border border-neutral-200/70 rounded-xl p-3 min-w-0 flex flex-col justify-center">
            <span className="text-[11px] text-neutral-500 font-medium truncate block">Cash Buffer</span>
            <div
              className="text-sm sm:text-base font-bold font-mono text-neutral-900 mt-0.5 tracking-tight truncate"
              title={`$${account.cash?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
            >
              ${account.cash?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>

          {/* Buying Power */}
          <div className="bg-neutral-50 border border-neutral-200/70 rounded-xl p-3 min-w-0 flex flex-col justify-center">
            <span className="text-[11px] text-neutral-500 font-medium truncate block">Buying Power</span>
            <div
              className="text-sm sm:text-base font-bold font-mono text-neutral-900 mt-0.5 tracking-tight truncate"
              title={`$${account.buying_power?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
            >
              ${account.buying_power?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>
        </div>
      </div>

      {/* 2. Active Thematic Basket */}
      {themes.length > 0 && (
        <div className="border-t border-slate-100 pt-5">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
              Active Thematic Basket
            </span>
            <span className="text-[11px] font-mono text-neutral-400">
              Discovered from News
            </span>
          </div>

          {themes.map((t) => (
            <div key={t.id} className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="font-bold text-sm text-neutral-900">{t.theme_name}</span>
                <span className="text-xs font-mono text-neutral-500">
                  {t.tickers?.length || 0} Target Assets
                </span>
              </div>
              <p className="text-xs text-neutral-600 leading-relaxed">{t.description}</p>
              
              <div className="flex flex-wrap gap-1.5 mt-1">
                {t.tickers?.map((ticker) => (
                  <span
                    key={ticker}
                    className="text-xs font-mono px-2.5 py-1 rounded-md bg-neutral-100 text-neutral-800 border border-neutral-200 font-medium"
                  >
                    {ticker}{' '}
                    <span className="text-neutral-500">
                      ({((t.allocation_weights?.[ticker] || 0) * 100).toFixed(0)}%)
                    </span>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 3. Current Holdings Table */}
      <div className="border-t border-slate-100 pt-5">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Current Holdings
          </span>
        </div>

        <div className="overflow-x-auto border border-neutral-200/80 rounded-xl">
          <table className="w-full text-left text-xs">
            <thead className="bg-neutral-50 text-neutral-500 uppercase font-semibold text-[11px] border-b border-neutral-200/80">
              <tr>
                <th className="py-2.5 px-3.5">Asset</th>
                <th className="py-2.5 px-3 text-right">Shares</th>
                <th className="py-2.5 px-3 text-right">Price</th>
                <th className="py-2.5 px-3 text-right">Value</th>
                <th className="py-2.5 px-3 text-right">% Port</th>
                <th className="py-2.5 px-3.5 text-right">P&L</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 font-mono text-neutral-700">
              {positions.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-neutral-400 font-sans">
                    No open positions. Layer 1 will discover and rebalance into themes on next schedule.
                  </td>
                </tr>
              ) : (
                positions.map((p) => {
                  const isProfit = (p.unrealized_pl || 0) >= 0;
                  const isOption = p.asset_class === 'us_option';
                  return (
                    <tr key={p.symbol} className="hover:bg-neutral-50/80 transition-colors">
                      <td className="py-2.5 px-3.5 font-bold text-neutral-900">
                        <div className="flex items-center gap-1.5">
                          <span>{p.symbol}</span>
                          {isOption && (
                            <span className="px-1.5 py-0.2 rounded text-[10px] font-sans font-medium bg-neutral-100 text-neutral-600 border border-neutral-200">
                              Option
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-2.5 px-3 text-right text-neutral-600">
                        {p.qty?.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}
                      </td>
                      <td className="py-2.5 px-3 text-right text-neutral-600">
                        ${p.current_price?.toFixed(2)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-semibold text-neutral-900">
                        ${p.market_value?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                      <td className="py-2.5 px-3 text-right font-medium text-neutral-800">
                        {p.weight_pct?.toFixed(1)}%
                      </td>
                      <td
                        className={`py-2.5 px-3.5 text-right font-semibold ${
                          isProfit ? 'text-emerald-600' : 'text-rose-600'
                        }`}
                      >
                        {isProfit ? '+' : ''}${p.unrealized_pl?.toFixed(2)}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
