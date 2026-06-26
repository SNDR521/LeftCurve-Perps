import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, List, CalendarDays, Settings, RefreshCw,
  BarChart3, ChevronDown, Newspaper, Wallet, Gauge, NotebookPen,
  BookOpen, ClipboardCheck, Menu, BellRing,
} from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchPerpsAccounts, syncPerpsAccount } from '../lib/api'
import { useState, createContext, useContext, useEffect } from 'react'
import useIsMobile from '../lib/useIsMobile'
import GlobalTickerBar from './GlobalTickerBar'
import AlertBell from './AlertBell'
import { useAuth } from '../auth/AuthContext'

// ── Global account context ────────────────────────────────────────
const AccountCtx = createContext({ perpsAccountId: null, setPerpsAccountId: () => {}, perpsAccounts: [] })
export function useAccount() { return useContext(AccountCtx) }

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/cockpit', icon: Gauge, label: 'Cockpit' },
  { to: '/trades', icon: List, label: 'Trade Log' },
  { to: '/reports', icon: BarChart3, label: 'Analytics' },
  { to: '/calendar', icon: CalendarDays, label: 'Calendar' },
  { to: '/plan', icon: NotebookPen, label: 'Daily Plan' },
  { to: '/playbooks', icon: BookOpen, label: 'Playbooks' },
  { to: '/reviews', icon: ClipboardCheck, label: 'Reviews' },
  { to: '/alarms', icon: BellRing, label: 'Alarms' },
  { to: '/news', icon: Newspaper, label: 'News' },
  { to: '/accounts', icon: Wallet, label: 'Accounts' },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

export default function Layout() {
  const queryClient = useQueryClient()
  const [perpsAccountId, setPerpsAccountId] = useState(null) // null = all perps accounts
  const [perpsAcctOpen, setPerpsAcctOpen] = useState(false)
  const { user, logout } = useAuth()
  const isMobile = useIsMobile()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const location = useLocation()
  // Close the drawer on navigation.
  useEffect(() => { setDrawerOpen(false) }, [location.pathname])

  const { data: perpsAccounts = [] } = useQuery({
    queryKey: ['perps-accounts'],
    queryFn: fetchPerpsAccounts,
    refetchInterval: (q) => (q.state.data || []).some(
      a => a.syncing || a.sync_progress?.state === 'running') ? 3000 : false,
  })

  // Perps sidebar sync — fan out the existing per-account background sync,
  // scoped by the account selector (null = all credentialed accounts).
  const perpsSyncable = perpsAccounts.filter(a => a.has_credentials)
  const perpsTargets = perpsAccountId == null
    ? perpsSyncable
    : perpsSyncable.filter(a => a.id === perpsAccountId)
  const perpsSyncMutation = useMutation({
    mutationFn: () => Promise.all(perpsTargets.map(a => syncPerpsAccount(a.id))),
    onSettled: () => queryClient.invalidateQueries(),
  })
  const perpsRunning = perpsTargets.some(a => a.syncing || a.sync_progress?.state === 'running')
  const perpsBusy = perpsSyncMutation.isPending || perpsRunning
  const perpsSelectedLabel = perpsAccountId == null
    ? null
    : (perpsAccounts.find(a => a.id === perpsAccountId)?.label || `Account ${perpsAccountId}`)
  const perpsSyncError = perpsTargets.map(a => a.last_sync_error).find(Boolean) || null

  return (
    <AccountCtx.Provider value={{ perpsAccountId, setPerpsAccountId, perpsAccounts }}>
      <div className="flex h-screen overflow-hidden">
        {drawerOpen && (
          <div
            className="fixed inset-0 z-30 bg-black/50 md:hidden"
            onClick={() => setDrawerOpen(false)}
          />
        )}
        {/* Sidebar */}
        <aside className={`fixed inset-y-0 left-0 z-40 w-[230px] bg-[#161718] border-r border-[#2a2c30] flex flex-col shrink-0 transition-transform duration-200 md:static md:z-auto md:transition-none ${drawerOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0`}>
          {/* Logo */}
          <div className="h-[60px] flex items-center gap-2.5 px-5 border-b border-[#2a2c30]">
            <img src="/brand/logo-mark.svg" alt="LeftCurve" className="w-8 h-8" />
            <div>
              <span className="text-[15px] font-semibold tracking-tight text-white">LeftCurve</span>
              <span className="text-[10px] text-[#4e5166] block -mt-0.5">Journal</span>
            </div>
          </div>

          {/* Alert bell in sidebar header area */}
          {!isMobile && (
            <div className="px-2.5 pt-3 flex items-center justify-end">
              <AlertBell />
            </div>
          )}

          {/* Perps Account Selector */}
          {perpsAccounts.length > 0 && (
            <div className="px-2.5 pt-3 pb-1">
              <p className="px-3 pb-1.5 text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">
                Account
              </p>
              <div className="relative">
                <button
                  onClick={() => setPerpsAcctOpen(!perpsAcctOpen)}
                  className="w-full flex items-center gap-2 px-3 py-2 bg-[#242629] border border-[#3a3c42]
                             rounded-lg text-[12px] text-left hover:border-[#4e5166] transition-colors"
                >
                  <Wallet className="w-3.5 h-3.5 text-[var(--accent)] shrink-0" />
                  <span className="flex-1 truncate text-[#e2e4ef]">
                    {perpsAccountId
                      ? (perpsAccounts.find(a => a.id === perpsAccountId)?.label || `Account ${perpsAccountId}`)
                      : 'All Accounts'}
                  </span>
                  <ChevronDown className={`w-3.5 h-3.5 text-[#4e5166] transition-transform ${perpsAcctOpen ? 'rotate-180' : ''}`} />
                </button>

                {perpsAcctOpen && (
                  <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-[#1e2024] border border-[#2a2c30]
                                  rounded-lg shadow-xl overflow-hidden"
                       style={{ backdropFilter: 'blur(8px)', boxShadow: '0 8px 32px rgba(0,0,0,0.5)' }}>
                    <button
                      onClick={() => { setPerpsAccountId(null); setPerpsAcctOpen(false) }}
                      className={`w-full flex items-center gap-2 px-3 py-2 text-[12px] text-left transition-colors
                        ${!perpsAccountId ? 'bg-[rgb(var(--accent-rgb)/0.2)] text-[var(--accent)]' : 'text-[#8d91a6] hover:bg-[#2a2c30]'}`}
                    >
                      All Accounts
                    </button>
                    {perpsAccounts.map(acc => (
                      <button
                        key={acc.id}
                        onClick={() => { setPerpsAccountId(acc.id); setPerpsAcctOpen(false) }}
                        className={`w-full flex items-center gap-2 px-3 py-2.5 text-[12px] text-left transition-colors
                          ${perpsAccountId === acc.id ? 'bg-[rgb(var(--accent-rgb)/0.2)] text-[var(--accent)]' : 'text-[#8d91a6] hover:bg-[#2a2c30]'}`}
                      >
                        <div className="flex-1 min-w-0">
                          <span className="text-[#e2e4ef] truncate block">{acc.label}</span>
                          <span className="text-[10px] text-[#4e5166]">{acc.venue}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Nav */}
          <nav className="flex-1 py-2 px-2.5 space-y-0.5 overflow-y-auto">
            <p className="px-3 pt-2 pb-1.5 text-[10px] font-semibold text-[#4e5166] uppercase tracking-[0.08em]">
              Menu
            </p>
            {navItems.map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  `relative flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] font-medium transition-all duration-150 ${
                    isActive
                      ? 'bg-[rgb(var(--accent-rgb)/0.2)] text-[var(--accent)]'
                      : 'text-[#8d91a6] hover:text-[#fcfefd] hover:bg-[#242629]'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive && (
                      <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-[var(--accent)] rounded-r-full" />
                    )}
                    <Icon className="w-[18px] h-[18px]" />
                    {label}
                  </>
                )}
              </NavLink>
            ))}
          </nav>

          {/* User / Logout */}
          {user && (
            <div className="px-3 py-2.5 border-t border-[#2a2c30] flex items-center gap-2.5">
              {user.avatar_url
                ? <img src={user.avatar_url} alt="" className="w-7 h-7 rounded-full shrink-0" />
                : <div className="w-7 h-7 rounded-full bg-[rgb(var(--accent-rgb)/0.2)] flex items-center justify-center shrink-0">
                    <span className="text-[11px] font-semibold text-[var(--accent)]">
                      {(user.name || user.email || '?')[0].toUpperCase()}
                    </span>
                  </div>
              }
              <span className="flex-1 min-w-0 text-[12px] text-[#8d91a6] truncate">
                {user.name || user.email}
              </span>
              <button
                onClick={logout}
                className="text-[11px] text-[#4e5166] hover:text-neutral-100 transition-colors shrink-0"
              >
                Log out
              </button>
            </div>
          )}

          {/* Sync Button — scoped by the account selector */}
          {perpsTargets.length > 0 && (
            <div className="p-3 border-t border-[#2a2c30]">
              <button
                onClick={() => perpsSyncMutation.mutate()}
                disabled={perpsBusy}
                className="btn-blue w-full flex items-center justify-center gap-2 text-[13px]
                           disabled:opacity-50 active:scale-[0.98]"
              >
                <RefreshCw className={`w-4 h-4 ${perpsBusy ? 'animate-spin' : ''}`} />
                {perpsBusy
                  ? 'Syncing…'
                  : (perpsAccountId == null ? 'Sync all accounts' : `Sync ${perpsSelectedLabel}`)}
              </button>
              {perpsSyncError && !perpsBusy && (
                <p className="text-[11px] text-[#de576f] mt-1.5 text-center truncate" title={perpsSyncError}>
                  {perpsSyncError}
                </p>
              )}
            </div>
          )}
        </aside>

        {/* Main Content */}
        <div className="flex-1 flex flex-col overflow-hidden bg-[#111213]">
          {/* Mobile top bar — drawer toggle + brand + alerts (md+ uses the sidebar) */}
          <div className="md:hidden h-12 shrink-0 flex items-center gap-2.5 px-3 bg-[#161718] border-b border-[#2a2c30]">
            <button
              onClick={() => setDrawerOpen(true)}
              className="p-2 -ml-1 rounded-lg text-[#8d91a6] hover:text-white hover:bg-[#242629] transition-colors"
              aria-label="Open menu"
            >
              <Menu className="w-5 h-5" />
            </button>
            <img src="/brand/logo-mark.svg" alt="" className="w-6 h-6" />
            <span className="text-[14px] font-semibold tracking-tight text-white">LeftCurve</span>
            <div className="flex-1" />
            {isMobile && <AlertBell />}
          </div>
          <GlobalTickerBar />
          <main className="flex-1 overflow-y-auto">
            <div className="max-w-[1400px] mx-auto px-4 py-4 md:px-6 md:py-6">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </AccountCtx.Provider>
  )
}
