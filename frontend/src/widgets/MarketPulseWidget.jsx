import { useQuery } from '@tanstack/react-query'
import { fetchTickerQuotes } from '../lib/api'
import useBybitTickers from '../lib/useBybitTickers'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

// Crypto rows stream live from Bybit's public WebSocket (no key, ~100ms).
// Index rows use the instruments a CFD trader actually tracks: ES/NQ/RTY
// futures (~23h sessions, unlike cash indices) and the DAX — all served via
// Yahoo on the backend (none are on Finnhub's free tier).
const CRYPTO = [
  { symbol: 'BTCUSDT', label: 'BTC', name: 'Bitcoin' },
  { symbol: 'ETHUSDT', label: 'ETH', name: 'Ethereum' },
  { symbol: 'SOLUSDT', label: 'SOL', name: 'Solana' },
]
const EQUITY = [
  { symbol: 'ES=F',   label: 'US500',  name: 'S&P 500 fut' },
  { symbol: 'NQ=F',   label: 'US100',  name: 'Nasdaq fut' },
  { symbol: 'RTY=F',  label: 'US2000', name: 'Russell fut' },
  { symbol: '^GDAXI', label: 'DAX40',  name: 'DAX' },
  { symbol: 'GC=F',   label: 'GOLD',   name: 'Gold fut' },
  { symbol: 'CL=F',   label: 'OIL',    name: 'WTI fut' },
  { symbol: '^VIX',   label: 'VIX',    name: 'Volatility' },
]

const EQUITY_SYMBOLS = EQUITY.map(t => t.symbol).join(',')

function fmt(price, big) {
  if (price == null) return '—'
  if (big && price >= 1000)
    return price.toLocaleString('en-US', { maximumFractionDigits: 0 })
  return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function Row({ label, name, price, pct, big, live }) {
  const isUp = pct != null && pct > 0
  const isDown = pct != null && pct < 0
  const color = isUp ? 'text-[#00d4aa]' : isDown ? 'text-[#de576f]' : 'text-[#8d91a6]'
  const Icon = isUp ? TrendingUp : isDown ? TrendingDown : Minus
  return (
    <div className="flex items-center justify-between px-2 py-1.5 rounded-lg hover:bg-[#242629] transition-colors">
      <div className="flex items-center gap-1.5">
        <span className="text-[12px] font-semibold text-[#e2e4ef]">{label}</span>
        <span className="text-[10px] text-[#4e5166]">{name}</span>
        {live && <span className="w-1 h-1 rounded-full bg-[#00d4aa]" title="streaming live from Bybit" />}
      </div>
      <div className="flex items-center gap-2 text-right">
        <span className="text-[12px] font-mono text-[#e2e4ef]">{fmt(price, big)}</span>
        {pct != null && (
          <span className={`flex items-center gap-0.5 text-[11px] font-medium ${color} w-[58px] justify-end`}>
            <Icon className="w-3 h-3 shrink-0" />
            {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
          </span>
        )}
      </div>
    </div>
  )
}

export default function MarketPulseWidget() {
  const live = useBybitTickers(CRYPTO.map(c => c.symbol))

  const { data: quotes = [] } = useQuery({
    queryKey: ['market-pulse-widget', EQUITY_SYMBOLS],
    queryFn: () => fetchTickerQuotes(EQUITY_SYMBOLS),
    refetchInterval: 30_000,
    staleTime: 25_000,
  })
  const bySymbol = Object.fromEntries(quotes.map(q => [q.symbol, q]))

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <p className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] mb-2 shrink-0">
        Market Pulse
      </p>
      <div className="flex-1 overflow-y-auto space-y-0.5 min-h-0">
        {EQUITY.map(({ symbol, label, name }) => {
          const q = bySymbol[symbol]
          return <Row key={symbol} label={label} name={name} price={q?.price} pct={q?.change_pct} />
        })}
        {CRYPTO.map(({ symbol, label, name }) => {
          const t = live[symbol]
          return <Row key={symbol} label={label} name={name} price={t?.price} pct={t?.pct24h} big live={t?.price != null} />
        })}
      </div>
    </div>
  )
}
