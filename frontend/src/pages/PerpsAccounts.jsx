import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Wallet, Trash2, RefreshCw } from 'lucide-react'
import { fetchPerpsAccounts, createPerpsAccount, deletePerpsAccount, syncPerpsAccount } from '../lib/api'

const VENUES = ['BYBIT', 'HYPERLIQUID']

function SyncProgress({ p }) {
  if (!p || p.state !== 'running') return null
  const span = (p.to_ms - p.from_ms) || 1
  const pct = Math.min(100, Math.max(0, ((p.cursor_ms - p.from_ms) / span) * 100))
  const date = new Date(p.cursor_ms).toLocaleDateString()
  const ageS = Math.max(0, Math.round((Date.now() - new Date(p.updated_at).getTime()) / 1000))
  const stalled = ageS > 60
  return (
    <div className="w-[220px]">
      <div className="h-1.5 bg-[#2a2c30] rounded-full overflow-hidden">
        <div className="h-full bg-[var(--accent)] rounded-full transition-all" style={{ width: `${pct}%` }} />
      </div>
      <div className="flex justify-between mt-0.5 text-[10px] text-[#4e5166]">
        <span>importing {date} · {pct.toFixed(0)}%</span>
        <span>{p.fills} fills · {p.funding} fdg</span>
      </div>
      <div className="text-[10px] text-[#4e5166]">
        {stalled && <span className="text-amber-400">may be stalled · </span>}updated {ageS}s ago
      </div>
    </div>
  )
}

function SyncButton({ acc }) {
  const qc = useQueryClient()
  const sync = useMutation({
    mutationFn: () => syncPerpsAccount(acc.id),
    onSuccess: () => qc.invalidateQueries(),
  })
  // `inFlight` = a sync is actually running now (in-process truth). The persisted
  // sync_progress.state can be a stale "running" after a crash/restart, so it must
  // NOT disable the button — otherwise the account locks with no way to retry.
  const inFlight = sync.isPending || acc.syncing
  const running = acc.sync_progress?.state === 'running'

  return (
    <div className="flex flex-col items-end gap-0.5">
      <button
        className="btn-ghost flex items-center gap-1.5 text-[12px]"
        disabled={inFlight}
        onClick={() => sync.mutate()}
      >
        <RefreshCw className={`w-3.5 h-3.5 ${inFlight ? 'animate-spin' : ''}`} />
        {inFlight ? 'Syncing…' : (running ? 'Resume sync' : 'Sync')}
      </button>
      <SyncProgress p={acc.sync_progress} />
      {acc.last_synced_at && !inFlight && !running && (
        <span className="text-[11px] text-[#4e5166]">
          Synced {new Date(acc.last_synced_at).toLocaleString()}
        </span>
      )}
      {acc.last_sync_error && !inFlight && (
        <span className="text-[11px] text-[#de576f] max-w-[200px] truncate" title={acc.last_sync_error}>
          {acc.last_sync_error}
        </span>
      )}
    </div>
  )
}

export default function PerpsAccounts() {
  const qc = useQueryClient()
  const { data: accounts = [] } = useQuery({
    queryKey: ['perps-accounts'],
    queryFn: fetchPerpsAccounts,
    refetchInterval: (q) => {
      const list = q.state.data || []
      return list.some(a => a.syncing || a.sync_progress?.state === 'running') ? 3000 : false
    },
  })
  const [venue, setVenue] = useState('BYBIT')
  const [label, setLabel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [address, setAddress] = useState('')
  const [error, setError] = useState(null)

  const create = useMutation({
    mutationFn: () => {
      const data = { venue, label }
      if (venue === 'BYBIT' && apiKey) { data.api_key = apiKey; data.api_secret = apiSecret }
      if (venue === 'HYPERLIQUID' && address) { data.address = address.trim() }
      return createPerpsAccount(data)
    },
    onSuccess: () => {
      setLabel('')
      setApiKey('')
      setApiSecret('')
      setAddress('')
      setError(null)
      qc.invalidateQueries({ queryKey: ['perps-accounts'] })
    },
    onError: (e) => setError(e.message),
  })
  const remove = useMutation({
    mutationFn: (id) => deletePerpsAccount(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['perps-accounts'] }),
  })

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-[#e2e4ef]">Exchange Accounts</h1>

      <div className="card p-4">
        <div className="flex items-end gap-3 flex-wrap">
          <label className="text-[12px] text-[#8d91a6]">
            Venue
            <select value={venue} onChange={(e) => setVenue(e.target.value)} className="input mt-1 block">
              {VENUES.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          </label>
          <label className="text-[12px] text-[#8d91a6] flex-1 min-w-[180px]">
            Label
            <input value={label} onChange={(e) => setLabel(e.target.value)}
                   placeholder="e.g. Bybit main" className="input mt-1 block w-full" />
          </label>
          {venue === 'BYBIT' && (
            <>
              <label className="text-[12px] text-[#8d91a6] flex-1 min-w-[180px]">
                API Key
                <input value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                       placeholder="API key" className="input mt-1 block w-full" />
              </label>
              <label className="text-[12px] text-[#8d91a6] flex-1 min-w-[180px]">
                API Secret
                <input type="password" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)}
                       placeholder="API secret" className="input mt-1 block w-full" />
              </label>
            </>
          )}
          {venue === 'HYPERLIQUID' && (
            <label className="text-[12px] text-[#8d91a6] flex-1 min-w-[260px]">
              Wallet address
              <input value={address} onChange={(e) => setAddress(e.target.value)}
                     placeholder="0x…" className="input mt-1 block w-full" />
            </label>
          )}
          <button className="btn-blue"
                  disabled={!label || create.isPending || (venue === 'HYPERLIQUID' && !address)}
                  onClick={() => create.mutate()}>Add account</button>
        </div>
        {venue === 'BYBIT' && (
          <p className="text-[11px] text-[#4e5166] mt-2">Use a read-only API key (no trade/withdraw permissions).</p>
        )}
        {venue === 'HYPERLIQUID' && (
          <p className="text-[11px] text-[#4e5166] mt-2">Read-only: paste your Hyperliquid wallet address (no keys needed).</p>
        )}
        {error && <p className="text-[12px] text-[#de576f] mt-2">{error}</p>}
      </div>

      <div className="card divide-y divide-[#2a2c30]">
        {accounts.length === 0 && <p className="p-4 text-[13px] text-[#4e5166]">No exchange accounts yet.</p>}
        {accounts.map(a => (
          <div key={a.id} className="flex items-center gap-3 px-4 py-3">
            <Wallet className="w-4 h-4 text-[var(--accent)]" />
            <span className="text-[13px] text-[#e2e4ef]">{a.label}</span>
            <span className="text-[11px] text-[#4e5166]">{a.venue}</span>
            <div className="ml-auto flex items-center gap-3">
              {a.has_credentials
                ? <SyncButton acc={a} />
                : <span className="text-[11px] text-[#4e5166]">No API key — add one to enable sync.</span>
              }
              <button className="text-[#4e5166] hover:text-[#de576f]" onClick={() => remove.mutate(a.id)} title="Delete">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
