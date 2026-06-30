import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ClipboardCheck } from 'lucide-react'
import {
  BarChart, Bar, XAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { fetchReviewDraft, fetchReview, saveReview } from '../lib/api'
import { encodePositionKey } from '../lib/positionKey'

const signedUsd = (n) => {
  if (n == null) return '—'
  return `${n >= 0 ? '+' : '-'}$${Math.abs(Number(n)).toFixed(2)}`
}
const pnlColor = (n) => (n == null || n === 0 ? 'text-[#8d91a6]' : n > 0 ? 'text-[#00d4aa]' : 'text-[#de576f]')

const toISO = (d) => d.toISOString().slice(0, 10)

// Monday of the week containing the given UTC date.
function mondayOf(date) {
  const d = new Date(date + 'T00:00:00Z')
  const dow = d.getUTCDay() // 0 Sun … 6 Sat
  const delta = dow === 0 ? -6 : 1 - dow
  d.setUTCDate(d.getUTCDate() + delta)
  return toISO(d)
}
// First of the month containing the given UTC date.
function firstOfMonth(date) {
  const d = new Date(date + 'T00:00:00Z')
  return toISO(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1)))
}

// Default = last COMPLETE period.
function defaultStart(type) {
  const now = new Date()
  const today = toISO(now)
  if (type === 'WEEK') {
    const thisMonday = new Date(mondayOf(today) + 'T00:00:00Z')
    thisMonday.setUTCDate(thisMonday.getUTCDate() - 7) // previous (complete) week
    return toISO(thisMonday)
  }
  // last complete month = first of previous month
  const d = new Date(now)
  return toISO(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - 1, 1)))
}

function normalize(type, date) {
  return type === 'WEEK' ? mondayOf(date) : firstOfMonth(date)
}

function Stat({ label, value, color }) {
  return (
    <div className="min-w-[110px]">
      <div className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">{label}</div>
      <div className={`text-[16px] font-semibold mt-0.5 ${color || 'text-[#e2e4ef]'}`}>{value}</div>
    </div>
  )
}

function DisciplineTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null
  const d = payload[0].payload
  const status = d.adherent === true ? 'adherent' : d.adherent === false ? 'breached' : 'not evaluated'
  return (
    <div className="bg-[#1e2024] border border-[#2a2c30] rounded-lg px-3 py-2 text-[11px]">
      <div className="text-[#e2e4ef] font-medium">{d.date}</div>
      <div className="text-[#8d91a6]">{d.trades_count} trades · {status}</div>
    </div>
  )
}

function DisciplineCurve({ adherence }) {
  const perDay = adherence?.per_day || []
  const data = perDay.map((d) => ({
    ...d,
    day: d.date.slice(8), // DD
    value: 1,
    fill: d.adherent === true ? '#00d4aa' : d.adherent === false ? '#de576f' : '#2a2c30',
  }))
  const caption = adherence?.days_evaluated
    ? `adherence ${adherence.rate_pct != null ? adherence.rate_pct.toFixed(0) : '—'}% · ${adherence.adherent_days}/${adherence.days_evaluated} days`
    : 'no evaluated days'

  return (
    <div className="card p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-[13px] font-semibold text-[#e2e4ef]">Discipline curve</h2>
        <span className="text-[11px] text-[#8d91a6]">{caption}</span>
      </div>
      {data.length === 0 ? (
        <div className="text-[12px] text-[#4e5166]">no plan cards in this period</div>
      ) : (
        <div className="h-[120px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
              <XAxis dataKey="day" tick={{ fill: '#4e5166', fontSize: 10 }} axisLine={false} tickLine={false} interval={0} />
              <Tooltip cursor={{ fill: '#ffffff08' }} content={<DisciplineTooltip />} />
              <Bar dataKey="value" radius={[2, 2, 0, 0]} isAnimationActive={false}>
                {data.map((d, i) => <Cell key={i} fill={d.fill} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

// Small trade card reused for best + worst highlights
function TradeCard({ t, tone }) {
  const borderColor = tone === 'win' ? 'border-[#00d4aa]' : 'border-[#de576f]'
  return (
    <Link
      to={`/trades/${t.position_key ? encodePositionKey(t.position_key) : t.id}`}
      className={`block card border ${borderColor} px-3 py-2 hover:bg-[#242629] transition-colors min-w-0`}
    >
      <div className="flex items-center gap-2 justify-between">
        <span className="text-[12px] font-semibold text-white truncate">{t.symbol}</span>
        <span className={`text-[12px] font-mono font-semibold ${pnlColor(t.pnl)}`}>{signedUsd(t.pnl)}</span>
        <span className="text-[11px] font-mono text-[#8d91a6] shrink-0">
          {t.r != null ? `${Number(t.r) >= 0 ? '+' : ''}${Number(t.r).toFixed(2)}R` : '—'}
        </span>
      </div>
      {t.setup && (
        <div className="text-[10px] text-[#4e5166] mt-0.5 truncate">{t.setup}</div>
      )}
    </Link>
  )
}

const PROBE_QUESTIONS = [
  'Entered too soon', 'Entered too late', 'Took profit too soon', 'Took profit too late',
  'Stops too tight', 'Poor risk/reward', 'Risked too much', 'Risked too little',
  'Missed a trade', 'Deviated from plan',
]

function DemonFinder({ demons }) {
  const ranked = demons?.ranked || []
  if (ranked.length === 0) return null
  const max = Math.max(...ranked.map((d) => d.count), 1)
  const top = demons.top
  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-[#2a2c30] flex items-center justify-between">
        <h2 className="text-[13px] font-semibold text-[#e2e4ef]">Demon Finder</h2>
        {demons.alarm === 'stop' && (
          <span className="badge bg-[#de576f] text-white text-[10px] font-bold">🛑 STOP TRADING</span>
        )}
      </div>
      <div className="p-4 space-y-2">
        {ranked.map((d) => (
          <div key={d.demon} className="flex items-center gap-3 text-[12px]">
            <span className="w-32 shrink-0 text-[#e2e4ef] truncate">{d.demon}</span>
            <div className="flex-1 h-2 rounded-full bg-[#242629] overflow-hidden">
              <div className="h-full bg-[#de576f]" style={{ width: `${(d.count / max) * 100}%` }} />
            </div>
            <span className="w-6 text-right font-mono text-[#8d91a6]">{d.count}</span>
            {d.max_streak >= 3 && (
              <span className={`badge text-[10px] ${d.max_streak >= 10
                ? 'bg-[#de576f] text-white' : 'bg-[#f59e0b]/15 text-[#f59e0b]'}`}>
                {d.max_streak >= 10 ? '🛑' : '⚠'} {d.max_streak} in a row
              </span>
            )}
          </div>
        ))}
        {top && (
          <p className="text-[12px] text-[#e2e4ef] pt-1">
            → <span className="text-[#de576f] font-semibold">Kill first:</span> {top.demon}
          </p>
        )}
      </div>
    </div>
  )
}

// Collapsible full trade list
function AllTradesList({ trades }) {
  const [open, setOpen] = useState(false)
  const [sortByDate, setSortByDate] = useState(false)

  if (!trades || trades.length === 0) return null

  const displayed = sortByDate
    ? [...trades].sort((a, b) => {
        if (!a.date && !b.date) return 0
        if (!a.date) return 1
        if (!b.date) return -1
        return a.date.localeCompare(b.date)
      })
    : trades // already sorted pnl asc from server

  return (
    <div className="card overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-3 text-left hover:bg-[#242629] transition-colors"
      >
        <span className="text-[13px] font-semibold text-[#e2e4ef]">
          {open ? '▾' : '▸'} All {trades.length} trades
        </span>
        {open && (
          <button
            onClick={(e) => { e.stopPropagation(); setSortByDate((v) => !v) }}
            className="text-[11px] text-[#4e5166] hover:text-[#8d91a6] transition-colors px-2 py-0.5 rounded border border-[#2a2c30]"
          >
            Sort by {sortByDate ? 'P&L' : 'date'}
          </button>
        )}
      </button>
      {open && (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-[#2a2c30]">
                <th className="text-left px-5 py-2 text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">Symbol</th>
                <th className="text-right px-3 py-2 text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">P&L</th>
                <th className="text-right px-3 py-2 text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">R</th>
                <th className="text-left px-3 py-2 text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">Date</th>
                <th className="text-left px-3 py-2 text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">Setup</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2a2c30]/50">
              {displayed.map((t) => {
                const isWin = t.pnl > 0
                return (
                  <tr key={t.id}
                    className={`hover:bg-[#242629] transition-colors ${!isWin ? 'bg-[#de576f]/5' : ''}`}>
                    <td className="px-5 py-2">
                      <Link to={`/trades/${t.position_key ? encodePositionKey(t.position_key) : t.id}`}
                        className="font-medium text-white hover:text-[var(--accent)] transition-colors flex items-center gap-1.5">
                        {!isWin && <span className="text-[#de576f] text-[10px]">⚑</span>}
                        {t.symbol}
                      </Link>
                    </td>
                    <td className={`px-3 py-2 text-right font-mono font-semibold ${pnlColor(t.pnl)}`}>
                      {signedUsd(t.pnl)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[#8d91a6]">
                      {t.r != null ? `${Number(t.r) >= 0 ? '+' : ''}${Number(t.r).toFixed(2)}R` : '—'}
                    </td>
                    <td className="px-3 py-2 text-[#8d91a6]">{t.date || '—'}</td>
                    <td className="px-3 py-2 text-[#8d91a6] max-w-[120px] truncate">{t.setup || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function Reviews() {
  const workspace = 'perps'
  const qc = useQueryClient()
  const [type, setType] = useState('WEEK')
  const [start, setStart] = useState(() => defaultStart('WEEK'))
  const [judgment, setJudgment] = useState({
    what_worked: '', what_didnt: '', next_focus: '', problem: '', why: '',
  })
  const [probeFlags, setProbeFlags] = useState([])
  const [savedFlash, setSavedFlash] = useState(false)

  function switchType(next) {
    setType(next)
    setStart(defaultStart(next))
  }
  function onDateChange(e) {
    const raw = e.target.value
    if (raw) setStart(normalize(type, raw))
  }

  const { data: draft, isLoading } = useQuery({
    queryKey: ['review-draft', type, start, workspace],
    queryFn: () => fetchReviewDraft(type, start, workspace),
  })

  const { data: saved } = useQuery({
    queryKey: ['review', type, start, workspace],
    queryFn: () => fetchReview(type, start, workspace),
  })

  useEffect(() => {
    setJudgment({
      what_worked: saved?.what_worked || '',
      what_didnt: saved?.what_didnt || '',
      next_focus: saved?.next_focus || '',
      problem: saved?.problem || '',
      why: saved?.why || '',
    })
    setProbeFlags(Array.isArray(saved?.probe_flags) ? saved.probe_flags : [])
  }, [saved, type, start, workspace])

  const saveMutation = useMutation({
    mutationFn: () => saveReview({
      period_type: type, period_start: start, workspace,
      ...judgment, probe_flags: probeFlags,
    }),
    onSuccess: () => {
      setSavedFlash(true)
      setTimeout(() => setSavedFlash(false), 1800)
      qc.invalidateQueries({ queryKey: ['review', type, start, workspace] })
    },
  })

  const setJ = (key) => (e) => setJudgment((j) => ({ ...j, [key]: e.target.value }))
  const toggleProbe = (q) =>
    setProbeFlags((f) => (f.includes(q) ? f.filter((x) => x !== q) : [...f, q]))

  const stats = draft?.stats || {}
  const period = draft?.period

  // Derived trade lists from the full sorted (pnl asc) trades array
  const trades = draft?.trades || []
  const brightSpots = draft?.bright_spots || {}

  // best-3: winners sorted by pnl desc, take 3
  const best3 = [...trades].filter((t) => t.pnl > 0).sort((a, b) => b.pnl - a.pnl).slice(0, 3)
  // worst-3: losers (pnl asc already), take 3
  const worst3 = trades.filter((t) => t.pnl < 0).slice(0, 3)

  const hasBrightSpots = brightSpots.best_symbol != null || brightSpots.best_setup != null

  const header = (
    <div className="flex items-center justify-between flex-wrap gap-4">
      <div className="flex items-center gap-3">
        <ClipboardCheck className="w-5 h-5 text-[var(--accent)]" />
        <div>
          <h1 className="text-[22px] font-semibold text-white">Reviews</h1>
          <p className="text-[13px] text-[#4e5166] mt-0.5">
            {period ? `${period.start} → ${period.end}` : 'the evening confrontation with the morning plan'}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <div className="flex bg-[#1a1b1e] border border-[#2a2c30] rounded-lg p-0.5 gap-0.5">
          {['WEEK', 'MONTH'].map((t) => (
            <button key={t} onClick={() => switchType(t)}
              className={`px-4 py-1.5 text-[12px] font-semibold rounded-md transition-all ${
                type === t ? 'bg-[var(--accent)] text-white' : 'text-[#4e5166] hover:text-[#8d91a6]'
              }`}>
              {t === 'WEEK' ? 'Week' : 'Month'}
            </button>
          ))}
        </div>
        <input type="date" value={start} onChange={onDateChange}
          className="input text-[12px] w-[150px]" />
      </div>
    </div>
  )

  return (
    <div className="space-y-5 max-w-[1100px]">
      {header}

      {isLoading ? (
        <div className="card p-16 flex items-center justify-center text-[#4e5166] text-sm">Loading…</div>
      ) : (
        <>
          {/* Stats row */}
          <div className="card p-4 flex flex-wrap items-start gap-x-8 gap-y-4">
            <Stat label="Trades" value={stats.total_trades ?? 0} />
            <Stat label="P&L" value={signedUsd(stats.total_pnl)} color={pnlColor(stats.total_pnl)} />
            <Stat label="Win %" value={stats.win_rate != null ? `${Number(stats.win_rate).toFixed(1)}%` : '—'} />
          </div>

          {/* Discipline curve */}
          <DisciplineCurve adherence={draft?.adherence} />

          {/* What worked zone */}
          <div className="space-y-3">
            <h2 className="text-[13px] font-semibold text-[#00d4aa] uppercase tracking-[0.06em]">What worked</h2>

            {/* Best-3 trade cards */}
            {best3.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                {best3.map((t) => <TradeCard key={t.id} t={t} tone="win" />)}
              </div>
            )}
            {best3.length === 0 && (
              <div className="text-[12px] text-[#4e5166]">no winning trades this period</div>
            )}

            {/* Bright-spots summary line */}
            {hasBrightSpots && (
              <div className="text-[12px] text-[#8d91a6] flex flex-wrap gap-x-4 gap-y-1">
                {brightSpots.best_setup && (
                  <span>
                    Best setup: <span className="text-[#00d4aa] font-semibold">{brightSpots.best_setup.name}</span>{' '}
                    <span className="text-[#00d4aa]">{signedUsd(brightSpots.best_setup.pnl)}</span>
                  </span>
                )}
                {brightSpots.best_symbol && (
                  <span>
                    Best symbol: <span className="text-[#00d4aa] font-semibold">{brightSpots.best_symbol.name}</span>{' '}
                    <span className="text-[#00d4aa]">{signedUsd(brightSpots.best_symbol.pnl)}</span>
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Biggest losses zone */}
          <div className="space-y-3">
            <h2 className="text-[13px] font-semibold text-[#de576f] uppercase tracking-[0.06em]">Biggest losses</h2>
            <p className="text-[11px] text-[#4e5166] -mt-1">Losses are normal in a profitable system. Review these for execution quality, not the outcome.</p>

            {/* Worst-3 trade cards */}
            {worst3.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                {worst3.map((t) => <TradeCard key={t.id} t={t} tone="loss" />)}
              </div>
            )}
            {worst3.length === 0 && (
              <div className="text-[12px] text-[#4e5166]">no losing trades this period</div>
            )}

            <DemonFinder demons={draft?.demons} />
          </div>

          {/* All N trades collapsible */}
          <AllTradesList trades={trades} />

          {draft?.days_without_card > 0 && (
            <div className="text-[12px] text-[#8d91a6]">
              {draft.days_without_card} trading {draft.days_without_card === 1 ? 'day' : 'days'} had no plan
            </div>
          )}

          {/* Judgment */}
          <div className="card p-4 space-y-4">
            <h2 className="text-[13px] font-semibold text-[#e2e4ef]">Your judgment</h2>

            <div>
              <label className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] block mb-1">What worked</label>
              <textarea className="input w-full text-[12px] resize-y" rows={3}
                value={judgment.what_worked} onChange={setJ('what_worked')}
                placeholder="the process that paid off" />
            </div>

            <div>
              <label className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] block mb-1">What didn't — consider</label>
              <div className="flex flex-wrap gap-1.5 mb-2">
                {PROBE_QUESTIONS.map((q) => {
                  const on = probeFlags.includes(q)
                  return (
                    <button key={q} type="button" onClick={() => toggleProbe(q)}
                      className={`text-[11px] px-2 py-1 rounded-md border transition-colors ${
                        on ? 'border-[#de576f] bg-[#de576f]/10 text-[#e2e4ef]'
                           : 'border-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6]'}`}>
                      {q}
                    </button>
                  )
                })}
              </div>
              <textarea className="input w-full text-[12px] resize-y" rows={3}
                value={judgment.what_didnt} onChange={setJ('what_didnt')}
                placeholder="where the leaks were" />
            </div>

            <div className="grid md:grid-cols-3 gap-3">
              <div>
                <label className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] block mb-1">Recurring problem</label>
                <textarea className="input w-full text-[12px] resize-y" rows={2}
                  value={judgment.problem} onChange={setJ('problem')}
                  placeholder={draft?.demons?.top ? `e.g. ${draft.demons.top.demon}` : 'the pattern that keeps costing you'} />
              </div>
              <div>
                <label className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] block mb-1">Why</label>
                <textarea className="input w-full text-[12px] resize-y" rows={2}
                  value={judgment.why} onChange={setJ('why')} placeholder="why it keeps happening" />
              </div>
              <div>
                <label className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] block mb-1">Action</label>
                <textarea className="input w-full text-[12px] resize-y" rows={2}
                  value={judgment.next_focus} onChange={setJ('next_focus')} placeholder="the one thing to fix" />
              </div>
            </div>

            <div className="flex items-center gap-3">
              <button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}
                className="btn-blue px-6 text-[13px] disabled:opacity-50 active:scale-[0.98]">
                {saveMutation.isPending ? 'Saving…' : 'Save'}
              </button>
              {savedFlash && <span className="text-[12px] text-[#00d4aa]">Saved</span>}
              {saveMutation.isError && (
                <span className="text-[12px] text-[#de576f]">{saveMutation.error?.message || 'Save failed'}</span>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
