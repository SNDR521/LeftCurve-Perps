import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Pencil, Trash2, Plus } from 'lucide-react'
import {
  fetchPlaybooks, createPlaybook, updatePlaybook, deletePlaybook,
} from '../lib/api'

const signedUsd = (n) => {
  if (n == null) return '—'
  return `${n >= 0 ? '+' : '-'}$${Math.abs(Number(n)).toFixed(2)}`
}
const pnlColor = (n) => (n == null || n === 0 ? 'text-[#8d91a6]' : n > 0 ? 'text-[#00d4aa]' : 'text-[#de576f]')

const RULE_FIELDS = [
  { key: 'context_requirements', label: 'Context requirements' },
  { key: 'entry_triggers', label: 'Entry triggers' },
  { key: 'invalidation', label: 'Invalidation' },
  { key: 'management', label: 'Management' },
]

const EMPTY = { name: '', context_requirements: '', entry_triggers: '', invalidation: '', management: '', notes: '' }

function RuleBlock({ label, text }) {
  if (!text) return null
  return (
    <div>
      <div className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] mb-0.5">{label}</div>
      <div className="text-[12px] text-[#c8ccd8] whitespace-pre-wrap leading-relaxed">{text}</div>
    </div>
  )
}

function StatsBlock({ stats }) {
  const s = stats || {}
  if (!s.trade_count) {
    return <div className="text-[12px] text-[#4e5166]">no trades yet</div>
  }
  return (
    <div className="space-y-2">
      <div>
        <div className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">Trades</div>
        <div className="text-[15px] font-semibold text-[#e2e4ef]">{s.trade_count}</div>
      </div>
      <div>
        <div className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">Win rate</div>
        <div className="text-[15px] font-semibold text-[#e2e4ef]">{Number(s.win_rate ?? 0).toFixed(1)}%</div>
      </div>
      <div>
        <div className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">Total P&amp;L</div>
        <div className={`text-[15px] font-semibold ${pnlColor(s.total_pnl)}`}>{signedUsd(s.total_pnl)}</div>
      </div>
    </div>
  )
}

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
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 py-10 px-4"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="card w-full max-w-[640px] p-5 space-y-4">
        <h2 className="text-[15px] font-semibold text-white">{isEdit ? 'Edit playbook' : 'New playbook'}</h2>

        <div>
          <label className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] block mb-1">Name</label>
          <input className="input w-full text-[13px]" value={form.name} onChange={set('name')}
            placeholder="e.g. Breakout" autoFocus />
        </div>

        {RULE_FIELDS.map(({ key, label }) => (
          <div key={key}>
            <label className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] block mb-1">{label}</label>
            <textarea className="input w-full text-[12px] resize-y" rows={2}
              value={form[key]} onChange={set(key)} />
          </div>
        ))}

        <div>
          <label className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] block mb-1">Notes</label>
          <textarea className="input w-full text-[12px] resize-y" rows={2}
            value={form.notes} onChange={set('notes')} />
        </div>

        {error && <div className="text-[12px] text-[#de576f]">{error}</div>}

        <div className="flex items-center justify-end gap-3 pt-1">
          <button onClick={onClose}
            className="text-[13px] text-[#8d91a6] hover:text-white transition-colors">Cancel</button>
          <button onClick={save} disabled={mutation.isPending}
            className="btn-blue px-5 text-[13px] disabled:opacity-50 active:scale-[0.98]">
            {mutation.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}

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

  const header = (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        <BookOpen className="w-5 h-5 text-[#38bdf8]" />
        <div>
          <h1 className="text-[22px] font-semibold text-white">Playbooks</h1>
          <p className="text-[13px] text-[#4e5166] mt-0.5">your edge on paper</p>
        </div>
      </div>
      <button onClick={() => setModal({ ...EMPTY })}
        className="btn-blue px-4 text-[13px] flex items-center gap-2 active:scale-[0.98]">
        <Plus className="w-4 h-4" /> New playbook
      </button>
    </div>
  )

  return (
    <div className="space-y-5">
      {header}

      {isLoading ? (
        <div className="card p-16 flex items-center justify-center text-[#4e5166] text-sm">Loading…</div>
      ) : playbooks.length === 0 ? (
        <div className="card p-16 text-center">
          <p className="text-[14px] text-[#8d91a6]">Define your first setup — rules on paper beat rules in your head.</p>
          <button onClick={() => setModal({ ...EMPTY })}
            className="btn-blue px-4 text-[13px] mt-4 inline-flex items-center gap-2 active:scale-[0.98]">
            <Plus className="w-4 h-4" /> New playbook
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {playbooks.map((pb) => (
            <div key={pb.id} className="card p-4">
              <div className="flex items-start justify-between gap-2 mb-3">
                <h3 className="text-[15px] font-semibold text-white">{pb.name}</h3>
                <div className="flex items-center gap-1 shrink-0">
                  <button onClick={() => setModal({
                    id: pb.id, name: pb.name,
                    context_requirements: pb.context_requirements || '',
                    entry_triggers: pb.entry_triggers || '',
                    invalidation: pb.invalidation || '',
                    management: pb.management || '',
                    notes: pb.notes || '',
                  })}
                    className="p-1.5 rounded-lg text-[#4e5166] hover:text-[#38bdf8] hover:bg-[#242629] transition-colors">
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={() => onDelete(pb)}
                    className="p-1.5 rounded-lg text-[#4e5166] hover:text-[#de576f] hover:bg-[#242629] transition-colors">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div className="col-span-2 space-y-3">
                  {RULE_FIELDS.map(({ key, label }) => (
                    <RuleBlock key={key} label={label} text={pb[key]} />
                  ))}
                  {pb.notes && (
                    <div>
                      <div className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] mb-0.5">Notes</div>
                      <div className="text-[12px] text-[#8d91a6] whitespace-pre-wrap leading-relaxed">{pb.notes}</div>
                    </div>
                  )}
                  {!pb.context_requirements && !pb.entry_triggers && !pb.invalidation && !pb.management && !pb.notes && (
                    <div className="text-[12px] text-[#4e5166]">no rules written yet</div>
                  )}
                </div>
                <div className="col-span-1 border-l border-[#2a2c30] pl-4">
                  <StatsBlock stats={pb.stats} />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {modal && (
        <PlaybookModal initial={modal} onClose={() => setModal(null)} onSaved={onSaved} />
      )}
    </div>
  )
}
