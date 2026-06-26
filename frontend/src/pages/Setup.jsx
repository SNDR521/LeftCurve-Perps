import { useState } from 'react'
import { setupAccount } from '../lib/api'

export default function Setup() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError(null)
    if (password.length < 8) { setError('Password must be at least 8 characters'); return }
    if (password !== confirm) { setError('Passwords do not match'); return }
    setBusy(true)
    try {
      await setupAccount({ email, password })
      window.location.href = '/'  // full reload so AuthProvider re-fetches /me
    } catch (err) {
      setError(err.message || 'Setup failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-neutral-950 text-neutral-100">
      <form onSubmit={submit} className="flex flex-col gap-4 w-full max-w-sm">
        <img src="/brand/logo-leftcurve.svg" alt="LeftCurve" className="h-12 mx-auto mb-2" />
        <p className="text-center text-sm text-neutral-400">Create your account to get started.</p>
        <input type="email" required placeholder="Email" value={email}
               onChange={(e) => setEmail(e.target.value)}
               className="w-full px-3 py-2 rounded bg-neutral-900 border border-neutral-700" />
        <input type="password" required placeholder="Password (min 8 characters)" value={password}
               onChange={(e) => setPassword(e.target.value)}
               className="w-full px-3 py-2 rounded bg-neutral-900 border border-neutral-700" />
        <input type="password" required placeholder="Confirm password" value={confirm}
               onChange={(e) => setConfirm(e.target.value)}
               className="w-full px-3 py-2 rounded bg-neutral-900 border border-neutral-700" />
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button type="submit" disabled={busy}
                className="w-full px-4 py-2 rounded bg-white text-black font-medium hover:bg-neutral-200 disabled:opacity-50">
          {busy ? 'Setting up…' : 'Create account'}
        </button>
      </form>
    </div>
  )
}
