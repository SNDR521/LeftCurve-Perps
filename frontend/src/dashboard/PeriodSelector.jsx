import { PERIODS } from './period'

// Shared timeframe selector for both dashboards. Controlled: the parent owns
// { period, custom } and persists it. Renders a fragment (pill group + optional
// date inputs) so it slots into each dashboard's existing header flex row.
export default function PeriodSelector({ period, custom, onChange }) {
  const cur = custom || { from: '', to: '' }
  const pillCls = (active) =>
    `px-2.5 py-1.5 rounded-md text-[11px] font-medium transition-all ${
      active ? 'bg-[var(--accent)] text-white' : 'text-[#4e5166] hover:text-[#8d91a6]'
    }`
  const dateCls =
    'bg-[#1e2024] border border-[#2a2c30] rounded-md px-2 py-1 text-[11px] text-[#e2e4ef] ' +
    'focus:outline-none focus:border-[var(--accent)]'

  return (
    <>
      <div className="flex gap-0.5 bg-[#1e2024] border border-[#2a2c30] rounded-lg p-0.5">
        {PERIODS.map(p => (
          <button key={p.key} onClick={() => onChange({ period: p.key, custom: cur })}
            className={pillCls(period === p.key)}>{p.label}</button>
        ))}
        <button onClick={() => onChange({ period: 'custom', custom: cur })}
          className={pillCls(period === 'custom')}>Custom</button>
      </div>
      {period === 'custom' && (
        <div className="flex items-center gap-1.5">
          <input type="date" className={dateCls} value={cur.from}
            max={cur.to || undefined}
            onChange={e => onChange({ period: 'custom', custom: { ...cur, from: e.target.value } })} />
          <span className="text-[#4e5166] text-[11px]">—</span>
          <input type="date" className={dateCls} value={cur.to}
            min={cur.from || undefined}
            onChange={e => onChange({ period: 'custom', custom: { ...cur, to: e.target.value } })} />
        </div>
      )}
    </>
  )
}
