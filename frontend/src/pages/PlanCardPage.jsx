import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, NotebookPen, Plus } from 'lucide-react'
import {
  fetchPlanCard, savePlanCard, fetchPlanScore, fetchPlaybooksLite,
  fetchWatchlist, fetchAlerts,
} from '../lib/api'

const TODAY = () => new Date().toISOString().slice(0, 10)
const MENTAL_STATES = ['Confident', 'Calm', 'Neutral', 'Nervous', 'Tired']

const BIAS_OPTIONS = ['Long', 'Short', 'Neutral']
const BIAS_COLORS = {
  Long: 'bg-[#00d4aa] text-white',
  Short: 'bg-[#de576f] text-white',
  Neutral: 'bg-[var(--accent)] text-white',
}

function BiasRow({ label, value, onChange, editable }) {
  return (
    <div>
      <label className="text-[11px] text-[#4e5166] block mb-1">{label}</label>
      <div className="flex gap-2">
        {BIAS_OPTIONS.map((opt) => {
          const active = value === opt
          return (
            <button key={opt} type="button" disabled={!editable}
              onClick={() => onChange(active ? '' : opt)}
              className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors disabled:opacity-60 ${
                active ? BIAS_COLORS[opt] : 'bg-[#242629] text-[#8d91a6] hover:text-[#e2e4ef]'
              }`}>
              {opt}
            </button>
          )
        })}
      </div>
    </div>
  )
}

const signedUsd = (n) => {
  if (n == null) return '—'
  return `${n >= 0 ? '+' : '-'}$${Math.abs(Number(n)).toFixed(2)}`
}
const pnlColor = (n) => (n == null || n === 0 ? 'text-[#8d91a6]' : n > 0 ? 'text-[#00d4aa]' : 'text-[#de576f]')

// add/subtract days to a YYYY-MM-DD string in UTC
function shiftDate(date, days) {
  const d = new Date(date + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}
function weekdayLabel(date) {
  const d = new Date(date + 'T00:00:00Z')
  return d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

const EMPTY_FORM = {
  session_start_hour: 0,
  playbook_id: '',
  a_setup_note: '',
  shortlist: [],
  not_today: '',
  mental_state: '',
  max_trades: '',
  max_daily_loss: '',
  r_per_trade: '',
  circuit_rules: '',
  key_lesson: '',
  tomorrow_focus: '',
  htf_bias: '',
  ltf_bias: '',
  expectations: '',
  key_levels_buy: '',
  key_levels_sell: '',
  did_well: '',
  did_poorly: '',
  eod_why: '',
}

function cardToForm(card) {
  if (!card) return { ...EMPTY_FORM }
  return {
    session_start_hour: card.session_start_hour ?? 0,
    playbook_id: card.playbook_id ?? '',
    a_setup_note: card.a_setup_note ?? '',
    shortlist: Array.isArray(card.shortlist) ? card.shortlist : [],
    not_today: card.not_today ?? '',
    mental_state: card.mental_state ?? '',
    max_trades: card.max_trades ?? '',
    max_daily_loss: card.max_daily_loss ?? '',
    r_per_trade: card.r_per_trade ?? '',
    circuit_rules: card.circuit_rules ?? '',
    key_lesson: card.key_lesson ?? '',
    tomorrow_focus: card.tomorrow_focus ?? '',
    htf_bias: card.htf_bias ?? '',
    ltf_bias: card.ltf_bias ?? '',
    expectations: card.expectations ?? '',
    key_levels_buy: card.key_levels_buy ?? '',
    key_levels_sell: card.key_levels_sell ?? '',
    did_well: card.did_well ?? '',
    did_poorly: card.did_poorly ?? '',
    eod_why: card.eod_why ?? '',
  }
}

// build the PUT body — empty strings become null, numbers parsed
function formToPayload(form) {
  const num = (v) => (v === '' || v == null ? null : Number(v))
  return {
    session_start_hour: form.session_start_hour === '' ? 0 : Number(form.session_start_hour),
    playbook_id: form.playbook_id === '' ? null : Number(form.playbook_id),
    a_setup_note: form.a_setup_note || null,
    shortlist: form.shortlist,
    not_today: form.not_today || null,
    mental_state: form.mental_state || null,
    max_trades: num(form.max_trades),
    max_daily_loss: num(form.max_daily_loss),
    r_per_trade: num(form.r_per_trade),
    circuit_rules: form.circuit_rules || null,
    key_lesson: form.key_lesson || null,
    tomorrow_focus: form.tomorrow_focus || null,
    htf_bias: form.htf_bias || null,
    ltf_bias: form.ltf_bias || null,
    expectations: form.expectations || null,
    key_levels_buy: form.key_levels_buy || null,
    key_levels_sell: form.key_levels_sell || null,
    did_well: form.did_well || null,
    did_poorly: form.did_poorly || null,
    eod_why: form.eod_why || null,
  }
}

function Section({ title, hint, children, className = '' }) {
  return (
    <div className={`card p-4 ${className}`}>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-[13px] font-semibold text-[#e2e4ef]">{title}</h2>
        {hint && <span className="text-[11px] text-[#4e5166]">{hint}</span>}
      </div>
      {children}
    </div>
  )
}

// ── Regime (read-only) ────────────────────────────────────────────────────────
function RegimeBlock({ market, snap }) {
  const b = snap?.breadth || {}
  const total = b.total
  const hasBreadth = b.above_20 != null || b.above_50 != null || b.above_200 != null
  const themes = Array.isArray(snap?.top_themes) ? snap.top_themes : []
  return (
    <div className="flex-1 min-w-[200px]">
      <div className="text-[11px] font-semibold text-[#8d91a6] uppercase tracking-wide mb-1.5">{market}</div>
      {hasBreadth ? (
        <div className="text-[12px] text-[#e2e4ef] font-mono">
          Above 20/50/200MA: {b.above_20 ?? '—'}/{b.above_50 ?? '—'}/{b.above_200 ?? '—'}
          {total != null && <span className="text-[#4e5166]"> of {total}</span>}
        </div>
      ) : (
        <div className="text-[12px] text-[#4e5166]">breadth unavailable</div>
      )}
      {themes.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {themes.map((t, i) => (
            <span key={i} className="badge bg-[rgb(var(--accent-rgb)/0.1)] text-[var(--accent)] text-[10px]">
              {t.theme} {t.score != null ? Number(t.score).toFixed(0) : ''}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function RegimePanel({ snapshot, isCreate }) {
  if (isCreate) {
    return <div className="text-[12px] text-[#4e5166]">regime will be captured when you save</div>
  }
  if (!snapshot) {
    return <div className="text-[12px] text-[#4e5166]">market data unavailable</div>
  }
  const markets = Object.keys(snapshot)
  if (markets.length === 0) {
    return <div className="text-[12px] text-[#4e5166]">market data unavailable</div>
  }
  return (
    <div className="flex flex-wrap gap-5">
      {markets.map((m) => (
        <RegimeBlock key={m} market={m} snap={snapshot[m]} />
      ))}
    </div>
  )
}

// ── Shortlist chip input ──────────────────────────────────────────────────────
function ShortlistInput({ value, onChange, readOnly }) {
  const [text, setText] = useState('')
  function commit(raw) {
    const sym = raw.trim().toUpperCase()
    if (!sym) return
    if (!value.includes(sym)) onChange([...value, sym])
    setText('')
  }
  function onKeyDown(e) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      commit(text)
    } else if (e.key === 'Backspace' && text === '' && value.length) {
      onChange(value.slice(0, -1))
    }
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {value.map((sym) => (
        <span key={sym} className="badge bg-[#242629] text-[#e2e4ef] text-[11px] inline-flex items-center gap-1">
          {sym}
          {!readOnly && (
            <button type="button" onClick={() => onChange(value.filter((s) => s !== sym))}
              className="text-[#4e5166] hover:text-[#de576f] leading-none">×</button>
          )}
        </span>
      ))}
      {!readOnly && (
        <input
          className="input flex-1 min-w-[160px] text-[12px]"
          value={text}
          placeholder="symbols you're allowed to trade today"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => commit(text)}
        />
      )}
      {readOnly && value.length === 0 && <span className="text-[12px] text-[#4e5166]">—</span>}
    </div>
  )
}

// ── Watchlist promotion section ───────────────────────────────────────────────
// Watchlist items as rows; each can be promoted into the shortlist form state.
// An amber dot marks symbols with an unseen LEVEL_CROSS alert. Edit mode only.
function WatchlistSection({ shortlist, onAdd, editable }) {
  const { data: items = [] } = useQuery({
    queryKey: ['watchlist'],
    queryFn: fetchWatchlist,
  })
  // Reuse a lightweight alerts fetch to flag symbols with unseen level crosses.
  const { data: alertData } = useQuery({
    queryKey: ['alerts-for-plan'],
    queryFn: () => fetchAlerts(50),
    staleTime: 60000,
    retry: false,
  })
  const flaggedSymbols = new Set(
    (alertData?.alerts || [])
      .filter(a => a.kind === 'LEVEL_CROSS' && !a.seen && (a.symbol || a.payload?.symbol))
      .map(a => a.symbol || a.payload?.symbol)
  )

  if (!Array.isArray(items) || items.length === 0) return null

  return (
    <Section title="Watchlist" hint="promote to shortlist">
      <div className="space-y-1.5">
        {items.map((item) => {
          const inList = shortlist.includes(item.symbol)
          const flagged = flaggedSymbols.has(item.symbol)
          const levels = Array.isArray(item.levels) ? item.levels : []
          return (
            <div key={item.id} className="flex items-center gap-2 text-[12px] py-1">
              <span className="font-mono text-[#e2e4ef] w-20 shrink-0 inline-flex items-center gap-1">
                {item.symbol}
                {flagged && <span className="inline-block w-[6px] h-[6px] rounded-full bg-[#f59e0b]"
                  title="unseen level cross" />}
              </span>
              <span className="badge bg-[#242629] text-[#8d91a6] text-[10px] shrink-0">{item.market}</span>
              <div className="flex flex-wrap gap-1 flex-1 min-w-0">
                {levels.map((lvl, i) => (
                  <span key={i} className="badge bg-[#1a1b1e] text-[#8d91a6] text-[10px]">
                    {lvl.label ? `${lvl.label}@` : ''}{lvl.price}
                  </span>
                ))}
              </div>
              <button
                type="button"
                disabled={!editable || inList}
                onClick={() => onAdd(item.symbol)}
                className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium transition-colors
                  disabled:opacity-40 disabled:cursor-default
                  bg-[#242629] text-[var(--accent)] hover:bg-[rgb(var(--accent-rgb)/0.15)]"
              >
                <Plus className="w-3 h-3" />
                {inList ? 'on list' : 'shortlist'}
              </button>
            </div>
          )
        })}
      </div>
    </Section>
  )
}

// ── Today's score card ────────────────────────────────────────────────────────
// Scored for the ACTIVE workspace — prop P&L never silently bleeds into a perps
// view (and vice versa). The combined day shows as an explicitly labeled line.
function ScoreCard({ score, combined, workspace }) {
  const { trades_count, max_trades, realized, max_daily_loss, offlist_symbols = [], flags = {}, adherent } = score
  const lossPct = max_daily_loss ? Math.min(Math.abs(Math.min(realized, 0)) / max_daily_loss, 1) : 0
  const showCombined = combined && combined.trades_count !== trades_count
  return (
    <Section title={`Today's score · ${workspace}`} hint="updates every 30s">
      <div className="flex flex-wrap items-center gap-6">
        <div>
          <div className="text-[11px] text-[#4e5166]">Trades</div>
          <div className="text-[18px] font-semibold mt-0.5 inline-flex items-center gap-2">
            <span className={flags.trades_over ? 'text-[#de576f]' : 'text-[#e2e4ef]'}>
              {trades_count}{max_trades != null ? ` / ${max_trades}` : ''}
            </span>
            {flags.trades_over && <span className="badge bg-[#de576f]/15 text-[#de576f] text-[10px]">OVER</span>}
          </div>
        </div>
        <div className="min-w-[160px]">
          <div className="text-[11px] text-[#4e5166]">Realized</div>
          <div className={`text-[18px] font-semibold mt-0.5 ${pnlColor(realized)}`}>{signedUsd(realized)}</div>
          {max_daily_loss != null && (
            <div className="h-1 mt-1.5 rounded-full bg-[#242629] overflow-hidden">
              <div className={`h-full ${flags.loss_breached ? 'bg-[#de576f]' : 'bg-[#f59e0b]'}`}
                style={{ width: `${lossPct * 100}%` }} />
            </div>
          )}
        </div>
        <div className="flex-1" />
        <div>
          {adherent
            ? <span className="text-[16px] font-bold text-[#00d4aa]">ADHERENT</span>
            : <span className="text-[16px] font-bold text-[#de576f]">BREACHED</span>}
        </div>
      </div>
      {offlist_symbols.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 mt-3">
          <span className="text-[11px] text-[#4e5166]">off-list:</span>
          {offlist_symbols.map((s) => (
            <span key={s} className="badge bg-[#de576f]/15 text-[#de576f] text-[10px]">{s}</span>
          ))}
        </div>
      )}
      {showCombined && (
        <div className="text-[11px] text-[#4e5166] mt-3">
          combined day (both workspaces): <span className={pnlColor(combined.realized)}>{signedUsd(combined.realized)}</span> · {combined.trades_count} trades
        </div>
      )}
    </Section>
  )
}

export default function PlanCardPage() {
  const qc = useQueryClient()
  const workspace = 'perps'
  const [date, setDate] = useState(TODAY)
  const [form, setForm] = useState({ ...EMPTY_FORM })
  const [savedFlash, setSavedFlash] = useState(false)

  const isToday = date === TODAY()
  const editable = isToday

  const { data: card, isLoading } = useQuery({
    queryKey: ['plan-card', date],
    queryFn: () => fetchPlanCard(date),
    retry: false,
  })
  const isCreate = !isLoading && card == null

  // Score follows the active workspace; the combined day rides along for the
  // explicitly labeled sub-line (never silently mixed into the headline).
  const { data: score } = useQuery({
    queryKey: ['plan-score', date, workspace],
    queryFn: () => fetchPlanScore(date, workspace),
    enabled: card != null,
    retry: false,
    refetchInterval: isToday ? 30000 : false,
  })
  const { data: combinedScore } = useQuery({
    queryKey: ['plan-score', date, 'all'],
    queryFn: () => fetchPlanScore(date, 'all'),
    enabled: card != null,
    retry: false,
    refetchInterval: isToday ? 30000 : false,
  })

  const { data: playbooks = [] } = useQuery({
    queryKey: ['playbooks-lite'],
    queryFn: fetchPlaybooksLite,
  })

  // reset form whenever the loaded card identity (date) changes
  useEffect(() => {
    setForm(cardToForm(card))
  }, [date, card])

  const saveMutation = useMutation({
    mutationFn: () => savePlanCard(date, formToPayload(form)),
    onSuccess: () => {
      setSavedFlash(true)
      setTimeout(() => setSavedFlash(false), 1800)
      qc.invalidateQueries({ queryKey: ['plan-card', date] })
      qc.invalidateQueries({ queryKey: ['plan-score', date] })
    },
  })

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const header = (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        <NotebookPen className="w-5 h-5 text-[var(--accent)]" />
        <div>
          <h1 className="text-[22px] font-semibold text-white flex items-center gap-2">
            {weekdayLabel(date)}
            {isToday && <span className="badge bg-[rgb(var(--accent-rgb)/0.15)] text-[var(--accent)] text-[10px]">Today</span>}
          </h1>
          <p className="text-[13px] text-[#4e5166] mt-0.5">two-minute commitment ritual</p>
        </div>
      </div>
      <div className="flex items-center gap-1">
        <button onClick={() => setDate((d) => shiftDate(d, -1))}
          className="p-2 rounded-lg text-[#8d91a6] hover:text-white hover:bg-[#242629] transition-colors">
          <ChevronLeft className="w-4 h-4" />
        </button>
        <button onClick={() => setDate((d) => shiftDate(d, 1))}
          disabled={isToday}
          className="p-2 rounded-lg text-[#8d91a6] hover:text-white hover:bg-[#242629] transition-colors disabled:opacity-30 disabled:hover:bg-transparent">
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )

  if (isLoading) {
    return (
      <div className="space-y-5">
        {header}
        <div className="card p-16 flex items-center justify-center text-[#4e5166] text-sm">Loading…</div>
      </div>
    )
  }

  return (
    <div className="space-y-4 max-w-[1100px]">
      {header}

      {!editable && (
        <div className="text-[12px] text-[#f59e0b]">Read-only — past plans cannot be edited.</div>
      )}

      {/* Regime */}
      <Section title="Regime" hint="frozen at first save">
        <RegimePanel snapshot={card?.regime_snapshot} isCreate={isCreate} />
      </Section>

      {/* Market read */}
      <Section title="Market read" hint="your directional read before the session">
        <div className="space-y-3">
          <div className="flex flex-wrap gap-6">
            <BiasRow label="HTF bias" value={form.htf_bias} editable={editable}
              onChange={(v) => setForm((f) => ({ ...f, htf_bias: v }))} />
            <BiasRow label="LTF bias" value={form.ltf_bias} editable={editable}
              onChange={(v) => setForm((f) => ({ ...f, ltf_bias: v }))} />
          </div>
          <div>
            <label className="text-[11px] text-[#4e5166] block mb-1">Expectations</label>
            <input className="input w-full text-[12px]" disabled={!editable}
              placeholder="what you expect today — e.g. range until US open"
              value={form.expectations} onChange={set('expectations')} />
          </div>
          <div className="grid lg:grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] text-[#4e5166] block mb-1">Key levels — buy side</label>
              <textarea className="input w-full text-[12px]" rows={2} disabled={!editable}
                placeholder="98,200 / 97,400"
                value={form.key_levels_buy} onChange={set('key_levels_buy')} />
            </div>
            <div>
              <label className="text-[11px] text-[#4e5166] block mb-1">Key levels — sell side</label>
              <textarea className="input w-full text-[12px]" rows={2} disabled={!editable}
                placeholder="101,500 / 102,800"
                value={form.key_levels_sell} onChange={set('key_levels_sell')} />
            </div>
          </div>
        </div>
      </Section>

      {/* A-setup */}
      <Section title="A-setup">
        <div className="flex flex-col lg:flex-row gap-3">
          <select
            className="input lg:w-56 text-[12px]"
            value={form.playbook_id}
            disabled={!editable}
            onChange={set('playbook_id')}
          >
            <option value="">— playbook —</option>
            {playbooks.map((pb) => (
              <option key={pb.id} value={pb.id}>{pb.name}</option>
            ))}
          </select>
          <input
            className="input flex-1 text-[12px]"
            placeholder="the one setup you're hunting today"
            value={form.a_setup_note}
            disabled={!editable}
            onChange={set('a_setup_note')}
          />
        </div>
      </Section>

      {/* Shortlist */}
      <Section title="Shortlist">
        <ShortlistInput
          value={form.shortlist}
          readOnly={!editable}
          onChange={(next) => setForm((f) => ({ ...f, shortlist: next }))}
        />
      </Section>

      {/* Watchlist → shortlist promotion (today only) */}
      {editable && (
        <WatchlistSection
          shortlist={form.shortlist}
          editable={editable}
          onAdd={(sym) => setForm((f) => (
            f.shortlist.includes(sym) ? f : { ...f, shortlist: [...f.shortlist, sym] }
          ))}
        />
      )}

      {/* Rules */}
      <Section title="Rules">
        <div className="grid lg:grid-cols-2 gap-3">
          <div>
            <label className="text-[11px] text-[#4e5166] block mb-1">Not today</label>
            <textarea className="input w-full text-[12px]" rows={2} disabled={!editable}
              placeholder="what you will NOT do today"
              value={form.not_today} onChange={set('not_today')} />
          </div>
          <div>
            <label className="text-[11px] text-[#4e5166] block mb-1">Circuit rules</label>
            <textarea className="input w-full text-[12px]" rows={2} disabled={!editable}
              placeholder="stop-trading triggers"
              value={form.circuit_rules} onChange={set('circuit_rules')} />
          </div>
        </div>
      </Section>

      {/* Mental state */}
      <Section title="Mental state">
        <div className="flex flex-wrap gap-2">
          {MENTAL_STATES.map((m) => {
            const active = form.mental_state === m
            return (
              <button key={m} type="button" disabled={!editable}
                onClick={() => setForm((f) => ({ ...f, mental_state: active ? '' : m }))}
                className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors disabled:opacity-60 ${
                  active ? 'bg-[var(--accent)] text-white' : 'bg-[#242629] text-[#8d91a6] hover:text-[#e2e4ef]'
                }`}>
                {m}
              </button>
            )
          })}
        </div>
      </Section>

      {/* Commitments */}
      <Section title="Commitments">
        <div className="flex flex-wrap gap-4">
          <div>
            <label className="text-[11px] text-[#4e5166] block mb-1">Max trades</label>
            <input type="number" className="input w-28 text-[12px]" disabled={!editable}
              value={form.max_trades} onChange={set('max_trades')} />
          </div>
          <div>
            <label className="text-[11px] text-[#4e5166] block mb-1">Max daily loss $</label>
            <input type="number" className="input w-32 text-[12px]" disabled={!editable}
              value={form.max_daily_loss} onChange={set('max_daily_loss')} />
          </div>
          <div>
            <label className="text-[11px] text-[#4e5166] block mb-1">R per trade</label>
            <input type="number" step="any" className="input w-28 text-[12px]" disabled={!editable}
              value={form.r_per_trade} onChange={set('r_per_trade')} />
          </div>
          <div>
            <label className="text-[11px] text-[#4e5166] block mb-1">Session starts (UTC)</label>
            <select className="input w-28 text-[12px]" disabled={!editable}
              value={form.session_start_hour} onChange={set('session_start_hour')}>
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>
              ))}
            </select>
          </div>
        </div>
      </Section>

      {/* Score (not in create mode) */}
      {!isCreate && score && <ScoreCard score={score} combined={combinedScore} workspace={workspace} />}

      {/* Post-session */}
      <Section title="Post-session" hint="the evening confrontation">
        <div className="grid lg:grid-cols-2 gap-3">
          <div>
            <label className="text-[11px] text-[#4e5166] block mb-1">Did well</label>
            <textarea className="input w-full text-[12px]" rows={2} disabled={!editable}
              placeholder="what you executed well today"
              value={form.did_well} onChange={set('did_well')} />
          </div>
          <div>
            <label className="text-[11px] text-[#4e5166] block mb-1">Did poorly</label>
            <textarea className="input w-full text-[12px]" rows={2} disabled={!editable}
              placeholder="where you slipped"
              value={form.did_poorly} onChange={set('did_poorly')} />
          </div>
          <div className="lg:col-span-2">
            <label className="text-[11px] text-[#4e5166] block mb-1">Why (to both)</label>
            <textarea className="input w-full text-[12px]" rows={2} disabled={!editable}
              placeholder="the real reason behind both"
              value={form.eod_why} onChange={set('eod_why')} />
          </div>
          <div>
            <label className="text-[11px] text-[#4e5166] block mb-1">Key lesson</label>
            <textarea className="input w-full text-[12px]" rows={2} disabled={!editable}
              placeholder="the one thing today taught you"
              value={form.key_lesson} onChange={set('key_lesson')} />
          </div>
          <div>
            <label className="text-[11px] text-[#4e5166] block mb-1">Tomorrow's focus</label>
            <textarea className="input w-full text-[12px]" rows={2} disabled={!editable}
              placeholder="what you'll do differently"
              value={form.tomorrow_focus} onChange={set('tomorrow_focus')} />
          </div>
        </div>
      </Section>

      {/* Save */}
      {editable && (
        <div className="flex items-center gap-3 sticky bottom-0 py-3">
          <button
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
            className="btn-blue px-6 text-[13px] disabled:opacity-50 active:scale-[0.98]"
          >
            {saveMutation.isPending ? 'Saving…' : 'Save'}
          </button>
          {savedFlash && <span className="text-[12px] text-[#00d4aa]">Saved</span>}
          {saveMutation.isError && (
            <span className="text-[12px] text-[#de576f]">{saveMutation.error?.message || 'Save failed'}</span>
          )}
        </div>
      )}
    </div>
  )
}
