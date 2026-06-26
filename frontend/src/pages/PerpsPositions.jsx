import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Plus, Filter, ChevronLeft, ChevronRight, ArrowUpDown } from 'lucide-react'
import { fetchPerpsPositions, fetchPerpsAccounts, fetchPerpsJournalBulk } from '../lib/api'
import { useAccount } from '../components/Layout'
import PerpsFillModal from '../components/PerpsFillModal'

const PER_PAGE = 50
const fmt = (n, d = 2) => (n == null ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }))

const COLUMNS = [
  { key: 'opened_at',    label: 'Date / Time', right: false },
  { key: 'symbol',       label: 'Symbol',      right: false },
  { key: 'direction',    label: 'Side',        right: false },
  { key: 'avg_entry',    label: 'Entry',       right: true },
  { key: 'avg_exit',     label: 'Exit',        right: true },
  { key: 'quantity',     label: 'Size',        right: true },
  { key: 'realized_pnl', label: 'Net P&L',     right: true },
  { key: 'r_multiple',   label: 'R',           right: true },
  { key: 'duration_seconds', label: 'Duration', right: true },
]

function fmtDur(s) {
  if (!s) return '—'
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
  if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

export default function PerpsPositions() {
  const navigate = useNavigate()
  const { perpsAccountId } = useAccount()
  const { data: accounts = [] } = useQuery({ queryKey: ['perps-accounts'], queryFn: fetchPerpsAccounts })
  const { data: positions = [], isLoading } = useQuery({
    queryKey: ['perps-positions', perpsAccountId],
    queryFn: () => fetchPerpsPositions({ ...(perpsAccountId && { account_id: perpsAccountId }) }),
  })
  const { data: bulk = {} } = useQuery({
    queryKey: ['perps-journal-bulk'],
    queryFn: fetchPerpsJournalBulk,
  })
  const [showFill, setShowFill] = useState(false)
  const [page, setPage] = useState(1)
  const [sortBy, setSortBy] = useState('opened_at')
  const [sortDir, setSortDir] = useState('desc')
  const [symbol, setSymbol] = useState('')
  const [side, setSide] = useState('')
  const [status, setStatus] = useState('')

  const symbols = useMemo(() => [...new Set(positions.map(p => p.symbol))].sort(), [positions])

  const filtered = useMemo(() => {
    let rows = positions
    if (symbol) rows = rows.filter(p => p.symbol === symbol)
    if (side) rows = rows.filter(p => p.direction === side)
    if (status) rows = rows.filter(p => p.status === status)
    const dir = sortDir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const va = a[sortBy], vb = b[sortBy]
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      return va < vb ? -dir : va > vb ? dir : 0
    })
  }, [positions, symbol, side, status, sortBy, sortDir])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PER_PAGE))
  // clamp: a background refetch can shrink the dataset while we sit on a late page
  const safePage = Math.min(page, totalPages)
  const pageRows = filtered.slice((safePage - 1) * PER_PAGE, safePage * PER_PAGE)

  // KPI cards intentionally show account-wide totals, not the filtered subset
  const closed = positions.filter(p => p.status === 'CLOSED')
  const totalPnl = closed.reduce((s, p) => s + (p.realized_pnl || 0), 0)
  const openCount = positions.filter(p => p.status === 'OPEN').length

  function handleSort(key) {
    const dir = sortBy === key && sortDir === 'desc' ? 'asc' : 'desc'
    setSortBy(key); setSortDir(dir); setPage(1)
  }
  const setF = (setter) => (v) => { setter(v); setPage(1) }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[22px] font-semibold text-white">Trade Log</h1>
          <p className="text-[13px] text-[#4e5166] mt-0.5">
            {filtered.length} {filtered.length === 1 ? 'position' : 'positions'}
          </p>
        </div>
        <button className="text-[12px] text-[#4e5166] hover:text-[#8d91a6] flex items-center gap-1 transition-colors disabled:opacity-40"
                disabled={accounts.length === 0}
                onClick={() => setShowFill(true)}
                title={accounts.length === 0 ? 'Add an exchange account first' : 'Manually add a fill'}>
          <Plus className="w-3.5 h-3.5" /> Manual fill
        </button>
      </div>

      <div className="flex gap-3">
        <div className="card px-4 py-3"><div className="text-[11px] text-[#4e5166]">Realized P&amp;L</div>
          <div className={`text-[18px] font-semibold ${totalPnl > 0 ? 'text-[#00d4aa]' : totalPnl < 0 ? 'text-[#de576f]' : 'text-[#8d91a6]'}`}>{fmt(totalPnl)}</div></div>
        <div className="card px-4 py-3"><div className="text-[11px] text-[#4e5166]">Closed</div>
          <div className="text-[18px] font-semibold text-[#e2e4ef]">{closed.length}</div></div>
        <div className="card px-4 py-3"><div className="text-[11px] text-[#4e5166]">Open</div>
          <div className="text-[18px] font-semibold text-[#e2e4ef]">{openCount}</div></div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2.5 flex-wrap">
        <div className="flex items-center gap-2 bg-[#1e2024] border border-[#2a2c30] rounded-lg px-3 py-1">
          <Filter className="w-3.5 h-3.5 text-[#4e5166]" />
          <select value={symbol} onChange={(e) => setF(setSymbol)(e.target.value)}
                  className="bg-transparent text-[12px] text-[#8d91a6] outline-none cursor-pointer">
            <option value="">All Symbols</option>
            {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-2 bg-[#1e2024] border border-[#2a2c30] rounded-lg px-3 py-1">
          <select value={side} onChange={(e) => setF(setSide)(e.target.value)}
                  className="bg-transparent text-[12px] text-[#8d91a6] outline-none cursor-pointer">
            <option value="">All Sides</option>
            <option value="LONG">Long</option>
            <option value="SHORT">Short</option>
          </select>
        </div>
        <div className="flex items-center gap-2 bg-[#1e2024] border border-[#2a2c30] rounded-lg px-3 py-1">
          <select value={status} onChange={(e) => setF(setStatus)(e.target.value)}
                  className="bg-transparent text-[12px] text-[#8d91a6] outline-none cursor-pointer">
            <option value="">All Status</option>
            <option value="OPEN">Open</option>
            <option value="CLOSED">Closed</option>
          </select>
        </div>
        {(symbol || side || status) && (
          <button onClick={() => { setSymbol(''); setSide(''); setStatus(''); setPage(1) }}
                  className="text-[11px] text-[#4e5166] hover:text-[#8d91a6] transition-colors">
            Clear filters
          </button>
        )}
      </div>

      {isLoading ? (
        <div className="card p-16 flex items-center justify-center text-[#4e5166] text-sm">Loading…</div>
      ) : (
      <div className="overflow-x-auto -mx-1 px-1">
        <table className="rows-table">
          <thead>
            <tr>
              {COLUMNS.map(col => (
                <th key={col.key} onClick={() => handleSort(col.key)} className={col.right ? 'th-right' : ''}>
                  <span className="inline-flex items-center gap-1">
                    {col.label}
                    {sortBy === col.key && <ArrowUpDown className="w-3 h-3 text-[var(--accent)]" />}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.length === 0 ? (
              <tr><td colSpan={COLUMNS.length}
                style={{ textAlign: 'center', padding: '48px 16px', color: '#4e5166', fontSize: 13 }}>
                No positions found. Sync your exchange account or add a fill manually.
              </td></tr>
            ) : pageRows.map(p => {
              const pnl = p.status === 'CLOSED' ? (p.realized_pnl ?? 0) : 0
              const rowClass = p.status === 'OPEN' ? '' : pnl > 0 ? 'row-win' : pnl < 0 ? 'row-loss' : ''
              return (
                <tr key={p.id} className={rowClass} onClick={() => navigate(`/trades/${p.id}`)}>
                  <td data-label="Date / Time">
                    <span className="text-[12px] font-mono text-[#8d91a6]">
                      {new Date(p.opened_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: '2-digit' })}
                    </span>
                    {p.opened_at_source === 'EXACT' && (
                      <span className="text-[11px] font-mono text-[#4e5166] ml-1.5">
                        {new Date(p.opened_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    )}
                  </td>
                  <td data-label="Symbol">
                    <span className="text-[13px] font-semibold text-[#fcfefd]">{p.symbol}</span>
                    {bulk[p.position_key]?.setup_name && (
                      <span className="badge bg-[rgb(var(--accent-rgb)/0.1)] text-[var(--accent)] text-[10px] ml-1.5">{bulk[p.position_key].setup_name}</span>
                    )}
                    {bulk[p.position_key]?.grade && (() => {
                      const gradeColors = { A: '#00d4aa', B: '#38bdf8', C: '#f59e0b', D: '#de576f' }
                      const c = gradeColors[bulk[p.position_key].grade] || '#8d91a6'
                      return (
                        <span className="badge text-[10px] ml-1" style={{ background: `${c}20`, color: c }}>
                          {bulk[p.position_key].grade}
                        </span>
                      )
                    })()}
                  </td>
                  <td data-label="Side">
                    <span className={`badge text-[11px] font-semibold ${
                      p.direction === 'LONG' ? 'bg-[#00d4aa]/10 text-[#00d4aa]' : 'bg-[#de576f]/10 text-[#de576f]'
                    }`}>{p.direction === 'LONG' ? '▲ Long' : '▼ Short'}</span>
                    {p.status === 'OPEN' && <span className="badge bg-[rgb(var(--accent-rgb)/0.1)] text-[var(--accent)] text-[10px] ml-1.5">OPEN</span>}
                  </td>
                  <td data-label="Entry" style={{ textAlign: 'right' }}><span className="font-mono text-[12px] text-[#8d91a6]">{fmt(p.avg_entry, 5)}</span></td>
                  <td data-label="Exit" style={{ textAlign: 'right' }}><span className="font-mono text-[12px] text-[#8d91a6]">{fmt(p.avg_exit, 5)}</span></td>
                  <td data-label="Size" style={{ textAlign: 'right' }}><span className="font-mono text-[12px] text-[#4e5166]">{fmt(p.quantity, 4)}</span></td>
                  <td data-label="Net P&L" style={{ textAlign: 'right' }}>
                    <span className={`font-mono text-[13px] font-semibold ${
                      p.status === 'OPEN' ? 'text-[#8d91a6]' : pnl > 0 ? 'text-[#00d4aa]' : pnl < 0 ? 'text-[#de576f]' : 'text-[#8d91a6]'
                    }`}>{p.status === 'OPEN' ? '—' : `${pnl >= 0 ? '+' : ''}$${Math.abs(pnl).toFixed(2)}`}</span>
                  </td>
                  <td data-label="R" style={{ textAlign: 'right' }}>
                    <span className="font-mono text-[12px] text-[#8d91a6]">
                      {p.r_multiple != null ? `${p.r_multiple >= 0 ? '+' : ''}${p.r_multiple.toFixed(2)}R` : '—'}
                    </span>
                  </td>
                  <td data-label="Duration" style={{ textAlign: 'right' }}><span className="text-[12px] text-[#4e5166]">{fmtDur(p.duration_seconds)}</span></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3">
          <button onClick={() => setPage(Math.max(1, safePage - 1))} disabled={safePage <= 1}
                  className="btn-ghost p-2 disabled:opacity-20"><ChevronLeft className="w-4 h-4" /></button>
          <span className="text-[12px] text-[#4e5166] font-mono">Page {safePage} of {totalPages}</span>
          <button onClick={() => setPage(Math.min(totalPages, safePage + 1))} disabled={safePage >= totalPages}
                  className="btn-ghost p-2 disabled:opacity-20"><ChevronRight className="w-4 h-4" /></button>
        </div>
      )}

      {showFill && <PerpsFillModal accounts={accounts} onClose={() => setShowFill(false)} />}
    </div>
  )
}
