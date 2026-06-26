import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchPerpsCockpit, savePerpsJournal } from '../lib/api'
import { useAccount } from '../components/Layout'

// Real-time mark prices straight from Bybit's public ticker stream — pushed
// ~100ms, no backend involved. The 5s REST poll stays the source of truth for
// positions/wallet; this only makes the marks (and what derives from them) live.
function useLiveMarks(symbols) {
  const [marks, setMarks] = useState({})
  const [connected, setConnected] = useState(false)
  const key = symbols.slice().sort().join(',')

  useEffect(() => {
    if (!key) { setMarks({}); setConnected(false); return undefined }
    let ws
    let closed = false
    let retryTimer

    function connect() {
      ws = new WebSocket('wss://stream.bybit.com/v5/public/linear')
      ws.onopen = () => {
        setConnected(true)
        ws.send(JSON.stringify({ op: 'subscribe', args: key.split(',').map((s) => `tickers.${s}`) }))
      }
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data)
          const d = msg?.data
          // tickers deltas only carry changed fields — markPrice may be absent
          if (d?.symbol && d.markPrice != null && d.markPrice !== '') {
            const m = Number(d.markPrice)
            if (Number.isFinite(m)) setMarks((prev) => (prev[d.symbol] === m ? prev : { ...prev, [d.symbol]: m }))
          }
        } catch { /* ignore malformed frames */ }
      }
      ws.onclose = () => {
        setConnected(false)
        if (!closed) retryTimer = setTimeout(connect, 3000)
      }
      ws.onerror = () => { try { ws.close() } catch { /* noop */ } }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(retryTimer)
      setConnected(false)
      try { ws && ws.close() } catch { /* noop */ }
    }
  }, [key])

  return { marks, connected }
}

// Live mids from Hyperliquid's public allMids stream — the same sub-second feed
// the HL position alarms use. Keyed by bare coin (BTC, ETH). One subscription
// covers every coin; we keep only the symbols we're showing. A periodic ping
// keeps the socket alive (HL drops idle clients ~60s).
function useHlMids(symbols) {
  const [marks, setMarks] = useState({})
  const [connected, setConnected] = useState(false)
  const key = symbols.slice().sort().join(',')

  useEffect(() => {
    if (!key) { setMarks({}); setConnected(false); return undefined }
    const wanted = new Set(key.split(','))
    let ws
    let closed = false
    let retryTimer
    let pingTimer

    function connect() {
      ws = new WebSocket('wss://api.hyperliquid.xyz/ws')
      ws.onopen = () => {
        setConnected(true)
        ws.send(JSON.stringify({ method: 'subscribe', subscription: { type: 'allMids' } }))
        pingTimer = setInterval(() => {
          try { ws.send(JSON.stringify({ method: 'ping' })) } catch { /* noop */ }
        }, 30000)
      }
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data)
          if (msg?.channel !== 'allMids') return
          const mids = msg.data?.mids || {}
          setMarks((prev) => {
            let next = prev
            for (const s of wanted) {
              const v = mids[s]
              if (v == null) continue
              const n = Number(v)
              if (Number.isFinite(n) && prev[s] !== n) {
                if (next === prev) next = { ...prev }
                next[s] = n
              }
            }
            return next
          })
        } catch { /* ignore malformed frames */ }
      }
      ws.onclose = () => {
        setConnected(false)
        clearInterval(pingTimer)
        if (!closed) retryTimer = setTimeout(connect, 3000)
      }
      ws.onerror = () => { try { ws.close() } catch { /* noop */ } }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(retryTimer)
      clearInterval(pingTimer)
      setConnected(false)
      try { ws && ws.close() } catch { /* noop */ }
    }
  }, [key])

  return { marks, connected }
}

// Re-derive the mark-dependent numbers from a streamed mark price.
function withLiveMark(p, mark) {
  if (mark == null || !(mark > 0)) return p
  const sign = p.direction === 'LONG' ? 1 : -1
  const entryNotional = p.avg_entry * p.qty
  const upnl = (mark - p.avg_entry) * p.qty * sign
  let live_r = p.live_r
  if (p.stop_price != null && p.live_r != null && Math.abs(p.avg_entry - p.stop_price) > 1e-12) {
    live_r = ((mark - p.avg_entry) * sign) / Math.abs(p.avg_entry - p.stop_price)
  }
  return {
    ...p,
    mark,
    upnl,
    upnl_pct: entryNotional > 0 ? (upnl / entryNotional) * 100 : p.upnl_pct,
    notional: mark * p.qty,
    liq_distance_pct: p.liq_price != null && mark > 0 ? (Math.abs(mark - p.liq_price) / mark) * 100 : p.liq_distance_pct,
    live_r,
  }
}

const fmt = (n, d = 2) => (n == null ? '—' : Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }))
const fmtPrice = (n, d = 5) => (n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }))

// signed dollar string: +$12.34 / -$8.00
const signedUsd = (n) => {
  if (n == null) return '—'
  return `${n >= 0 ? '+' : '-'}$${Math.abs(Number(n)).toFixed(2)}`
}
const pnlColor = (n) => (n == null || n === 0 ? 'text-[#8d91a6]' : n > 0 ? 'text-[#00d4aa]' : 'text-[#de576f]')

// "in 2h 41m" from a future epoch-ms instant
function fundingCountdown(nextMs) {
  if (!nextMs) return null
  const diff = nextMs - Date.now()
  if (diff <= 0) return 'now'
  const h = Math.floor(diff / 3_600_000)
  const m = Math.floor((diff % 3_600_000) / 60_000)
  return h > 0 ? `in ${h}h ${m}m` : `in ${m}m`
}

function StatBlock({ label, children, sub }) {
  return (
    <div className="card px-4 py-3">
      <div className="text-[11px] text-[#4e5166]">{label}</div>
      <div className="text-[18px] font-semibold leading-tight mt-0.5">{children}</div>
      {sub != null && <div className="text-[11px] text-[#4e5166] mt-0.5">{sub}</div>}
    </div>
  )
}

// Inline stop editor — click value to edit; Enter/blur saves, Escape cancels.
// stopSource 'exchange' = the SL read from the exchange (Bybit's stopLoss, or a
// Hyperliquid Stop trigger order); editing writes a journal stop, which overrides
// the exchange one for risk math.
function StopCell({ accountId, symbol, stopPrice, stopSource }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [failed, setFailed] = useState(false)

  const mutation = useMutation({
    mutationFn: savePerpsJournal,
    onSuccess: () => { setFailed(false); qc.invalidateQueries({ queryKey: ['perps-cockpit'] }) },
    // a stop that silently fails to persist is unacceptable on a risk screen
    onError: () => setFailed(true),
  })

  function open() {
    setValue(stopPrice != null ? String(stopPrice) : '')
    setEditing(true)
  }
  function commit() {
    setEditing(false)
    const next = value === '' ? null : Number(value)
    // no-op if unchanged
    if (next === (stopPrice ?? null)) return
    if (next != null && Number.isNaN(next)) return
    mutation.mutate({ position_key: `${accountId}:${symbol}:open`, stop_price: next })
  }

  if (editing) {
    return (
      <input
        autoFocus
        type="number"
        step="any"
        className="w-20 input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); commit() }
          else if (e.key === 'Escape') { e.preventDefault(); setEditing(false) }
        }}
      />
    )
  }

  return (
    <span className="inline-flex items-center gap-1.5">
      <button
        onClick={(e) => { e.stopPropagation(); open() }}
        className={`font-mono text-[12px] text-[#8d91a6] hover:text-[#fcfefd] transition-colors ${mutation.isPending ? 'opacity-40' : ''}`}
        title="Click to edit stop"
      >
        {stopPrice != null ? fmtPrice(stopPrice) : '—'}
      </button>
      {stopSource === 'exchange' && (
        <span className="text-[9px] uppercase tracking-wide text-[#4e5166]" title="Stop-loss read from the exchange">exchange</span>
      )}
      {failed && (
        <span className="text-[10px] text-[#de576f]" title="The stop was not saved — retry">
          save failed
        </span>
      )}
    </span>
  )
}

const COLUMNS = ['Symbol', 'Side', 'Size', 'Entry', 'Mark', 'uPnL', 'R', 'Lev', 'Liq', 'Funding', 'Proj/24h', 'Accrued', 'Stop']

export default function PerpsCockpit() {
  const { perpsAccountId } = useAccount()
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['perps-cockpit', perpsAccountId],
    queryFn: () => fetchPerpsCockpit(perpsAccountId ? { account_id: perpsAccountId } : {}),
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
    retry: false,
  })
  // Stream marks from each venue's WS and merge. Bybit perps are USDT-quoted and
  // Hyperliquid uses bare coins, so the two symbol sets are disjoint — partition by
  // suffix so each socket only opens for the venue actually on screen.
  const symbols = (data?.positions ?? []).map((p) => p.symbol)
  const bybitSyms = symbols.filter((s) => s.endsWith('USDT'))
  const hlSyms = symbols.filter((s) => !s.endsWith('USDT'))
  const { marks: bybitMarks, connected: bybitConn } = useLiveMarks(bybitSyms)
  const { marks: hlMarks, connected: hlConn } = useHlMids(hlSyms)
  const marks = { ...bybitMarks, ...hlMarks }
  // "Live" only when every venue actually on screen is connected (a single account
  // is one venue, so normally just that one; robust if a mixed view ever appears).
  const connected = symbols.length > 0 &&
    (bybitSyms.length ? bybitConn : true) && (hlSyms.length ? hlConn : true)

  const header = (
    <div>
      <h1 className="text-[22px] font-semibold text-white">Cockpit</h1>
      <p className="text-[13px] text-[#4e5166] mt-0.5">
        read-only — {connected ? 'marks stream live' : 'live'} · positions refresh every 5s
      </p>
    </div>
  )

  if (isLoading) {
    return (
      <div className="space-y-5">
        {header}
        <div className="flex gap-3">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="card px-4 py-3 h-[64px] w-40 animate-pulse" />
          ))}
        </div>
        <div className="card p-16 flex items-center justify-center text-[#4e5166] text-sm">Loading…</div>
      </div>
    )
  }

  if (isError) {
    const msg = error?.message || 'Failed to load cockpit'
    const friendly = /no active bybit account/i.test(msg) || /404/.test(msg)
    return (
      <div className="space-y-5">
        {header}
        {friendly ? (
          <div className="card p-8 text-center">
            <p className="text-[14px] text-[#e2e4ef]">Connect a perps account to use the cockpit</p>
            <p className="text-[12px] text-[#4e5166] mt-1.5">The cockpit shows live risk for an active perps account.</p>
          </div>
        ) : (
          <div className="card p-6 border border-[#de576f]/40">
            <p className="text-[13px] text-[#de576f]">{msg}</p>
            <p className="text-[11px] text-[#4e5166] mt-1.5">retrying on next poll</p>
          </div>
        )}
      </div>
    )
  }

  const { account, positions = [], asof, plan } = data
  // Merge streamed marks: uPnL, %, notional, R and liq distance go real-time.
  const livePositions = positions.map((p) => withLiveMark(p, marks[p.symbol]))
  const openUpnl = positions.length
    ? livePositions.reduce((s, p) => s + (p.upnl ?? 0), 0)
    : (account.open_upnl ?? 0)
  const sessionPnl = (account.realized_today ?? 0) + openUpnl

  // Loss-cap progress bar shown only when a daily-loss cap is set and the day is in the red.
  const showLossBar = plan && plan.max_daily_loss != null && plan.realized < 0
  const lossPct = showLossBar
    ? Math.min((Math.abs(plan.realized) / plan.max_daily_loss) * 100, 100)
    : 0
  const stale = asof ? Date.now() - Date.parse(asof) > 15000 : false
  const asofTime = asof ? new Date(asof).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'

  return (
    <div className="space-y-5">
      {header}

      {/* Header strip */}
      <div className="flex gap-3 flex-wrap">
        <StatBlock label="Equity" sub={`avail $${fmt(account.available)}`}>
          <span className="text-[#e2e4ef]">${fmt(account.equity)}</span>
        </StatBlock>

        <StatBlock
          label="Session P&L"
          sub={`realized ${signedUsd(account.realized_today)} · open ${signedUsd(openUpnl)}`}
        >
          <span className={pnlColor(sessionPnl)}>{signedUsd(sessionPnl)}</span>
          {showLossBar && (
            <div className="mt-1.5">
              <div className="h-1 rounded bg-[#2a2c30] overflow-hidden">
                <div
                  className="h-full rounded"
                  style={{ width: `${lossPct}%`, background: plan.loss_breached ? '#de576f' : '#f59e0b' }}
                />
              </div>
              <div className="text-[10px] text-[#4e5166] mt-0.5">loss cap ${fmt(plan.max_daily_loss, 0)}</div>
            </div>
          )}
        </StatBlock>

        <StatBlock label="Trades today">
          {plan && plan.max_trades != null ? (
            <span className="inline-flex items-center gap-2">
              <span className={plan.trades_over ? 'text-[#de576f]' : 'text-[#e2e4ef]'}>
                {plan.trades_count} / {plan.max_trades}
              </span>
              {plan.trades_over && (
                <span className="badge bg-[#de576f]/15 text-[#de576f] text-[10px]">OVER</span>
              )}
            </span>
          ) : (
            <span className="text-[#e2e4ef]">{plan ? plan.trades_count : (account.trades_today ?? 0)}</span>
          )}
        </StatBlock>

        <StatBlock label="Open risk">
          <span className="inline-flex items-center gap-2">
            <span className={account.open_risk_pct > 2 ? 'text-[#de576f]' : 'text-[#e2e4ef]'}>
              ${fmt(account.open_risk_usd)} · {fmt(account.open_risk_pct, 1)}%
            </span>
            {account.unstopped_count > 0 && (
              <span className="badge bg-[#f59e0b]/15 text-[#f59e0b] text-[10px]">{account.unstopped_count} unstopped</span>
            )}
          </span>
        </StatBlock>

        <StatBlock label="Exposure" sub={`net ${signedUsd(account.net_notional)}`}>
          <span className="text-[#e2e4ef]">{fmt(account.exposure_pct, 1)}%</span>
        </StatBlock>
      </div>

      {plan === null && (
        <Link to="/plan" className="inline-block text-[12px] text-[#4e5166] hover:text-[#8d91a6] transition-colors">
          no plan today → set one
        </Link>
      )}

      {/* Positions */}
      {positions.length === 0 ? (
        <div className="card p-8 text-center text-[13px] text-[#8d91a6]">
          No open positions — session stats above stay live.
        </div>
      ) : (
        <div className="overflow-x-auto -mx-1 px-1">
          <table className="rows-table">
            <thead>
              <tr>
                {COLUMNS.map((c, i) => (
                  <th key={c} className={i === 0 || i === 1 ? '' : 'th-right'}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {livePositions.map((p) => {
                const liqDist = p.liq_distance_pct
                const rowClass = liqDist != null && liqDist < 5
                  ? 'bg-[#de576f]/10'
                  : liqDist != null && liqDist < 15
                  ? 'bg-[#f59e0b]/5'
                  : ''
                const countdown = p.funding_rate ? fundingCountdown(p.next_funding_at) : null
                return (
                  <tr key={p.symbol} className={rowClass}>
                    <td data-label="Symbol"><span className="text-[13px] font-semibold text-[#fcfefd]">{p.symbol}</span></td>
                    <td data-label="Side">
                      <span className={`badge text-[11px] font-semibold ${
                        p.direction === 'LONG' ? 'bg-[#00d4aa]/10 text-[#00d4aa]' : 'bg-[#de576f]/10 text-[#de576f]'
                      }`}>{p.direction === 'LONG' ? '▲ Long' : '▼ Short'}</span>
                    </td>
                    <td data-label="Size" style={{ textAlign: 'right' }}><span className="font-mono text-[12px] text-[#4e5166]">{fmt(p.qty, 4)}</span></td>
                    <td data-label="Entry" style={{ textAlign: 'right' }}><span className="font-mono text-[12px] text-[#8d91a6]">{fmtPrice(p.avg_entry)}</span></td>
                    <td data-label="Mark" style={{ textAlign: 'right' }}><span className="font-mono text-[12px] text-[#8d91a6]">{fmtPrice(p.mark)}</span></td>
                    <td data-label="uPnL" style={{ textAlign: 'right' }}>
                      <span className={`font-mono text-[13px] font-semibold ${pnlColor(p.upnl)}`}>
                        {signedUsd(p.upnl)}
                        {p.upnl_pct != null && <span className="text-[11px] font-normal ml-1">({p.upnl_pct >= 0 ? '+' : ''}{fmt(p.upnl_pct, 2)}%)</span>}
                      </span>
                    </td>
                    <td data-label="R" style={{ textAlign: 'right' }}>
                      <span className={`font-mono text-[12px] ${p.live_r == null ? 'text-[#4e5166]' : pnlColor(p.live_r)}`}>
                        {p.live_r != null ? `${p.live_r >= 0 ? '+' : ''}${fmt(p.live_r, 2)}R` : '—'}
                      </span>
                    </td>
                    <td data-label="Lev" style={{ textAlign: 'right' }}><span className="font-mono text-[12px] text-[#8d91a6]">{p.leverage != null ? `${fmt(p.leverage, 0)}x` : '—'}</span></td>
                    <td data-label="Liq" style={{ textAlign: 'right' }}>
                      <span className="font-mono text-[12px] text-[#8d91a6]">{fmtPrice(p.liq_price)}</span>
                      {p.liq_distance_pct != null && (
                        <span className="block text-[10px] text-[#4e5166]">{fmt(p.liq_distance_pct, 1)}% away</span>
                      )}
                    </td>
                    <td data-label="Funding" style={{ textAlign: 'right' }}>
                      {p.funding_rate ? (
                        <>
                          <span className="font-mono text-[12px] text-[#8d91a6]">{fmt(p.funding_rate * 100, 4)}%</span>
                          {countdown && <span className="block text-[10px] text-[#4e5166]">{countdown}</span>}
                        </>
                      ) : <span className="font-mono text-[12px] text-[#4e5166]">—</span>}
                    </td>
                    <td data-label="Proj/24h" style={{ textAlign: 'right' }}>
                      <span className={`font-mono text-[12px] ${pnlColor(p.projected_funding_24h)}`}>{signedUsd(p.projected_funding_24h)}</span>
                    </td>
                    <td data-label="Accrued" style={{ textAlign: 'right' }}>
                      <span className={`font-mono text-[12px] ${pnlColor(p.accrued_funding)}`}>{signedUsd(p.accrued_funding)}</span>
                    </td>
                    <td data-label="Stop" style={{ textAlign: 'right' }} onClick={(e) => e.stopPropagation()}>
                      <StopCell accountId={account.account_id} symbol={p.symbol} stopPrice={p.stop_price} stopSource={p.stop_source} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center gap-2 text-[11px] text-[#4e5166] font-mono">
        {connected && <span className="w-2 h-2 rounded-full bg-[#00d4aa]" title="Mark prices streaming live from the exchange" />}
        {stale && <span className="w-2 h-2 rounded-full bg-[#f59e0b] animate-pulse" title="Position data may be stale" />}
        as of {asofTime}{connected ? ' · marks live' : ''}
      </div>
    </div>
  )
}
