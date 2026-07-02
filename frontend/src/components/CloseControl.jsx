import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { closePerpsPosition } from '../lib/api'

const PRESETS = [0.1, 0.25, 0.5, 0.75, 1]

const fmtQty = (n) => Number(n).toLocaleString(undefined, { maximumFractionDigits: 6 })

// Close controls for one cockpit position row. Preset % chips arm an inline
// confirm (5s auto-revert); custom qty goes through a small modal. All closes
// are reduce-only market orders; the backend does authoritative lot rounding,
// so previews show "≈". Errors render inline (house style, cf. StopCell).
export default function CloseControl({ accountId, symbol, qty }) {
  const qc = useQueryClient()
  const [armed, setArmed] = useState(null) // {fraction} | {qty}
  const [showModal, setShowModal] = useState(false)
  const [customQty, setCustomQty] = useState('')
  const [error, setError] = useState(null)
  const revertTimer = useRef(null)
  const errorTimer = useRef(null)
  const firing = useRef(false)

  useEffect(() => () => { clearTimeout(revertTimer.current); clearTimeout(errorTimer.current) }, [])

  const mutation = useMutation({
    mutationFn: closePerpsPosition,
    onSuccess: () => {
      setArmed(null); setShowModal(false); setError(null)
      qc.invalidateQueries({ queryKey: ['perps-cockpit'] })
    },
    onError: (e) => {
      setArmed(null); setShowModal(false)
      setError(e?.message || 'close failed')
      clearTimeout(errorTimer.current)
      errorTimer.current = setTimeout(() => setError(null), 8000)
    },
    onSettled: () => { firing.current = false },
  })

  function arm(sel) {
    setError(null)
    setArmed(sel)
    clearTimeout(revertTimer.current)
    revertTimer.current = setTimeout(() => setArmed(null), 5000)
  }

  function confirm() {
    if (firing.current) return
    firing.current = true
    clearTimeout(revertTimer.current)
    const body = { account_id: accountId, symbol }
    if (armed.fraction != null) body.fraction = armed.fraction
    else body.qty = armed.qty
    mutation.mutate(body)
  }

  function openCustom() {
    setError(null); setArmed(null); setCustomQty(''); setShowModal(true)
  }

  const customValid = (() => {
    const n = Number(customQty)
    return Number.isFinite(n) && n > 0 && n <= qty
  })()

  if (mutation.isPending) {
    return <span className="text-[11px] text-[#f59e0b] font-mono animate-pulse">closing…</span>
  }

  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
      {armed ? (
        <>
          <button onClick={confirm}
            className="text-[11px] font-semibold px-2 py-0.5 rounded bg-[#de576f] text-white hover:bg-[#c94b62] transition-colors">
            Confirm close ≈{fmtQty(armed.fraction != null ? armed.fraction * qty : armed.qty)} @ mkt
          </button>
          <button onClick={() => { clearTimeout(revertTimer.current); setArmed(null) }}
            className="text-[12px] text-[#4e5166] hover:text-[#8d91a6] px-1" title="Cancel">✕</button>
        </>
      ) : (
        <>
          {PRESETS.map((f) => (
            <button key={f} onClick={() => arm({ fraction: f })}
              className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-[#2a2c30] text-[#8d91a6] hover:border-[#de576f]/60 hover:text-[#de576f] transition-colors">
              {f * 100}%
            </button>
          ))}
          <button onClick={openCustom} title="Custom quantity"
            className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-[#2a2c30] text-[#8d91a6] hover:border-[#de576f]/60 hover:text-[#de576f] transition-colors">
            …
          </button>
        </>
      )}
      {error && <span className="text-[10px] text-[#de576f] ml-1" title={error}>{error}</span>}

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={() => setShowModal(false)}>
          <div className="card p-5 w-[320px]" onClick={(e) => e.stopPropagation()}>
            <div className="text-[13px] font-semibold text-white mb-1">Close {symbol}</div>
            <div className="text-[11px] text-[#4e5166] mb-3">
              position size {fmtQty(qty)} · reduce-only market order
            </div>
            <div className="flex items-center gap-2">
              <input autoFocus type="number" step="any" min="0" max={qty}
                className="input flex-1" placeholder="quantity"
                value={customQty} onChange={(e) => setCustomQty(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && customValid) { setShowModal(false); arm({ qty: Number(customQty) }) }
                  else if (e.key === 'Escape') setShowModal(false)
                }} />
              <button onClick={() => setCustomQty(String(qty))}
                className="text-[11px] text-[#4e5166] hover:text-[#8d91a6]">max</button>
            </div>
            {!customValid && customQty !== '' && (
              <p className="text-[11px] text-[#de576f] mt-2">must be between 0 and {fmtQty(qty)}</p>
            )}
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setShowModal(false)}
                className="text-[12px] text-[#4e5166] hover:text-[#8d91a6] px-2 py-1">Cancel</button>
              <button disabled={!customValid}
                onClick={() => { setShowModal(false); arm({ qty: Number(customQty) }) }}
                className="text-[12px] font-semibold px-3 py-1 rounded bg-[#de576f] text-white disabled:opacity-40">
                Review close
              </button>
            </div>
          </div>
        </div>
      )}
    </span>
  )
}
