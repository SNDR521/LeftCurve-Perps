import { useState, useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  updateProfile, changePassword,
  telegramStatus, telegramLinkStart, telegramUnlink,
  telegramBotConfig, telegramActivateBot, telegramDeleteBot,
  searchInstruments,
} from '../lib/api'
import { useAuth } from '../auth/AuthContext'
import { usePreferences } from '../preferences/PreferencesContext'
import {
  Database, Send, Monitor, ChevronUp, ChevronDown, X, Plus, Search,
} from 'lucide-react'

export default function Settings() {
  const { user, refresh } = useAuth()

  return (
    <div className="space-y-6 max-w-3xl">
      <h1 className="text-[22px] font-semibold text-white">Settings</h1>

      {/* ── Profile ───────────────────────────────────────────────── */}
      <ProfileSection user={user} refresh={refresh} />

      {/* ── Appearance ────────────────────────────────────────────── */}
      <AppearanceSection />

      {/* ── Telegram ──────────────────────────────────────────────── */}
      <TelegramSection />

      {/* ── Database ─────────────────────────────────────────────── */}
      <section className="card p-5 space-y-3">
        <div className="flex items-center gap-2.5">
          <Database className="w-4.5 h-4.5 text-[var(--accent)]" />
          <h2 className="text-[15px] font-semibold text-white">Data Storage</h2>
        </div>
        <p className="text-[13px] text-[#8d91a6]">
          Your data lives in this instance's database — SQLite by default (a local file), or Postgres if you set{' '}
          <code className="text-[#e2e4ef] bg-[#2a2c30] px-1.5 py-0.5 rounded text-[11px]">DATABASE_URL</code>.
          It stays on the machine where you run LeftCurve.
        </p>
      </section>
    </div>
  )
}


// ── Appearance Section ─────────────────────────────────────────────────────

const PERIODS_LIST = [
  { key: 'today', label: 'Daily' },
  { key: 'week', label: 'Weekly' },
  { key: 'month', label: 'Monthly' },
  { key: 'year', label: 'Yearly' },
  { key: 'all', label: 'Overall' },
]

const PAGE_OPTIONS = [
  { value: '/', label: 'Dashboard' },
  { value: '/cockpit', label: 'Cockpit' },
  { value: '/trades', label: 'Trade Log' },
  { value: '/reports', label: 'Analytics' },
  { value: '/calendar', label: 'Calendar' },
  { value: '/plan', label: 'Daily Plan' },
]

const ACCENT_SWATCHES = [
  { hex: '#38bdf8', label: 'Sky (default)' },
  { hex: '#00d4aa', label: 'Emerald' },
  { hex: '#8b5cf6', label: 'Violet' },
  { hex: '#f59e0b', label: 'Amber' },
  { hex: '#f43f5e', label: 'Rose' },
]

function AppearanceSection() {
  const { prefs, updatePrefs } = usePreferences()
  const tickerBar = prefs.ticker_bar ?? { enabled: true, symbols: [] }
  const accent = prefs.theme?.accent || '#38bdf8'
  const density = prefs.theme?.density || 'comfortable'
  const [hexInput, setHexInput] = useState(accent)
  const accentTimer = useRef(null)

  // Keep the hex field in sync when accent changes from a swatch click.
  useEffect(() => { setHexInput(accent) }, [accent])

  // Clear any pending debounced accent write on unmount.
  useEffect(() => () => clearTimeout(accentTimer.current), [])

  function setAccent(hex) {
    updatePrefs({ theme: { ...prefs.theme, accent: hex } })
  }
  function setDensity(d) {
    updatePrefs({ theme: { ...prefs.theme, density: d } })
  }
  // Debounced so typing/dragging a hex value doesn't spam PUT /api/preferences.
  function handleHexInput(e) {
    const val = e.target.value
    setHexInput(val)
    clearTimeout(accentTimer.current)
    if (/^#[0-9a-fA-F]{6}$/.test(val)) {
      accentTimer.current = setTimeout(() => setAccent(val), 300)
    }
  }
  // Commit immediately on blur in case the debounce hasn't fired yet.
  function commitHex() {
    clearTimeout(accentTimer.current)
    if (/^#[0-9a-fA-F]{6}$/.test(hexInput) && hexInput !== accent) setAccent(hexInput)
  }
  const [searchQ, setSearchQ] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searching, setSearching] = useState(false)
  const searchRef = useRef(null)
  const timerRef = useRef(null)

  // Debounced instrument search
  useEffect(() => {
    if (!searchQ.trim()) { setSearchResults([]); return }
    timerRef.current = setTimeout(async () => {
      setSearching(true)
      try {
        const res = await searchInstruments(searchQ)
        setSearchResults(res || [])
      } catch { setSearchResults([]) }
      finally { setSearching(false) }
    }, 250)
    return () => clearTimeout(timerRef.current)
  }, [searchQ])

  // Ensure the pending debounce timer is cleared on unmount.
  useEffect(() => () => clearTimeout(timerRef.current), [])

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

  return (
    <section className="card p-5 space-y-5">
      <div className="flex items-center gap-2.5">
        <Monitor className="w-4 h-4 text-[var(--accent)]" />
        <h2 className="text-[15px] font-semibold text-white">Appearance</h2>
      </div>

      {/* Accent color */}
      <div className="space-y-2">
        <p className="text-[13px] text-[#e2e4ef]">Accent color</p>
        <p className="text-[11px] text-[#4e5166]">Recolors buttons, links, and active states</p>
        <div className="flex items-center gap-2 flex-wrap">
          {ACCENT_SWATCHES.map(s => (
            <button
              key={s.hex}
              title={s.label}
              onClick={() => setAccent(s.hex)}
              className="w-7 h-7 rounded-full transition-all focus:outline-none"
              style={{
                background: s.hex,
                boxShadow: accent === s.hex ? `0 0 0 2px #111213, 0 0 0 4px ${s.hex}` : 'none',
                transform: accent === s.hex ? 'scale(1.15)' : 'scale(1)',
              }}
              aria-pressed={accent === s.hex}
            />
          ))}
          <input
            type="text"
            value={hexInput}
            onChange={handleHexInput}
            onBlur={commitHex}
            placeholder="#rrggbb"
            maxLength={7}
            className="input text-[12px] py-1 px-2 w-24 font-mono"
          />
        </div>
      </div>

      {/* Layout density */}
      <div className="border-t border-[#2a2c30] pt-4 space-y-2">
        <p className="text-[13px] text-[#e2e4ef]">Layout density</p>
        <p className="text-[11px] text-[#4e5166]">Compact reduces card and table row padding</p>
        <div className="flex gap-1.5">
          {['comfortable', 'compact'].map(d => (
            <button
              key={d}
              onClick={() => setDensity(d)}
              className={`px-4 py-1.5 rounded-md text-[12px] font-medium transition-all capitalize ${
                density === d
                  ? 'bg-[var(--accent)] text-white'
                  : 'bg-[#2a2c30] text-[#8d91a6] hover:text-[#e2e4ef]'
              }`}
            >
              {d}
            </button>
          ))}
        </div>
      </div>

      {/* Market Ticker Toggle */}
      <div className="border-t border-[#2a2c30] pt-4 flex items-center justify-between gap-4">
        <div>
          <p className="text-[13px] text-[#e2e4ef]">Show market ticker bar</p>
          <p className="text-[11px] text-[#4e5166] mt-0.5">Live prices in the top bar</p>
        </div>
        <button
          onClick={() => toggleEnabled(!tickerBar.enabled)}
          className={`relative inline-flex rounded-full transition-colors focus:outline-none ${
            tickerBar.enabled ? 'bg-[var(--accent)]' : 'bg-[#2a2c30]'
          }`}
          style={{ minWidth: '2.5rem', width: '2.5rem', height: '1.375rem' }}
          aria-checked={tickerBar.enabled}
          role="switch"
        >
          <span
            className={`absolute top-0.5 left-0.5 bg-white rounded-full shadow transition-transform ${
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
              <div key={s.symbol} className="flex items-center gap-2">
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
                    : 'bg-[rgb(var(--accent-rgb)/0.1)] text-[var(--accent)] border border-[rgb(var(--accent-rgb)/0.2)]'
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
                        : 'bg-[rgb(var(--accent-rgb)/0.1)] text-[var(--accent)] border border-[rgb(var(--accent-rgb)/0.2)]'
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
                  ? 'bg-[var(--accent)] text-white'
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
          value={prefs.landing?.path || '/'}
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


// ── Telegram Section ───────────────────────────────────────────────────────

function TelegramSection() {
  const qc = useQueryClient()
  const [linking, setLinking] = useState(false)
  const [linkHint, setLinkHint] = useState(null)
  const [actionErr, setActionErr] = useState(null)

  // Bot activation state
  const [botToken, setBotToken] = useState('')
  const [botMsg, setBotMsg] = useState(null)
  const [botErr, setBotErr] = useState(null)
  const [botPending, setBotPending] = useState(false)

  const { data: status, isLoading } = useQuery({
    queryKey: ['telegram-status'],
    queryFn: telegramStatus,
    refetchInterval: (query) => (query.state.data?.linked ? false : 3000),
  })

  const { data: botCfg } = useQuery({
    queryKey: ['telegram-bot-config'],
    queryFn: telegramBotConfig,
  })

  async function handleConnect() {
    setLinking(true)
    setLinkHint(null)
    setActionErr(null)
    try {
      const { url } = await telegramLinkStart()
      window.open(url, '_blank')
      setLinkHint('Open Telegram and press Start. This link expires in 15 minutes.')
    } catch (e) {
      setActionErr(e.message)
    } finally {
      setLinking(false)
    }
  }

  async function handleDisconnect() {
    setActionErr(null)
    try {
      await telegramUnlink()
      qc.invalidateQueries({ queryKey: ['telegram-status'] })
      setLinkHint(null)
    } catch (e) {
      setActionErr(e.message)
    }
  }

  async function handleActivateBot() {
    setBotMsg(null)
    setBotErr(null)
    setBotPending(true)
    try {
      const res = await telegramActivateBot(botToken.trim(), window.location.origin)
      qc.invalidateQueries({ queryKey: ['telegram-bot-config'] })
      qc.invalidateQueries({ queryKey: ['telegram-status'] })
      setBotToken('')
      if (res.webhook_set === false) {
        setBotErr(`Token saved, but webhook registration failed: ${res.error || 'unknown'} — check the URL and retry.`)
      } else {
        setBotMsg(`✓ Active: @${res.username}`)
      }
    } catch (e) {
      setBotErr(e.message || 'Activation failed')
    } finally {
      setBotPending(false)
    }
  }

  async function handleDeleteBot() {
    setBotMsg(null)
    setBotErr(null)
    try {
      await telegramDeleteBot()
      qc.invalidateQueries({ queryKey: ['telegram-bot-config'] })
      qc.invalidateQueries({ queryKey: ['telegram-status'] })
    } catch (e) {
      setBotErr(e.message || 'Failed to disconnect bot')
    }
  }

  const botReady = status?.bot_username != null

  return (
    <section className="card p-5 space-y-4">
      <div className="flex items-center gap-2.5">
        <Send className="w-4.5 h-4.5 text-[var(--accent)]" />
        <h2 className="text-[15px] font-semibold text-white">Telegram</h2>
      </div>

      {/* ── LeftCurve bot activation ─────────────────────────────── */}
      <div className="border border-[#2a2c30] rounded-lg p-4 space-y-3 bg-[#15171a]">
        <p className="text-[12px] font-semibold text-[#8d91a6] uppercase tracking-wide">LeftCurve Telegram bot</p>

        {botCfg?.configured ? (
          <div className="space-y-2">
            <p className="text-[13px] text-[#00d4aa]">
              ✓ @{botCfg.username} active
            </p>
            {botCfg.webhook_set_at && (
              <p className="text-[11px] text-[#4e5166]">webhook registered</p>
            )}
            <button
              onClick={handleDeleteBot}
              className="btn-ghost text-[12px] text-[#de576f] hover:text-[#de576f]"
            >
              Disconnect bot
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="flex gap-2">
              <input
                type="password"
                value={botToken}
                onChange={(e) => setBotToken(e.target.value)}
                placeholder="BotFather token"
                className="input flex-1 text-[13px]"
              />
              <button
                onClick={handleActivateBot}
                disabled={botPending || !botToken.trim()}
                className="btn-blue text-[12px] px-3 disabled:opacity-40"
              >
                {botPending ? 'Activating…' : 'Activate'}
              </button>
            </div>
            <p className="text-[11px] text-[#4e5166]">
              Create a bot with @BotFather, paste its token, and Activate. Then connect below — no server setup.
            </p>
          </div>
        )}

        {botErr && <p className="text-[12px] text-[#de576f]">{botErr}</p>}
        {botMsg && <p className="text-[12px] text-[#00d4aa]">{botMsg}</p>}
      </div>

      {/* ── Per-user connect ─────────────────────────────────────────── */}
      {isLoading ? (
        <p className="text-[13px] text-[#4e5166]">Loading…</p>
      ) : !botReady ? (
        <div className="space-y-3">
          <button disabled className="btn-blue text-[13px] opacity-40 cursor-not-allowed">
            Connect Telegram
          </button>
        </div>
      ) : status?.linked ? (
        <div className="space-y-2">
          <p className="text-[13px] text-[#00d4aa]">
            ✅ Connected{status.username ? ` — @${status.username}` : ''}
          </p>
          <button
            onClick={handleDisconnect}
            className="btn-ghost text-[13px] text-[#de576f] hover:text-[#de576f]"
          >
            Disconnect
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <button
            onClick={handleConnect}
            disabled={linking}
            className="btn-blue text-[13px] disabled:opacity-50"
          >
            {linking ? 'Opening…' : 'Connect Telegram'}
          </button>
          {linkHint && (
            <p className="text-[12px] text-[#8d91a6]">{linkHint}</p>
          )}
        </div>
      )}

      {actionErr && <p className="text-[12px] text-[#de576f]">{actionErr}</p>}
    </section>
  )
}


// ── Profile Section ────────────────────────────────────────────────────────

function ProfileSection({ user, refresh }) {
  const [name, setName] = useState(user?.name || '')
  const [savingName, setSavingName] = useState(false)
  const [nameMsg, setNameMsg] = useState(null)
  const [cur, setCur] = useState(''); const [nw, setNw] = useState(''); const [confirm, setConfirm] = useState('')
  const [pwMsg, setPwMsg] = useState(null); const [pwErr, setPwErr] = useState(null); const [savingPw, setSavingPw] = useState(false)

  async function saveName() {
    setSavingName(true); setNameMsg(null)
    try { await updateProfile({ name }); await refresh?.(); setNameMsg('Saved') }
    catch (e) { setNameMsg(e.message) } finally { setSavingName(false) }
  }
  async function savePw() {
    setPwErr(null); setPwMsg(null)
    if (nw.length < 8) { setPwErr('New password must be at least 8 characters'); return }
    if (nw !== confirm) { setPwErr('New passwords do not match'); return }
    setSavingPw(true)
    try { await changePassword({ current_password: cur, new_password: nw }); setPwMsg('Password changed'); setCur(''); setNw(''); setConfirm('') }
    catch (e) { setPwErr(e.message) } finally { setSavingPw(false) }
  }

  return (
    <section className="card p-5 space-y-4">
      <h2 className="text-[15px] font-semibold text-white">Profile</h2>
      <div className="space-y-1.5">
        <label className="text-[11px] text-[#8d91a6]">Display name</label>
        <div className="flex gap-2">
          <input className="input flex-1" value={name} onChange={e => setName(e.target.value)} placeholder={user?.email} />
          <button onClick={saveName} disabled={savingName} className="btn-blue text-[12px] px-3 disabled:opacity-50">Save</button>
        </div>
        {nameMsg && <p className="text-[11px] text-[#8d91a6]">{nameMsg}</p>}
      </div>
      <div className="border-t border-[#2a2c30] pt-4 space-y-2">
        <label className="text-[11px] text-[#8d91a6]">Change password</label>
        <input type="password" className="input w-full" placeholder="Current password" value={cur} onChange={e => setCur(e.target.value)} />
        <input type="password" className="input w-full" placeholder="New password (min 8)" value={nw} onChange={e => setNw(e.target.value)} />
        <input type="password" className="input w-full" placeholder="Confirm new password" value={confirm} onChange={e => setConfirm(e.target.value)} />
        <button onClick={savePw} disabled={savingPw} className="btn-blue text-[12px] px-3 disabled:opacity-50">Change password</button>
        {pwErr && <p className="text-[11px] text-[#de576f]">{pwErr}</p>}
        {pwMsg && <p className="text-[11px] text-[#00d4aa]">{pwMsg}</p>}
      </div>
    </section>
  )
}
