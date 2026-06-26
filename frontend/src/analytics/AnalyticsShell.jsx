import { useMemo, useState } from 'react'
import PeriodSelector from '../dashboard/PeriodSelector'
import { getDateRange, loadPeriod, savePeriod } from '../dashboard/period'

export default function AnalyticsShell({ adapter }) {
  const accountParams = adapter.useAccountParams()
  const init = useMemo(() => loadPeriod(adapter.storageKey, 'all'), [adapter.storageKey])
  const [period, setPeriod] = useState(init.period)
  const [custom, setCustom] = useState(init.custom)
  const [activeKey, setActiveKey] = useState(adapter.tabs[0].key)

  // PeriodSelector emits a single { period, custom } object.
  function onPeriodChange({ period: p, custom: c }) {
    setPeriod(p); setCustom(c); savePeriod(adapter.storageKey, p, c)
  }

  const params = { ...accountParams, ...getDateRange(period, custom) }
  const tab = adapter.tabs.find((t) => t.key === activeKey) || adapter.tabs[0]
  const TabComponent = tab.Component

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-[22px] font-semibold text-white">{adapter.title}</h1>
          <p className="text-[13px] text-[#4e5166] mt-0.5">{adapter.subtitle}</p>
          {adapter.Coverage && <adapter.Coverage params={params} />}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <PeriodSelector period={period} custom={custom} onChange={onPeriodChange} />
        </div>
      </div>

      <div className="overflow-x-auto">
        <div className="tab-bar w-fit flex-nowrap">
          {adapter.tabs.map((t) => (
            <button key={t.key} onClick={() => setActiveKey(t.key)}
                    className={`tab-item flex items-center gap-1.5 shrink-0 ${activeKey === t.key ? 'active' : ''}`}>
              {t.icon ? <t.icon className="w-3.5 h-3.5" /> : null}{t.label}
            </button>
          ))}
        </div>
      </div>

      <TabComponent tabKey={tab.key} params={params} {...(tab.props || {})}
                    fetch={tab.fetch} normalize={tab.normalize} />
    </div>
  )
}
