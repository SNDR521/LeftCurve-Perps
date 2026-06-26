// Shared trade-detail helpers, extracted verbatim from pages/TradeDetail.jsx.
// Pure extraction — no behavioural changes. The prop page keeps its own copies
// until Task 8 migrates it onto the shell.

export const EMOTIONS = ['Confident', 'Calm', 'Nervous', 'FOMO', 'Revenge', 'Greedy', 'Fearful', 'Neutral', 'Frustrated', 'Euphoric']
export const SETUPS = ['Breakout', 'Mean Reversion', 'Pullback', 'Range Break', 'Trend Continuation', 'Reversal', 'Scalp', 'News Play']
export const MISTAKE_TAGS = ['Overtrading', 'FOMO', 'Revenge', 'Moved SL', 'Early Exit', 'Late Entry', 'Sized Up', 'No Plan', 'Chased', 'Ignored Signal']

export function AutopsyMarkdown({ text }) {
  if (!text) return null
  return (
    <div className="space-y-1.5 text-[13px] leading-relaxed text-[#c8ccd8]">
      {text.split('\n').map((line, i) => {
        if (line.startsWith('## '))
          return <h3 key={i} className="text-[14px] font-semibold text-[#e2e4ef] mt-4 mb-1 border-b border-[#2a2c30] pb-1">{inlineMd(line.slice(3))}</h3>
        if (line.startsWith('### '))
          return <h4 key={i} className="text-[13px] font-semibold text-[#8d91a6] mt-3">{inlineMd(line.slice(4))}</h4>
        if (line.startsWith('- ') || line.startsWith('* '))
          return <div key={i} className="flex items-start gap-2 ml-3"><span className="text-[#4e5166] mt-1 shrink-0">•</span><span>{inlineMd(line.slice(2))}</span></div>
        if (line.trim() === '---') return <hr key={i} className="border-[#2a2c30] my-3" />
        if (!line.trim()) return <div key={i} className="h-1.5" />
        return <p key={i}>{inlineMd(line)}</p>
      })}
    </div>
  )
}

export function inlineMd(text) {
  const parts = []
  let rem = text, k = 0
  while (rem) {
    const b = rem.match(/\*\*(.+?)\*\*/)
    if (b) {
      if (b.index) parts.push(rem.slice(0, b.index))
      parts.push(<strong key={k++} className="font-semibold text-white">{b[1]}</strong>)
      rem = rem.slice(b.index + b[0].length)
      continue
    }
    parts.push(rem)
    break
  }
  return parts
}

export function Label({ children }) {
  return <label className="block text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em] mb-1.5">{children}</label>
}

export function MetricCell({ icon: Icon, label, value, color }) {
  return (
    <div className="px-3 py-2.5 text-center">
      <p className="text-[9px] text-[#4e5166] font-semibold uppercase">{label}</p>
      <p className="text-[12px] font-mono mt-0.5" style={color ? { color } : { color: '#8d91a6' }}>{value}</p>
    </div>
  )
}

export function QuickStat({ label, value, color }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[11px] text-[#4e5166]">{label}</span>
      <span className={`text-[12px] font-mono font-medium ${color || 'text-[#8d91a6]'}`}>{value}</span>
    </div>
  )
}

export function fmtDur(s) {
  if (!s) return '—'
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
  if (h > 24) return `${Math.floor(h / 24)}d ${h % 24}h`
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}
