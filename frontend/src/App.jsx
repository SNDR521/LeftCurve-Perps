import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import PerpsDashboard from './pages/PerpsDashboard'
import PerpsCockpit from './pages/PerpsCockpit'
import PerpsPositions from './pages/PerpsPositions'
import PerpsPositionDetail from './pages/PerpsPositionDetail'
import PerpsReports from './pages/PerpsReports'
import PerpsCalendar from './pages/PerpsCalendar'
import PerpsAccounts from './pages/PerpsAccounts'
import PlanCardPage from './pages/PlanCardPage'
import Playbooks from './pages/Playbooks'
import Reviews from './pages/Reviews'
import Alarms from './pages/Alarms'
import News from './pages/News'
import Settings from './pages/Settings'
import { AuthProvider, useAuth } from './auth/AuthContext'
import Login from './pages/Login'

function RequireAuth({ children }) {
  const { user } = useAuth()
  if (user === undefined) {
    return (
      <div className="min-h-screen grid place-items-center bg-neutral-950 text-neutral-400">
        Loading…
      </div>
    )
  }
  if (user === null) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<RequireAuth><Layout /></RequireAuth>}>
            <Route path="/" element={<PerpsDashboard />} />
            <Route path="/cockpit" element={<PerpsCockpit />} />
            <Route path="/trades" element={<PerpsPositions />} />
            <Route path="/trades/:id" element={<PerpsPositionDetail />} />
            <Route path="/reports" element={<PerpsReports />} />
            <Route path="/calendar" element={<PerpsCalendar />} />
            <Route path="/accounts" element={<PerpsAccounts />} />
            <Route path="/plan" element={<PlanCardPage />} />
            <Route path="/playbooks" element={<Playbooks />} />
            <Route path="/reviews" element={<Reviews />} />
            <Route path="/alarms" element={<Alarms />} />
            <Route path="/news" element={<News />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
