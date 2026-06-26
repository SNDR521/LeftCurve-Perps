import { useEffect, useState } from 'react'

// Real-time crypto tickers straight from Bybit's public linear WebSocket —
// no API key, no quota, ~100ms pushes. Returns {SYMBOL: {price, pct24h}}.
// Deltas only carry changed fields, so state merges per symbol.
export default function useBybitTickers(symbols) {
  const [tickers, setTickers] = useState({})
  const key = (symbols || []).slice().sort().join(',')

  useEffect(() => {
    if (!key) { setTickers({}); return undefined }
    let ws
    let closed = false
    let retryTimer

    function connect() {
      ws = new WebSocket('wss://stream.bybit.com/v5/public/linear')
      ws.onopen = () => {
        ws.send(JSON.stringify({ op: 'subscribe', args: key.split(',').map((s) => `tickers.${s}`) }))
      }
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data)
          const d = msg?.data
          if (!d?.symbol) return
          const price = Number(d.lastPrice ?? d.markPrice)
          const pct = d.price24hPcnt != null && d.price24hPcnt !== '' ? Number(d.price24hPcnt) * 100 : null
          setTickers((prev) => {
            const cur = prev[d.symbol] || {}
            const next = {
              price: Number.isFinite(price) ? price : cur.price,
              pct24h: pct != null && Number.isFinite(pct) ? pct : cur.pct24h,
            }
            if (next.price === cur.price && next.pct24h === cur.pct24h) return prev
            return { ...prev, [d.symbol]: next }
          })
        } catch { /* ignore malformed frames */ }
      }
      ws.onclose = () => { if (!closed) retryTimer = setTimeout(connect, 3000) }
      ws.onerror = () => { try { ws.close() } catch { /* noop */ } }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(retryTimer)
      try { ws && ws.close() } catch { /* noop */ }
    }
  }, [key])

  return tickers
}
