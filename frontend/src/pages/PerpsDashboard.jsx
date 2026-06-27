import { useMemo, useState, useCallback, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, RefreshCw } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { DashboardCtx } from '../dashboard/DashboardContext'
import DashboardGrid from '../dashboard/DashboardGrid'
import PERPS_WIDGET_REGISTRY, { PERPS_DEFAULT_LAYOUT, PERPS_DEFAULT_WIDGETS } from '../widgets/perpsRegistry'
import { getDateRange, getPeriodLabel, loadPeriod, savePeriod } from '../dashboard/period'
import PeriodSelector from '../dashboard/PeriodSelector'
import { fetchPerpsOverview, fetchPerpsPerformance, fetchPerpsDailyPnl, fetchPerpsDrawdown, fetchPerpsEquity, fetchPerpsCockpit, fetchPerpsAccounts, syncPerpsAccount } from '../lib/api'
import { useAccount } from '../components/Layout'
import TodayPlanCard from '../components/TodayPlanCard'
import { usePreferences } from '../preferences/PreferencesContext'

const fmtMoney = (n) => (n == null ? '—' : Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
const signedUsd = (n) => (n == null ? '—' : `${n >= 0 ? '+' : '-'}$${Math.abs(Number(n)).toFixed(2)}`)

function CockpitStrip() {
  const { perpsAccountId } = useAccount()
  const { data } = useQuery({
    queryKey: ['perps-cockpit', perpsAccountId],
    queryFn: () => fetchPerpsCockpit(perpsAccountId ? { account_id: perpsAccountId } : {}),
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
    retry: false,
  })
  if (!data) return null
  const { account, positions = [] } = data
  const sessionPnl = (account.realized_today ?? 0) + (account.open_upnl ?? 0)
  return (
    <Link to="/cockpit"
          className="card px-4 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] hover:border-[#4e5166] transition-colors">
      <span className="text-[#8d91a6]">Equity <span className="font-mono text-[#e2e4ef]">${fmtMoney(account.equity)}</span></span>
      <span className="text-[#4e5166]">·</span>
      <span className="text-[#8d91a6]">Session <span className={`font-mono font-semibold ${sessionPnl > 0 ? 'text-[#00d4aa]' : sessionPnl < 0 ? 'text-[#de576f]' : 'text-[#8d91a6]'}`}>{signedUsd(sessionPnl)}</span></span>
      <span className="text-[#4e5166]">·</span>
      <span className="text-[#8d91a6]"><span className="font-mono text-[#e2e4ef]">{positions.length}</span> open</span>
      <span className="text-[#4e5166]">·</span>
      <span className="text-[#8d91a6]">risk <span className="font-mono text-[#e2e4ef]">${fmtMoney(account.open_risk_usd)}</span></span>
      <ChevronRight className="w-4 h-4 text-[#4e5166] ml-auto" />
    </Link>
  )
}

// Sync the selected perps account (or all, when "All Accounts" is active),
// poll until the server-side sync finishes, then refresh the dashboard.
function SyncButton() {
  const qc = useQueryClient()
  const { perpsAccountId } = useAccount()
  const { data: accounts = [] } = useQuery({ queryKey: ['perps-accounts'], queryFn: fetchPerpsAccounts })
  const [busy, setBusy] = useState(false)
  if (accounts.length === 0) return null
  const targets = perpsAccountId ? accounts.filter((a) => a.id === perpsAccountId) : accounts

  async function doSync() {
    if (busy || targets.length === 0) return
    setBusy(true)
    await Promise.all(targets.map((a) => syncPerpsAccount(a.id).catch(() => {})))
    const ids = new Set(targets.map((a) => a.id))
    let polls = 0
    const poll = async () => {
      polls += 1
      const fresh = await fetchPerpsAccounts().catch(() => null)
      if (fresh) qc.setQueryData(['perps-accounts'], fresh)
      const stillSyncing = fresh && fresh.some((a) => ids.has(a.id) && a.is_syncing)
      // Require ≥2 polls so a just-started sync registers; 120-poll (~5min) safety cap.
      if ((!stillSyncing && polls >= 2) || polls > 120) {
        setBusy(false)
        qc.invalidateQueries()
      } else {
        setTimeout(poll, 2500)
      }
    }
    setTimeout(poll, 2500)
  }

  return (
    <button onClick={doSync} disabled={busy}
      className="inline-flex items-center gap-1.5 text-[12px] text-[#8d91a6] hover:text-white border border-[#2a2c30] hover:border-[#4e5166] rounded-lg px-3 py-1.5 transition-colors disabled:opacity-60">
      <RefreshCw className={`w-3.5 h-3.5 ${busy ? 'animate-spin' : ''}`} />
      {busy ? 'Syncing…' : 'Sync'}
    </button>
  )
}

const PERPS_FETCHERS = {
  fetchOverview: fetchPerpsOverview,
  fetchPerformance: fetchPerpsPerformance,
  fetchDailyPnl: fetchPerpsDailyPnl,
  fetchDrawdown: fetchPerpsDrawdown,
  fetchEquity: fetchPerpsEquity,
}

const PERPS_PERIOD_KEY = 'leftcurve_perps_period'

export default function PerpsDashboard() {
  const { prefs, prefsLoaded } = usePreferences()
  const [periodState, setPeriodState] = useState(() => loadPeriod(PERPS_PERIOD_KEY, prefs.default_period || 'all'))
  const { period, custom } = periodState
  const onPeriodChange = (next) => { setPeriodState(next); savePeriod(PERPS_PERIOD_KEY, next.period, next.custom) }

  // Prefs load asynchronously. On a fresh browser (no saved period), apply the
  // user's preferred default_period once prefs arrive. The once-guard ensures a
  // mid-session period change is never clobbered.
  const appliedDefault = useRef(false)
  useEffect(() => {
    if (!prefsLoaded || appliedDefault.current) return
    appliedDefault.current = true
    if (localStorage.getItem(PERPS_PERIOD_KEY)) return
    const dp = prefs.default_period
    if (dp) setPeriodState(prev => ({ ...prev, period: dp }))
  }, [prefsLoaded, prefs.default_period])
  const { perpsAccountId } = useAccount()
  const queryParams = useMemo(
    () => ({ ...getDateRange(period, custom), ...(perpsAccountId && { account_id: perpsAccountId }) }),
    [period, custom, perpsAccountId],
  )
  const identity = useCallback((v) => v, [])
  const viewFmt = useCallback(() => 'currency', [])

  const dashCtx = useMemo(() => ({
    queryParams, view: 'Dollars', BALANCE: 0, oneR: null,
    convertVal: identity, viewFmt, chartSuffix: '$', period,
    fetchers: PERPS_FETCHERS,
  }), [queryParams, period, identity, viewFmt])

  const headerLeft = (
    <>
      <div>
        <h1 className="text-xl font-semibold text-[#e2e4ef]">Perps Dashboard</h1>
        <p className="text-[11px] text-[#4e5166] mt-0.5">{getPeriodLabel(period, custom)}</p>
      </div>
      <PeriodSelector period={period} custom={custom} onChange={onPeriodChange} />
    </>
  )

  return (
    <DashboardCtx.Provider value={dashCtx}>
      <div className="space-y-4">
        <div className="flex justify-end">
          <SyncButton />
        </div>
        <CockpitStrip />
        <TodayPlanCard workspace="perps" />
        <DashboardGrid registry={PERPS_WIDGET_REGISTRY} defaultLayout={PERPS_DEFAULT_LAYOUT}
                       defaultWidgets={PERPS_DEFAULT_WIDGETS}
                       storageKey="leftcurve_perps_dashboard_layout" widgetsKey="leftcurve_perps_dashboard_widgets"
                       headerLeft={headerLeft} />
      </div>
    </DashboardCtx.Provider>
  )
}
