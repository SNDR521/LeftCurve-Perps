import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  updateProfile, changePassword,
  telegramStatus, telegramLinkStart, telegramUnlink,
  telegramBotConfig, telegramActivateBot, telegramDeleteBot,
} from '../lib/api'
import { useAuth } from '../auth/AuthContext'
import {
  Database, Send,
} from 'lucide-react'

export default function Settings() {
  const { user, refresh } = useAuth()

  return (
    <div className="space-y-6 max-w-3xl">
      <h1 className="text-[22px] font-semibold text-white">Settings</h1>

      {/* ── Profile ───────────────────────────────────────────────── */}
      <ProfileSection user={user} refresh={refresh} />

      {/* ── Telegram ──────────────────────────────────────────────── */}
      <TelegramSection />

      {/* ── Database ─────────────────────────────────────────────── */}
      <section className="card p-5 space-y-3">
        <div className="flex items-center gap-2.5">
          <Database className="w-4.5 h-4.5 text-[#38bdf8]" />
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
        <Send className="w-4.5 h-4.5 text-[#38bdf8]" />
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
