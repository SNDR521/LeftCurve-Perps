import { useAccount } from '../components/Layout'
import {
  fetchPerpsOverview, fetchPerpsPerformance, fetchPerpsCoverage,
  fetchPerpsHeatmap, fetchPerpsRDistribution,
  fetchPerpsCrossAnalysis, fetchPerpsDimensions, fetchPerpsInsights,
} from '../lib/api'
import { useQuery } from '@tanstack/react-query'
import { Layers } from 'lucide-react'
import CrossAnalysisTab from './tabs/CrossAnalysisTab'
import OverviewTab from './tabs/OverviewTab'
import GroupTab from './tabs/GroupTab'
import SessionsTab from './tabs/SessionsTab'
import HeatmapTab from './tabs/HeatmapTab'
import HoldTimeTab from './tabs/HoldTimeTab'
import GradesTab from './tabs/GradesTab'
import MistakesTab from './tabs/MistakesTab'
import RDistTab from './tabs/RDistTab'
import FundingTab from './tabs/FundingTab'
import FeesTab from './tabs/FeesTab'
import LeverageTab from './tabs/LeverageTab'
import { normGroupPerf, normSession, normHoldtime, normGrades, normMistakes } from './normalize'

function Coverage({ params }) {
  const { data: c } = useQuery({ queryKey: ['perps-coverage', params], queryFn: () => fetchPerpsCoverage(params) })
  if (!c || c.exact >= c.total) return null
  return (
    <p className="text-[11px] text-[#f59e0b] mt-1">
      Session and hold-time stats cover {c.exact} of {c.total} trades — the rest have unverified entry times.
    </p>
  )
}

export const perpsAdapter = {
  title: 'Perps Analytics',
  subtitle: 'Performance breakdowns for your perps trading',
  storageKey: 'leftcurve_perps_analytics_period',
  Coverage,
  useAccountParams() {
    const { perpsAccountId } = useAccount()
    return perpsAccountId ? { account_id: perpsAccountId } : {}
  },
  tabs: [
    { key: 'overview', label: 'Overview', Component: OverviewTab, fetch: (p) => fetchPerpsOverview(p) },
    { key: 'cross', label: 'Cross Analysis', icon: Layers, Component: CrossAnalysisTab,
      props: { ns: 'perps-cross', fetchDimensions: fetchPerpsDimensions, fetchCross: fetchPerpsCrossAnalysis, fetchInsights: fetchPerpsInsights } },
    { key: 'sessions', label: 'Sessions', Component: SessionsTab,
      fetch: (p) => fetchPerpsPerformance('session', p), normalize: normSession },
    { key: 'heatmap', label: 'Heatmap', Component: HeatmapTab,
      fetch: (p) => fetchPerpsHeatmap(p) },
    { key: 'holdtime', label: 'Hold-time', Component: HoldTimeTab,
      fetch: (p) => fetchPerpsPerformance('holdtime', p), normalize: normHoldtime },
    { key: 'symbols', label: 'Symbols', Component: GroupTab, props: { title: 'By Symbol', labelHeader: 'Symbol' },
      fetch: (p) => fetchPerpsPerformance('symbol', p), normalize: normGroupPerf('group') },
    { key: 'direction', label: 'Direction', Component: GroupTab, props: { title: 'Long vs Short', labelHeader: 'Direction' },
      fetch: (p) => fetchPerpsPerformance('direction', p), normalize: normGroupPerf('group') },
    { key: 'funding', label: 'Funding', Component: FundingTab },
    { key: 'fees', label: 'Fees', Component: FeesTab },
    { key: 'leverage', label: 'Leverage', Component: LeverageTab },
    { key: 'setups', label: 'Setups', Component: GroupTab, props: { title: 'By Setup', labelHeader: 'Setup' },
      fetch: (p) => fetchPerpsPerformance('setup', p), normalize: normGroupPerf('group') },
    { key: 'grades', label: 'Grades', Component: GradesTab,
      fetch: (p) => fetchPerpsPerformance('grade', p), normalize: normGrades },
    { key: 'mistakes', label: 'Mistakes', Component: MistakesTab,
      fetch: (p) => fetchPerpsPerformance('mistake', p), normalize: normMistakes },
    { key: 'tags', label: 'Tags', Component: GroupTab, props: { title: 'By Tag', labelHeader: 'Tag' },
      fetch: (p) => fetchPerpsPerformance('tag', p), normalize: normGroupPerf('group') },
    { key: 'rdist', label: 'R-Dist.', Component: RDistTab,
      fetch: (p, mode) => fetchPerpsRDistribution({ ...p, mode }),
      props: { modes: ['stored', 'actual'] } },
  ],
}
