import { useQuery } from '@tanstack/react-query'
import { fetchPerpsFunding } from '../../lib/api'
import { fmt$, pnlColor, TH, ErrorBox, ExportButton } from './_ui'
import { downloadCsv } from '../csv'

function Insight({ children }) {
  return <p className="text-[15px] text-white leading-relaxed">{children}</p>
}

export default function FundingTab({ params }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['perps-costs', 'funding', params],
    queryFn: () => fetchPerpsFunding(params),
  })

  if (isLoading) return <div className="skeleton-shimmer h-52 w-full rounded-lg" />
  if (isError) return <ErrorBox />

  const bySymbol = data?.by_symbol ?? []
  const byMonth = data?.by_month ?? []

  if (bySymbol.length === 0 && byMonth.length === 0) {
    return <p className="px-5 py-8 text-center text-[#4e5166] text-[13px]">No funding events yet.</p>
  }

  const net = data?.net ?? 0
  let insight
  if (net < 0) {
    const worst = bySymbol[0]
    insight = bySymbol.length === 0
      ? <>Funding consumed {data?.pct_of_gross ?? '—'}% of gross profit ({fmt$(net)}).</>
      : <>Funding consumed {data?.pct_of_gross ?? '—'}% of gross profit ({fmt$(net)}). Worst: {worst.symbol} ({fmt$(worst.net)}).</>
  } else {
    insight = <>Funding EARNED you {fmt$(net)} net.</>
  }

  return (
    <div className="space-y-4">
      <Insight>{insight}</Insight>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card overflow-hidden">
          <div className="px-5 py-4 border-b border-[#2a2c30] flex items-center justify-between gap-3">
            <h2 className="text-[14px] font-semibold text-white">By Symbol</h2>
            <ExportButton
              onClick={() => downloadCsv('funding-by-symbol', ['Symbol', 'Paid', 'Received', 'Net'],
                bySymbol.map((r) => [r.symbol, r.paid, r.received, r.net]))}
              disabled={!bySymbol.length} />
          </div>
          {bySymbol.length === 0 ? (
            <p className="px-5 py-8 text-center text-[#4e5166] text-[13px]">No data yet</p>
          ) : (
            <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-[#4e5166] border-b border-[#2a2c30]">
                  <TH>Symbol</TH>
                  <TH right>Paid</TH>
                  <TH right>Received</TH>
                  <TH right>Net</TH>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#2a2c30]/50">
                {bySymbol.map(r => (
                  <tr key={r.symbol} className="hover:bg-[#242629] transition-colors">
                    <td className="px-4 py-3 font-semibold text-[#38bdf8]">{r.symbol}</td>
                    <td className="px-4 py-3 text-right font-mono text-[#8d91a6]">{fmt$(r.paid)}</td>
                    <td className="px-4 py-3 text-right font-mono text-[#8d91a6]">{fmt$(r.received)}</td>
                    <td className={`px-4 py-3 text-right font-mono font-semibold ${pnlColor(r.net)}`}>{fmt$(r.net)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </div>
        <div className="card overflow-hidden">
          <div className="px-5 py-4 border-b border-[#2a2c30] flex items-center justify-between gap-3">
            <h2 className="text-[14px] font-semibold text-white">By Month</h2>
            <ExportButton
              onClick={() => downloadCsv('funding-by-month', ['Month', 'Net'],
                byMonth.map((r) => [r.month, r.net]))}
              disabled={!byMonth.length} />
          </div>
          {byMonth.length === 0 ? (
            <p className="px-5 py-8 text-center text-[#4e5166] text-[13px]">No data yet</p>
          ) : (
            <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-[#4e5166] border-b border-[#2a2c30]">
                  <TH>Month</TH>
                  <TH right>Net</TH>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#2a2c30]/50">
                {byMonth.map(r => (
                  <tr key={r.month} className="hover:bg-[#242629] transition-colors">
                    <td className="px-4 py-3 font-medium text-white">{r.month}</td>
                    <td className={`px-4 py-3 text-right font-mono font-semibold ${pnlColor(r.net)}`}>{fmt$(r.net)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
