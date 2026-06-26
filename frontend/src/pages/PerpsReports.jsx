import AnalyticsShell from '../analytics/AnalyticsShell'
import { perpsAdapter } from '../analytics/perpsAdapter'

export default function PerpsReports() {
  return <AnalyticsShell adapter={perpsAdapter} />
}
