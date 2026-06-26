import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell } from 'lucide-react'
import { fetchAlerts, checkAlerts, markAlertsSeen } from '../lib/api'
import { useAuth } from '../auth/AuthContext'

// Relative time, matching the News page idiom.
function relTime(value) {
  if (!value) return ''
  const ts = typeof value === 'number' ? value * 1000 : Date.parse(value)
  if (Number.isNaN(ts)) return ''
  const diff = (Date.now() - ts) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

// One-line human summary of an alert, by kind.
function alertText(a) {
  const p = a.payload || {}
  if (a.kind === 'LEVEL_CROSS') {
    const arrow = p.direction === 'down' ? '↓' : '↑'
    const lvl = p.level != null ? p.level : ''
    const label = p.label ? ` (${p.label})` : ''
    return `${a.symbol || p.symbol} crossed ${lvl}${label} ${arrow}`
  }
  if (a.kind === 'THEME_STATUS') {
    return `${p.theme}: ${p.old_status} → ${p.new_status}`
  }
  if (a.kind === 'ALARM') {
    return p.message ? `${p.message} — ${p.text || ''}`.trim() : (p.text || a.symbol)
  }
  return a.symbol || a.kind
}

// Muted sub-line per kind.
function alertSub(a) {
  const p = a.payload || {}
  if (a.kind === 'THEME_STATUS') {
    const syms = Array.isArray(p.matched_symbols) ? p.matched_symbols.join(', ') : ''
    return syms
  }
  if (a.kind === 'ALARM') {
    return `${p.source === 'eod' ? 'EOD' : 'live'} · ${relTime(a.triggered_at)}`
  }
  return p.source ? `${p.source} · ${relTime(a.triggered_at)}` : relTime(a.triggered_at)
}

export default function AlertBell() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [banner, setBanner] = useState(null) // {id, text}
  const wrapRef = useRef(null)
  const bannerTimer = useRef(null)

  // Cheap poll: crypto evaluated server-side; surfaces unseen count + new alerts.
  const { data: check } = useQuery({
    queryKey: ['alerts-check'],
    queryFn: checkAlerts,
    refetchInterval: 60000,
    refetchIntervalInBackground: false,
    retry: false,
    enabled: !!user,
  })

  // Recent list, only fetched while the dropdown is open.
  const { data: list } = useQuery({
    queryKey: ['alerts-list'],
    queryFn: () => fetchAlerts(20),
    enabled: open && !!user,
    retry: false,
  })

  // Transient banner when a poll surfaces brand-new alerts.
  useEffect(() => {
    const fresh = check?.new
    if (Array.isArray(fresh) && fresh.length > 0) {
      const a = fresh[0]
      setBanner({ id: a.id, text: alertText(a) })
      if (bannerTimer.current) clearTimeout(bannerTimer.current)
      bannerTimer.current = setTimeout(() => setBanner(null), 6000)
    }
  }, [check])

  useEffect(() => () => { if (bannerTimer.current) clearTimeout(bannerTimer.current) }, [])

  // Outside-click closes the dropdown.
  useEffect(() => {
    if (!open) return
    function onDoc(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  if (!user) return null

  const unseen = check?.unseen_count || 0
  const alerts = Array.isArray(list?.alerts) ? list.alerts : []

  async function onMarkAll() {
    try {
      await markAlertsSeen({ all: true })
      qc.invalidateQueries({ queryKey: ['alerts-check'] })
      qc.invalidateQueries({ queryKey: ['alerts-list'] })
    } catch { /* harmless — leave state as-is */ }
  }

  return (
    <>
      <div ref={wrapRef} className="relative">
        <button
          onClick={() => setOpen(o => !o)}
          className="relative p-2 rounded-lg text-[#8d91a6] hover:text-white hover:bg-[#242629] transition-colors"
          title="Alerts"
        >
          <Bell className="w-[18px] h-[18px]" />
          {unseen > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-[16px] px-1 rounded-full bg-[#de576f]
                             text-white text-[9px] font-semibold flex items-center justify-center leading-none">
              {unseen > 99 ? '99+' : unseen}
            </span>
          )}
        </button>

        {open && (
          <div className="absolute z-50 top-full right-0 mt-1.5 w-[min(320px,calc(100vw-1.5rem))] bg-[#1e2024] border border-[#2a2c30]
                          rounded-lg shadow-xl overflow-hidden"
               style={{ boxShadow: '0 8px 32px rgba(0,0,0,0.5)' }}>
            <div className="px-3 py-2 border-b border-[#2a2c30] flex items-center justify-between">
              <span className="text-[12px] font-semibold text-[#e2e4ef]">Alerts</span>
              {unseen > 0 && <span className="text-[10px] text-[#4e5166]">{unseen} new</span>}
            </div>
            <div className="max-h-[360px] overflow-y-auto">
              {alerts.length === 0 ? (
                <div className="px-3 py-6 text-center text-[12px] text-[#4e5166]">No alerts yet</div>
              ) : (
                alerts.map(a => (
                  <div
                    key={a.id}
                    className={`px-3 py-2 border-b border-[#242629] last:border-b-0 ${a.seen ? '' : 'bg-[rgb(var(--accent-rgb)/0.05)]'}`}
                  >
                    <div className="text-[12px] text-[#e2e4ef]">{alertText(a)}</div>
                    <div className="text-[10px] text-[#4e5166] mt-0.5 truncate">{alertSub(a)}</div>
                  </div>
                ))
              )}
            </div>
            <button
              onClick={onMarkAll}
              className="w-full px-3 py-2 text-[11px] text-[var(--accent)] hover:bg-[#242629] transition-colors border-t border-[#2a2c30]"
            >
              Mark all seen
            </button>
          </div>
        )}
      </div>

      {banner && (
        <div className="fixed top-3 left-1/2 -translate-x-1/2 z-[60] bg-[#1e2024] border border-[rgb(var(--accent-rgb)/0.4)]
                        rounded-lg shadow-xl px-4 py-2.5 flex items-center gap-2.5"
             style={{ boxShadow: '0 8px 32px rgba(0,0,0,0.5)' }}>
          <Bell className="w-4 h-4 text-[var(--accent)] shrink-0" />
          <span className="text-[12px] text-[#e2e4ef]">{banner.text}</span>
        </div>
      )}
    </>
  )
}
