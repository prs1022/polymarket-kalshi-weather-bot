import { motion } from 'framer-motion'
import type { BotStats } from '../types'

interface Props {
  stats: BotStats
  liveStats?: BotStats | null
  liveEnabled?: boolean
  onToggleLive?: () => void
}

export function StatsCards({ stats, liveStats, liveEnabled }: Props) {
  // Always show LIVE stats; fall back to sim stats if live not available
  const displayStats = liveStats ?? stats

  const winRate = displayStats.total_trades > 0 ? (displayStats.winning_trades / displayStats.total_trades * 100) : 0
  const returnPercent = displayStats.bankroll - displayStats.total_pnl > 0
    ? ((displayStats.total_pnl / (displayStats.bankroll - displayStats.total_pnl)) * 100)
    : 0

  return (
    <div className="flex items-center gap-3">
      {/* LIVE status indicator (display only, not clickable) */}
      <span
        className={`text-[10px] px-2 py-0.5 rounded border ${
          liveEnabled
            ? 'border-orange-500/50 text-orange-400 bg-orange-500/10'
            : 'border-neutral-700 text-neutral-500'
        }`}
      >
        {liveEnabled ? '● LIVE' : '○ IDLE'}
      </span>

      <div className="w-px h-3 bg-neutral-800" />

      <motion.div className="flex items-center gap-1.5" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <span className="text-[10px] text-neutral-600 uppercase">Bank</span>
        <span className="text-sm font-semibold tabular-nums text-neutral-100">
          ${displayStats.bankroll >= 1000 ? (displayStats.bankroll / 1000).toFixed(1) + 'K' : displayStats.bankroll.toFixed(0)}
        </span>
      </motion.div>

      <div className="w-px h-3 bg-neutral-800" />

      <motion.div className="flex items-center gap-1.5" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.05 }}>
        <span className="text-[10px] text-neutral-600 uppercase">P&L</span>
        <span className={`text-sm font-semibold tabular-nums ${displayStats.total_pnl >= 0 ? 'text-green-500 glow-green' : 'text-red-500 glow-red'}`}>
          {displayStats.total_pnl >= 0 ? '+' : ''}${Math.abs(displayStats.total_pnl).toFixed(0)}
        </span>
        <span className={`text-[10px] tabular-nums ${returnPercent >= 0 ? 'text-green-500/60' : 'text-red-500/60'}`}>
          {returnPercent >= 0 ? '+' : ''}{returnPercent.toFixed(1)}%
        </span>
      </motion.div>

      <div className="w-px h-3 bg-neutral-800" />

      <motion.div className="flex items-center gap-1.5" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.1 }}>
        <span className="text-[10px] text-neutral-600 uppercase">Win</span>
        <span className={`text-sm font-semibold tabular-nums ${winRate >= 55 ? 'text-green-500' : winRate >= 45 ? 'text-yellow-500' : 'text-red-500'}`}>
          {winRate.toFixed(0)}%
        </span>
        <span className="text-[10px] text-neutral-600 tabular-nums">
          {displayStats.winning_trades}/{displayStats.total_trades}
        </span>
      </motion.div>

      <div className="w-px h-3 bg-neutral-800" />

      <motion.div className="flex items-center gap-1.5" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.15 }}>
        <span className="text-[10px] text-neutral-600 uppercase">Trades</span>
        <span className="text-sm font-semibold tabular-nums text-neutral-100">{displayStats.total_trades}</span>
        {displayStats.is_running && <div className="live-dot" />}
      </motion.div>
    </div>
  )
}
