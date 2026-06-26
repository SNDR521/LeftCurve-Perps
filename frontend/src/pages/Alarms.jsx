import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { BellRing, Plus, Trash2, ToggleLeft, ToggleRight } from 'lucide-react'
import { fetchAlarms, updateAlarm, deleteAlarm } from '../lib/api'
import AlarmDialog from '../components/AlarmDialog'

const TABS = [
  { key: 'ACTIVE',    label: 'Active' },
  { key: 'TRIGGERED', label: 'Triggered' },
  { key: '',          label: 'All' },
]

const STATUS_DOT = {
  ACTIVE:    '#00d4aa',
  TRIGGERED: '#f59e0b',
  PAUSED:    '#4e5166',
  EXPIRED:   '#4e5166',
  DISABLED:  '#4e5166',
}

const COND_MAP = {
  CROSS:      'crosses',
  CROSS_UP:   'crosses up',
  CROSS_DOWN: 'crosses down',
  GTE:        '≥',
  LTE:        '≤',
  PCT_MOVE:   'moves %',
}

function condText(a) {
  const c = COND_MAP[a.condition] || a.condition
  return `${a.symbol} ${c} ${a.value ?? ''}`.trim()
}

function statusDot(status) {
  const color = STATUS_DOT[status] || '#4e5166'
  return (
    <span
      className="inline-block w-2 h-2 rounded-full shrink-0"
      style={{ backgroundColor: color }}
      title={status}
    />
  )
}

export default function Alarms() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('ACTIVE')
  const [dialogOpen, setDialogOpen] = useState(false)

  const { data: alarms = [], isLoading, isError } = useQuery({
    queryKey: ['alarms'],
    queryFn: () => fetchAlarms(),
    retry: false,
  })

  const toggleMutation = useMutation({
    mutationFn: ({ id, payload }) => updateAlarm(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alarms'] }),
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => deleteAlarm(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alarms'] }),
  })

  // Client-side tab filter
  const visible = tab
    ? alarms.filter((a) => a.status === tab)
    : alarms

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <BellRing className="w-5 h-5 text-[var(--accent)]" />
          <h1 className="text-[18px] font-semibold text-[#e2e4ef]">Alarms</h1>
        </div>
        <button
          onClick={() => setDialogOpen(true)}
          className="btn-blue flex items-center gap-1.5 text-[13px]"
        >
          <Plus className="w-4 h-4" />
          New alarm
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-[#1a1b1e] border border-[#2a2c30] rounded-lg p-0.5 w-fit">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-1.5 text-[12px] font-medium rounded-md transition-all ${
              tab === key
                ? 'bg-[var(--accent)] text-white'
                : 'text-[#4e5166] hover:text-[#8d91a6]'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* List */}
      {isLoading && (
        <div className="text-[13px] text-[#4e5166] py-8 text-center">Loading…</div>
      )}
      {isError && (
        <div className="text-[13px] text-[#de576f] py-4">Failed to load alarms.</div>
      )}
      {!isLoading && !isError && visible.length === 0 && (
        <div className="card py-12 text-center">
          <BellRing className="w-8 h-8 text-[#4e5166] mx-auto mb-3" />
          <p className="text-[13px] text-[#4e5166]">No alarms here yet.</p>
          <button
            onClick={() => setDialogOpen(true)}
            className="mt-4 text-[12px] text-[var(--accent)] hover:brightness-125 transition"
          >
            + New alarm
          </button>
        </div>
      )}

      {!isLoading && visible.length > 0 && (
        <div className="space-y-2">
          {visible.map((a) => (
            <AlarmCard
              key={a.id}
              alarm={a}
              onToggle={(payload) => toggleMutation.mutate({ id: a.id, payload })}
              onDelete={() => deleteMutation.mutate(a.id)}
            />
          ))}
        </div>
      )}

      {dialogOpen && <AlarmDialog onClose={() => setDialogOpen(false)} />}
    </div>
  )
}

function AlarmCard({ alarm: a, onToggle, onDelete }) {
  const once = a.trigger_mode === 'ONCE'

  return (
    <div className="card flex items-start gap-3">
      {/* Status dot */}
      <div className="pt-1 shrink-0">{statusDot(a.status)}</div>

      {/* Main content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[13px] font-medium text-[#e2e4ef]">{condText(a)}</span>

          {/* Once / Every chip */}
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#2a2c30] text-[#8d91a6] font-medium shrink-0">
            {once ? 'Once' : 'Every'}
          </span>

          {/* Delivery marker */}
          {a.deliver?.in_app && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[rgb(var(--accent-rgb)/0.1)] text-[var(--accent)] font-medium shrink-0">
              in-app
            </span>
          )}
          {a.deliver?.telegram && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[rgb(var(--accent-rgb)/0.1)] text-[var(--accent)] font-medium shrink-0">
              ✈ TG
            </span>
          )}
        </div>

        {/* Sub-line: market + message */}
        <div className="mt-0.5 text-[11px] text-[#4e5166] truncate">
          {a.market && <span className="mr-2">{a.market}</span>}
          {a.message && <span className="italic">{a.message}</span>}
          {a.fired_count > 0 && (
            <span className="ml-2 text-[#f59e0b]">fired {a.fired_count}×</span>
          )}
        </div>
      </div>

      {/* Toggle + delete */}
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={() => {
            const turnOn = !a.enabled || a.status !== 'ACTIVE'
            onToggle(turnOn ? { status: 'ACTIVE' } : { enabled: false })
          }}
          title={a.enabled && a.status === 'ACTIVE' ? 'Disable' : 'Enable'}
          className="text-[#4e5166] hover:text-[var(--accent)] transition-colors"
        >
          {a.enabled && a.status === 'ACTIVE'
            ? <ToggleRight className="w-5 h-5 text-[#00d4aa]" />
            : <ToggleLeft className="w-5 h-5" />
          }
        </button>
        <button
          onClick={onDelete}
          title="Delete alarm"
          className="text-[#4e5166] hover:text-[#de576f] transition-colors"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}
