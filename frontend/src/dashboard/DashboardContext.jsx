import { createContext, useContext } from 'react'

export const DashboardCtx = createContext({})
export function useDashboard() { return useContext(DashboardCtx) }
