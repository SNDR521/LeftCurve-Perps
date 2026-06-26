export const normGroupPerf = (labelKey) => (rows = []) =>
  rows.map((r) => ({
    label: r[labelKey] ?? r.group ?? r.primary ?? '—',
    trade_count: r.trade_count ?? r.count ?? 0,
    win_rate: r.win_rate,
    total_pnl: r.total_pnl,
    avg_pnl: r.avg_pnl,
    profit_factor: r.profit_factor,
    best_trade: r.best_trade,
    worst_trade: r.worst_trade,
  }))

export const normCrossPrimary = (data) =>
  data?.primary_totals
    ? Object.entries(data.primary_totals).map(([label, m]) => ({ label, ...m }))
    : []

export const normOverview = (d) => d

export const normSession = (rows = []) =>
  rows.map((r) => ({
    session: r.session ?? r.group ?? r.label,
    utc_hours: r.utc_hours,
    trade_count: r.trade_count ?? 0,
    win_rate: r.win_rate ?? 0,
    total_pnl: r.total_pnl ?? 0,
    avg_pnl: r.avg_pnl ?? 0,
    best_trade: r.best_trade,
    worst_trade: r.worst_trade,
  }))

export const normHoldtime = (rows = []) =>
  rows.map((r) => ({
    label: r.bucket ?? r.group ?? r.label ?? '—',
    trade_count: r.trade_count ?? 0,
    win_rate: r.win_rate,
    total_pnl: r.total_pnl,
    avg_pnl: r.avg_pnl,
    profit_factor: r.profit_factor,
  }))

export const normGrades = (rows = []) =>
  rows.map((r) => ({
    grade: r.grade ?? r.group ?? 'Ungraded',
    count: r.count ?? r.trade_count ?? 0,
    win_rate: r.win_rate ?? 0,
    avg_pnl: r.avg_pnl ?? 0,
    total_pnl: r.total_pnl ?? 0,
    profit_factor: r.profit_factor,
  }))

export const normMistakes = (rows = []) =>
  rows.map((r) => ({
    mistake: r.mistake ?? r.group ?? '—',
    count: r.count ?? r.trade_count ?? 0,
    total_pnl: r.total_pnl ?? 0,
    avg_pnl: r.avg_pnl ?? 0,
    max_streak: r.max_streak ?? null,
  }))
