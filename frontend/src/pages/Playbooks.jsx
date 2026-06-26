import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Pencil, Trash2, Plus, TrendingUp } from 'lucide-react'
import {
  fetchPlaybooks, createPlaybook, updatePlaybook, deletePlaybook,
} from '../lib/api'

const signedUsd = (n) => {
  if (n == null) return '—'
  return `${n >= 0 ? '+' : '-'}$${Math.abs(Number(n)).toFixed(2)}`
}
const pnlColor = (n) => (n == null || n === 0 ? 'text-[#8d91a6]' : n > 0 ? 'text-[#00d4aa]' : 'text-[#de576f]')

const RULE_FIELDS = [
  {
    key: 'context_requirements',
    label: 'Context requirements',
    placeholder: 'Regime / session / market conditions that must be true before considering a trade',
  },
  {
    key: 'entry_triggers',
    label: 'Entry triggers',
    placeholder: 'The exact price action or indicator signal that pulls the trigger',
  },
  {
    key: 'invalidation',
    label: 'Invalidation',
    placeholder: 'What would prove the idea wrong — price level, structure break, time',
  },
  {
    key: 'management',
    label: 'Management',
    placeholder: 'Scaling plan, stop adjustments, partial targets, max hold time',
  },
]

const EMPTY = { name: '', context_requirements: '', entry_triggers: '', invalidation: '', management: '', notes: '' }

/* ── Small label used throughout ──────────────────────────────────────────── */
function Label({ children }) {
  return (
    <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[#4e5166] mb-1">
      {children}
    </div>
  )
}

/* ── Horizontal stats pill row at the top of each card ───────────────────── */
function StatsPillRow({ stats }) {
  const s = stats || {}
  if (!s.trade_count) {
    return (
      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[#111213] border border-[#2a2c30]">
        <span className="text-[11px] text-[#4e5166]">no trades yet</span>
      </div>
    )
  }
  return (
    <div className="flex items-center gap-px flex-wrap">
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-l-md bg-[#111213] border border-[#2a2c30]">
        <Label>Trades</Label>
        <span className="text-[13px] font-semibold text-[#e2e4ef] -mt-0.5">{s.trade_count}</span>
      </div>
      <div className="flex items-center gap-2 px-3 py-1.5 bg-[#111213] border-t border-b border-[#2a2c30]">
        <Label>Win rate</Label>
        <span className="text-[13px] font-semibold text-[#e2e4ef] -mt-0.5">{Number(s.win_rate ?? 0).toFixed(1)}%</span>
      </div>
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-r-md bg-[#111213] border border-[#2a2c30]">
        <Label>P&amp;L</Label>
        <span className={`text-[13px] font-semibold -mt-0.5 ${pnlColor(s.total_pnl)}`}>{signedUsd(s.total_pnl)}</span>
      </div>
    </div>
  )
}

/* ── Single rule block inside the card grid ──────────────────────────────── */
function RuleBlock({ label, text }) {
  return (
    <div className="min-h-[48px]">
      <Label>{label}</Label>
      {text
        ? <div className="text-[12px] text-[#c8ccd8] whitespace-pre-wrap leading-relaxed">{text}</div>
        : <div className="text-[12px] text-[#2e3038] italic">—</div>
      }
    </div>
  )
}

/* ── Create / edit modal ─────────────────────────────────────────────────── */
function PlaybookModal({ initial, onClose, onSaved }) {
  const [form, setForm] = useState(initial)
  const [error, setError] = useState(null)
  const isEdit = initial.id != null

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const mutation = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name.trim(),
        context_requirements: form.context_requirements || null,
        entry_triggers: form.entry_triggers || null,
        invalidation: form.invalidation || null,
        management: form.management || null,
        notes: form.notes || null,
      }
      return isEdit ? updatePlaybook(initial.id, body) : createPlaybook(body)
    },
    onSuccess: () => onSaved(),
    onError: (err) => setError(err?.message || 'Save failed'),
  })

  function save() {
    if (!form.name.trim()) { setError('Name is required'); return }
    setError(null)
    mutation.mutate()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 py-10 px-4"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="card w-full max-w-[680px] p-6 space-y-5">

        {/* Modal header */}
        <div className="flex items-center gap-2.5 pb-1 border-b border-[#2a2c30]">
          <BookOpen className="w-4 h-4 text-[var(--accent)]" />
          <h2 className="text-[15px] font-semibold text-white">
            {isEdit ? 'Edit playbook' : 'New playbook'}
          </h2>
        </div>

        {/* Name */}
        <div>
          <label className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] block mb-1.5">
            Name
          </label>
          <input
            className="input w-full text-[13px]"
            value={form.name}
            onChange={set('name')}
            placeholder="e.g. Breakout, Opening Range, Trend continuation…"
            autoFocus
          />
        </div>

        {/* Rule fields — 2-col on sm+, stacked on xs */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {RULE_FIELDS.map(({ key, label, placeholder }) => (
            <div key={key}>
              <label className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] block mb-1.5">
                {label}
              </label>
              <textarea
                className="input w-full text-[12px] resize-y leading-relaxed"
                rows={3}
                value={form[key]}
                onChange={set(key)}
                placeholder={placeholder}
              />
            </div>
          ))}
        </div>

        {/* Notes — full width */}
        <div>
          <label className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] block mb-1.5">
            Notes
          </label>
          <textarea
            className="input w-full text-[12px] resize-y leading-relaxed"
            rows={2}
            value={form.notes}
            onChange={set('notes')}
            placeholder="Extra context, edge cases, links to example charts…"
          />
        </div>

        {error && <div className="text-[12px] text-[#de576f] bg-[#de576f]/10 px-3 py-2 rounded-lg">{error}</div>}

        {/* Actions */}
        <div className="flex items-center justify-end gap-3 pt-1 border-t border-[#2a2c30]">
          <button
            onClick={onClose}
            className="text-[13px] text-[#8d91a6] hover:text-white transition-colors px-1"
          >
            Cancel
          </button>
          <button
            onClick={save}
            disabled={mutation.isPending}
            className="btn-blue px-5 text-[13px] disabled:opacity-50 active:scale-[0.98]"
          >
            {mutation.isPending ? 'Saving…' : 'Save playbook'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── Individual playbook card ─────────────────────────────────────────────── */
function PlaybookCard({ pb, onEdit, onDelete }) {
  const hasRules = pb.context_requirements || pb.entry_triggers || pb.invalidation || pb.management
  const hasNotes = !!pb.notes

  return (
    <div className="card p-5 flex flex-col gap-4">

      {/* Card header: name + actions */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h3 className="text-[16px] font-semibold text-white leading-tight truncate">{pb.name}</h3>
        </div>
        <div className="flex items-center gap-0.5 shrink-0 -mt-0.5">
          <button
            onClick={onEdit}
            className="p-1.5 rounded-lg text-[#4e5166] hover:text-[var(--accent)] hover:bg-[#242629] transition-colors"
            title="Edit playbook"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={onDelete}
            className="p-1.5 rounded-lg text-[#4e5166] hover:text-[#de576f] hover:bg-[#242629] transition-colors"
            title="Delete playbook"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Stats pill row */}
      <StatsPillRow stats={pb.stats} />

      {/* Rules grid */}
      <div className="pt-1 border-t border-[#2a2c30]">
        {hasRules ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4 mt-3">
            {RULE_FIELDS.map(({ key, label }) => (
              <RuleBlock key={key} label={label} text={pb[key]} />
            ))}
          </div>
        ) : (
          <div className="mt-3 text-[12px] text-[#4e5166] italic">No rules written yet — add them with the edit button above.</div>
        )}
      </div>

      {/* Notes — full width with divider */}
      {hasNotes && (
        <div className="pt-3 border-t border-[#2a2c30]">
          <Label>Notes</Label>
          <div className="text-[12px] text-[#8d91a6] whitespace-pre-wrap leading-relaxed">{pb.notes}</div>
        </div>
      )}
    </div>
  )
}

/* ── Page ─────────────────────────────────────────────────────────────────── */
export default function Playbooks() {
  const qc = useQueryClient()
  const [modal, setModal] = useState(null) // null | {form...}

  const { data: playbooks = [], isLoading } = useQuery({
    queryKey: ['playbooks'],
    queryFn: fetchPlaybooks,
  })

  const delMutation = useMutation({
    mutationFn: deletePlaybook,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['playbooks'] }),
  })

  function onSaved() {
    setModal(null)
    qc.invalidateQueries({ queryKey: ['playbooks'] })
    qc.invalidateQueries({ queryKey: ['playbook-names'] })
  }

  function onDelete(pb) {
    if (confirm(`Delete playbook "${pb.name}"? Journal entries keep their setup name.`)) {
      delMutation.mutate(pb.id)
    }
  }

  function openEdit(pb) {
    setModal({
      id: pb.id,
      name: pb.name,
      context_requirements: pb.context_requirements || '',
      entry_triggers: pb.entry_triggers || '',
      invalidation: pb.invalidation || '',
      management: pb.management || '',
      notes: pb.notes || '',
    })
  }

  return (
    <div className="space-y-6">

      {/* Page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center"
            style={{ background: 'rgb(var(--accent-rgb) / 0.12)', border: '1px solid rgb(var(--accent-rgb) / 0.2)' }}>
            <BookOpen className="w-4.5 h-4.5 text-[var(--accent)]" style={{ width: '18px', height: '18px' }} />
          </div>
          <div>
            <h1 className="text-[22px] font-semibold text-white leading-tight">Playbooks</h1>
            <p className="text-[12px] text-[#4e5166] mt-0.5">your edge on paper — rules before trades</p>
          </div>
        </div>
        <button
          onClick={() => setModal({ ...EMPTY })}
          className="btn-blue px-4 text-[13px] flex items-center gap-2 active:scale-[0.98]"
        >
          <Plus className="w-4 h-4" /> New playbook
        </button>
      </div>

      {/* Body */}
      {isLoading ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {[0, 1].map((i) => (
            <div key={i} className="card p-5 h-64 skeleton-shimmer" />
          ))}
        </div>
      ) : playbooks.length === 0 ? (
        /* Empty state */
        <div className="card p-12 flex flex-col items-center justify-center text-center gap-4">
          <div className="w-12 h-12 rounded-full flex items-center justify-center"
            style={{ background: 'rgb(var(--accent-rgb) / 0.08)', border: '1px solid rgb(var(--accent-rgb) / 0.15)' }}>
            <TrendingUp className="w-5 h-5 text-[var(--accent)]" style={{ opacity: 0.7 }} />
          </div>
          <div>
            <p className="text-[15px] font-semibold text-[#e2e4ef]">No playbooks yet</p>
            <p className="text-[13px] text-[#4e5166] mt-1.5 max-w-xs mx-auto">
              Define your setups — rules on paper beat rules in your head.
            </p>
          </div>
          <button
            onClick={() => setModal({ ...EMPTY })}
            className="btn-blue px-5 text-[13px] inline-flex items-center gap-2 active:scale-[0.98] mt-1"
          >
            <Plus className="w-4 h-4" /> Create your first playbook
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {playbooks.map((pb) => (
            <PlaybookCard
              key={pb.id}
              pb={pb}
              onEdit={() => openEdit(pb)}
              onDelete={() => onDelete(pb)}
            />
          ))}
        </div>
      )}

      {modal && (
        <PlaybookModal initial={modal} onClose={() => setModal(null)} onSaved={onSaved} />
      )}
    </div>
  )
}
