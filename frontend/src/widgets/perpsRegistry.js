import {
  TrendingUp, Target, BarChart3, DollarSign, Clock, Zap,
  PieChart as PieIcon, CalendarDays, ArrowUpRight, ArrowDownRight,
  Activity, Layers, Sigma, TrendingDown, Globe, Radio,
} from 'lucide-react'

import StatCardWidget from './StatCardWidget'
import WinLossPieWidget from './WinLossPieWidget'
import PnlBarWidget from './PnlBarWidget'
import PerpsEquityWidget from './PerpsEquityWidget'
import PerpsCalendarWidget from './PerpsCalendarWidget'
import StreaksWidget from './StreaksWidget'
import MarketPulseWidget from './MarketPulseWidget'
import NewsWidget from './NewsWidget'

// Perps widget registry — mirrors the shape of registry.js but for perps dashboards.
// Prop-firm-specific widgets (compliance, drawdown, risk_monitor) and the prop
// equity_curve/calendar are intentionally excluded. Market Pulse and Squawk are
// workspace-agnostic and available in both.

const PERPS_WIDGET_REGISTRY = [
  // ── Stat cards ──────────────────────────────────────────────────
  {
    id: 'stat_net_pnl',
    label: 'Net P&L',
    icon: DollarSign,
    component: StatCardWidget,
    props: { metricKey: 'total_pnl', label: 'Net P&L', format: 'currency', icon: 'DollarSign' },
    defaultW: 2, defaultH: 2,
    minW: 2, minH: 2,
    category: 'Stats',
  },
  {
    id: 'stat_win_rate',
    label: 'Win Rate',
    icon: Target,
    component: StatCardWidget,
    props: { metricKey: 'win_rate', label: 'Trade Win %', format: 'percent', icon: 'Target' },
    defaultW: 2, defaultH: 2,
    minW: 2, minH: 2,
    category: 'Stats',
  },
  {
    id: 'stat_profit_factor',
    label: 'Profit Factor',
    icon: TrendingUp,
    component: StatCardWidget,
    props: { metricKey: 'profit_factor', label: 'Profit Factor', format: 'ratio', icon: 'TrendingUp' },
    defaultW: 2, defaultH: 2,
    minW: 2, minH: 2,
    category: 'Stats',
  },
  {
    id: 'stat_total_trades',
    label: 'Total Trades',
    icon: BarChart3,
    component: StatCardWidget,
    props: { metricKey: 'total_trades', label: 'Total Trades', format: 'integer', icon: 'BarChart3' },
    defaultW: 2, defaultH: 2,
    minW: 2, minH: 2,
    category: 'Stats',
  },
  {
    id: 'stat_avg_win',
    label: 'Avg Win',
    icon: ArrowUpRight,
    component: StatCardWidget,
    props: { metricKey: 'avg_win', label: 'Avg Win', format: 'currency', icon: 'ArrowUpRight' },
    defaultW: 2, defaultH: 2,
    minW: 2, minH: 2,
    category: 'Stats',
  },
  {
    id: 'stat_avg_loss',
    label: 'Avg Loss',
    icon: ArrowDownRight,
    component: StatCardWidget,
    props: { metricKey: 'avg_loss', label: 'Avg Loss', format: 'currency', icon: 'ArrowDownRight' },
    defaultW: 2, defaultH: 2,
    minW: 2, minH: 2,
    category: 'Stats',
  },
  {
    id: 'stat_expectancy',
    label: 'Expectancy',
    icon: Activity,
    component: StatCardWidget,
    props: { metricKey: 'expectancy', label: 'Expectancy', format: 'currency', icon: 'Activity' },
    defaultW: 2, defaultH: 2,
    minW: 2, minH: 2,
    category: 'Stats',
  },
  {
    id: 'stat_avg_r',
    label: 'Avg R-Multiple',
    icon: Target,
    component: StatCardWidget,
    props: { metricKey: 'avg_r_multiple', label: 'Avg R-Multiple', format: 'r', icon: 'Target' },
    defaultW: 2, defaultH: 2,
    minW: 2, minH: 2,
    category: 'Stats',
  },
  {
    id: 'stat_sharpe',
    label: 'Sharpe Ratio',
    icon: Sigma,
    component: StatCardWidget,
    props: { metricKey: 'sharpe_ratio', label: 'Sharpe Ratio', format: 'ratio', icon: 'Activity' },
    defaultW: 2, defaultH: 2,
    minW: 2, minH: 2,
    category: 'Stats',
  },
  {
    id: 'stat_sortino',
    label: 'Sortino Ratio',
    icon: TrendingDown,
    component: StatCardWidget,
    props: { metricKey: 'sortino_ratio', label: 'Sortino Ratio', format: 'ratio', icon: 'Activity' },
    defaultW: 2, defaultH: 2,
    minW: 2, minH: 2,
    category: 'Stats',
  },
  {
    id: 'stat_max_drawdown',
    label: 'Max Drawdown',
    icon: TrendingDown,
    component: StatCardWidget,
    props: { metricKey: 'max_drawdown', label: 'Max Drawdown', format: 'currency', icon: 'ArrowDownRight' },
    defaultW: 2, defaultH: 2,
    minW: 2, minH: 2,
    category: 'Stats',
  },
  {
    id: 'streaks',
    label: 'Win / Loss Streaks',
    icon: Zap,
    component: StreaksWidget,
    defaultW: 4, defaultH: 2,
    minW: 3, minH: 2,
    category: 'Stats',
  },
  // ── Charts ───────────────────────────────────────────────────────
  {
    id: 'perps_equity',
    label: 'Equity Curve',
    icon: TrendingUp,
    component: PerpsEquityWidget,
    defaultW: 12, defaultH: 4,
    minW: 6, minH: 3,
    category: 'Charts',
  },
  {
    id: 'win_loss_pie',
    label: 'Win / Loss Distribution',
    icon: PieIcon,
    component: WinLossPieWidget,
    defaultW: 4, defaultH: 4,
    minW: 3, minH: 3,
    category: 'Charts',
  },
  {
    id: 'pnl_by_symbol',
    label: 'P&L by Symbol',
    icon: BarChart3,
    component: PnlBarWidget,
    props: { groupBy: 'symbol' },
    defaultW: 6, defaultH: 4,
    minW: 4, minH: 3,
    category: 'Charts',
  },
  {
    id: 'pnl_by_weekday',
    label: 'P&L by Weekday',
    icon: CalendarDays,
    component: PnlBarWidget,
    props: { groupBy: 'weekday' },
    defaultW: 6, defaultH: 4,
    minW: 4, minH: 3,
    category: 'Charts',
  },
  {
    id: 'pnl_by_hour',
    label: 'P&L by Hour',
    icon: Clock,
    component: PnlBarWidget,
    props: { groupBy: 'hour' },
    defaultW: 6, defaultH: 4,
    minW: 4, minH: 3,
    category: 'Charts',
  },
  {
    id: 'pnl_by_direction',
    label: 'Long vs Short',
    icon: Layers,
    component: PnlBarWidget,
    props: { groupBy: 'direction' },
    defaultW: 6, defaultH: 4,
    minW: 4, minH: 3,
    category: 'Charts',
  },
  // ── Overview ─────────────────────────────────────────────────────
  {
    id: 'perps_calendar',
    label: 'Trade Calendar',
    icon: CalendarDays,
    component: PerpsCalendarWidget,
    defaultW: 12, defaultH: 5,
    minW: 6, minH: 4,
    category: 'Overview',
  },
  // ── Market ───────────────────────────────────────────────────────
  {
    id: 'market_pulse',
    label: 'Market Pulse',
    icon: Globe,
    component: MarketPulseWidget,
    defaultW: 4, defaultH: 4,
    minW: 3, minH: 3,
    category: 'Market',
  },
  {
    id: 'squawk',
    label: 'Squawk (FinancialJuice)',
    icon: Radio,
    component: NewsWidget,
    defaultW: 6, defaultH: 5,
    minW: 4, minH: 3,
    category: 'Market',
  },
]

export default PERPS_WIDGET_REGISTRY

// Default layout: stat row → equity → charts row → calendar
export const PERPS_DEFAULT_LAYOUT = [
  // Stat cards row
  { i: 'stat_net_pnl',        x: 0,  y: 0,  w: 2, h: 2 },
  { i: 'stat_win_rate',       x: 2,  y: 0,  w: 2, h: 2 },
  { i: 'stat_profit_factor',  x: 4,  y: 0,  w: 2, h: 2 },
  { i: 'stat_total_trades',   x: 6,  y: 0,  w: 2, h: 2 },
  { i: 'stat_avg_win',        x: 8,  y: 0,  w: 2, h: 2 },
  { i: 'stat_avg_loss',       x: 10, y: 0,  w: 2, h: 2 },
  // Equity curve
  { i: 'perps_equity',        x: 0,  y: 2,  w: 12, h: 4 },
  // Charts row
  { i: 'win_loss_pie',        x: 0,  y: 6,  w: 4, h: 4 },
  { i: 'pnl_by_symbol',       x: 4,  y: 6,  w: 4, h: 4 },
  { i: 'pnl_by_weekday',      x: 8,  y: 6,  w: 4, h: 4 },
  // Calendar
  { i: 'perps_calendar',      x: 0,  y: 10, w: 12, h: 5 },
]

export const PERPS_DEFAULT_WIDGETS = PERPS_DEFAULT_LAYOUT.map(l => l.i)
