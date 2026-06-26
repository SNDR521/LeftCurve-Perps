import { useNavigate } from 'react-router-dom'
import { useQueryClient, useMutation, useQuery } from '@tanstack/react-query'
import { useState, useEffect, useRef } from 'react'
import {
  ArrowLeft, Save, Trash2, Upload, BarChart3, Image, AlertTriangle, Plus,
} from 'lucide-react'
import TradeChart from './TradeChart'
import { fetchPlaybookNames } from '../lib/api'
import {
  EMOTIONS, SETUPS, MISTAKE_TAGS, Label, MetricCell, QuickStat, fmtDur,
} from './bits'

const GRADE_COLORS = { A: '#00d4aa', B: '#38bdf8', C: '#f59e0b', D: '#de576f' }

const EMPTY_JOURNAL = {
  setup_name: '', notes: '', emotion_before: '', emotion_after: '',
  rating: null, mistakes: '', lessons: '', followed_plan: null, was_overtrading: false,
  grade: null, mistake_tags: [],
  stop_price: null, stop_triggered: false, targets: [],
}

export default function TradeDetailShell({ adapter, id }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const fileRef = useRef(null)

  const { data, isLoading } = adapter.useDetail(id)

  const { data: playbookNames = [] } = useQuery({
    queryKey: ['playbook-names'],
    queryFn: fetchPlaybookNames,
    staleTime: 60_000,
  })
  const setupOptions = [...new Set([...playbookNames, ...SETUPS])]

  const [form, setForm] = useState(EMPTY_JOURNAL)
  const [showScreenshot, setShowScreenshot] = useState(false)
  const [activeTab, setActiveTab] = useState('journal')

  // Initialise form from journal whenever the journal identity changes.
  const journal = data?.journal
  useEffect(() => {
    if (journal) {
      setForm({
        setup_name: journal.setup_name || '',
        notes: journal.notes || '',
        emotion_before: journal.emotion_before || '',
        emotion_after: journal.emotion_after || '',
        rating: journal.rating ?? null,
        mistakes: journal.mistakes || '',
        lessons: journal.lessons || '',
        followed_plan: journal.followed_plan ?? null,
        was_overtrading: journal.was_overtrading || false,
        grade: journal.grade || null,
        mistake_tags: journal.mistake_tags || [],
        stop_price: journal.stop_price ?? null,
        stop_triggered: journal.stop_triggered || false,
        targets: (journal.targets || []).map(t => ({ price: t.price, pct: t.pct, triggered: t.triggered || false })),
      })
    } else {
      setForm(EMPTY_JOURNAL)
    }
  }, [journal])

  const invalidate = () => adapter.invalidate(queryClient, id)

  const [saveError, setSaveError] = useState(null)
  const saveMutation = useMutation({
    mutationFn: (payload) => adapter.saveJournal(data, payload),
    onSuccess: () => { setSaveError(null); invalidate() },
    onError: (err) => setSaveError(typeof err?.message === 'string' && err.message.length < 120
      ? err.message : 'Save failed — check the entered values'),
  })

  const delMutation = useMutation({
    mutationFn: () => adapter.deleteTrade(data, id),
    onSuccess: () => navigate(adapter.backTo),
  })

  const uploadMutation = useMutation({
    // live form goes along so adapters can persist typed-but-unsaved fields
    // (prop's save-then-upload two-step) instead of clobbering them
    mutationFn: (file) => adapter.uploadScreenshot(data, file, form),
    onSuccess: () => { setShowScreenshot(true); invalidate() },
  })

  function updateField(key, value) {
    setForm(prev => ({ ...prev, [key]: value }))
  }

  function handleScreenshot(e) {
    const file = e.target.files?.[0]
    if (!file) return
    uploadMutation.mutate(file)
  }

  // ── Targets editor helpers ──────────────────────────────────────────
  const targets = form.targets || []
  const pctSum = targets.reduce((s, t) => s + (Number(t.pct) || 0), 0)
  const pctOver = pctSum > 100

  function updateTarget(idx, key, value) {
    setForm(prev => {
      const next = [...(prev.targets || [])]
      next[idx] = { ...next[idx], [key]: value }
      return { ...prev, targets: next }
    })
  }
  function addTarget() {
    setForm(prev => ({ ...prev, targets: [...(prev.targets || []), { price: null, pct: null, triggered: false }] }))
  }
  function removeTarget(idx) {
    setForm(prev => ({ ...prev, targets: (prev.targets || []).filter((_, i) => i !== idx) }))
  }

  function buildPayload() {
    const payload = {
      setup_name: form.setup_name || null,
      notes: form.notes || null,
      emotion_before: form.emotion_before || null,
      emotion_after: form.emotion_after || null,
      rating: form.rating ?? null,
      mistakes: form.mistakes || null,
      lessons: form.lessons || null,
      followed_plan: form.followed_plan ?? null,
      was_overtrading: form.was_overtrading,
      grade: form.grade || null,
      mistake_tags: form.mistake_tags || [],
    }
    if (adapter.riskEditable) {
      payload.stop_price = form.stop_price === '' ? null : form.stop_price
      payload.stop_triggered = form.stop_triggered
      payload.targets = (form.targets || [])
        .filter(t => t.price != null && t.price !== '')
        .map(t => ({ price: Number(t.price), pct: t.pct == null || t.pct === '' ? null : Number(t.pct), triggered: !!t.triggered }))
    }
    return payload
  }

  function handleSave() {
    if (adapter.riskEditable) {
      if (pctOver) return // button is disabled too; belt and braces
      // a target row with a price but no % (or vice versa) would 422 — block
      // with a visible message instead of silently failing
      const partial = (form.targets || []).some(t => {
        const hasPrice = t.price != null && t.price !== ''
        const hasPct = t.pct != null && t.pct !== ''
        return hasPrice !== hasPct
      })
      if (partial) {
        setSaveError('Each target needs both a price and a % of position')
        return
      }
    }
    setSaveError(null)
    saveMutation.mutate(buildPayload())
  }

  if (isLoading) return <div className="text-[#4e5166] p-8">Loading...</div>
  if (!data) return <div className="text-[#4e5166] p-8">Trade not found</div>

  const pnl = data.pnl || 0
  const isWin = pnl > 0
  const pnlColor = isWin ? 'text-[#00d4aa]' : pnl < 0 ? 'text-[#de576f]' : 'text-[#8d91a6]'
  const pnlBg = isWin ? 'bg-[#00d4aa]/5 border-[#00d4aa]/10' : pnl < 0 ? 'bg-[#de576f]/5 border-[#de576f]/10' : 'bg-[#2a2c30] border-[#2a2c30]'

  const estimated = data.confidence === 'ESTIMATED'
  const metricCells = adapter.metricCells(data)
  const quickStats = adapter.quickStats(data)
  const chartProps = adapter.chartProps(data)
  const executions = data.executions || []

  const tabs = [
    { key: 'journal', label: 'Journal' },
    { key: 'execution', label: 'Execution' },
    ...(adapter.riskEditable ? [{ key: 'risk', label: 'Risk' }] : []),
    ...(adapter.extraTabs || []).map(t => ({ key: t.key, label: t.label })),
  ]
  const isExtraTab = (adapter.extraTabs || []).some(t => t.key === activeTab)
  const activeExtra = (adapter.extraTabs || []).find(t => t.key === activeTab)

  const metricGridCols = metricCells.length <= 4 ? 'grid-cols-4' : 'grid-cols-4 md:grid-cols-8'

  return (
    <div className="space-y-4">
      {/* ── Header ──────────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(adapter.backTo)} className="p-2 hover:bg-[#2a2c30] rounded-lg transition-colors">
          <ArrowLeft className="w-5 h-5 text-[#4e5166]" />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2.5">
            <h1 className="text-[20px] font-semibold text-white">{data.symbol}</h1>
            <span className={`badge text-[11px] ${
              data.direction === 'LONG' ? 'bg-[#00d4aa]/10 text-[#00d4aa]' : 'bg-[#de576f]/10 text-[#de576f]'
            }`}>{data.direction}</span>
            {journal?.setup_name && (
              <span className="badge bg-[rgb(var(--accent-rgb)/0.1)] text-[var(--accent)] text-[10px]">{journal.setup_name}</span>
            )}
            {journal?.grade && (() => {
              const gc = GRADE_COLORS[journal.grade] || '#8d91a6'
              return <span className="badge text-[11px] font-bold" style={{ background: `${gc}20`, color: gc }}>Grade {journal.grade}</span>
            })()}
            {estimated && (
              <span className="badge text-[10px] bg-[#f59e0b]/15 text-[#f59e0b] border border-[#f59e0b]/30">entry unverified</span>
            )}
          </div>
          <p className="text-[12px] text-[#4e5166] mt-0.5">
            {data.entryTime && new Date(data.entryTime).toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
            {data.exitTime && ` → ${new Date(data.exitTime).toLocaleString('en-GB', { hour: '2-digit', minute: '2-digit' })}`}
            {data.durationSeconds && ` · ${fmtDur(data.durationSeconds)}`}
            {adapter.headerMeta && adapter.headerMeta(data)}
          </p>
        </div>
        <div className={`px-4 py-2 rounded-xl border ${pnlBg}`}>
          <p className={`text-[22px] font-mono font-semibold ${pnlColor}`}>
            {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
          </p>
          {Number.isFinite(data.actualR) && (
            <p className={`text-[11px] font-mono text-center ${pnlColor} opacity-70`}>
              {data.actualR >= 0 ? '+' : ''}{data.actualR.toFixed(2)}R
            </p>
          )}
          {Number.isFinite(data.plannedRR) && Number.isFinite(data.actualR) && (
            <p className="text-[10px] font-mono text-center text-[#4e5166]">plan {data.plannedRR.toFixed(1)}:1</p>
          )}
        </div>
      </div>

      {/* ── Chart ───────────────────────────────────────────── */}
      <div className="card overflow-hidden">
        <div className="h-[420px] bg-[#161718] relative">
          {showScreenshot && data.screenshotUrl ? (
            <img src={data.screenshotUrl} alt="Trade chart" className="w-full h-full object-contain" />
          ) : (
            <TradeChart {...chartProps} />
          )}

          {/* Top-right controls — chart provides its own; these are screenshot/upload */}
          <div className="absolute top-2 right-2 flex items-center gap-1 z-30">
            {data.screenshotUrl && (
              <button
                onClick={() => setShowScreenshot(v => !v)}
                title={showScreenshot ? 'Show chart' : 'Show screenshot'}
                className={`p-1.5 border border-[#2a2c30] rounded-lg transition-colors backdrop-blur-sm ${
                  showScreenshot
                    ? 'bg-[#2a2c30] text-white'
                    : 'bg-[#1e2024]/90 text-[#4e5166] hover:bg-[#2a2c30] hover:text-[#8d91a6]'
                }`}
              >
                {showScreenshot ? <BarChart3 className="w-3.5 h-3.5" /> : <Image className="w-3.5 h-3.5" />}
              </button>
            )}
            <button
              onClick={() => fileRef.current?.click()}
              disabled={uploadMutation.isPending}
              title="Upload screenshot"
              className="p-1.5 bg-[#1e2024]/90 border border-[#2a2c30] hover:bg-[#2a2c30] rounded-lg transition-colors backdrop-blur-sm"
            >
              <Upload className={`w-3.5 h-3.5 ${uploadMutation.isPending ? 'text-[var(--accent)] animate-pulse' : 'text-[#4e5166]'}`} />
            </button>
          </div>

          <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleScreenshot} />
        </div>

        {/* Metrics bar */}
        <div className={`grid ${metricGridCols} divide-x divide-[#2a2c30] border-t border-[#2a2c30]`}>
          {metricCells.map((m) => (
            <MetricCell key={m.label} label={m.label} value={m.value} color={m.color} />
          ))}
        </div>
      </div>

      {/* ── Executions ──────────────────────────────────────── */}
      {adapter.showExecutionsTable !== false && executions.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-[#2a2c30]">
            <h3 className="text-[11px] font-semibold text-[#4e5166] uppercase tracking-wider">
              Executions · {executions.length} fills
            </h3>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#2a2c30]">
                {['Time', 'Side', 'Price', 'Qty', 'Fee', 'Amount'].map(h => (
                  <th key={h} className="px-4 py-2 text-left text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2a2c30]/50">
              {executions.map((ex, i) => {
                const isBuy = ex.side === 'BUY'
                const fundColor = (ex.funding_amount ?? 0) >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]'
                return (
                  <tr key={ex.executed_at ? `${ex.executed_at}-${i}` : i} className={ex.is_funding ? 'opacity-60' : ''}>
                    <td className="px-4 py-2.5 font-mono text-[11px] text-[#8d91a6]">
                      {ex.executed_at
                        ? new Date(ex.time * 1000).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
                        : '—'}
                    </td>
                    <td className="px-4 py-2.5">
                      {ex.is_funding ? (
                        <span className="badge text-[10px] bg-[#f59e0b]/10 text-[#f59e0b]">Funding</span>
                      ) : (
                        <span className={`badge text-[10px] ${isBuy ? 'bg-[#00d4aa]/10 text-[#00d4aa]' : 'bg-[#de576f]/10 text-[#de576f]'}`}>
                          {isBuy ? '▲ Buy' : '▼ Sell'}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-[11px] text-[#8d91a6]">
                      {ex.is_funding ? '—' : Number(ex.price).toLocaleString(undefined, { maximumFractionDigits: 6 })}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-[11px] text-[#8d91a6]">
                      {ex.is_funding ? '—' : Number(ex.quantity).toLocaleString(undefined, { maximumFractionDigits: 4 })}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-[11px] text-[#8d91a6]">
                      {ex.fee == null ? '—' : `$${Number(ex.fee).toFixed(2)}`}
                    </td>
                    <td className={`px-4 py-2.5 font-mono text-[11px] ${ex.is_funding ? fundColor : 'text-[#8d91a6]'}`}>
                      {ex.is_funding
                        ? `${(ex.funding_amount ?? 0) >= 0 ? '+' : ''}$${Number(ex.funding_amount ?? 0).toFixed(2)}`
                        : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Adapter-supplied extra sections (e.g. prop legs table) ─ */}
      {(adapter.extraSections || []).map((section) => (
        <div key={section.key}>{section.render(data)}</div>
      ))}

      {/* ── Two-column layout ───────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left: tabs (2/3 width) */}
        <div className="lg:col-span-2 space-y-4">
          {/* Tab bar */}
          <div className="flex gap-0.5 bg-[#1e2024] border border-[#2a2c30] rounded-lg p-0.5 w-fit">
            {tabs.map(t => (
              <button key={t.key} onClick={() => setActiveTab(t.key)}
                className={`px-4 py-1.5 rounded-md text-[12px] font-medium transition-all ${
                  activeTab === t.key ? 'bg-[#2a2c30] text-white' : 'text-[#4e5166] hover:text-[#8d91a6]'
                }`}>{t.label}</button>
            ))}
          </div>

          {activeTab === 'journal' && (
            <div className="card p-5 space-y-4">
              <div>
                <Label>Setup / Playbook</Label>
                <div className="flex gap-2">
                  <input type="text" value={form.setup_name}
                    onChange={(e) => updateField('setup_name', e.target.value)}
                    placeholder="Type or select..."
                    className="input flex-1" list="setup-suggestions" />
                  <datalist id="setup-suggestions">
                    {setupOptions.map(s => <option key={s} value={s} />)}
                  </datalist>
                </div>
              </div>

              <div>
                <Label>Trade notes</Label>
                <textarea value={form.notes}
                  onChange={(e) => updateField('notes', e.target.value)}
                  rows={4} placeholder="Why did you take this trade? What was your thesis?"
                  className="input w-full resize-y" />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label>Emotion before</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {EMOTIONS.map(e => (
                      <button key={e} onClick={() => updateField('emotion_before', e)}
                        className={`px-2 py-1 rounded-md text-[11px] font-medium transition-all ${
                          form.emotion_before === e
                            ? 'bg-[var(--accent)] text-white'
                            : 'bg-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6] hover:bg-[#2a2d3a]'
                        }`}>{e}</button>
                    ))}
                  </div>
                </div>
                <div>
                  <Label>Emotion after</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {EMOTIONS.map(e => (
                      <button key={e} onClick={() => updateField('emotion_after', e)}
                        className={`px-2 py-1 rounded-md text-[11px] font-medium transition-all ${
                          form.emotion_after === e
                            ? 'bg-[var(--accent)] text-white'
                            : 'bg-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6] hover:bg-[#2a2d3a]'
                        }`}>{e}</button>
                    ))}
                  </div>
                </div>
              </div>

              <div>
                <Label>Mistake tags</Label>
                <div className="flex flex-wrap gap-1.5">
                  {MISTAKE_TAGS.map(tag => {
                    const active = (form.mistake_tags || []).includes(tag)
                    return (
                      <button key={tag} onClick={() => {
                        const curr = form.mistake_tags || []
                        updateField('mistake_tags', active ? curr.filter(t => t !== tag) : [...curr, tag])
                      }}
                        className={`px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all border ${
                          active
                            ? 'bg-[#de576f]/10 border-[#de576f]/30 text-[#de576f]'
                            : 'bg-[#1e2024] border-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6] hover:border-[#3a3c42]'
                        }`}>{tag}</button>
                    )
                  })}
                </div>
              </div>

              <div>
                <Label>Lessons learned</Label>
                <textarea value={form.lessons}
                  onChange={(e) => updateField('lessons', e.target.value)}
                  rows={2} placeholder="Key takeaways..."
                  className="input w-full resize-y" />
              </div>
            </div>
          )}

          {activeTab === 'execution' && (
            <div className="card p-5 space-y-4">
              <div>
                <Label>Trade Grade</Label>
                <p className="text-[10px] text-[#4e5166] mb-2">Rate execution quality independent of outcome</p>
                <div className="flex gap-2">
                  {[
                    { g: 'A', label: 'Perfect', color: '#00d4aa', desc: 'Followed plan exactly' },
                    { g: 'B', label: 'Good',    color: '#38bdf8', desc: 'Minor deviations' },
                    { g: 'C', label: 'Average', color: '#f59e0b', desc: 'Notable mistakes' },
                    { g: 'D', label: 'Poor',    color: '#de576f', desc: 'Broke the rules' },
                  ].map(({ g, label, color, desc }) => (
                    <button key={g} onClick={() => updateField('grade', form.grade === g ? null : g)}
                      title={desc}
                      className={`flex-1 py-2.5 rounded-xl font-bold text-[15px] transition-all border ${
                        form.grade === g
                          ? 'scale-105 shadow-lg'
                          : 'bg-[#2a2c30] border-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6]'
                      }`}
                      style={form.grade === g ? { background: `${color}20`, borderColor: `${color}40`, color } : {}}
                    >
                      {g}
                      <span className="block text-[8px] font-normal mt-0.5 opacity-70">{label}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <Label>Execution rating</Label>
                <div className="flex gap-2">
                  {[1, 2, 3, 4, 5].map(n => (
                    <button key={n} onClick={() => updateField('rating', n)}
                      className={`w-12 h-12 rounded-xl font-semibold text-sm transition-all ${
                        form.rating === n
                          ? 'bg-[var(--accent)] text-white scale-110 shadow-lg shadow-[rgb(var(--accent-rgb)/0.2)]'
                          : 'bg-[#2a2c30] text-[#4e5166] hover:bg-[#2a2d3a] hover:text-[#8d91a6]'
                      }`}>{n}</button>
                  ))}
                  <div className="flex items-center ml-2">
                    {form.rating && (
                      <span className="text-[12px] text-[#4e5166]">
                        {['', 'Poor', 'Below avg', 'Average', 'Good', 'Perfect'][form.rating]}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>Followed plan?</Label>
                  <div className="flex gap-2">
                    <button onClick={() => updateField('followed_plan', true)}
                      className={`flex-1 py-2.5 rounded-lg text-[12px] font-medium transition-all ${
                        form.followed_plan === true
                          ? 'bg-[#00d4aa]/10 text-[#00d4aa] border border-[#00d4aa]/20'
                          : 'bg-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6]'
                      }`}>Yes</button>
                    <button onClick={() => updateField('followed_plan', false)}
                      className={`flex-1 py-2.5 rounded-lg text-[12px] font-medium transition-all ${
                        form.followed_plan === false
                          ? 'bg-[#de576f]/10 text-[#de576f] border border-[#de576f]/20'
                          : 'bg-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6]'
                      }`}>No</button>
                  </div>
                </div>
                <div>
                  <Label>Overtrading?</Label>
                  <div className="flex gap-2">
                    <button onClick={() => updateField('was_overtrading', true)}
                      className={`flex-1 py-2.5 rounded-lg text-[12px] font-medium transition-all ${
                        form.was_overtrading === true
                          ? 'bg-[#de576f]/10 text-[#de576f] border border-[#de576f]/20'
                          : 'bg-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6]'
                      }`}>Yes</button>
                    <button onClick={() => updateField('was_overtrading', false)}
                      className={`flex-1 py-2.5 rounded-lg text-[12px] font-medium transition-all ${
                        form.was_overtrading === false
                          ? 'bg-[#00d4aa]/10 text-[#00d4aa] border border-[#00d4aa]/20'
                          : 'bg-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6]'
                      }`}>No</button>
                  </div>
                </div>
              </div>

              {form.followed_plan === false && (
                <div className="bg-[#de576f]/5 border border-[#de576f]/10 rounded-lg p-3 flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 text-[#de576f] shrink-0 mt-0.5" />
                  <p className="text-[12px] text-[#de576f]">
                    You didn't follow your plan. Make sure to note what went wrong in the Mistakes field.
                  </p>
                </div>
              )}
            </div>
          )}

          {activeTab === 'risk' && adapter.riskEditable && (
            <div className="card p-5 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>Stop-loss price</Label>
                  <input type="number" step="any" value={form.stop_price ?? ''}
                    onChange={(e) => updateField('stop_price', e.target.value === '' ? null : e.target.value)}
                    placeholder="—" className="input w-full" />
                </div>
                <div>
                  <Label>Stop was hit</Label>
                  <div className="flex gap-2">
                    <button onClick={() => updateField('stop_triggered', true)}
                      className={`flex-1 py-2.5 rounded-lg text-[12px] font-medium transition-all ${
                        form.stop_triggered === true
                          ? 'bg-[#de576f]/10 text-[#de576f] border border-[#de576f]/20'
                          : 'bg-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6]'
                      }`}>Yes</button>
                    <button onClick={() => updateField('stop_triggered', false)}
                      className={`flex-1 py-2.5 rounded-lg text-[12px] font-medium transition-all ${
                        form.stop_triggered === false
                          ? 'bg-[#00d4aa]/10 text-[#00d4aa] border border-[#00d4aa]/20'
                          : 'bg-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6]'
                      }`}>No</button>
                  </div>
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <Label>Targets</Label>
                  <span className={`text-[10px] font-mono ${pctOver ? 'text-[#de576f]' : 'text-[#4e5166]'}`}>Σ {pctSum}%</span>
                </div>
                <div className="space-y-2">
                  {targets.map((t, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      <input type="number" step="any" value={t.price ?? ''}
                        onChange={(e) => updateTarget(idx, 'price', e.target.value === '' ? null : e.target.value)}
                        placeholder="Price" className="input flex-1" />
                      <input type="number" step="any" value={t.pct ?? ''}
                        onChange={(e) => updateTarget(idx, 'pct', e.target.value === '' ? null : e.target.value)}
                        placeholder="%" className="input w-20" />
                      <label className="flex items-center gap-1 text-[11px] text-[#4e5166] whitespace-nowrap">
                        <input type="checkbox" checked={!!t.triggered}
                          onChange={(e) => updateTarget(idx, 'triggered', e.target.checked)}
                          className="accent-[#00d4aa] w-3.5 h-3.5" />
                        hit
                      </label>
                      <button onClick={() => removeTarget(idx)}
                        className="p-1.5 text-[#4e5166] hover:text-[#de576f] transition-colors">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
                <button onClick={addTarget} disabled={pctSum >= 100}
                  className={`mt-2 flex items-center gap-1.5 text-[12px] transition-colors ${
                    pctSum >= 100 ? 'text-[#2a2c30] cursor-not-allowed' : 'text-[var(--accent)] hover:text-[#7dd3fc]'
                  }`}>
                  <Plus className="w-3.5 h-3.5" /> Add target
                </button>
                {pctOver && (
                  <p className="text-[11px] text-[#de576f] mt-1.5">Target percentages sum to {pctSum}% — must be ≤ 100% to save.</p>
                )}
              </div>

              <div className="pt-3 border-t border-[#2a2c30] text-[12px] text-[#8d91a6] font-mono">
                Planned R:R — {Number.isFinite(data.plannedRR) ? `${data.plannedRR.toFixed(1)}:1` : '—'}
                {' · '}
                Actual R — {Number.isFinite(data.actualR) ? `${data.actualR >= 0 ? '+' : ''}${data.actualR.toFixed(2)}` : '—'}
                {data.riskSource && ` (from ${data.riskSource})`}
              </div>
            </div>
          )}

          {isExtraTab && activeExtra && (
            <div>{activeExtra.render(data)}</div>
          )}

          {/* Save bar — not on extra tabs */}
          {!isExtraTab && (
            <div className="flex items-center justify-between">
              {adapter.deleteTrade ? (
                <button onClick={() => { if (confirm('Delete this trade?')) delMutation.mutate() }}
                  className="flex items-center gap-2 text-[12px] text-[#4e5166] hover:text-[#de576f] transition-colors">
                  <Trash2 className="w-3.5 h-3.5" /> Delete trade
                </button>
              ) : <span />}
              <div className="flex items-center gap-3">
                {saveError && (
                  <span className="text-[11px] text-[#de576f]">{saveError}</span>
                )}
                {saveMutation.isSuccess && !saveError && (
                  <span className="text-[11px] text-[#00d4aa]">Saved</span>
                )}
                <button onClick={handleSave} disabled={saveMutation.isPending || (adapter.riskEditable && pctOver)}
                  className="btn-primary flex items-center gap-2 text-[13px]">
                  <Save className="w-4 h-4" />
                  {saveMutation.isPending ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Right sidebar (1/3 width) */}
        <div className="space-y-4">
          <div className="card p-4 space-y-4">
            <adapter.TagsPanel data={data} />
            <div className="border-t border-[#2a2c30] pt-4 space-y-3">
              <h3 className="text-[11px] font-semibold text-[#4e5166] uppercase tracking-wider">
                {adapter.quickStatsTitle ? adapter.quickStatsTitle(data) : 'Quick stats'}
              </h3>
              {quickStats.map((s) => (
                <QuickStat key={s.label} label={s.label} value={s.value} color={s.color} />
              ))}
            </div>
          </div>

          {adapter.RiskCard ? (
            <adapter.RiskCard data={data} />
          ) : (journal?.stop_price != null || (journal?.targets && journal.targets.length > 0)) && (
            <div className="card p-4 space-y-3">
              <h3 className="text-[11px] font-semibold text-[#4e5166] uppercase tracking-wider">Risk</h3>
              {journal?.stop_price != null && <QuickStat label="Stop Loss" value={Number(journal.stop_price).toLocaleString(undefined, { maximumFractionDigits: 6 })} />}
              {journal?.targets?.length > 0 && <QuickStat label="Targets" value={`${journal.targets.length}`} />}
              {data.riskSource && <QuickStat label="Risk source" value={data.riskSource} />}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
