export const PERIODS = [
  { key: 'today', label: 'Daily' },
  { key: 'week', label: 'Weekly' },
  { key: 'month', label: 'Monthly' },
  { key: 'year', label: 'Yearly' },
  { key: 'all', label: 'Overall' },
]

export function getDateRange(period, custom) {
  const now = new Date()
  const fmt = (d) => d.toISOString().split('T')[0]
  switch (period) {
    case 'today': return { from_date: fmt(now), to_date: fmt(now) }
    case 'week': {
      const s = new Date(now); const d = s.getDay()
      s.setDate(s.getDate() - (d === 0 ? 6 : d - 1))
      return { from_date: fmt(s), to_date: fmt(now) }
    }
    case 'month': return { from_date: fmt(new Date(now.getFullYear(), now.getMonth(), 1)), to_date: fmt(now) }
    case 'year': return { from_date: fmt(new Date(now.getFullYear(), 0, 1)), to_date: fmt(now) }
    case 'custom': return {
      ...(custom?.from && { from_date: custom.from }),
      ...(custom?.to && { to_date: custom.to }),
    }
    default: return {}
  }
}

export function getPeriodLabel(p, custom) {
  const n = new Date()
  const d = (s) => new Date(s + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
  switch (p) {
    case 'today': return n.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    case 'week': { const s = new Date(n); const dd = s.getDay(); s.setDate(s.getDate() - (dd === 0 ? 6 : dd - 1)); return `${s.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} — ${n.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}` }
    case 'month': return n.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
    case 'year': return String(n.getFullYear())
    case 'custom': {
      if (custom?.from && custom?.to) return `${d(custom.from)} — ${d(custom.to)}`
      if (custom?.from) return `From ${d(custom.from)}`
      if (custom?.to) return `Until ${d(custom.to)}`
      return 'Custom range'
    }
    default: return 'All time'
  }
}

const EMPTY_CUSTOM = { from: '', to: '' }

export function loadPeriod(storageKey, defaultPeriod) {
  try {
    const raw = localStorage.getItem(storageKey)
    if (raw) {
      const v = JSON.parse(raw)
      return { period: v.period || defaultPeriod, custom: { ...EMPTY_CUSTOM, ...(v.custom || {}) } }
    }
  } catch { /* ignore */ }
  return { period: defaultPeriod, custom: { ...EMPTY_CUSTOM } }
}

export function savePeriod(storageKey, period, custom) {
  try { localStorage.setItem(storageKey, JSON.stringify({ period, custom })) } catch { /* ignore */ }
}
