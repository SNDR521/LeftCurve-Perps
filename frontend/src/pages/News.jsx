import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchEquityNews, fetchCryptoNews, fetchTickerQuotes } from '../lib/api'
import { ExternalLink, RefreshCw, TrendingUp, TrendingDown, Minus } from 'lucide-react'

// Yahoo-compatible symbols (the /quotes endpoint is Yahoo-only): ^VIX for the
// volatility index and the -USD crypto pairs Yahoo serves. The old bare VIX /
// BINANCE:* symbols never resolved on the prior Finnhub free tier either.
const WATCHLIST = 'SPY,QQQ,IWM,^VIX,BTC-USD,ETH-USD,SOL-USD,BNB-USD'

const SYMBOL_LABELS = {
  SPY: 'SPY', QQQ: 'QQQ', IWM: 'IWM', '^VIX': 'VIX',
  'BTC-USD': 'BTC', 'ETH-USD': 'ETH', 'SOL-USD': 'SOL', 'BNB-USD': 'BNB',
}

function timeAgo(value) {
  if (!value) return ''
  const ts = typeof value === 'number' ? value * 1000 : Date.parse(value)
  const diff = (Date.now() - ts) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function fmt(price, symbol) {
  if (!price) return '—'
  if (symbol?.startsWith('BINANCE:') && price >= 1000) {
    return price.toLocaleString('en-US', { maximumFractionDigits: 0 })
  }
  return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function NewsCard({ item, type }) {
  const related = item.related ? item.related.split(',').slice(0, 3).filter(Boolean) : []
  const tags = type === 'crypto' ? related : []

  return (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block group p-4 bg-[#1e2024] border border-[#2a2c30] rounded-xl hover:border-[#3a3c42]
                 hover:bg-[#242629] transition-all"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <span className="text-[11px] font-medium text-[#4f6ef7] bg-[#4f6ef7]/10 px-2 py-0.5 rounded-full">
              {item.source}
            </span>
            {tags.map(t => (
              <span key={t} className="text-[10px] font-medium text-[#00d4aa] bg-[#00d4aa]/10 px-1.5 py-0.5 rounded-full">
                {t}
              </span>
            ))}
            <span className="text-[11px] text-[#4e5166] ml-auto shrink-0">{timeAgo(item.datetime)}</span>
          </div>
          <p className="text-[13px] font-medium text-[#e2e4ef] leading-snug group-hover:text-white transition-colors line-clamp-2">
            {item.headline}
          </p>
          {item.summary && (
            <p className="text-[12px] text-[#8d91a6] mt-1 line-clamp-2 leading-relaxed">
              {item.summary}
            </p>
          )}
        </div>
        <ExternalLink className="w-3.5 h-3.5 text-[#4e5166] group-hover:text-[#8d91a6] shrink-0 mt-0.5 transition-colors" />
      </div>
    </a>
  )
}

function WatchlistPanel() {
  const { data: quotes = [] } = useQuery({
    queryKey: ['news-watchlist'],
    queryFn: () => fetchTickerQuotes(WATCHLIST),
    refetchInterval: 30_000,
    staleTime: 25_000,
  })

  return (
    <div className="bg-[#1e2024] border border-[#2a2c30] rounded-xl p-4">
      <h3 className="text-[11px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] mb-3">
        Market Pulse
      </h3>
      <div className="space-y-1">
        {quotes.map(q => {
          const label = SYMBOL_LABELS[q.symbol] || q.symbol
          const pct = q.change_pct
          const isUp = pct != null && pct > 0
          const isDown = pct != null && pct < 0
          const color = isUp ? 'text-[#00d4aa]' : isDown ? 'text-[#de576f]' : 'text-[#8d91a6]'
          const Icon = isUp ? TrendingUp : isDown ? TrendingDown : Minus

          return (
            <div key={q.symbol} className="flex items-center justify-between py-1.5 border-b border-[#2a2c30] last:border-0">
              <span className="text-[12px] font-semibold text-[#8d91a6]">{label}</span>
              <div className="flex items-center gap-2">
                <span className="text-[13px] font-mono text-[#e2e4ef]">{fmt(q.price, q.symbol)}</span>
                {pct != null && (
                  <span className={`flex items-center gap-0.5 text-[11px] font-medium ${color} w-[60px] justify-end`}>
                    <Icon className="w-3 h-3 shrink-0" />
                    {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function News() {
  const [tab, setTab] = useState('equity')

  const equityQ = useQuery({
    queryKey: ['news-equity'],
    queryFn: () => fetchEquityNews(50),
    refetchInterval: 30_000,
    staleTime: 25_000,
    enabled: tab === 'equity',
  })

  const cryptoQ = useQuery({
    queryKey: ['news-crypto'],
    queryFn: () => fetchCryptoNews(50),
    refetchInterval: 30_000,
    staleTime: 25_000,
    enabled: tab === 'crypto',
  })

  const active = tab === 'equity' ? equityQ : cryptoQ
  const news = active.data || []
  const lastUpdated = active.dataUpdatedAt

  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 10_000)
    return () => clearInterval(id)
  }, [])

  const secsSince = lastUpdated ? Math.floor((now - lastUpdated) / 1000) : null

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-[22px] font-bold text-[#fcfefd] tracking-tight">News</h1>
          <p className="text-[13px] text-[#4e5166] mt-0.5">
            {secsSince != null
              ? secsSince < 10 ? 'Updated just now' : `Updated ${secsSince}s ago`
              : 'Loading...'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {active.isFetching && <RefreshCw className="w-4 h-4 text-[#4e5166] animate-spin" />}
          <div className="flex bg-[#1a1b1e] border border-[#2a2c30] rounded-lg p-0.5">
            {[
              { key: 'equity', label: 'Equity' },
              { key: 'crypto', label: 'Crypto' },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`px-4 py-1.5 text-[12px] font-medium rounded-md transition-all ${
                  tab === key
                    ? 'bg-[#4f6ef7] text-white'
                    : 'text-[#4e5166] hover:text-[#8d91a6]'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex gap-5">
        {/* News feed */}
        <div className="flex-1 min-w-0 space-y-2.5">
          {active.isLoading && (
            <div className="space-y-2.5">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="h-[88px] rounded-xl skeleton" />
              ))}
            </div>
          )}
          {!active.isLoading && news.length === 0 && (
            <div className="text-[13px] text-[#4e5166] text-center py-16">No news available</div>
          )}
          {news.map(item => (
            <NewsCard key={item.id} item={item} type={tab} />
          ))}
        </div>

        {/* Sidebar */}
        <div className="w-[240px] shrink-0 space-y-4">
          <WatchlistPanel />
        </div>
      </div>
    </div>
  )
}
