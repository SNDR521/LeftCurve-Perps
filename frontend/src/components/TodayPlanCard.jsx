import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { fetchPlanCard, fetchPlanScore } from '../lib/api'

// Today in UTC, matching the plan-card date keying used elsewhere.
function todayUtc() {
  return new Date().toISOString().slice(0, 10)
}

const signedUsd = (n) => (n == null ? '—' : `${n >= 0 ? '+' : '-'}$${Math.abs(Number(n)).toFixed(2)}`)
const pnlColor = (n) => (n == null || n === 0 ? 'text-[#8d91a6]' : n > 0 ? 'text-[#00d4aa]' : 'text-[#de576f]')

// Live plan summary shared by both dashboards. Renders nothing while loading
// or when both queries error — a dashboard must never degrade on plan failure.
// `workspace` scopes the live numbers to the dashboard showing them: the perps
// dashboard must not display prop P&L (and vice versa). /plan stays combined.
export default function TodayPlanCard({ workspace = 'all' }) {
  const today = todayUtc()

  const cardQ = useQuery({
    queryKey: ['plan-card', today],
    queryFn: () => fetchPlanCard(today),
    refetchInterval: 30000,
    retry: false,
  })
  const scoreQ = useQuery({
    queryKey: ['plan-score', today, workspace],
    queryFn: () => fetchPlanScore(today, workspace),
    refetchInterval: 30000,
    retry: false,
  })

  if (cardQ.isLoading) return null
  if (cardQ.isError && scoreQ.isError) return null

  const card = cardQ.data

  // No plan today — slim CTA.
  if (!card) {
    return (
      <Link
        to="/plan"
        className="card px-4 py-2.5 flex items-center gap-2 text-[12px] text-[#8d91a6] hover:border-[#4e5166] transition-colors"
      >
        <span>No plan for today —</span>
        <span className="text-[#38bdf8] font-medium">Create today's plan →</span>
      </Link>
    )
  }

  const score = scoreQ.data
  const flags = score?.flags || {}
  const maxTrades = card.max_trades
  const maxLoss = card.max_daily_loss
  const rPerTrade = card.r_per_trade

  const hasCommitment = maxTrades != null || maxLoss != null || rPerTrade != null

  // Commitments summary — only the set ones.
  const commitParts = []
  if (maxTrades != null) commitParts.push(`max ${maxTrades} trades`)
  if (maxLoss != null) commitParts.push(`$${Number(maxLoss).toFixed(0)} loss cap`)
  if (rPerTrade != null) commitParts.push(`${rPerTrade}R`)

  const setupNote = card.a_setup_note || card.playbook_ref || null
  const tradesCount = score?.trades_count
  const realized = score?.realized

  return (
    <Link
      to="/plan"
      className="card px-4 py-2.5 flex items-center gap-3 text-[12px] hover:border-[#4e5166] transition-colors"
    >
      <span className="text-[#8d91a6] shrink-0 font-medium">Today's plan</span>

      {setupNote && (
        <>
          <span className="text-[#4e5166]">·</span>
          <span className="text-[#e2e4ef] truncate max-w-[220px]" title={setupNote}>{setupNote}</span>
        </>
      )}

      {commitParts.length > 0 && (
        <>
          <span className="text-[#4e5166]">·</span>
          <span className="text-[#8d91a6] truncate">{commitParts.join(' · ')}</span>
        </>
      )}

      {/* Live chips from score */}
      {score && (
        <span className="flex items-center gap-2 ml-auto shrink-0">
          {tradesCount != null && (
            <span className={`badge text-[10px] ${flags.trades_over ? 'bg-[#de576f]/15 text-[#de576f]' : 'bg-[#2a2c30] text-[#8d91a6]'}`}>
              trades {tradesCount}{maxTrades != null ? `/${maxTrades}` : ''}
            </span>
          )}
          {realized != null && (
            <span className={`badge text-[10px] bg-[#2a2c30] ${pnlColor(realized)}`}>{signedUsd(realized)}</span>
          )}
          {hasCommitment && (
            <span className={`badge text-[10px] font-semibold ${score.adherent ? 'bg-[#00d4aa]/15 text-[#00d4aa]' : 'bg-[#de576f]/15 text-[#de576f]'}`}>
              {score.adherent ? 'ADHERENT' : 'BREACHED'}
            </span>
          )}
        </span>
      )}

      <ChevronRight className={`w-4 h-4 text-[#4e5166] shrink-0 ${score ? '' : 'ml-auto'}`} />
    </Link>
  )
}
