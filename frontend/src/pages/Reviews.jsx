import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ClipboardCheck } from 'lucide-react'
import {
  BarChart, Bar, XAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { fetchReviewDraft, fetchReview, saveReview } from '../lib/api'

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

function FlaggedTrades({ flagged }) {
  if (!flagged || flagged.length === 0) return null
  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-[#2a2c30]">
        <h2 className="text-[13px] font-semibold text-[#e2e4ef]">Flagged trades</h2>
      </div>
      <div className="divide-y divide-[#2a2c30]/50">
        {flagged.map((t, i) => {
          const to = `/trades/${t.id}`
          return (
            <Link key={i} to={to}
              className="flex items-center gap-3 px-5 py-2.5 hover:bg-[#242629] transition-colors">
              <span className="text-[13px] font-medium text-white w-28 truncate">{t.symbol}</span>
              <span className="flex-1" />
              <span className={`text-[13px] font-mono font-semibold ${pnlColor(t.pnl)}`}>{signedUsd(t.pnl)}</span>
              <span className="text-[12px] font-mono text-[#8d91a6] w-16 text-right">
                {t.r != null ? `${Number(t.r) >= 0 ? '+' : ''}${Number(t.r).toFixed(2)}R` : '—'}
              </span>
            </Link>
          )
        })}
      </div>
    </div>
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

  const header = (
    <div className="flex items-center justify-between flex-wrap gap-4">
      <div className="flex items-center gap-3">
        <ClipboardCheck className="w-5 h-5 text-[#38bdf8]" />
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
                type === t ? 'bg-[#38bdf8] text-white' : 'text-[#4e5166] hover:text-[#8d91a6]'
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
          {/* Stat row — scoped to the active workspace */}
          <div className="card p-4 flex flex-wrap items-start gap-x-8 gap-y-4">
            <Stat label="Trades" value={stats.total_trades ?? 0} />
            <Stat label="P&L" value={signedUsd(stats.total_pnl)} color={pnlColor(stats.total_pnl)} />
            <Stat label="Win %" value={stats.win_rate != null ? `${Number(stats.win_rate).toFixed(1)}%` : '—'} />
          </div>

          <DisciplineCurve adherence={draft?.adherence} />

          <FlaggedTrades flagged={draft?.flagged} />

          <DemonFinder demons={draft?.demons} />

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
