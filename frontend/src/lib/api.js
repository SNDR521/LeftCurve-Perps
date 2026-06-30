// In dev, Vite proxies /api/* → localhost:8000/api/* (no prefix stripping)
// In production, configure nginx to forward /api/* unchanged

// ── Market data (shared, no workspace prefix) ─────────────────────────────────

async function marketDataRequest(path, options = {}) {
  const res = await fetch(`/api/market${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    credentials: 'include',
    ...options,
  })
  if (res.status === 401) {
    window.location.href = '/login'
    throw new Error('Not authenticated')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

export function fetchTickerQuotes(symbols) {
  const qs = symbols ? `?symbols=${symbols}` : ''
  return marketDataRequest(`/quotes${qs}`)
}

export function fetchEquityNews(limit = 40) {
  return marketDataRequest(`/news/equity?limit=${limit}`)
}

export function fetchCryptoNews(limit = 40) {
  return marketDataRequest(`/news/crypto?limit=${limit}`)
}

export function fetchSquawk(limit = 50) {
  return marketDataRequest(`/squawk?limit=${limit}`)
}

// ── User auth (email + password, single-user) ──

export async function fetchMe() {
  const res = await fetch('/api/auth/me', { credentials: 'include' })
  if (!res.ok) return null
  return res.json()
}

export async function logout() {
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
}

export async function login(email, password) {
  const res = await fetch('/api/auth/login', {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || 'Login failed')
  return res.json()
}

export async function validateToken(rawToken) {
  const res = await fetch(`/api/auth/tokens/${rawToken}`, { credentials: 'include' })
  return res.ok ? res.json() : { valid: false }
}

export async function redeemInvite(payload) {  // {token,email,password,name?}
  const res = await fetch('/api/auth/redeem-invite', {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || 'Could not create account')
  return res.json()
}

export async function resetPassword(token, password) {
  const res = await fetch('/api/auth/reset-password', {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, password }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || 'Reset failed')
  return res.json()
}

export async function needsSetup() {
  const res = await fetch('/api/auth/needs-setup', { credentials: 'include' })
  if (!res.ok) return { needs_setup: false }
  return res.json()
}

export async function setupAccount({ email, password }) {
  const res = await fetch('/api/auth/setup', {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || 'Setup failed')
  return res.json()
}

export async function updateProfile(data) {  // { name }
  const res = await fetch('/api/auth/me', {
    method: 'PUT', credentials: 'include',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || 'Update failed')
  return res.json()
}

export async function changePassword(data) {  // { current_password, new_password }
  const res = await fetch('/api/auth/change-password', {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || 'Change failed')
  return res.json()
}

// ── Perps (exchange accounts, fills, positions) ──────────────────────

async function perpsRequest(path, options = {}) {
  const res = await fetch(`/api/perps${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    credentials: 'include',
    ...options,
  })
  if (res.status === 401) { window.location.href = '/login'; throw new Error('Not authenticated') }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

export function fetchPerpsAccounts() { return perpsRequest('/accounts') }
export function createPerpsAccount(data) { return perpsRequest('/accounts', { method: 'POST', body: JSON.stringify(data) }) }
export function deletePerpsAccount(id) { return perpsRequest(`/accounts/${id}`, { method: 'DELETE' }) }
export function syncPerpsAccount(id) { return perpsRequest(`/accounts/${id}/sync`, { method: 'POST' }) }

export function fetchPerpsPositions(params = {}) {
  const qs = new URLSearchParams(params).toString()
  return perpsRequest(`/positions${qs ? '?' + qs : ''}`)
}

export function fetchPerpsFills(params = {}) {
  const qs = new URLSearchParams(params).toString()
  return perpsRequest(`/fills${qs ? '?' + qs : ''}`)
}
export function createPerpsFill(data) { return perpsRequest('/fills', { method: 'POST', body: JSON.stringify(data) }) }
export function deletePerpsFill(id) { return perpsRequest(`/fills/${id}`, { method: 'DELETE' }) }

// ── Perps Analytics ───────────────────────────────────────────────

export function fetchPerpsOverview(params = {}) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/analytics/overview${qs ? '?' + qs : ''}`) }
export function fetchPerpsCoverage(params = {}) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/analytics/coverage${qs ? '?' + qs : ''}`) }
export function fetchPerpsPerformance(groupBy, params = {}) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/analytics/by-${groupBy}${qs ? '?' + qs : ''}`) }
export function fetchPerpsDailyPnl(params = {}) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/analytics/daily-pnl${qs ? '?' + qs : ''}`) }
export function fetchPerpsHeatmap(params = {}) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/analytics/heatmap${qs ? '?' + qs : ''}`) }
export function fetchPerpsRDistribution(params = {}) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/analytics/r-distribution${qs ? '?' + qs : ''}`) }
export function fetchPerpsDrawdown(params = {}) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/reports/drawdown${qs ? '?' + qs : ''}`) }
export function fetchPerpsFunding(params = {}) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/analytics/funding${qs ? '?' + qs : ''}`) }
export function fetchPerpsFees(params = {}) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/analytics/fees${qs ? '?' + qs : ''}`) }
export function fetchPerpsLeverage(params = {}) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/analytics/leverage${qs ? '?' + qs : ''}`) }
export function fetchPerpsCrossAnalysis(params = {}) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/analytics/cross${qs ? '?' + qs : ''}`) }
export function fetchPerpsDimensions() { return perpsRequest('/analytics/dimensions') }
export function fetchPerpsInsights(params = {}) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/analytics/insights${qs ? '?' + qs : ''}`) }
export function fetchPerpsEquity(params = {}) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/reports/equity${qs ? '?' + qs : ''}`) }

export function fetchPerpsCockpit(params = {}) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/cockpit${qs ? '?' + qs : ''}`) }

export function fetchPerpsPosition(id) { return perpsRequest(`/positions/${id}`) }
export function fetchPerpsPositionDetail(key) { return perpsRequest(`/positions/detail?key=${encodeURIComponent(key)}`) }
export function fetchPerpsChartData(params) { const qs = new URLSearchParams(params).toString(); return perpsRequest(`/chart-data?${qs}`) }
export function fetchPerpsJournalBulk() { return perpsRequest(`/journal/bulk`) }
export async function uploadPerpsScreenshot(positionKey, file) {
  const fd = new FormData(); fd.append('file', file)
  const res = await fetch(`/api/perps/journal/screenshot?position_key=${encodeURIComponent(positionKey)}`,
    { method: 'POST', body: fd, credentials: 'include' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
export function fetchPerpsJournal(positionKey) { return perpsRequest(`/journal?position_key=${encodeURIComponent(positionKey)}`) }
export function savePerpsJournal(data) { return perpsRequest('/journal', { method: 'PUT', body: JSON.stringify(data) }) }
export function fetchPerpsTags() { return perpsRequest('/journal/tags') }
export function createPerpsTag(data) { return perpsRequest('/journal/tags', { method: 'POST', body: JSON.stringify(data) }) }
export function linkPerpsTag(position_key, tag_id) { return perpsRequest('/journal/tag-link', { method: 'POST', body: JSON.stringify({ position_key, tag_id }) }) }
export function unlinkPerpsTag(position_key, tag_id) { return perpsRequest('/journal/tag-unlink', { method: 'POST', body: JSON.stringify({ position_key, tag_id }) }) }

// ── Workflow (daily plan cards, playbooks, reviews) ──────────────────

async function workflowRequest(path, options = {}) {
  const res = await fetch(`/api/workflow${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    credentials: 'include',
    ...options,
  })
  if (res.status === 401) { window.location.href = '/login'; throw new Error('Not authenticated') }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    const e = new Error(err.detail || 'Request failed')
    e.status = res.status
    throw e
  }
  return res.json()
}

// Plan card fetch returns null on 404 (create mode) so the query never retry-spams.
export async function fetchPlanCard(date) {
  try {
    return await workflowRequest(`/plan-cards/${date}`)
  } catch (e) {
    if (e.status === 404) return null
    throw e
  }
}
export function savePlanCard(date, data) { return workflowRequest(`/plan-cards/${date}`, { method: 'PUT', body: JSON.stringify(data) }) }
export function fetchPlanScore(date, workspace = 'all') { return workflowRequest(`/plan-cards/${date}/score?workspace=${workspace}`) }
export function fetchPlanCards(params = {}) {
  const qs = new URLSearchParams(params).toString()
  return workflowRequest(`/plan-cards${qs ? '?' + qs : ''}`)
}
// Watchlist (per-user symbols with personal levels)
export function fetchWatchlist() { return workflowRequest('/watchlist') }
export function createWatchlistItem(data) { return workflowRequest('/watchlist', { method: 'POST', body: JSON.stringify(data) }) }
export function updateWatchlistItem(id, data) { return workflowRequest(`/watchlist/${id}`, { method: 'PUT', body: JSON.stringify(data) }) }
export function deleteWatchlistItem(id) { return workflowRequest(`/watchlist/${id}`, { method: 'DELETE' }) }

// Alerts inbox + near-live check (the Layout bell polls /check every 60s).
export function fetchAlerts(limit = 20) { return workflowRequest(`/alerts?limit=${limit}`) }
export function checkAlerts() { return workflowRequest('/alerts/check') }
export function markAlertsSeen(body) { return workflowRequest('/alerts/seen', { method: 'POST', body: JSON.stringify(body) }) }

// Cross-workspace personal record for badges + ticker panel.
export function fetchSymbolStats(symbols) {
  const joined = Array.isArray(symbols) ? symbols.join(',') : symbols
  return workflowRequest(`/symbol-stats?symbols=${encodeURIComponent(joined)}`)
}

export function fetchPlaybookNames() { return workflowRequest('/playbooks/names') }
export function fetchPlaybooksLite() { return workflowRequest('/playbooks') }

// Playbooks (full CRUD — fetchPlaybooks == playbooksLite full payload incl. stats)
export const fetchPlaybooks = fetchPlaybooksLite
export function createPlaybook(data) { return workflowRequest('/playbooks', { method: 'POST', body: JSON.stringify(data) }) }
export function updatePlaybook(id, data) { return workflowRequest(`/playbooks/${id}`, { method: 'PUT', body: JSON.stringify(data) }) }
export function deletePlaybook(id) { return workflowRequest(`/playbooks/${id}`, { method: 'DELETE' }) }

// Reviews
export function fetchReviewDraft(type, start, workspace) { return workflowRequest(`/reviews/draft?type=${type}&start=${start}&workspace=${workspace}`) }
export function fetchReview(type, start, workspace) { return workflowRequest(`/reviews?type=${type}&start=${start}&workspace=${workspace}`) }
export function saveReview(data) { return workflowRequest('/reviews', { method: 'PUT', body: JSON.stringify(data) }) }

// ── Alarms ────────────────────────────────────────────────────────────

async function alarmsRequest(path, options = {}) {
  const res = await fetch(`/api/alarms${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    credentials: 'include',
    ...options,
  })
  if (res.status === 401) { window.location.href = '/login'; throw new Error('Not authenticated') }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

export function fetchAlarms(status) {
  return alarmsRequest(status ? `?status=${status}` : '')
}
export function createAlarm(body) {
  return alarmsRequest('', { method: 'POST', body: JSON.stringify(body) })
}
export function updateAlarm(id, body) {
  return alarmsRequest(`/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}
export function deleteAlarm(id) {
  return alarmsRequest(`/${id}`, { method: 'DELETE' })
}

export const telegramStatus = () => alarmsRequest('/telegram/status')
export const telegramLinkStart = () => alarmsRequest('/telegram/link/start', { method: 'POST' })
export const telegramUnlink = () => alarmsRequest('/telegram/link', { method: 'DELETE' })
export const telegramBotConfig   = () => alarmsRequest('/telegram/bot-config')
export const telegramActivateBot = (token, baseUrl) => alarmsRequest('/telegram/bot-config', { method: 'POST', body: JSON.stringify({ token, base_url: baseUrl }) })
export const telegramDeleteBot   = () => alarmsRequest('/telegram/bot-config', { method: 'DELETE' })

// ── Preferences ────────────────────────────────────────────────────────────

async function prefsRequest(path, options = {}) {
  const res = await fetch(`/api/preferences${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    credentials: 'include',
    ...options,
  })
  if (res.status === 401) { window.location.href = '/login'; throw new Error('Not authenticated') }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

export function fetchPreferences() { return prefsRequest('') }
export function updatePreferences(partial) {
  return prefsRequest('', { method: 'PUT', body: JSON.stringify(partial) })
}
export function searchInstruments(q) {
  return marketDataRequest(`/search?q=${encodeURIComponent(q)}`)
}
