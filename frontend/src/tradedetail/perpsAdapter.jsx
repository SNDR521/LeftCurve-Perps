import { useQuery } from '@tanstack/react-query'
import {
  fetchPerpsPositionDetail, fetchPerpsPositionDetailById, fetchPerpsChartData,
  savePerpsJournal, uploadPerpsScreenshot,
} from '../lib/api'
import { decodePositionKey } from '../lib/positionKey'
import { fmtDur } from './bits'
import { parseUtcSeconds } from './chartMath'
import PerpsTagEditor from './PerpsTagEditor'

const fmtUsd = (v) => (v == null ? '—' : `${v >= 0 ? '' : '-'}$${Math.abs(v).toFixed(2)}`)
const fmtNum = (v, d = 4) => (v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }))

function screenshotUrlFrom(path) {
  if (!path) return null
  const basename = path.replace(/\\/g, '/').split('/').pop()
  return `/api/screenshots/${basename}`
}

function normalize(detail) {
  if (!detail) return null
  const { position: p, journal, fills = [], risk = {} } = detail
  const executions = fills.map((f) => ({
    time: parseUtcSeconds(f.executed_at),
    side: f.side,
    price: f.price,
    quantity: f.quantity,
    is_funding: f.is_funding,
    funding_amount: f.funding_amount,
    fee: f.fee,
    executed_at: f.executed_at,
  }))
  return {
    symbol: p.symbol,
    direction: p.direction,
    status: p.status,
    entryTime: p.opened_at,
    exitTime: p.closed_at,
    durationSeconds: p.duration_seconds,
    pnl: p.realized_pnl,
    actualR: risk.actual_r,
    plannedRR: risk.planned_rr,
    riskSource: risk.risk_source,
    confidence: p.opened_at_source,
    journal,
    executions,
    screenshotUrl: screenshotUrlFrom(journal?.screenshot_path),
    positionKey: p.position_key,
    raw: detail,
  }
}

export const perpsAdapter = {
  backTo: '/trades',
  backLabel: 'Trade Log',

  useDetail(encodedKey) {
    const decoded = decodePositionKey(encodedKey)
    // A position_key always contains ':' ({account}:{symbol}:…); a bare numeric id
    // (the fallback when a row has no key) does not — route it to the id-based
    // detail endpoint, which is still served, so keyless positions still resolve.
    const byKey = decoded.includes(':')
    return useQuery({
      queryKey: ['perps-detail', encodedKey],
      queryFn: () => (byKey ? fetchPerpsPositionDetail(decoded) : fetchPerpsPositionDetailById(decoded)),
      select: normalize,
    })
  },

  saveJournal(data, payload) {
    return savePerpsJournal({ position_key: data.positionKey, ...payload })
  },

  uploadScreenshot(data, file) {
    return uploadPerpsScreenshot(data.positionKey, file)
  },

  deleteTrade: null,

  invalidate(queryClient, encodedKey) {
    queryClient.invalidateQueries(['perps-detail', encodedKey])
    queryClient.invalidateQueries(['perps-positions'])
  },

  chartProps(data) {
    const p = data.raw.position
    return {
      symbol: data.symbol,
      direction: data.direction,
      entryTime: data.entryTime,
      exitTime: data.exitTime,
      durationSeconds: data.durationSeconds,
      executions: data.executions,
      mfePrice: p.mfe_price,
      maePrice: p.mae_price,
      mfeUsd: p.mfe_usd,
      maeUsd: p.mae_usd,
      realizedPnl: p.realized_pnl,
      avgEntry: p.avg_entry,
      stop: data.journal?.stop_price,
      targets: data.journal?.targets ?? [],
      totalFunding: p.total_funding,
      confidence: data.confidence,
      fetchCandles: (symbol, fromTs, toTs, interval) =>
        fetchPerpsChartData({ symbol, from_ts: fromTs, to_ts: toTs, interval,
                              ...(p.exchange_account_id != null && { account_id: p.exchange_account_id }) }).then((r) => r),
      intervals: [
        { label: 'Auto', value: null },
        { label: '1m', value: '1' },
        { label: '5m', value: '5' },
        { label: '15m', value: '15' },
        { label: '1h', value: '60' },
        { label: '4h', value: '240' },
        { label: '1D', value: 'D' },
      ],
      pickInterval: (duration) => {
        const d = duration ?? 0
        if (d < 300) return '1'
        if (d < 3600) return '5'
        if (d < 14400) return '15'
        if (d < 86400) return '60'
        if (d < 604800) return '240'
        return 'D'
      },
    }
  },

  metricCells(data) {
    const p = data.raw.position
    return [
      { label: 'Entry', value: fmtNum(p.avg_entry) },
      { label: 'Exit', value: p.avg_exit == null ? '—' : fmtNum(p.avg_exit) },
      { label: 'Qty', value: fmtNum(p.quantity) },
      { label: 'Net P&L', value: fmtUsd(p.realized_pnl), color: p.realized_pnl >= 0 ? '#00d4aa' : '#de576f' },
      { label: 'Fees', value: fmtUsd(p.total_fees) },
      { label: 'Funding', value: fmtUsd(p.total_funding), color: (p.total_funding ?? 0) >= 0 ? '#00d4aa' : '#de576f' },
      { label: 'MFE', value: fmtUsd(p.mfe_usd), color: '#00d4aa' },
      { label: 'MAE', value: p.mae_usd == null ? '—' : fmtUsd(-Math.abs(p.mae_usd)), color: '#de576f' },
    ]
  },

  quickStats(data) {
    const pnlColor = data.pnl > 0 ? 'text-[#00d4aa]' : data.pnl < 0 ? 'text-[#de576f]' : 'text-[#8d91a6]'
    const p = data.raw.position
    const confidenceVerified = data.confidence === 'EXACT'
    return [
      { label: 'Net P&L', value: fmtUsd(data.pnl), color: pnlColor },
      { label: 'Actual R', value: Number.isFinite(data.actualR) ? `${data.actualR >= 0 ? '+' : ''}${data.actualR.toFixed(2)}R` : '—', color: pnlColor },
      { label: 'Planned R:R', value: Number.isFinite(data.plannedRR) ? `${data.plannedRR.toFixed(1)}:1` : '—' },
      { label: 'Duration', value: fmtDur(data.durationSeconds) },
      { label: 'Funding', value: fmtUsd(p.total_funding), color: (p.total_funding ?? 0) >= 0 ? 'text-[#00d4aa]' : 'text-[#de576f]' },
      { label: 'Confidence', value: confidenceVerified ? 'Verified' : 'Estimated', color: confidenceVerified ? 'text-[#00d4aa]' : 'text-[#f59e0b]' },
    ]
  },

  TagsPanel: PerpsTagEditor,
  extraTabs: [],
  riskEditable: true,
}
