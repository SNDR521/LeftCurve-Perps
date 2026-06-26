import { useQuery } from '@tanstack/react-query'
import { fmtNum, pnlColor, Loading, Empty, ErrorBox } from './_ui'

function Stat({ label, value, color }) {
  return (
    <div className="card px-4 py-3">
      <div className="text-[11px] text-[#4e5166]">{label}</div>
      <div className={`text-[18px] font-semibold ${color || 'text-[#e2e4ef]'}`}>{value}</div>
    </div>
  )
}

export default function OverviewTab({ tabKey, params, fetch }) {
  const { data: ov, isLoading, isError } = useQuery({ queryKey: [tabKey, params], queryFn: () => fetch(params) })
  if (isLoading) return <Loading />
  if (isError) return <ErrorBox />
  if (!ov || !ov.total_trades) return <Empty />
  const c = pnlColor(ov.total_pnl)
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
      <Stat label="Total P&L" value={`$${fmtNum(ov.total_pnl)}`} color={c} />
      <Stat label="Trades" value={ov.total_trades} />
      <Stat label="Win rate" value={`${fmtNum(ov.win_rate, 1)}%`} />
      <Stat label="Profit factor" value={fmtNum(ov.profit_factor)} />
      <Stat label="Expectancy" value={`$${fmtNum(ov.expectancy)}`} />
      <Stat label="Avg win" value={`$${fmtNum(ov.avg_win)}`} color="text-[#00d4aa]" />
      <Stat label="Avg loss" value={`$${fmtNum(ov.avg_loss)}`} color="text-[#de576f]" />
      <Stat label="Avg R" value={ov.avg_r_multiple == null ? '—' : fmtNum(ov.avg_r_multiple)} />
      <Stat label="Max drawdown" value={`$${fmtNum(ov.max_drawdown)}`} color="text-[#de576f]" />
      <Stat label="Best trade" value={`$${fmtNum(ov.best_trade)}`} color="text-[#00d4aa]" />
      <Stat label="Worst trade" value={`$${fmtNum(ov.worst_trade)}`} color="text-[#de576f]" />
      <Stat label="Sharpe" value={ov.sharpe_ratio == null ? '—' : fmtNum(ov.sharpe_ratio)} />
      <Stat label="Sortino" value={ov.sortino_ratio == null ? '—' : fmtNum(ov.sortino_ratio)} />
    </div>
  )
}
