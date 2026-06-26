import { useMemo, useState, useEffect, useRef } from 'react'
import PeriodSelector from '../dashboard/PeriodSelector'
import { getDateRange, loadPeriod, savePeriod } from '../dashboard/period'
import { usePreferences } from '../preferences/PreferencesContext'

export default function AnalyticsShell({ adapter }) {
  const accountParams = adapter.useAccountParams()
  const { prefs, prefsLoaded } = usePreferences()
  const init = useMemo(() => loadPeriod(adapter.storageKey, prefs.default_period || 'all'), [adapter.storageKey, prefs.default_period])
  const [period, setPeriod] = useState(init.period)
  const [custom, setCustom] = useState(init.custom)
  const [activeKey, setActiveKey] = useState(adapter.tabs[0].key)

  // Prefs load asynchronously. On a fresh browser (no saved period), apply the
  // user's preferred default_period once prefs arrive. The once-guard ensures a
  // mid-session period change is never clobbered.
  const appliedDefault = useRef(false)
  useEffect(() => {
    if (!prefsLoaded || appliedDefault.current) return
    appliedDefault.current = true
    if (localStorage.getItem(adapter.storageKey)) return
    const dp = prefs.default_period
    if (dp) setPeriod(dp)
  }, [prefsLoaded, prefs.default_period, adapter.storageKey])

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
