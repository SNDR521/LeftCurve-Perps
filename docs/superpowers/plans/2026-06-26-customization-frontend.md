# Customization Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire preferences context (load/save via backend API), apply theme CSS vars + density on the document root, make GlobalTickerBar data-driven from prefs, and add an Appearance section to Settings with ticker band editor, default period, and landing page controls.

**Architecture:** A new `PreferencesContext` (TanStack Query) is the single source of truth for user prefs. It is mounted inside `RequireAuth` in `App.jsx` wrapping `<Layout/>`. GlobalTickerBar becomes fully data-driven. Settings gains an Appearance card. The `loadPeriod` seed falls back to `prefs.default_period` when localStorage is empty. The landing redirect lives in a tiny `LandingRedirect` route component inside `App.jsx`.

**Tech Stack:** React 18, TanStack Query v5, react-router-dom v6, Tailwind CSS + custom CSS vars, Vite build.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `frontend/src/lib/api.js` | Add `fetchPreferences`, `updatePreferences`, `searchInstruments` |
| Create | `frontend/src/preferences/PreferencesContext.jsx` | TanStack Query provider + `usePreferences()` hook |
| Modify | `frontend/src/index.css` | Add `--accent` root var + density rules |
| Modify | `frontend/src/App.jsx` | Mount `PreferencesProvider`, add `LandingRedirect` |
| Modify | `frontend/src/components/GlobalTickerBar.jsx` | Drive entirely from `usePreferences` |
| Modify | `frontend/src/pages/Settings.jsx` | Add `AppearanceSection` component |
| Modify | `frontend/src/dashboard/period.js` | `loadPeriod` falls back to arg `defaultPeriod` (already does — verify) |
| Modify | `frontend/src/pages/PerpsDashboard.jsx` | Pass `prefs.default_period` as fallback to `loadPeriod` |
| Modify | `frontend/src/analytics/AnalyticsShell.jsx` | Same for analytics period seed |

---

### Task 1: api.js — add preferences + market search helpers

**Files:**
- Modify: `frontend/src/lib/api.js`

- [ ] **Step 1: Add three new exported functions at the end of api.js**

Append after the alarms section:

```js
// ── Preferences ────────────────────────────────────────────────────────────

async function prefsRequest(path, options = {}) {
  const res = await fetch(`/api/preferences${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    credentials: 'include',
    ...options,
  })
  if (res.status === 401) { window.location.href = '/login'; throw new Error('Not authenticated') }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

export function fetchPreferences() { return prefsRequest('') }
export function updatePreferences(partial) {
  return prefsRequest('', { method: 'PUT', body: JSON.stringify(partial) })
}
export function searchInstruments(q) {
  return marketDataRequest(`/search?q=${encodeURIComponent(q)}`)
}
```

- [ ] **Step 2: Verify build succeeds with no errors**

```
cd C:\TradeEdge\leftcurve-perps\frontend && npm run build
```

Expected: exits 0, no "is not exported" errors for the new names.

- [ ] **Step 3: Commit**

```
git -C C:\TradeEdge\leftcurve-perps add frontend/src/lib/api.js
git -C C:\TradeEdge\leftcurve-perps commit -m "feat(api): add fetchPreferences, updatePreferences, searchInstruments helpers"
```

---

### Task 2: PreferencesContext.jsx — TanStack Query provider

**Files:**
- Create: `frontend/src/preferences/PreferencesContext.jsx`

- [ ] **Step 1: Create the file**

```jsx
import { createContext, useContext, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchPreferences, updatePreferences } from '../lib/api'

const DEFAULT_PREFS = {
  ticker_bar: {
    enabled: true,
    symbols: [
      { symbol: 'ES=F',   label: 'US500',  source: 'yahoo' },
      { symbol: 'NQ=F',   label: 'US100',  source: 'yahoo' },
      { symbol: 'BTCUSDT',label: 'BTC',    source: 'bybit' },
      { symbol: 'ETHUSDT',label: 'ETH',    source: 'bybit' },
      { symbol: 'SOLUSDT',label: 'SOL',    source: 'bybit' },
    ],
  },
  default_period: 'all',
  pnl_view: 'dollars',
  landing: { path: '/' },
  theme: { accent: '#38bdf8', density: 'comfortable' },
}

const PreferencesCtx = createContext({ prefs: DEFAULT_PREFS, updatePrefs: () => {} })

export function PreferencesProvider({ children }) {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['preferences'],
    queryFn: fetchPreferences,
    staleTime: 5 * 60_000,
    // Don't throw on error — fall back to defaults
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
    <PreferencesCtx.Provider value={{ prefs, updatePrefs }}>
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
```

- [ ] **Step 2: Mount PreferencesProvider in App.jsx**

In `App.jsx`, import `PreferencesProvider` and wrap the `<Layout />` inside `RequireAuth`:

Change:
```jsx
<Route element={<RequireAuth><Layout /></RequireAuth>}>
```
To:
```jsx
<Route element={<RequireAuth><PreferencesProvider><Layout /></PreferencesProvider></RequireAuth>}>
```

Also add the import at the top:
```jsx
import { PreferencesProvider } from './preferences/PreferencesContext'
```

- [ ] **Step 3: Add LandingRedirect route**

In `App.jsx`, import `usePreferences` and add a `LandingRedirect` component above `App`:

```jsx
import { usePreferences } from './preferences/PreferencesContext'

function LandingRedirect() {
  const { prefs } = usePreferences()
  const target = prefs?.landing?.path || '/'
  // Only redirect from exactly '/' — deep links pass through unchanged
  return <Navigate to={target} replace />
}
```

Then change the root route from:
```jsx
<Route path="/" element={<PerpsDashboard />} />
```
To:
```jsx
<Route path="/" element={<LandingRedirect />} />
<Route path="/dashboard" element={<PerpsDashboard />} />
```

And update `navItems` in `Layout.jsx` to point Dashboard to `/dashboard` instead of `/`:
```js
{ to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
```

**IMPORTANT:** The `LandingRedirect` must only fire when the user is at exactly `/`. All other routes keep working because `LandingRedirect` only renders at `path="/"`.

- [ ] **Step 4: Build check**

```
cd C:\TradeEdge\leftcurve-perps\frontend && npm run build
```

Expected: exits 0.

- [ ] **Step 5: Commit**

```
git -C C:\TradeEdge\leftcurve-perps add frontend/src/preferences/PreferencesContext.jsx frontend/src/App.jsx frontend/src/components/Layout.jsx
git -C C:\TradeEdge\leftcurve-perps commit -m "feat(preferences): add PreferencesContext provider + landing redirect"
```

---

### Task 3: index.css — add --accent var + density rules

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Add --accent to :root and density rules**

At the very top of `@layer base` block, before the scrollbar rules, insert:

```css
  :root {
    --accent: #38bdf8;
  }
```

After the `.card` definition in `@layer components`, add:

```css
  /* ── Density ──────────────────────────────── */
  :root[data-density="compact"] .card { padding: 12px !important; }
  :root[data-density="compact"] .rows-table tbody tr td { padding: 6px 10px; }
  :root[data-density="compact"] .rows-table thead th { padding: 2px 10px 6px; }
```

- [ ] **Step 2: Build check**

```
cd C:\TradeEdge\leftcurve-perps\frontend && npm run build
```

- [ ] **Step 3: Commit**

```
git -C C:\TradeEdge\leftcurve-perps add frontend/src/index.css
git -C C:\TradeEdge\leftcurve-perps commit -m "feat(css): add --accent root var + compact density rules"
```

---

### Task 4: GlobalTickerBar — driven by usePreferences

**Files:**
- Modify: `frontend/src/components/GlobalTickerBar.jsx`

- [ ] **Step 1: Rewrite GlobalTickerBar**

Replace the entire file with:

```jsx
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

  const hasAny = restData.length > 0 || Object.keys(live).length > 0
  if (!hasAny && tickerBar.symbols.length === 0) return null

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
```

- [ ] **Step 2: Build check**

```
cd C:\TradeEdge\leftcurve-perps\frontend && npm run build
```

Expected: exits 0. Grep confirms no LABELS/CRYPTO constants remain:
```
grep -n "LABELS\|const CRYPTO" frontend/src/components/GlobalTickerBar.jsx
```
Expected: no matches.

- [ ] **Step 3: Commit**

```
git -C C:\TradeEdge\leftcurve-perps add frontend/src/components/GlobalTickerBar.jsx
git -C C:\TradeEdge\leftcurve-perps commit -m "feat(ticker): drive GlobalTickerBar from usePreferences, remove hardcoded LABELS/CRYPTO"
```

---

### Task 5: period.js seed — use prefs.default_period when localStorage empty

**Files:**
- Modify: `frontend/src/pages/PerpsDashboard.jsx`
- Modify: `frontend/src/analytics/AnalyticsShell.jsx`

The `loadPeriod(storageKey, defaultPeriod)` function in `period.js` already accepts a `defaultPeriod` argument and uses it as the fallback when localStorage is empty (`return { period: defaultPeriod, ... }`). No change needed to `period.js`.

We just need the callers to pass `prefs.default_period` instead of the hardcoded `'all'`.

- [ ] **Step 1: Update PerpsDashboard.jsx**

Import `usePreferences`:
```jsx
import { usePreferences } from '../preferences/PreferencesContext'
```

Inside `PerpsDashboard`, read `prefs` before the `useState`:
```jsx
const { prefs } = usePreferences()
const [periodState, setPeriodState] = useState(() => loadPeriod('leftcurve_perps_period', prefs.default_period || 'all'))
```

Replace the existing `useState` init line:
```jsx
// OLD:
const [periodState, setPeriodState] = useState(() => loadPeriod('leftcurve_perps_period', 'all'))
// NEW: (useState initializer captures prefs.default_period at mount; that's correct — prefs is the placeholder value synchronously)
const { prefs } = usePreferences()
const [periodState, setPeriodState] = useState(() => loadPeriod('leftcurve_perps_period', prefs.default_period || 'all'))
```

- [ ] **Step 2: Update AnalyticsShell.jsx**

Import `usePreferences`:
```jsx
import { usePreferences } from '../preferences/PreferencesContext'
```

Inside `AnalyticsShell`, add before `useMemo`:
```jsx
const { prefs } = usePreferences()
const init = useMemo(() => loadPeriod(adapter.storageKey, prefs.default_period || 'all'), [adapter.storageKey, prefs.default_period])
```

Replace the existing `useMemo` line:
```jsx
// OLD:
const init = useMemo(() => loadPeriod(adapter.storageKey, 'all'), [adapter.storageKey])
// NEW:
const { prefs } = usePreferences()
const init = useMemo(() => loadPeriod(adapter.storageKey, prefs.default_period || 'all'), [adapter.storageKey, prefs.default_period])
```

- [ ] **Step 3: Build check**

```
cd C:\TradeEdge\leftcurve-perps\frontend && npm run build
```

- [ ] **Step 4: Commit**

```
git -C C:\TradeEdge\leftcurve-perps add frontend/src/pages/PerpsDashboard.jsx frontend/src/analytics/AnalyticsShell.jsx
git -C C:\TradeEdge\leftcurve-perps commit -m "feat(period): seed default period from prefs.default_period when localStorage is empty"
```

---

### Task 6: Settings.jsx — add AppearanceSection

**Files:**
- Modify: `frontend/src/pages/Settings.jsx`

- [ ] **Step 1: Add imports and AppearanceSection to Settings**

At the top of `Settings.jsx`, add imports:
```jsx
import { usePreferences } from '../preferences/PreferencesContext'
import { searchInstruments } from '../lib/api'
import { Monitor, ChevronUp, ChevronDown, X, Plus, Search } from 'lucide-react'
```

Add to the `Settings` default export component, before the Telegram section:
```jsx
{/* ── Appearance ────────────────────────────────────────────── */}
<AppearanceSection />
```

Then add the `AppearanceSection` component (and sub-components) after the existing `ProfileSection`:

```jsx
// ── Appearance Section ─────────────────────────────────────────────────────

function AppearanceSection() {
  const { prefs, updatePrefs } = usePreferences()
  const tickerBar = prefs.ticker_bar ?? { enabled: true, symbols: [] }
  const [searchQ, setSearchQ] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searching, setSearching] = useState(false)
  const searchRef = useRef(null)

  // Debounced instrument search
  useEffect(() => {
    if (!searchQ.trim()) { setSearchResults([]); return }
    const tid = setTimeout(async () => {
      setSearching(true)
      try {
        const res = await searchInstruments(searchQ)
        setSearchResults(res || [])
      } catch { setSearchResults([]) }
      finally { setSearching(false) }
    }, 250)
    return () => clearTimeout(tid)
  }, [searchQ])

  function toggleEnabled(enabled) {
    updatePrefs({ ticker_bar: { ...tickerBar, enabled } })
  }

  function moveSymbol(idx, dir) {
    const syms = [...tickerBar.symbols]
    const target = idx + dir
    if (target < 0 || target >= syms.length) return
    ;[syms[idx], syms[target]] = [syms[target], syms[idx]]
    updatePrefs({ ticker_bar: { ...tickerBar, symbols: syms } })
  }

  function removeSymbol(idx) {
    const syms = tickerBar.symbols.filter((_, i) => i !== idx)
    updatePrefs({ ticker_bar: { ...tickerBar, symbols: syms } })
  }

  function updateLabel(idx, label) {
    const syms = tickerBar.symbols.map((s, i) => i === idx ? { ...s, label } : s)
    updatePrefs({ ticker_bar: { ...tickerBar, symbols: syms } })
  }

  function addSymbol(sym) {
    if (!sym?.symbol) return
    if (tickerBar.symbols.some(s => s.symbol === sym.symbol)) return
    const syms = [...tickerBar.symbols, { symbol: sym.symbol, label: sym.label || sym.symbol, source: sym.source || 'yahoo' }]
    updatePrefs({ ticker_bar: { ...tickerBar, symbols: syms } })
    setSearchQ('')
    setSearchResults([])
  }

  function addFreeText() {
    const raw = searchQ.trim().toUpperCase()
    if (!raw) return
    const source = /USDT$/i.test(raw) ? 'bybit' : 'yahoo'
    addSymbol({ symbol: raw, label: raw, source })
  }

  const PERIODS_LIST = [
    { key: 'today', label: 'Daily' },
    { key: 'week', label: 'Weekly' },
    { key: 'month', label: 'Monthly' },
    { key: 'year', label: 'Yearly' },
    { key: 'all', label: 'Overall' },
  ]

  const PAGE_OPTIONS = [
    { value: '/dashboard', label: 'Dashboard' },
    { value: '/cockpit', label: 'Cockpit' },
    { value: '/trades', label: 'Trade Log' },
    { value: '/reports', label: 'Analytics' },
    { value: '/calendar', label: 'Calendar' },
    { value: '/plan', label: 'Daily Plan' },
  ]

  return (
    <section className="card p-5 space-y-5">
      <div className="flex items-center gap-2.5">
        <Monitor className="w-4 h-4 text-[#38bdf8]" />
        <h2 className="text-[15px] font-semibold text-white">Appearance</h2>
      </div>

      {/* Market Ticker Toggle */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-[13px] text-[#e2e4ef]">Show market ticker bar</p>
          <p className="text-[11px] text-[#4e5166] mt-0.5">Live prices in the top bar</p>
        </div>
        <button
          onClick={() => toggleEnabled(!tickerBar.enabled)}
          className={`relative inline-flex w-10 h-5.5 rounded-full transition-colors focus:outline-none ${
            tickerBar.enabled ? 'bg-[#38bdf8]' : 'bg-[#2a2c30]'
          }`}
          style={{ minWidth: '2.5rem', height: '1.375rem' }}
          aria-checked={tickerBar.enabled}
          role="switch"
        >
          <span
            className={`absolute top-0.5 left-0.5 w-4.5 h-4.5 bg-white rounded-full shadow transition-transform ${
              tickerBar.enabled ? 'translate-x-[1.125rem]' : 'translate-x-0'
            }`}
            style={{ width: '1.125rem', height: '1.125rem' }}
          />
        </button>
      </div>

      {/* Symbol editor — only when enabled */}
      {tickerBar.enabled && (
        <div className="space-y-3 border-t border-[#2a2c30] pt-4">
          <p className="text-[12px] font-semibold text-[#8d91a6] uppercase tracking-wide">Ticker symbols</p>

          {/* Symbols list */}
          <div className="space-y-1.5">
            {tickerBar.symbols.map((s, i) => (
              <div key={s.symbol} className="flex items-center gap-2 group">
                {/* Reorder */}
                <div className="flex flex-col gap-0">
                  <button onClick={() => moveSymbol(i, -1)} disabled={i === 0}
                    className="text-[#4e5166] hover:text-[#8d91a6] disabled:opacity-20 leading-none">
                    <ChevronUp className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={() => moveSymbol(i, 1)} disabled={i === tickerBar.symbols.length - 1}
                    className="text-[#4e5166] hover:text-[#8d91a6] disabled:opacity-20 leading-none">
                    <ChevronDown className="w-3.5 h-3.5" />
                  </button>
                </div>
                {/* Symbol id */}
                <span className="font-mono text-[11px] text-[#4e5166] w-20 shrink-0 truncate">{s.symbol}</span>
                {/* Editable label */}
                <input
                  value={s.label}
                  onChange={e => updateLabel(i, e.target.value)}
                  className="input text-[12px] py-1 px-2 flex-1 min-w-0"
                />
                {/* Source badge */}
                <span className={`badge text-[10px] shrink-0 ${
                  s.source === 'bybit'
                    ? 'bg-[#f7931a]/10 text-[#f7931a] border border-[#f7931a]/20'
                    : 'bg-[#38bdf8]/10 text-[#38bdf8] border border-[#38bdf8]/20'
                }`}>
                  {s.source}
                </span>
                {/* Remove */}
                <button onClick={() => removeSymbol(i)}
                  className="text-[#4e5166] hover:text-[#de576f] shrink-0">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>

          {/* Add symbol search */}
          <div className="relative" ref={searchRef}>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#4e5166] pointer-events-none" />
                <input
                  value={searchQ}
                  onChange={e => setSearchQ(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') addFreeText() }}
                  placeholder="Search or type symbol + Enter"
                  className="input text-[12px] py-1.5 pl-8 w-full"
                />
              </div>
              <button onClick={addFreeText} disabled={!searchQ.trim()}
                className="btn-blue text-[12px] px-3 py-1.5 disabled:opacity-40 flex items-center gap-1">
                <Plus className="w-3.5 h-3.5" /> Add
              </button>
            </div>

            {/* Dropdown results */}
            {searchResults.length > 0 && (
              <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-[#1e2024] border border-[#2a2c30] rounded-lg shadow-xl overflow-hidden max-h-48 overflow-y-auto">
                {searching && <p className="px-3 py-2 text-[12px] text-[#4e5166]">Searching…</p>}
                {searchResults.map(r => (
                  <button
                    key={r.symbol}
                    onClick={() => addSymbol(r)}
                    className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-[#2a2c30] transition-colors"
                  >
                    <span className="font-mono text-[11px] text-[#4e5166] w-20 shrink-0 truncate">{r.symbol}</span>
                    <span className="text-[12px] text-[#e2e4ef] flex-1 truncate">{r.label}</span>
                    <span className={`badge text-[10px] shrink-0 ${
                      r.source === 'bybit'
                        ? 'bg-[#f7931a]/10 text-[#f7931a] border border-[#f7931a]/20'
                        : 'bg-[#38bdf8]/10 text-[#38bdf8] border border-[#38bdf8]/20'
                    }`}>{r.source}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Default dashboard timeframe */}
      <div className="border-t border-[#2a2c30] pt-4 space-y-2">
        <p className="text-[13px] text-[#e2e4ef]">Default dashboard timeframe</p>
        <p className="text-[11px] text-[#4e5166]">Used when no period is saved in browser storage</p>
        <div className="flex gap-1 flex-wrap">
          {PERIODS_LIST.map(p => (
            <button
              key={p.key}
              onClick={() => updatePrefs({ default_period: p.key })}
              className={`px-3 py-1.5 rounded-md text-[12px] font-medium transition-all ${
                prefs.default_period === p.key
                  ? 'bg-[#38bdf8] text-white'
                  : 'bg-[#2a2c30] text-[#8d91a6] hover:text-[#e2e4ef]'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Default landing page */}
      <div className="border-t border-[#2a2c30] pt-4 space-y-2">
        <p className="text-[13px] text-[#e2e4ef]">Default landing page</p>
        <p className="text-[11px] text-[#4e5166]">Where to land after login (deep links always work)</p>
        <select
          value={prefs.landing?.path || '/dashboard'}
          onChange={e => updatePrefs({ landing: { path: e.target.value } })}
          className="input text-[12px] py-1.5"
        >
          {PAGE_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>
    </section>
  )
}
```

Note: `useRef` must be imported. Add it to the existing React import or the `useState` import at the top of the file.

- [ ] **Step 2: Add missing imports to Settings.jsx**

The file uses `useState` already. Add `useRef` and `useEffect` to the React imports, and the new named imports from api and lucide-react.

- [ ] **Step 3: Build check**

```
cd C:\TradeEdge\leftcurve-perps\frontend && npm run build
```

- [ ] **Step 4: Commit**

```
git -C C:\TradeEdge\leftcurve-perps add frontend/src/pages/Settings.jsx
git -C C:\TradeEdge\leftcurve-perps commit -m "feat(settings): add Appearance section with ticker editor, default period, landing page"
```

---

### Task 7: Final verification + single commit

- [ ] **Step 1: Clean build**

```
cd C:\TradeEdge\leftcurve-perps\frontend && npm run build
```

Expected: exits 0.

- [ ] **Step 2: Grep checks**

```powershell
# usePreferences used in GlobalTickerBar + Settings + PerpsDashboard + AnalyticsShell
Select-String -Path "C:\TradeEdge\leftcurve-perps\frontend\src\**\*.jsx" -Pattern "usePreferences" -Recurse
```

Expected: matches in GlobalTickerBar.jsx, Settings.jsx, PerpsDashboard.jsx, AnalyticsShell.jsx, PreferencesContext.jsx.

```powershell
# No hardcoded LABELS or CRYPTO constants in GlobalTickerBar
Select-String -Path "C:\TradeEdge\leftcurve-perps\frontend\src\components\GlobalTickerBar.jsx" -Pattern "const LABELS|const CRYPTO"
```

Expected: no matches.

- [ ] **Step 3: Squash commit (master)**

All prior task commits are already on master. If you prefer one final commit:

```
git -C C:\TradeEdge\leftcurve-perps add -A
git -C C:\TradeEdge\leftcurve-perps commit -m "feat(customization): preferences context + customizable ticker band + appearance settings (frontend)"
```
