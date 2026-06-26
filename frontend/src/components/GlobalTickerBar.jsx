import { useQuery } from '@tanstack/react-query'
import { fetchTickerQuotes } from '../lib/api'
import useBybitTickers from '../lib/useBybitTickers'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

// Index/futures rows come from the backend (Yahoo: ES/NQ/RTY futures, DAX,
// VIX, gold, oil); crypto streams live from Bybit's public WebSocket.
const LABELS = {
  'ES=F': 'US500',
  'NQ=F': 'US100',
  'RTY=F': 'US2000',
  '^GDAXI': 'DAX40',
  '^VIX': 'VIX',
  'GC=F': 'GOLD',
  'CL=F': 'OIL',
}

const CRYPTO = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
const CRYPTO_LABELS = { BTCUSDT: 'BTC', ETHUSDT: 'ETH', SOLUSDT: 'SOL' }

function fmt(price, big) {
  if (price == null || price === 0) return '—'
  if (big && price >= 1000) {
    return price.toLocaleString('en-US', { maximumFractionDigits: 0 })
  }
  return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function Cell({ label, price, pct, big, divider }) {
  const isUp = pct != null && pct > 0
  const isDown = pct != null && pct < 0
  const color = isUp ? 'text-[#00d4aa]' : isDown ? 'text-[#de576f]' : 'text-[#8d91a6]'
  const Icon = isUp ? TrendingUp : isDown ? TrendingDown : Minus
  return (
    <div className={`flex items-center gap-1.5 px-3 shrink-0 ${divider ? 'border-l border-[#2a2c30]' : ''}`}>
      <span className="text-[11px] font-semibold text-[#8d91a6] tracking-wide">{label}</span>
      <span className="text-[12px] font-mono font-medium text-[#e2e4ef]">{fmt(price, big)}</span>
      {pct != null && (
        <span className={`flex items-center gap-0.5 text-[11px] font-medium ${color}`}>
          <Icon className="w-3 h-3" />
          {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
        </span>
      )}
    </div>
  )
}

export default function GlobalTickerBar() {
  const { data = [] } = useQuery({
    queryKey: ['ticker-bar'],
    queryFn: () => fetchTickerQuotes(),
    refetchInterval: 30_000,
    staleTime: 25_000,
  })
  const live = useBybitTickers(CRYPTO)

  const hasAny = data.length > 0 || Object.keys(live).length > 0
  if (!hasAny) return null

  return (
    <div className="h-9 bg-[#161718] border-b border-[#2a2c30] flex items-center px-4 gap-0 overflow-x-auto shrink-0">
      {data.map((q, i) => (
        <Cell
          key={q.symbol}
          label={LABELS[q.symbol] || q.symbol}
          price={q.price}
          pct={q.change_pct}
          divider={i > 0}
        />
      ))}
      {CRYPTO.map((sym, i) => (
        <Cell
          key={sym}
          label={CRYPTO_LABELS[sym]}
          price={live[sym]?.price}
          pct={live[sym]?.pct24h}
          big
          divider={data.length > 0 || i > 0}
        />
      ))}
    </div>
  )
}
