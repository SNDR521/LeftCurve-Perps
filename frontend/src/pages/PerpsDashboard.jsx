import { useMemo, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { DashboardCtx } from '../dashboard/DashboardContext'
import DashboardGrid from '../dashboard/DashboardGrid'
import PERPS_WIDGET_REGISTRY, { PERPS_DEFAULT_LAYOUT, PERPS_DEFAULT_WIDGETS } from '../widgets/perpsRegistry'
import { getDateRange, getPeriodLabel, loadPeriod, savePeriod } from '../dashboard/period'
import PeriodSelector from '../dashboard/PeriodSelector'
import { fetchPerpsOverview, fetchPerpsPerformance, fetchPerpsDailyPnl, fetchPerpsDrawdown, fetchPerpsEquity, fetchPerpsCockpit } from '../lib/api'
import { useAccount } from '../components/Layout'
import TodayPlanCard from '../components/TodayPlanCard'

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

export default function PerpsDashboard() {
  const [periodState, setPeriodState] = useState(() => loadPeriod('leftcurve_perps_period', 'all'))
  const { period, custom } = periodState
  const onPeriodChange = (next) => { setPeriodState(next); savePeriod('leftcurve_perps_period', next.period, next.custom) }
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
