// Pure helpers for TradeChart. No lightweight-charts imports — testable in isolation.
//
// executions: [{time(unix sec), side:'BUY'|'SELL', price, quantity, is_funding, funding_amount}]

// Backend datetimes are naive UTC ISO strings. `new Date(naive)` would parse
// them as LOCAL time and shift everything by the machine's UTC offset —
// append 'Z' unless a timezone suffix is already present.
export function parseUtcSeconds(s) {
  if (s == null) return null
  if (typeof s === 'number') return Math.floor(s)
  const str = String(s)
  const hasTz = /[zZ]$/.test(str) || /[+-]\d{2}:?\d{2}$/.test(str)
  return Math.floor(Date.parse(hasTz ? str : str + 'Z') / 1000)
}

// Snap line-series points onto candle boundaries. Points at times BETWEEN
// candles would each get their own equal-width column on the shared time
// scale, visually stretching the trade region and scattering the markers.
export function snapToInterval(points, intervalSec) {
  if (!intervalSec) return points
  return dedupeByTime(points.map(p => ({
    time: Math.floor(p.time / intervalSec) * intervalSec,
    value: p.value,
  })))
}

// Collapse duplicate consecutive times, keeping the LAST value at each time.
// lightweight-charts rejects non-ascending times, so any line-series data must be deduped.
export function dedupeByTime(points) {
  const out = []
  for (const p of points) {
    if (out.length > 0 && out[out.length - 1].time === p.time) out[out.length - 1] = p
    else out.push(p)
  }
  return out
}

// Returns step-series points for rolling average entry and exit lines.
export function rollingAvgLines(executions, direction) {
  const entrySide = direction === 'LONG' ? 'BUY' : 'SELL'
  let entryQty = 0, entryNotional = 0, exitQty = 0, exitNotional = 0
  const entryLine = [], exitLine = []
  for (const e of [...executions].filter(x => !x.is_funding).sort((a, b) => a.time - b.time)) {
    if (e.side === entrySide) { entryQty += e.quantity; entryNotional += e.price * e.quantity }
    else { exitQty += e.quantity; exitNotional += e.price * e.quantity }
    if (entryQty > 0) entryLine.push({ time: e.time, value: entryNotional / entryQty })
    if (exitQty > 0) exitLine.push({ time: e.time, value: exitNotional / exitQty })
  }
  return { entryLine, exitLine }
}

// Unrealized PnL per candle from the executions state machine.
export function runningPnlSeries(candles, executions, direction) {
  const evs = [...executions].filter(x => !x.is_funding).sort((a, b) => a.time - b.time)
  const sign = direction === 'LONG' ? 1 : -1
  let i = 0, netQty = 0, entryQty = 0, entryNotional = 0
  const out = []
  for (const c of candles) {
    while (i < evs.length && evs[i].time <= c.time) {
      const e = evs[i++]
      const isEntry = (e.side === 'BUY') === (direction === 'LONG')
      if (isEntry) { netQty += e.quantity; entryQty += e.quantity; entryNotional += e.price * e.quantity }
      else netQty -= e.quantity
    }
    const avgEntry = entryQty > 0 ? entryNotional / entryQty : null
    out.push({ time: c.time, value: avgEntry != null && netQty > 1e-12 ? (c.close - avgEntry) * netQty * sign : 0 })
  }
  return out
}
