import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createPerpsFill } from '../lib/api'

// Defined at module scope (NOT inside the component) so inputs keep focus across renders.
function Field({ label, value, onChange, type = 'text', placeholder = '' }) {
  return (
    <label className="text-[12px] text-[#8d91a6] block">
      {label}
      <input type={type} value={value} onChange={onChange} placeholder={placeholder}
             className="input mt-1 block w-full" />
    </label>
  )
}

export default function PerpsFillModal({ accounts, onClose }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({
    exchange_account_id: accounts[0]?.id ?? '', symbol: '', asset_class: 'PERP',
    side: 'BUY', price: '', quantity: '', fee: '0', funding_amount: '',
    stop_price: '', risk_amount: '', executed_at: new Date().toISOString().slice(0, 16),
  })
  const [error, setError] = useState(null)
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const save = useMutation({
    mutationFn: () => {
      const num = (v) => (v === '' || v === null ? null : Number(v))
      return createPerpsFill({
        exchange_account_id: Number(form.exchange_account_id),
        symbol: form.symbol.trim().toUpperCase(),
        asset_class: form.asset_class, side: form.side,
        price: num(form.price), quantity: num(form.quantity), fee: num(form.fee) ?? 0,
        funding_amount: num(form.funding_amount), stop_price: num(form.stop_price),
        risk_amount: num(form.risk_amount),
        executed_at: new Date(form.executed_at).toISOString(),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['perps-positions'] })
      qc.invalidateQueries({ queryKey: ['perps-fills'] })
      onClose()
    },
    onError: (e) => setError(e.message),
  })

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60" onClick={onClose}>
      <div className="card p-5 w-[460px] max-w-[92vw]" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-[15px] font-semibold text-[#e2e4ef] mb-4">New fill</h2>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-[12px] text-[#8d91a6] block">
            Account
            <select value={form.exchange_account_id} onChange={set('exchange_account_id')} className="input mt-1 block w-full">
              {accounts.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}
            </select>
          </label>
          <Field label="Symbol" value={form.symbol} onChange={set('symbol')} placeholder="BTCUSDT" />
          <label className="text-[12px] text-[#8d91a6] block">
            Asset class
            <select value={form.asset_class} onChange={set('asset_class')} className="input mt-1 block w-full">
              <option value="PERP">PERP</option><option value="SPOT">SPOT</option>
            </select>
          </label>
          <label className="text-[12px] text-[#8d91a6] block">
            Side
            <select value={form.side} onChange={set('side')} className="input mt-1 block w-full">
              <option value="BUY">BUY</option><option value="SELL">SELL</option>
            </select>
          </label>
          <Field label="Price" value={form.price} onChange={set('price')} type="number" />
          <Field label="Quantity" value={form.quantity} onChange={set('quantity')} type="number" />
          <Field label="Fee" value={form.fee} onChange={set('fee')} type="number" />
          <Field label="Funding (signed)" value={form.funding_amount} onChange={set('funding_amount')} type="number" />
          <Field label="Stop price (opt)" value={form.stop_price} onChange={set('stop_price')} type="number" />
          <Field label="Risk amount (opt)" value={form.risk_amount} onChange={set('risk_amount')} type="number" />
          <Field label="Executed at" value={form.executed_at} onChange={set('executed_at')} type="datetime-local" />
        </div>
        {error && <p className="text-[12px] text-[#de576f] mt-2">{error}</p>}
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-blue" disabled={save.isPending || !form.symbol || form.price === '' || form.quantity === ''}
                  onClick={() => save.mutate()}>Save fill</button>
        </div>
      </div>
    </div>
  )
}
