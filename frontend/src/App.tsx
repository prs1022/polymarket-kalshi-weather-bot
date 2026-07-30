import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { fetchDashboard } from './api'
import { StatsCards } from './components/StatsCards'
import { SignalsTable } from './components/SignalsTable'
import { TradesTable } from './components/TradesTable'
import { EquityChart } from './components/EquityChart'
import { Terminal } from './components/Terminal'
import { MicrostructurePanel } from './components/MicrostructurePanel'
import { CalibrationPanel } from './components/CalibrationPanel'

function LiveClock() {
  const [time, setTime] = useState(new Date())
  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(interval)
  }, [])
  // Display Beijing time (UTC+8) regardless of viewer's local timezone
  const beijingTime = new Date(time.getTime() + 8 * 60 * 60 * 1000)
  return (
    <span className="text-xs tabular-nums text-neutral-400">
      {beijingTime.toISOString().slice(11, 19)}
    </span>
  )
}

function RefreshBar({ interval }: { interval: number }) {
  const [progress, setProgress] = useState(100)

  useEffect(() => {
    setProgress(100)
    const step = 100 / (interval / 1000)
    const timer = setInterval(() => {
      setProgress(p => Math.max(0, p - step))
    }, 1000)
    return () => clearInterval(timer)
  }, [interval])

  return (
    <div className="refresh-bar w-16">
      <div className="refresh-fill" style={{ width: `${progress}%` }} />
    </div>
  )
}

function App() {

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: fetchDashboard,
    refetchInterval: 5000,
  })

  const activeSignals = data?.active_signals ?? []
  const recentTrades = (data?.recent_trades ?? []).filter(t => t.is_live)
  const btcPrice = data?.btc_price
  const micro = data?.microstructure

  // Use LIVE stats as primary; fall back to sim stats
  const simStats = data?.stats ?? {
    is_running: false,
    last_run: null,
    total_trades: 0,
    total_pnl: 0,
    bankroll: 10000,
    winning_trades: 0,
    win_rate: 0
  }
  const stats = data?.live_stats ?? simStats
  const equityCurve = data?.equity_curve ?? []
  const calibration = data?.calibration ?? null

  if (isLoading) {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="relative w-10 h-10 mx-auto mb-4">
            <div className="absolute inset-0 border-2 border-neutral-800 rounded-full" />
            <div className="absolute inset-0 border-2 border-transparent border-t-green-500 rounded-full animate-spin" />
          </div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-widest font-mono">Initializing</div>
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="text-red-500 text-xs uppercase mb-2 tracking-wider">Connection Error</div>
          <button
            onClick={() => refetch()}
            className="px-3 py-1.5 bg-neutral-900 border border-neutral-700 text-neutral-300 text-xs uppercase tracking-wider"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen bg-black text-neutral-200 flex flex-col overflow-hidden">
      {/* ===== HEADER ===== */}
      <motion.header
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="shrink-0 border-b border-neutral-800 px-3 py-1.5 flex items-center gap-4 relative"
      >
        <div className="scan-line" />

        <div className="flex items-center gap-2 shrink-0">
          <h1 className="text-xs font-bold text-neutral-100 uppercase tracking-widest whitespace-nowrap font-mono">
            TRADING TERMINAL
          </h1>
          <span className={`px-1.5 py-0.5 text-[9px] font-bold uppercase ${
            stats.is_running
              ? 'bg-green-500/10 text-green-500 border border-green-500/20'
              : 'bg-neutral-800 text-neutral-500 border border-neutral-700'
          }`}>
            {stats.is_running ? 'Live' : 'Idle'}
          </span>
        </div>

        {btcPrice && (
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-sm font-bold tabular-nums text-neutral-100">
              ${btcPrice.price.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </span>
            <span className={`text-[10px] tabular-nums ${btcPrice.change_24h >= 0 ? 'text-green-500' : 'text-red-500'}`}>
              {btcPrice.change_24h >= 0 ? '+' : ''}{btcPrice.change_24h.toFixed(2)}%
            </span>
          </div>
        )}

        <div className="flex-1" />

        <StatsCards
          stats={simStats}
          liveStats={data?.live_stats}
          liveEnabled={data?.live_enabled}
        />

        <div className="flex items-center gap-2 shrink-0">
          <LiveClock />
        </div>
      </motion.header>

      {/* ===== MAIN GRID ===== */}
      <div className="flex-1 min-h-0 grid grid-cols-[300px_1fr] grid-rows-[1fr] gap-0">

        {/* ===== LEFT COLUMN ===== */}
        <div className="flex flex-col border-r border-neutral-800 min-h-0 overflow-hidden">
          {/* Microstructure */}
          {micro && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="shrink-0 border-b border-neutral-800 px-2 py-2"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Microstructure</span>
                <span className="text-[9px] text-neutral-600 tabular-nums">{micro.source}</span>
              </div>
              <MicrostructurePanel micro={micro} />
            </motion.div>
          )}

          {/* Equity chart */}
          <div className="border-b border-neutral-800" style={{ height: '28%', minHeight: '120px' }}>
            <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Equity</span>
              <span className={`text-[10px] tabular-nums ${stats.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                {stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl.toFixed(2)}
              </span>
            </div>
            <div className="h-[calc(100%-24px)] p-1">
              <EquityChart data={equityCurve} initialBankroll={stats.bankroll - stats.total_pnl} />
            </div>
          </div>

          {/* Calibration */}
          {calibration && calibration.total_with_outcome > 0 && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="shrink-0 border-b border-neutral-800 px-2 py-2"
            >
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Calibration</span>
                <span className="text-[9px] text-neutral-600 tabular-nums">{calibration.total_with_outcome} settled</span>
              </div>
              <CalibrationPanel calibration={calibration} />
            </motion.div>
          )}

          {/* Terminal fills remaining */}
          <div className="flex-1 min-h-0">
            <Terminal
              isRunning={stats.is_running}
              lastRun={stats.last_run}
              stats={{ total_trades: stats.total_trades, total_pnl: stats.total_pnl }}
            />
          </div>
        </div>

        {/* ===== RIGHT COLUMN (Signals + Trades) ===== */}
        <div className="flex flex-col min-h-0 overflow-hidden">
          {/* Signals - top portion */}
          <div className="flex flex-col min-h-0" style={{ height: '50%' }}>
            <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Signals</span>
              <span className="text-[10px] text-amber-400 tabular-nums">{activeSignals.length} BTC</span>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0">
              <SignalsTable
                signals={activeSignals}
                weatherSignals={[]}
              />
            </div>
          </div>

          {/* Trades */}
          <div className="flex flex-col min-h-0 border-t border-neutral-800" style={{ height: '50%' }}>
            <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Trades</span>
              <span className="text-[10px] text-neutral-600 tabular-nums">{recentTrades.length}</span>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0">
              <TradesTable trades={recentTrades} />
            </div>
          </div>
        </div>
      </div>

      {/* ===== FOOTER ===== */}
      <footer className="shrink-0 border-t border-neutral-800 px-3 py-0.5 flex items-center justify-between">
        <span className="text-[10px] text-neutral-700 font-mono">
          Binance/Coinbase | Open-Meteo | Polymarket + Kalshi
        </span>
        <div className="flex items-center gap-3">
          <RefreshBar interval={5000} />
          <span className="text-[10px] text-neutral-700 font-mono">BTC 5-min</span>
          <div className="flex items-center gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
            <span className="text-[10px] text-neutral-600 font-mono">Connected</span>
          </div>
        </div>
      </footer>
    </div>
  )
}

export default App
