import { createContext, useContext, useEffect, useState } from 'react'
import { fetchMe, logout as apiLogout } from '../lib/api'

const AuthCtx = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined) // undefined = loading, null = anonymous
  useEffect(() => {
    fetchMe().then(setUser).catch(() => setUser(null))
  }, [])
  const refresh = async () => { try { setUser(await fetchMe()) } catch { /* keep current */ } }
  const logout = async () => {
    await apiLogout()
    setUser(null)
    window.location.href = '/login'
  }
  return <AuthCtx.Provider value={{ user, logout, refresh }}>{children}</AuthCtx.Provider>
}

export const useAuth = () => useContext(AuthCtx)
