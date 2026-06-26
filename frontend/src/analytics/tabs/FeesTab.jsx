import { useQuery } from '@tanstack/react-query'
import { fetchPerpsFees } from '../../lib/api'
import { fmt$, TH, ErrorBox, ExportButton } from './_ui'
import { downloadCsv } from '../csv'

function Insight({ children }) {
  return <p className="text-[15px] text-white leading-relaxed">{children}</p>
}

export default function FeesTab({ params }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['perps-costs', 'fees', params],
    queryFn: () => fetchPerpsFees(params),
  })

  if (isLoading) return <div className="skeleton-shimmer h-52 w-full rounded-lg" />
  if (isError) return <ErrorBox />

  const bySymbol = data?.by_symbol ?? []

  if (!data || (bySymbol.length === 0 && !data.total)) {
    return <p className="px-5 py-8 text-center text-[#4e5166] text-[13px]">No fee data yet.</p>
  }

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <Insight>
          {Math.round(data.taker_share_pct)}% of your fills were taker — maker entries on the same flow would have saved ≈ {fmt$(data.maker_savings_estimate)}.
        </Insight>
        <p className="text-[13px] text-[#8d91a6]">
          Total fees {fmt$(data.total)}{data.pct_of_gross != null ? ` — ${data.pct_of_gross}% of gross profit` : ''}
        </p>
      </div>
      <div className="card overflow-hidden">
        <div className="px-5 py-4 border-b border-[#2a2c30] flex items-center justify-between gap-3">
          <h2 className="text-[14px] font-semibold text-white">By Symbol</h2>
          <ExportButton
            onClick={() => downloadCsv('fees-by-symbol', ['Symbol', 'Total fees', 'Cost per round-trip'],
              bySymbol.map((r) => [r.symbol, r.fees_total, r.round_trip_cost]))}
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
                <TH right>Total fees</TH>
                <TH right>Cost per round-trip</TH>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2a2c30]/50">
              {bySymbol.map(r => (
                <tr key={r.symbol} className="hover:bg-[#242629] transition-colors">
                  <td className="px-4 py-3 font-semibold text-[#38bdf8]">{r.symbol}</td>
                  <td className="px-4 py-3 text-right font-mono text-[#8d91a6]">{fmt$(r.fees_total)}</td>
                  <td className="px-4 py-3 text-right font-mono text-[#8d91a6]">{fmt$(r.round_trip_cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </div>
    </div>
  )
}
