/**
 * Utility functions for the BTC 5-min trading bot dashboard
 */

/**
 * Convert UTC timestamp string to Beijing time (UTC+8) Date object.
 * Backend stores all timestamps in UTC (naive datetime without timezone suffix).
 * This function ensures correct conversion regardless of the viewer's local timezone.
 */
function toBeijingDate(utcTimestamp: string): Date {
  // If the timestamp already has timezone info (Z or +00:00), parse directly
  // Otherwise treat it as UTC by appending 'Z'
  let ts = utcTimestamp
  if (!ts.endsWith('Z') && !ts.includes('+') && !ts.includes('-', 10)) {
    ts = ts + 'Z'
  }
  const date = new Date(ts)
  // Convert to Beijing time (UTC+8) by creating a new Date from the shifted time
  const beijingMs = date.getTime() + 8 * 60 * 60 * 1000
  return new Date(beijingMs)
}

/** Format UTC timestamp as Beijing time string (HH:MM:SS) */
export function formatBeijingTime(utcTimestamp: string): string {
  try {
    return toBeijingDate(utcTimestamp).toISOString().slice(11, 19)
  } catch {
    return '--:--:--'
  }
}

/** Format UTC timestamp as Beijing date-time string (MM/DD HH:MM) */
export function formatBeijingDateTime(utcTimestamp: string): string {
  try {
    const d = toBeijingDate(utcTimestamp)
    const mm = String(d.getUTCMonth() + 1).padStart(2, '0')
    const dd = String(d.getUTCDate()).padStart(2, '0')
    const hh = String(d.getUTCHours()).padStart(2, '0')
    const mi = String(d.getUTCMinutes()).padStart(2, '0')
    return `${mm}/${dd} ${hh}:${mi}`
  } catch {
    return '--/-- --:--'
  }
}

/** Format UTC timestamp as Beijing date string (Mon D) */
export function formatBeijingDate(utcTimestamp: string): string {
  try {
    const d = toBeijingDate(utcTimestamp)
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    return `${months[d.getUTCMonth()]} ${d.getUTCDate()}`
  } catch {
    return '--'
  }
}

/** Format distance from now in Beijing time (e.g. "3m", "1h", "2s") */
export function formatDistanceToNowBeijing(utcTimestamp: string): string {
  try {
    let ts = utcTimestamp
    if (!ts.endsWith('Z') && !ts.includes('+') && !ts.includes('-', 10)) {
      ts = ts + 'Z'
    }
    const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
    if (diff < 60) return `${diff}s`
    if (diff < 3600) return `${Math.floor(diff / 60)}m`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`
    return `${Math.floor(diff / 86400)}d`
  } catch {
    return '--'
  }
}

export function getMarketUrl(platform: string, ticker: string, eventSlug?: string): string {
  const platformLower = platform.toLowerCase()

  if (platformLower === 'polymarket') {
    if (eventSlug) {
      return `https://polymarket.com/event/${eventSlug}`
    }
    return `https://polymarket.com/event/${ticker}`
  }

  if (platformLower === 'kalshi') {
    return `https://kalshi.com/markets/${ticker}`
  }

  return '#'
}

export function formatCurrency(value: number, showSign = false): string {
  const formatted = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 2
  }).format(Math.abs(value))

  if (showSign && value !== 0) {
    return value >= 0 ? `+${formatted}` : `-${formatted}`
  }
  return value < 0 ? `-${formatted}` : formatted
}

export function formatPercent(value: number, decimals = 1): string {
  return `${(value * 100).toFixed(decimals)}%`
}

export const platformStyles: Record<string, { badge: string; icon: string; name: string }> = {
  polymarket: {
    badge: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
    icon: 'P',
    name: 'Polymarket'
  },
  kalshi: {
    badge: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
    icon: 'K',
    name: 'Kalshi'
  }
}

export function getPnlColorClass(pnl: number | null): string {
  if (pnl === null) return 'text-neutral-500'
  if (pnl > 0) return 'text-green-500'
  if (pnl < 0) return 'text-red-500'
  return 'text-neutral-400'
}

export function formatCountdown(seconds: number): string {
  if (seconds <= 0) return 'Ended'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

export function debounce<T extends (...args: any[]) => void>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeoutId: ReturnType<typeof setTimeout> | null = null

  return (...args: Parameters<T>) => {
    if (timeoutId) {
      clearTimeout(timeoutId)
    }
    timeoutId = setTimeout(() => {
      func(...args)
    }, wait)
  }
}
