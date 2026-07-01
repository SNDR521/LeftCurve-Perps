import { useMemo, useState, useCallback, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, CircleDot } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { DashboardCtx } from '../dashboard/DashboardContext'
import DashboardGrid from '../dashboard/DashboardGrid'
import PERPS_WIDGET_REGISTRY, { PERPS_DEFAULT_LAYOUT, PERPS_DEFAULT_WIDGETS } from '../widgets/perpsRegistry'
import { getDateRange, getPeriodLabel, loadPeriod, savePeriod } from '../dashboard/period'
import PeriodSelector from '../dashboard/PeriodSelector'
import { fetchPerpsOverview, fetchPerpsPerformance, fetchPerpsDailyPnl, fetchPerpsDrawdown, fetchPerpsEquity, fetchPerpsCockpit } from '../lib/api'
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


const PERPS_FETCHERS = {
  fetchOverview: fetchPerpsOverview,
  fetchPerformance: fetchPerpsPerformance,
  fetchDailyPnl: fetchPerpsDailyPnl,
  fetchDrawdown: fetchPerpsDrawdown,
  fetchEquity: fetchPerpsEquity,
}

const PERPS_PERIOD_KEY = 'leftcurve_perps_period'
const PERPS_BREAKEVEN_KEY = 'perps_dashboard_exclude_breakeven'

const VIEWS = ['Dollars', 'Percentage', 'R-Multiple']

function pnlViewToDisplay(v) {
  if (v === 'r-multiple') return 'R-Multiple'
  if (v === 'percentage') return 'Percentage'
  return 'Dollars'
}

export default function PerpsDashboard() {
  const { prefs, prefsLoaded } = usePreferences()
  const [periodState, setPeriodState] = useState(() => loadPeriod(PERPS_PERIOD_KEY, prefs.default_period || 'all'))
  const { period, custom } = periodState
  const onPeriodChange = (next) => { setPeriodState(next); savePeriod(PERPS_PERIOD_KEY, next.period, next.custom) }
  const [view, setView] = useState(() => pnlViewToDisplay(prefs?.pnl_view))
  const [excludeBreakeven, setExcludeBreakeven] = useState(() => {
    try { return localStorage.getItem(PERPS_BREAKEVEN_KEY) === 'true' } catch { return false }
  })

  // Prefs load asynchronously. On a fresh browser (no saved period), apply the
  // user's preferred default_period and P&L view once prefs arrive. The once-guard
  // ensures a mid-session change is never clobbered.
  const appliedDefault = useRef(false)
  useEffect(() => {
    if (!prefsLoaded || appliedDefault.current) return
    appliedDefault.current = true
    if (prefs?.pnl_view) setView(pnlViewToDisplay(prefs.pnl_view))
    if (localStorage.getItem(PERPS_PERIOD_KEY)) return
    const dp = prefs.default_period
    if (dp) setPeriodState(prev => ({ ...prev, period: dp }))
  }, [prefsLoaded, prefs.default_period, prefs?.pnl_view])

  function toggleBreakeven() {
    const next = !excludeBreakeven
    setExcludeBreakeven(next)
    try { localStorage.setItem(PERPS_BREAKEVEN_KEY, String(next)) } catch { /* ignore */ }
  }

  const { perpsAccountId } = useAccount()
  const queryParams = useMemo(() => {
    const p = { ...getDateRange(period, custom) }
    if (perpsAccountId) p.account_id = perpsAccountId
    if (excludeBreakeven) { p.exclude_breakeven = true; p.breakeven_threshold = 5 }
    return p
  }, [period, custom, perpsAccountId, excludeBreakeven])

  // Percentage denominator: wallet balance at the period start (not equity —
  // no floating P&L). R denominator: avg dollar risk per trade. Both come from
  // the overview (deduped with the widgets' own overview query by key).
  const { data: overviewData } = useQuery({
    queryKey: ['overview', queryParams],
    queryFn: () => fetchPerpsOverview(queryParams),
  })
  const BALANCE = overviewData?.period_start_balance ?? null
  const oneR = overviewData?.avg_risk_amount ?? null

  const convertVal = useCallback((v) => {
    if (v == null) return null
    if (view === 'Percentage') return BALANCE ? (v / BALANCE) * 100 : null
    if (view === 'R-Multiple') return oneR ? v / oneR : null
    return v
  }, [view, BALANCE, oneR])

  const viewFmt = useCallback(() => {
    if (view === 'Percentage') return 'percent'
    if (view === 'R-Multiple') return 'r'
    return 'currency'
  }, [view])

  const chartSuffix = view === 'Percentage' ? '%' : view === 'R-Multiple' ? 'R' : '$'

  const dashCtx = useMemo(() => ({
    queryParams, view, BALANCE, oneR,
    convertVal, viewFmt, chartSuffix, period,
    fetchers: PERPS_FETCHERS,
  }), [queryParams, view, BALANCE, oneR, convertVal, viewFmt, chartSuffix, period])

  const headerLeft = (
    <>
      <div>
        <h1 className="text-xl font-semibold text-[#e2e4ef]">Perps Dashboard</h1>
        <p className="text-[11px] text-[#4e5166] mt-0.5">{getPeriodLabel(period, custom)}</p>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <PeriodSelector period={period} custom={custom} onChange={onPeriodChange} />
        {/* P&L view */}
        <div className="flex gap-0.5 bg-[#1e2024] border border-[#2a2c30] rounded-lg p-0.5">
          {VIEWS.map(v => (
            <button key={v} onClick={() => setView(v)}
              className={`px-2.5 py-1.5 rounded-md text-[11px] font-medium transition-all ${
                view === v ? 'bg-[var(--accent)] text-white' : 'text-[#4e5166] hover:text-[#8d91a6]'
              }`}>{v}</button>
          ))}
        </div>
        {/* Breakeven filter */}
        <button
          onClick={toggleBreakeven}
          title={excludeBreakeven ? 'Breakeven trades excluded' : 'Include breakeven trades'}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all border ${
            excludeBreakeven
              ? 'bg-amber-400/10 border-amber-400/30 text-amber-400'
              : 'bg-[#1e2024] border-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6]'
          }`}
        >
          <CircleDot className="w-3.5 h-3.5" />
          BE
        </button>
      </div>
    </>
  )

  return (
    <DashboardCtx.Provider value={dashCtx}>
      <div className="space-y-4">
        {prefs?.show_cockpit_header !== false && <CockpitStrip />}
        {prefs?.show_plan_header !== false && <TodayPlanCard workspace="perps" />}
        <DashboardGrid registry={PERPS_WIDGET_REGISTRY} defaultLayout={PERPS_DEFAULT_LAYOUT}
                       defaultWidgets={PERPS_DEFAULT_WIDGETS}
                       storageKey="leftcurve_perps_dashboard_layout" widgetsKey="leftcurve_perps_dashboard_widgets"
                       headerLeft={headerLeft} />
      </div>
    </DashboardCtx.Provider>
  )
}
