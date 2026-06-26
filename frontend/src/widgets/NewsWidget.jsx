import { useQuery } from '@tanstack/react-query'
import { useState, useEffect } from 'react'
import { fetchSquawk } from '../lib/api'
import { ExternalLink, Radio } from 'lucide-react'

const INTERVAL = 60

function timeAgo(iso) {
  if (!iso) return ''
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`
  return `${Math.floor(diff / 86400)}d`
}

export default function NewsWidget() {
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const { data: items = [], dataUpdatedAt } = useQuery({
    queryKey: ['squawk-widget'],
    queryFn: () => fetchSquawk(30),
    refetchInterval: INTERVAL * 1000,
    staleTime: 0,
  })

  const secsSince = dataUpdatedAt ? Math.floor((now - dataUpdatedAt) / 1000) : null
  const secsLeft = secsSince != null ? Math.max(0, INTERVAL - secsSince) : null
  const progress = secsSince != null ? Math.min(secsSince / INTERVAL, 1) : 0

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex items-center justify-between mb-1.5 shrink-0">
        <div className="flex items-center gap-1.5">
          <Radio className="w-3 h-3 text-[#de576f]" />
          <p className="text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">
            Squawk
          </p>
        </div>
        {secsLeft != null && (
          <span className="text-[10px] text-[#4e5166]">
            {secsLeft === 0 ? 'refreshing…' : `${secsLeft}s`}
          </span>
        )}
      </div>
      {/* countdown progress bar */}
      <div className="h-px bg-[#2a2c30] mb-2 shrink-0 overflow-hidden rounded-full">
        <div
          className="h-full bg-[#4f6ef7] transition-all duration-1000 ease-linear"
          style={{ width: `${(1 - progress) * 100}%` }}
        />
      </div>

      <div className="flex-1 overflow-y-auto space-y-px min-h-0">
        {items.map(item => (
          <a
            key={item.id}
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="group flex items-start gap-2 px-2 py-1.5 rounded-lg hover:bg-[#242629] transition-colors"
          >
            <span className="text-[10px] text-[#4e5166] shrink-0 mt-0.5 w-[28px] text-right">
              {timeAgo(item.datetime)}
            </span>
            <span className="text-[12px] text-[#c8cad6] leading-snug group-hover:text-white transition-colors flex-1">
              {item.headline}
            </span>
            <ExternalLink className="w-3 h-3 text-[#4e5166] shrink-0 mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity" />
          </a>
        ))}
        {!items.length && (
          <p className="text-[12px] text-[#4e5166] px-2 py-4 text-center">Loading squawk...</p>
        )}
      </div>
    </div>
  )
}
