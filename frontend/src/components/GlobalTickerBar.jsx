import { useQuery } from '@tanstack/react-query'
import { fetchTickerQuotes } from '../lib/api'
import useBybitTickers from '../lib/useBybitTickers'
import { usePreferences } from '../preferences/PreferencesContext'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

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
  const { prefs } = usePreferences()
  const tickerBar = prefs.ticker_bar ?? { enabled: true, symbols: [] }

  // Partition symbols by source
  const bybitSymbols = tickerBar.symbols
    .filter(s => s.source === 'bybit' || /USDT$/i.test(s.symbol))
    .map(s => s.symbol)
  const otherSymbols = tickerBar.symbols
    .filter(s => s.source !== 'bybit' && !/USDT$/i.test(s.symbol))
    .map(s => s.symbol)

  const { data: restData = [] } = useQuery({
    queryKey: ['ticker-bar', otherSymbols.join(',')],
    queryFn: () => fetchTickerQuotes(otherSymbols.join(',')),
    enabled: otherSymbols.length > 0,
    refetchInterval: 30_000,
    staleTime: 25_000,
  })

  const live = useBybitTickers(bybitSymbols)

  if (!tickerBar.enabled) return null
  if (tickerBar.symbols.length === 0) return null

  // Build a lookup for rest prices by symbol
  const restBySymbol = Object.fromEntries(restData.map(q => [q.symbol, q]))

  return (
    <div className="h-9 bg-[#161718] border-b border-[#2a2c30] flex items-center px-4 gap-0 overflow-x-auto shrink-0">
      {tickerBar.symbols.map((entry, i) => {
        const isBybit = entry.source === 'bybit' || /USDT$/i.test(entry.symbol)
        const price = isBybit ? live[entry.symbol]?.price : restBySymbol[entry.symbol]?.price
        const pct = isBybit ? live[entry.symbol]?.pct24h : restBySymbol[entry.symbol]?.change_pct
        const big = isBybit && price != null && price >= 1000
        return (
          <Cell
            key={entry.symbol}
            label={entry.label || entry.symbol}
            price={price}
            pct={pct}
            big={big}
            divider={i > 0}
          />
        )
      })}
    </div>
  )
}
