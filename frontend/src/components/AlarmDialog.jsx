import { useState, useRef, useEffect } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { X, BellRing, ChevronDown, Check } from 'lucide-react'
import { createAlarm } from '../lib/api'

const SYMBOL_CONDITIONS = [
  { value: 'CROSS',      label: 'Crosses (either direction)' },
  { value: 'CROSS_UP',   label: 'Crosses up' },
  { value: 'CROSS_DOWN', label: 'Crosses down' },
  { value: 'GTE',        label: '≥ (price ≥ value)' },
  { value: 'LTE',        label: '≤ (price ≤ value)' },
  { value: 'PCT_MOVE',   label: '% move from ref price' },
]

const POSITION_CONDITIONS = [
  { value: 'NEAR_STOP', label: 'Price near my stop' },
  { value: 'UPNL',      label: 'Open P&L crosses' },
  { value: 'LIQ_DIST',  label: 'Near liquidation' },
]

const PLAN_CONDITIONS = [
  { value: 'PLAN_LOSS_LIMIT',  label: 'Daily loss limit hit' },
  { value: 'PLAN_MAX_TRADES',  label: 'Max trades hit' },
]

const CONDITIONS_BY_TARGET = {
  SYMBOL:   SYMBOL_CONDITIONS,
  POSITION: POSITION_CONDITIONS,
  PLAN:     PLAN_CONDITIONS,
}

const COND_MAP = {
  CROSS:      'crosses',
  CROSS_UP:   'crosses up',
  CROSS_DOWN: 'crosses down',
  GTE:        '≥',
  LTE:        '≤',
  PCT_MOVE:   'moves %',
}

const DEFAULT_UNIT_BY_CONDITION = { NEAR_STOP: 'PCT', UPNL: 'USD' }

const DEFAULT_CONDITION_BY_TARGET = {
  SYMBOL:   'GTE',
  POSITION: 'NEAR_STOP',
  PLAN:     'PLAN_LOSS_LIMIT',
}

const TARGETS = [
  { value: 'SYMBOL',   label: 'Symbol' },
  { value: 'POSITION', label: 'My position' },
  { value: 'PLAN',     label: 'Plan' },
]

const MARKETS = [
  { value: 'CRYPTO',  label: 'Crypto' },
  { value: 'EQUITY',  label: 'Equity' },
]

const TRIGGERS = [
  { value: 'ONCE',  label: 'Once' },
  { value: 'EVERY', label: 'Every time' },
]

const EXPIRY_CHIPS = [
  { key: 'never',  label: 'Never',  ms: null },
  { key: '1h',     label: '1h',     ms: 3600e3 },
  { key: '4h',     label: '4h',     ms: 4 * 3600e3 },
  { key: '1d',     label: '1d',     ms: 24 * 3600e3 },
  { key: '1w',     label: '1w',     ms: 7 * 24 * 3600e3 },
  { key: 'custom', label: 'Pick…',  ms: undefined },
]

function buildPreview({ targetType, symbol, condition, value, unit, refPrice, triggerMode, message }) {
  const mode = triggerMode === 'ONCE' ? 'once' : 'every time'

  if (targetType === 'PLAN') {
    if (condition === 'PLAN_LOSS_LIMIT') return `Alert ${mode}: daily loss limit reached.`
    if (condition === 'PLAN_MAX_TRADES') return `Alert ${mode}: max trades limit reached.`
    return 'Fill in the fields above.'
  }

  const sym = (symbol || '').trim().toUpperCase() || 'SYMBOL'

  if (targetType === 'POSITION') {
    if (condition === 'NEAR_STOP') {
      const unitLabel = unit === 'ABS' ? 'pts' : '%'
      return `Alert ${mode} when ${sym} — price within ${value || '…'}${unitLabel} of my stop.`
    }
    if (condition === 'UPNL') {
      const unitLabel = unit === 'R' ? 'R' : 'USD'
      return `Alert ${mode} when ${sym} — open P&L crosses ${value || '…'} ${unitLabel}.`
    }
    if (condition === 'LIQ_DIST') {
      return `Alert ${mode} when ${sym} — within ${value || '…'}% of liquidation.`
    }
    return 'Fill in the fields above.'
  }

  // SYMBOL
  const condLabel = COND_MAP[condition] || condition
  let base = `${sym} ${condLabel} ${value ?? ''}`
  if (condition === 'PCT_MOVE' && refPrice) base += ` from ${refPrice}`
  base = base.trim()
  let preview = `Alert ${mode} when ${base}.`
  if (message) preview += ` "${message}"`
  return preview
}

// ── Small themed controls ────────────────────────────────────────────────
function Field({ label, hint, children }) {
  return (
    <div>
      {label && (
        <span className="block mb-1.5 text-[10.5px] font-semibold uppercase tracking-[0.06em] text-[#8d91a6]">
          {label}
          {hint && <span className="ml-1 normal-case tracking-normal font-normal text-[#4e5166]">{hint}</span>}
        </span>
      )}
      {children}
    </div>
  )
}

function Segmented({ options, value, onChange }) {
  return (
    <div className="flex gap-[3px] bg-[#15171a] border border-[#2a2c30] rounded-lg p-[3px]">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={`flex-1 py-1.5 text-[12px] font-semibold rounded-md transition-all
            ${value === o.value
              ? 'bg-[#38bdf8] text-[#0b1116] shadow-[0_1px_4px_rgba(56,189,248,0.35)]'
              : 'text-[#7e8497] hover:text-[#b6bccb]'}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Dropdown({ options, value, onChange }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])
  const cur = options.find((o) => o.value === value)
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full h-[38px] px-3 flex items-center justify-between rounded-lg
                   bg-[#15171a] border border-[#2a2c30] text-[13px] text-[#e8ebf2]
                   hover:border-[#3a3c42] focus:border-[#38bdf8] focus:outline-none transition-colors"
      >
        <span className="truncate">{cur?.label || 'Select…'}</span>
        <ChevronDown className={`w-3.5 h-3.5 text-[#5a6072] shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="absolute z-20 mt-1 w-full max-h-60 overflow-y-auto rounded-lg py-1
                        bg-[#1e2024] border border-[#2a2c30]"
             style={{ boxShadow: '0 10px 30px rgba(0,0,0,0.55)' }}>
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              onClick={() => { onChange(o.value); setOpen(false) }}
              className={`w-full px-3 py-2 flex items-center justify-between text-left text-[12.5px] transition-colors
                ${o.value === value ? 'text-[#38bdf8] bg-[#38bdf8]/[0.06]' : 'text-[#c7ccd8] hover:bg-[#26282d]'}`}
            >
              <span className="truncate">{o.label}</span>
              {o.value === value && <Check className="w-3.5 h-3.5 shrink-0" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Switch({ on, locked, onClick }) {
  return (
    <button
      type="button"
      disabled={locked}
      onClick={onClick}
      aria-pressed={on}
      className={`relative w-[34px] h-[19px] rounded-full shrink-0 transition-colors
        ${locked ? 'bg-[#1e6b86] cursor-default' : on ? 'bg-[#38bdf8]' : 'bg-[#33363d]'}`}
    >
      <span className={`absolute top-[2px] w-[15px] h-[15px] rounded-full bg-white transition-all
        ${on || locked ? 'right-[2px]' : 'left-[2px]'}`} />
    </button>
  )
}

// ── Dialog ───────────────────────────────────────────────────────────────
export default function AlarmDialog({ onClose }) {
  const qc = useQueryClient()

  const [targetType, setTargetType] = useState('SYMBOL')
  const [symbol, setSymbol] = useState('')
  const [market, setMarket] = useState('CRYPTO')
  const [condition, setCondition] = useState('GTE')
  const [value, setValue] = useState('')
  const [unit, setUnit] = useState('PCT')
  const [refPrice, setRefPrice] = useState('')
  const [triggerMode, setTriggerMode] = useState('ONCE')
  const [expiryMode, setExpiryMode] = useState('never')
  const [expiresAt, setExpiresAt] = useState('')      // submit value (ISO from chip, or local from picker)
  const [message, setMessage] = useState('')
  const [deliverTelegram, setDeliverTelegram] = useState(false)
  const [error, setError] = useState(null)

  function handleTargetChange(key) {
    const defaultCondition = DEFAULT_CONDITION_BY_TARGET[key]
    setTargetType(key)
    setCondition(defaultCondition)
    setValue('')
    setUnit(DEFAULT_UNIT_BY_CONDITION[defaultCondition] || 'PCT')
    setRefPrice('')
  }

  function handleConditionChange(c) {
    setCondition(c)
    setUnit(DEFAULT_UNIT_BY_CONDITION[c] || 'PCT')
  }

  function pickExpiry(chip) {
    setExpiryMode(chip.key)
    if (chip.key === 'never') setExpiresAt('')
    else if (chip.key === 'custom') setExpiresAt('')   // reveal the picker; user chooses
    else setExpiresAt(new Date(Date.now() + chip.ms).toISOString())
  }

  const saveMutation = useMutation({
    mutationFn: (body) => createAlarm(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['alarms'] })
      onClose()
    },
    onError: (e) => setError(e.message || 'Failed to create alarm'),
  })

  function validate() {
    if (targetType === 'PLAN') return null
    if (!symbol.trim()) return 'Symbol is required.'
    if (value === '' || value === null) return 'Value is required.'
    if (targetType === 'SYMBOL' && condition === 'PCT_MOVE' && (!refPrice || isNaN(Number(refPrice)))) {
      return 'Ref price is required for % Move.'
    }
    return null
  }

  function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    const err = validate()
    if (err) { setError(err); return }

    const body = {
      target_type: targetType,
      trigger_mode: triggerMode,
      deliver: { in_app: true, telegram: deliverTelegram },
      condition,
    }

    if (targetType === 'SYMBOL') {
      body.symbol = symbol.trim().toUpperCase()
      body.market = market
      body.value = Number(value)
      if (condition === 'PCT_MOVE' && refPrice) body.params = { ref_price: Number(refPrice) }
    } else if (targetType === 'POSITION') {
      body.symbol = symbol.trim().toUpperCase()
      body.market = 'CRYPTO'
      body.value = Number(value)
      if (condition === 'NEAR_STOP' || condition === 'UPNL') body.params = { unit }
    }

    if (message.trim()) body.message = message.trim()
    if (expiresAt) body.expires_at = new Date(expiresAt).toISOString()

    saveMutation.mutate(body)
  }

  const conditions = CONDITIONS_BY_TARGET[targetType] || SYMBOL_CONDITIONS
  const preview = buildPreview({ targetType, symbol, condition, value, unit, refPrice, triggerMode, message })

  const unitOptions =
    condition === 'UPNL'
      ? [{ value: 'USD', label: 'USD' }, { value: 'R', label: 'R' }]
      : [{ value: 'PCT', label: '%' }, { value: 'ABS', label: 'pts' }]

  const showUnit   = targetType === 'POSITION' && (condition === 'NEAR_STOP' || condition === 'UPNL')
  const showValue  = targetType !== 'PLAN'
  const showSymbol = targetType !== 'PLAN'
  const showMarket = targetType === 'SYMBOL'
  const channels = deliverTelegram ? 'in-app + Telegram' : 'in-app'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
         onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="flex flex-col w-full max-w-[430px] max-h-[90vh] rounded-[14px] overflow-hidden
                      bg-[#1b1d21] border border-[#2a2c30]"
           style={{ boxShadow: '0 20px 60px rgba(0,0,0,0.55)' }}>

        {/* Header */}
        <div className="flex items-center gap-2.5 px-4 py-3.5 border-b border-[#26282d] shrink-0">
          <BellRing className="w-4 h-4 text-[#38bdf8]" />
          <span className="text-[14px] font-semibold tracking-tight text-[#f2f4f8]">New alarm</span>
          <button onClick={onClose} className="ml-auto text-[#4e5166] hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <form id="alarm-form" onSubmit={handleSubmit}
              className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-3.5">

          <Field label="Target">
            <Segmented options={TARGETS} value={targetType} onChange={handleTargetChange} />
          </Field>

          {showSymbol && (
            <div className="flex gap-2.5">
              <div className="flex-[1.4]">
                <Field label="Symbol">
                  <input
                    type="text"
                    value={symbol}
                    onChange={(e) => setSymbol(e.target.value)}
                    placeholder="e.g. BTC"
                    className="w-full h-[38px] px-3 rounded-lg bg-[#15171a] border border-[#2a2c30]
                               text-[13px] text-[#e8ebf2] uppercase placeholder:normal-case placeholder:text-[#565b6b]
                               focus:border-[#38bdf8] focus:outline-none transition-colors"
                    required
                  />
                </Field>
              </div>
              {showMarket && (
                <div className="w-[170px]">
                  <Field label="Market">
                    <Segmented options={MARKETS} value={market} onChange={setMarket} />
                  </Field>
                </div>
              )}
            </div>
          )}

          <Field label="Condition">
            <Dropdown options={conditions} value={condition} onChange={handleConditionChange} />
          </Field>

          {showValue && (
            <Field label="Value">
              <div className="flex h-[38px] rounded-lg overflow-hidden bg-[#15171a] border border-[#2a2c30]
                              focus-within:border-[#38bdf8] transition-colors">
                <input
                  type="number"
                  step="any"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  placeholder={targetType === 'SYMBOL' && condition === 'PCT_MOVE' ? '%' : 'price / value'}
                  className="flex-1 min-w-0 bg-transparent px-3 text-[13px] text-[#e8ebf2]
                             placeholder:text-[#565b6b] outline-none"
                  required
                />
                {showUnit && (
                  <div className="flex items-center gap-[2px] p-[3px] bg-[#101215] border-l border-[#2a2c30]">
                    {unitOptions.map((u) => (
                      <button
                        key={u.value}
                        type="button"
                        onClick={() => setUnit(u.value)}
                        className={`text-[11px] font-semibold px-2.5 py-[5px] rounded-md transition-colors
                          ${unit === u.value ? 'bg-[#2a2c30] text-[#e8ebf2]' : 'text-[#7e8497] hover:text-[#b6bccb]'}`}
                      >
                        {u.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </Field>
          )}

          {targetType === 'SYMBOL' && condition === 'PCT_MOVE' && (
            <Field label="Reference price">
              <input
                type="number"
                step="any"
                value={refPrice}
                onChange={(e) => setRefPrice(e.target.value)}
                placeholder="entry / ref price"
                className="w-full h-[38px] px-3 rounded-lg bg-[#15171a] border border-[#2a2c30]
                           text-[13px] text-[#e8ebf2] placeholder:text-[#565b6b]
                           focus:border-[#38bdf8] focus:outline-none transition-colors"
              />
            </Field>
          )}

          {targetType === 'PLAN' && (
            <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-[#15171a] border border-[#2a2c30]">
              <BellRing className="w-3.5 h-3.5 text-[#4e5166] shrink-0" />
              <p className="text-[12px] text-[#8d91a6]">Fires when today&apos;s plan-card limit is reached.</p>
            </div>
          )}

          <Field label="Trigger">
            <Segmented options={TRIGGERS} value={triggerMode} onChange={setTriggerMode} />
          </Field>

          <Field label="Expires">
            <div className="flex flex-wrap gap-1.5">
              {EXPIRY_CHIPS.map((chip) => (
                <button
                  key={chip.key}
                  type="button"
                  onClick={() => pickExpiry(chip)}
                  className={`text-[11.5px] font-medium px-3 py-1.5 rounded-md border transition-colors
                    ${expiryMode === chip.key
                      ? 'bg-[#38bdf8]/[0.12] border-[#38bdf8] text-[#38bdf8]'
                      : 'bg-[#15171a] border-[#2a2c30] text-[#8d91a6] hover:border-[#3a3c42]'}`}
                >
                  {chip.label}
                </button>
              ))}
            </div>
            {expiryMode === 'custom' && (
              <input
                type="datetime-local"
                value={expiresAt}
                onChange={(e) => setExpiresAt(e.target.value)}
                className="mt-2 w-full h-[38px] px-3 rounded-lg bg-[#15171a] border border-[#2a2c30]
                           text-[13px] text-[#e8ebf2] focus:border-[#38bdf8] focus:outline-none transition-colors
                           [color-scheme:dark]"
              />
            )}
          </Field>

          <Field label="Deliver to">
            <div className="flex flex-col gap-2.5">
              <div className="flex items-center gap-2.5">
                <Switch on locked />
                <span className="text-[12.5px] text-[#c7ccd8]">In-app</span>
                <span className="text-[10.5px] text-[#565b6b]">· AlertBell</span>
              </div>
              <div className="flex items-center gap-2.5">
                <Switch on={deliverTelegram} onClick={() => setDeliverTelegram((v) => !v)} />
                <span className="text-[12.5px] text-[#c7ccd8]">Telegram</span>
                <span className="text-[10.5px] text-[#565b6b]">· if connected in Settings</span>
              </div>
            </div>
          </Field>

          <Field label="Message" hint="optional">
            <input
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Custom note shown when fired"
              className="w-full h-[38px] px-3 rounded-lg bg-[#15171a] border border-[#2a2c30]
                         text-[13px] text-[#e8ebf2] placeholder:text-[#565b6b]
                         focus:border-[#38bdf8] focus:outline-none transition-colors"
            />
          </Field>

          {/* Preview */}
          <div className="flex items-start gap-2.5 px-3 py-2.5 rounded-lg bg-[#15171a]
                          border border-[#2a2c30] border-l-2 border-l-[#38bdf8]">
            <BellRing className="w-3.5 h-3.5 text-[#38bdf8] shrink-0 mt-0.5" />
            <div className="min-w-0">
              <p className="text-[9.5px] font-bold uppercase tracking-[0.1em] text-[#4e5166]">Preview</p>
              <p className="text-[12.5px] text-[#c7ccd8] mt-0.5">{preview} <span className="text-[#4e5166]">→ {channels}</span></p>
            </div>
          </div>

          {error && <p className="text-[12px] text-[#de576f]">{error}</p>}
        </form>

        {/* Footer */}
        <div className="flex justify-end gap-2.5 px-4 py-3 border-t border-[#26282d] bg-[#191b1f] shrink-0">
          <button type="button" onClick={onClose}
                  className="text-[13px] text-[#8d91a6] hover:text-white px-3.5 py-2 transition-colors">
            Cancel
          </button>
          <button
            type="submit"
            form="alarm-form"
            disabled={saveMutation.isPending}
            className="text-[13px] font-semibold text-[#0b1116] bg-[#38bdf8] hover:bg-[#5cc6f7]
                       rounded-lg px-4 py-2 transition-colors disabled:opacity-50
                       shadow-[0_2px_8px_rgba(56,189,248,0.3)]"
          >
            {saveMutation.isPending ? 'Creating…' : 'Create alarm'}
          </button>
        </div>
      </div>
    </div>
  )
}
