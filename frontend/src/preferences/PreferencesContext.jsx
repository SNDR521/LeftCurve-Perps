import { createContext, useContext, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchPreferences, updatePreferences } from '../lib/api'

const DEFAULT_PREFS = {
  ticker_bar: {
    enabled: true,
    symbols: [
      { symbol: 'ES=F',    label: 'US500', source: 'yahoo' },
      { symbol: 'NQ=F',    label: 'US100', source: 'yahoo' },
      { symbol: 'BTCUSDT', label: 'BTC',   source: 'bybit' },
      { symbol: 'ETHUSDT', label: 'ETH',   source: 'bybit' },
      { symbol: 'SOLUSDT', label: 'SOL',   source: 'bybit' },
    ],
  },
  default_period: 'all',
  pnl_view: 'dollars',
  landing: { path: '/' },
  theme: { accent: '#38bdf8', density: 'comfortable' },
}

const PreferencesCtx = createContext({ prefs: DEFAULT_PREFS, updatePrefs: () => {}, prefsLoaded: false })

export function PreferencesProvider({ children }) {
  const qc = useQueryClient()
  const { data, isSuccess } = useQuery({
    queryKey: ['preferences'],
    queryFn: fetchPreferences,
    staleTime: 5 * 60_000,
    retry: false,
    placeholderData: DEFAULT_PREFS,
  })
  const prefs = data ?? DEFAULT_PREFS

  // Apply theme whenever prefs change
  useEffect(() => {
    const accent = prefs.theme?.accent || '#38bdf8'
    const density = prefs.theme?.density || 'comfortable'
    document.documentElement.style.setProperty('--accent', accent)
    document.documentElement.dataset.density = density
  }, [prefs.theme?.accent, prefs.theme?.density])

  async function updatePrefs(partial) {
    // Optimistic update
    qc.setQueryData(['preferences'], (old) => deepMerge(old ?? DEFAULT_PREFS, partial))
    try {
      const fresh = await updatePreferences(partial)
      qc.setQueryData(['preferences'], fresh)
    } catch {
      // Revert on error
      qc.invalidateQueries({ queryKey: ['preferences'] })
    }
  }

  return (
    <PreferencesCtx.Provider value={{ prefs, updatePrefs, prefsLoaded: isSuccess }}>
      {children}
    </PreferencesCtx.Provider>
  )
}

export function usePreferences() { return useContext(PreferencesCtx) }

// Shallow-deep merge: merges one level of nesting (enough for our prefs shape)
function deepMerge(base, partial) {
  const result = { ...base }
  for (const [k, v] of Object.entries(partial)) {
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
      result[k] = { ...(base[k] || {}), ...v }
    } else {
      result[k] = v
    }
  }
  return result
}
