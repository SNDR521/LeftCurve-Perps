import { useState, useEffect } from 'react'
import { login, needsSetup } from '../lib/api'
import Setup from './Setup'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [setupCheck, setSetupCheck] = useState(null) // null=loading, true/false

  useEffect(() => {
    needsSetup().then(({ needs_setup }) => setSetupCheck(needs_setup)).catch(() => setSetupCheck(false))
  }, [])

  async function submit(e) {
    e.preventDefault()
    setError(null)
    try {
      await login(email, password)
      window.location.href = '/'   // full reload so AuthProvider re-fetches /me
    } catch (err) {
      setError(err.message || 'Login failed')
    }
  }

  if (setupCheck === null) {
    return (
      <div className="min-h-screen grid place-items-center bg-neutral-950 text-neutral-400">
        Loading…
      </div>
    )
  }

  if (setupCheck === true) return <Setup />

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-neutral-950 text-neutral-100">
      <form onSubmit={submit} className="flex flex-col gap-4 w-full max-w-sm">
        <img src="/brand/logo-leftcurve.svg" alt="LeftCurve" className="h-12 mx-auto mb-2" />
        <input type="email" required placeholder="Email" value={email}
               onChange={(e) => setEmail(e.target.value)}
               className="w-full px-3 py-2 rounded bg-neutral-900 border border-neutral-700" />
        <input type="password" required placeholder="Password" value={password}
               onChange={(e) => setPassword(e.target.value)}
               className="w-full px-3 py-2 rounded bg-neutral-900 border border-neutral-700" />
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button type="submit" className="w-full px-4 py-2 rounded bg-white text-black font-medium hover:bg-neutral-200">
          Log in
        </button>
      </form>
    </div>
  )
}
