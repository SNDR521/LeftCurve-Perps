import { useEffect, useRef, useState } from 'react'
import {
  createChart, ColorType, CrosshairMode,
  CandlestickSeries, LineSeries, BaselineSeries,
  createSeriesMarkers, LineStyle,
} from 'lightweight-charts'
import { Crosshair, Maximize2, Minimize2, Layers } from 'lucide-react'
import { rollingAvgLines, runningPnlSeries, dedupeByTime, snapToInterval, parseUtcSeconds } from './chartMath'

// ── Theme (matches base LightweightChart) ─────────────────────────────────────

const THEME = {
  layout:          { background: { type: ColorType.Solid, color: '#161718' }, textColor: '#4e5166' },
  grid:            { vertLines: { color: '#1e2030' }, horzLines: { color: '#1e2030' } },
  crosshair:       { mode: CrosshairMode.Normal },
  timeScale:       { borderColor: '#2a2c30', timeVisible: true, secondsVisible: false },
  rightPriceScale: { borderColor: '#2a2c30' },
}

const CANDLE_COLORS = {
  upColor: '#00d4aa', downColor: '#de576f',
  borderUpColor: '#00d4aa', borderDownColor: '#de576f',
  wickUpColor: '#00d4aa', wickDownColor: '#de576f',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const toTs = parseUtcSeconds

// Approx interval length (minutes) for the adapter-specific codes we may receive.
// Handles both prop codes ('1m','5m','15m','60m','4h','1d') and perps codes
// ('1','5','15','60','240','D', etc.).
function intervalMinutes(interval) {
  if (!interval) return 5
  const s = String(interval)
  if (s === 'D' || s === '1d') return 1440
  const m = s.match(/^(\d+)(m|h)?$/)
  if (!m) return 5
  const n = parseInt(m[1], 10)
  if (m[2] === 'h') return n * 60
  // perps bare-number codes are minutes ('60' = 1h, '240' = 4h); prop 'Nm' is minutes too
  return n
}

// Buffer (seconds) on each side of the trade window.
// Derived from interval minutes (≈120 bars of padding) but at least 6× the trade
// duration so short scalps still show context.
function bufferSeconds(durationSeconds, interval) {
  const mins = intervalMinutes(interval)
  return Math.max(mins * 120 * 60, (durationSeconds ?? 0) * 6)
}

const DEFAULT_LAYERS = {
  executions: true,
  avgLines: true,
  mfeMae: true,
  funding: true,
  slTp: true,
  pnlPane: true,
}

function loadLayers() {
  try {
    const raw = localStorage.getItem('tradechart_layers')
    if (raw) return { ...DEFAULT_LAYERS, ...JSON.parse(raw) }
  } catch { /* ignore */ }
  return { ...DEFAULT_LAYERS }
}

const fmtUsd = (v) => {
  const a = Math.abs(v)
  const s = a >= 1000 ? a.toLocaleString(undefined, { maximumFractionDigits: 0 })
                      : a.toFixed(2)
  return `${v < 0 ? '-' : ''}$${s}`
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function TradeChart({
  symbol,
  direction,
  entryTime,
  exitTime,
  durationSeconds,
  executions = [],
  mfePrice,
  maePrice,
  mfeUsd,
  maeUsd,
  realizedPnl,
  avgEntry,
  stop,
  targets = [],
  totalFunding = 0,
  confidence,
  fetchCandles,
  intervals = [],
  pickInterval,
  // Adapter opt-out: prop quantities are lots, so a price×qty PnL pane would
  // chart financially meaningless numbers there.
  disablePnlPane = false,
}) {
  const containerRef = useRef(null)
  const chartRef     = useRef(null)
  const rangeRef     = useRef(null)
  const shadingRef   = useRef(null)
  const [status, setStatus]         = useState('loading')
  const [errorMsg, setErrorMsg]     = useState('')
  const [freeMode, setFreeMode]     = useState(false)
  const [tfOverride, setTfOverride] = useState(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [layers, setLayers]         = useState(loadLayers)
  const [layersOpen, setLayersOpen] = useState(false)

  const estimated = confidence === 'ESTIMATED'
  const dirSign   = direction === 'SHORT' ? -1 : 1

  // Callers may recreate the fetcher/arrays every render — depend on content
  // keys (not identities) and read the fetcher through a ref so the chart
  // doesn't tear down and refetch on every parent render.
  const fetchRef = useRef(fetchCandles)
  fetchRef.current = fetchCandles
  const execKey = executions.map(e => `${e.time}:${e.side}:${e.quantity}:${e.price}:${e.is_funding ? 1 : 0}`).join('|')
  const targetsKey = targets.map(t => `${t?.price}:${t?.pct}`).join('|')

  const autoInterval = pickInterval ? pickInterval(durationSeconds) : null
  const interval     = tfOverride ?? autoInterval

  // Reset timeframe override when trade changes
  useEffect(() => { setTfOverride(null) }, [entryTime])

  // Persist layer toggles
  useEffect(() => {
    try { localStorage.setItem('tradechart_layers', JSON.stringify(layers)) } catch { /* ignore */ }
  }, [layers])

  // Esc exits fullscreen
  useEffect(() => {
    if (!fullscreen) return
    const onKey = (e) => { if (e.key === 'Escape') setFullscreen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fullscreen])

  // For ESTIMATED confidence, trade-relative overlays are fiction — suppress them.
  const showExecutions = layers.executions && !estimated
  const showAvgLines   = layers.avgLines   && !estimated
  const showMfeMae     = layers.mfeMae     && !estimated
  const showPnlPane    = layers.pnlPane    && !estimated && !disablePnlPane
  const showFunding    = layers.funding    && !estimated
  const showSlTp       = layers.slTp

  useEffect(() => {
    if (!containerRef.current || !entryTime || !fetchRef.current) return

    const entryTs = toTs(entryTime)
    const exitTs  = exitTime ? toTs(exitTime) : entryTs + (durationSeconds ?? 300)
    const buf     = bufferSeconds(durationSeconds, interval)
    const fromTs  = entryTs - buf
    const toTs_   = exitTs  + buf

    rangeRef.current = {
      from: entryTs - Math.floor(buf * 0.75),
      to:   exitTs  + Math.floor(buf * 0.75),
    }

    setStatus('loading')
    let chart   = null
    let cleanup = false

    fetchRef.current(symbol, fromTs, toTs_, interval)
      .then(({ candles }) => {
        if (cleanup || !containerRef.current) return
        if (!candles?.length) throw new Error('No candle data returned')

        const lastCandleTs = candles[candles.length - 1].time
        const intervalSec = Math.max(intervalMinutes(interval) * 60, 60)

        chart = createChart(containerRef.current, {
          ...THEME,
          width:  containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
          handleScroll: true,
          handleScale:  true,
        })
        chartRef.current = chart

        const series = chart.addSeries(CandlestickSeries, CANDLE_COLORS)
        series.setData(candles)

        const nonFunding = executions.filter(e => !e.is_funding)

        // ── Execution markers ─────────────────────────────────────────
        // Side-based, slim: buys are blue ▴ under the bar, sells red ▾ above,
        // each labeled with its executed size. size: 0 collapses the chunky
        // canvas shape; the text glyph renders independently at the layout
        // font size in the marker color.
        const fmtQty = (q) => (q == null ? '' : ` ${Number(Number(q).toFixed(4))}`)
        if (showExecutions && nonFunding.length) {
          const markers = nonFunding
            .slice()
            .sort((a, b) => a.time - b.time)
            .map(e => {
              const isBuy = String(e.side).toUpperCase() === 'BUY'
              return {
                time: e.time,
                position: isBuy ? 'belowBar' : 'aboveBar',
                color: isBuy ? '#38bdf8' : '#de576f',
                shape: 'circle',
                size: 0,
                text: `${isBuy ? '▴' : '▾'}${fmtQty(e.quantity)}`,
              }
            })

          if (showFunding) {
            for (const e of executions.filter(x => x.is_funding)) {
              markers.push({ time: e.time, position: 'inBar', color: '#f59e0b', shape: 'circle', text: '', size: 0.5 })
            }
          }

          if (markers.length) {
            markers.sort((a, b) => a.time - b.time)
            createSeriesMarkers(series, markers)
          }
        } else if (showFunding) {
          const fundMarkers = executions.filter(x => x.is_funding)
            .map(e => ({ time: e.time, position: 'inBar', color: '#f59e0b', shape: 'circle', text: '', size: 0.5 }))
            .sort((a, b) => a.time - b.time)
          if (fundMarkers.length) createSeriesMarkers(series, fundMarkers)
        }

        // ── Rolling average lines ─────────────────────────────────────
        if (showAvgLines && nonFunding.length) {
          const { entryLine, exitLine } = rollingAvgLines(executions, direction)
          const extend = (line) => {
            // snap to candle boundaries — off-grid times would inject phantom
            // time-scale columns and stretch the trade region
            const pts = snapToInterval(line, intervalSec)
            if (pts.length) {
              // closed trades: the avg lines end AT the exit — running them to
              // the latest candle paints them across price action after the
              // trade. Open trades extend to the last candle (still live).
              const rawTail = exitTime ? exitTs : lastCandleTs
              const tail = Math.floor(rawTail / intervalSec) * intervalSec
              const last = pts[pts.length - 1]
              if (tail > last.time) pts.push({ time: tail, value: last.value })
            }
            return pts
          }
          const lineOpts = { lineWidth: 1, lineStyle: LineStyle.Dashed, lastValueVisible: false, priceLineVisible: false }
          if (entryLine.length) {
            const es = chart.addSeries(LineSeries, { ...lineOpts, color: '#38bdf8' })
            es.setData(extend(entryLine))
          }
          if (exitLine.length) {
            const xs = chart.addSeries(LineSeries, { ...lineOpts, color: '#f59e0b' })
            xs.setData(extend(exitLine))
          }
        }

        // ── MFE / MAE bands ───────────────────────────────────────────
        if (showMfeMae && avgEntry != null) {
          if (Number.isFinite(mfePrice)) {
            series.createPriceLine({
              price: avgEntry + mfePrice * dirSign,
              color: '#00d4aa', lineWidth: 1, lineStyle: LineStyle.Dotted, title: 'MFE', axisLabelVisible: true,
            })
          }
          if (Number.isFinite(maePrice)) {
            series.createPriceLine({
              price: avgEntry - maePrice * dirSign,
              color: '#de576f', lineWidth: 1, lineStyle: LineStyle.Dotted, title: 'MAE', axisLabelVisible: true,
            })
          }
        }

        // ── SL / targets ──────────────────────────────────────────────
        if (showSlTp) {
          if (Number.isFinite(stop)) {
            series.createPriceLine({
              price: stop, color: '#de576f', lineWidth: 1, lineStyle: LineStyle.Dashed, title: 'SL', axisLabelVisible: true,
            })
          }
          targets.forEach((t, idx) => {
            if (!Number.isFinite(t?.price)) return
            series.createPriceLine({
              price: t.price, color: '#00d4aa', lineWidth: 1, lineStyle: LineStyle.Dashed,
              title: `TP${idx + 1}`, axisLabelVisible: true,
            })
          })
        }

        // ── Running PnL pane ──────────────────────────────────────────
        let pnlSeries = null
        if (showPnlPane && nonFunding.length) {
          const pnlData = dedupeByTime(runningPnlSeries(candles, executions, direction))
          if (pnlData.length) {
            pnlSeries = chart.addSeries(BaselineSeries, {
              baseValue: { type: 'price', price: 0 },
              topLineColor:   '#00d4aa',
              topFillColor1:  'rgba(0,212,170,0.28)',
              topFillColor2:  'rgba(0,212,170,0.05)',
              bottomLineColor: '#de576f',
              bottomFillColor1: 'rgba(222,87,111,0.05)',
              bottomFillColor2: 'rgba(222,87,111,0.28)',
              lineWidth: 1,
              lastValueVisible: false,
              priceLineVisible: false,
            }, 1) // paneIndex 1 — v5 supports the 3-arg overload (verified in typings.d.ts)
            pnlSeries.setData(pnlData)
            const panes = chart.panes()
            if (panes.length > 1) panes[1].setHeight(Math.max(80, Math.floor(containerRef.current.clientHeight * 0.22)))
          }
        }

        chart.timeScale().setVisibleRange(rangeRef.current)

        // ── Trade duration shading overlay ────────────────────────────
        function refreshShading() {
          const el = shadingRef.current
          const c  = chartRef.current
          if (!el || !c) return
          const x1 = c.timeScale().timeToCoordinate(entryTs)
          const x2 = c.timeScale().timeToCoordinate(exitTs)
          if (x1 == null || x2 == null) { el.style.opacity = '0'; return }
          el.style.left    = `${Math.min(x1, x2)}px`
          el.style.width   = `${Math.max(Math.abs(x2 - x1), 4)}px`
          el.style.opacity = '1'
        }
        chart.timeScale().subscribeVisibleTimeRangeChange(refreshShading)
        setTimeout(refreshShading, 50)

        // ── Resize ────────────────────────────────────────────────────
        const ro = new ResizeObserver(() => {
          if (containerRef.current && chart) {
            chart.applyOptions({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight })
            setTimeout(refreshShading, 16)
          }
        })
        ro.observe(containerRef.current)
        chart._ro = ro

        // ── Lazy history loading ──────────────────────────────────────
        // Panning within ~15 bars of either edge fetches another chunk and
        // prepends/appends it (official lightweight-charts infinite-history
        // pattern: setData inside the logical-range subscription preserves
        // the view). The source decides the floor: when a fetch comes back
        // empty (Bybit pre-listing, Yahoo intraday retention), that edge is
        // marked exhausted and we stop asking.
        let allCandles = candles
        let loadingHist = false
        let noOlder = false
        let noNewer = false
        const CHUNK_BARS = 600

        async function loadMore(edge) {
          if (loadingHist || cleanup) return
          loadingHist = true
          try {
            let from, to
            if (edge === 'older') {
              to = allCandles[0].time - 1
              from = to - CHUNK_BARS * intervalSec
            } else {
              from = allCandles[allCandles.length - 1].time + 1
              to = Math.min(from + CHUNK_BARS * intervalSec, Math.floor(Date.now() / 1000))
              if (to <= from) { noNewer = true; return }
            }
            const res = await fetchRef.current(symbol, from, to, interval)
            if (cleanup) return
            const firstT = allCandles[0].time
            const lastT = allCandles[allCandles.length - 1].time
            const fresh = (res?.candles || []).filter(c =>
              edge === 'older' ? c.time < firstT : c.time > lastT)
            if (!fresh.length) {
              if (edge === 'older') noOlder = true; else noNewer = true
              return
            }
            allCandles = edge === 'older' ? [...fresh, ...allCandles] : [...allCandles, ...fresh]
            series.setData(allCandles)
            if (pnlSeries) {
              pnlSeries.setData(dedupeByTime(runningPnlSeries(allCandles, executions, direction)))
            }
          } catch {
            // source refused (rate limit, retention wall) — stop asking this edge
            if (edge === 'older') noOlder = true; else noNewer = true
          } finally {
            loadingHist = false
          }
        }

        function onLogicalRange(range) {
          if (!range || cleanup) return
          const info = series.barsInLogicalRange(range)
          if (!info) return
          if (info.barsBefore < 15 && !noOlder) loadMore('older')
          else if (info.barsAfter < 15 && !noNewer) loadMore('newer')
        }
        chart.timeScale().subscribeVisibleLogicalRangeChange(onLogicalRange)

        setStatus('ok')
      })
      .catch((err) => {
        if (!cleanup) { setErrorMsg(err.message ?? 'Unknown error'); setStatus('error') }
      })

    return () => {
      cleanup = true
      chartRef.current = null
      if (chart) { chart._ro?.disconnect(); chart.remove() }
    }
    // Full rebuild on any layer toggle is acceptable — keeps layer logic simple.
    // execKey/targetsKey stand in for the executions/targets arrays so unstable
    // identities from the parent can't cause a rebuild storm.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    symbol, direction, entryTime, exitTime, durationSeconds, execKey,
    mfePrice, maePrice, avgEntry, stop, targetsKey, interval, estimated,
    showExecutions, showAvgLines, showMfeMae, showFunding, showSlTp, showPnlPane,
  ])

  function snapToTrade() {
    if (chartRef.current && rangeRef.current) {
      chartRef.current.timeScale().setVisibleRange(rangeRef.current)
      setFreeMode(false)
    }
  }

  function goFree() {
    if (chartRef.current) {
      chartRef.current.timeScale().fitContent()
      setFreeMode(true)
    }
  }

  const toggleLayer = (key) => setLayers(prev => ({ ...prev, [key]: !prev[key] }))

  // ── Legend strip ────────────────────────────────────────────────────────────
  const leftOnTable = (Number.isFinite(mfeUsd) && Number.isFinite(realizedPnl))
    ? mfeUsd - Math.max(realizedPnl, 0)
    : null
  const legendSegments = []
  if (Number.isFinite(mfeUsd))   legendSegments.push({ label: 'MFE', value: fmtUsd(mfeUsd), color: '#00d4aa' })
  if (Number.isFinite(maeUsd))   legendSegments.push({ label: 'MAE', value: fmtUsd(-Math.abs(maeUsd)), color: '#de576f' })
  if (Number.isFinite(leftOnTable)) legendSegments.push({ label: 'Left on table', value: fmtUsd(leftOnTable), color: leftOnTable > 0 ? '#f59e0b' : '#8d91a6' })
  if (Number.isFinite(totalFunding) && totalFunding !== 0) legendSegments.push({ label: 'Funding', value: fmtUsd(totalFunding), color: totalFunding >= 0 ? '#00d4aa' : '#de576f' })

  const LAYER_ITEMS = [
    { key: 'executions', label: 'Executions', disabled: estimated },
    { key: 'avgLines',   label: 'Avg lines',  disabled: estimated },
    { key: 'mfeMae',     label: 'MFE / MAE',  disabled: estimated },
    { key: 'funding',    label: 'Funding',    disabled: estimated },
    { key: 'slTp',       label: 'SL / TP',    disabled: false },
    ...(disablePnlPane ? [] : [{ key: 'pnlPane', label: 'PnL pane', disabled: estimated }]),
  ]

  return (
    <div className={fullscreen ? 'fixed inset-0 z-50 bg-[#161718] p-4 flex flex-col' : 'relative w-full h-full flex flex-col'}>
      <div className="relative w-full flex-1 min-h-0 bg-[#161718]">
        <div ref={containerRef} className="w-full h-full" />

        {/* Trade duration shading */}
        <div
          ref={shadingRef}
          className="absolute top-0 bottom-0 pointer-events-none opacity-0"
          style={{
            backgroundColor: 'rgb(var(--accent-rgb)/0.05)',
            borderLeft:  '1px solid rgb(var(--accent-rgb)/0.2)',
            borderRight: '1px solid rgb(var(--accent-rgb)/0.2)',
          }}
        />

        {/* Timeframe selector */}
        {status === 'ok' && intervals.length > 0 && (
          <div className="absolute top-2 left-2 z-10 flex items-center gap-0.5 bg-[#1e2024]/90 border border-[#2a2c30] rounded-lg p-0.5 backdrop-blur-sm">
            {intervals.map(tf => {
              const active = tfOverride === tf.value
              return (
                <button
                  key={tf.value ?? 'auto'}
                  onClick={() => setTfOverride(tf.value)}
                  className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                    active ? 'bg-[rgb(var(--accent-rgb)/0.2)] text-[var(--accent)]' : 'text-[#4e5166] hover:text-[#8d91a6]'
                  }`}
                >
                  {tf.value === null ? 'Auto' : tf.label}
                </button>
              )
            })}
          </div>
        )}

        {/* Top-right controls: confidence chip, layers, fullscreen */}
        <div className="absolute top-2 right-2 z-20 flex items-center gap-1.5">
          {estimated && (
            <span
              className="px-2 py-1 rounded-lg text-[10px] font-medium bg-[#f59e0b]/15 text-[#f59e0b] border border-[#f59e0b]/30 backdrop-blur-sm cursor-help"
              title="This trade's entry time can't be verified against the exchange's fill history, so execution markers, avg lines, MFE/MAE and the PnL pane are hidden — they would be guesses. The chart centers on the close."
            >
              entry time unverified
            </span>
          )}

          <div className="relative">
            <button
              onClick={() => setLayersOpen(o => !o)}
              className="flex items-center gap-1.5 px-2 py-1 bg-[#1e2024]/90 border border-[#2a2c30] text-[#8d91a6] rounded-lg text-[10px] font-medium backdrop-blur-sm hover:bg-[#2a2c30] hover:text-[#c9cddb] transition-colors"
            >
              <Layers className="w-3 h-3" /> Layers
            </button>
            {layersOpen && (
              <div className="absolute right-0 mt-1 w-40 bg-[#1e2024] border border-[#2a2c30] rounded-lg p-1.5 shadow-xl">
                {LAYER_ITEMS.map(item => (
                  <label
                    key={item.key}
                    className={`flex items-center gap-2 px-2 py-1 rounded text-[11px] ${
                      item.disabled ? 'text-[#4e5166] opacity-50 cursor-not-allowed' : 'text-[#8d91a6] hover:bg-[#2a2c30] cursor-pointer'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={!!layers[item.key]}
                      disabled={item.disabled}
                      onChange={() => toggleLayer(item.key)}
                      className="accent-[var(--accent)] w-3 h-3"
                    />
                    {item.label}
                  </label>
                ))}
              </div>
            )}
          </div>

          <button
            onClick={() => setFullscreen(f => !f)}
            className="flex items-center justify-center p-1.5 bg-[#1e2024]/90 border border-[#2a2c30] text-[#8d91a6] rounded-lg backdrop-blur-sm hover:bg-[#2a2c30] hover:text-[#c9cddb] transition-colors"
            title={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
          >
            {fullscreen ? <Minimize2 className="w-3 h-3" /> : <Maximize2 className="w-3 h-3" />}
          </button>
        </div>

        {/* Snap / Free browse toggle */}
        {status === 'ok' && (
          <div className="absolute bottom-2 left-2 z-10">
            {freeMode ? (
              <button
                onClick={snapToTrade}
                className="flex items-center gap-1.5 px-2 py-1 bg-[#1e2024]/90 border border-[rgb(var(--accent-rgb)/0.4)] text-[var(--accent)] rounded-lg text-[10px] font-medium backdrop-blur-sm hover:bg-[#2a2c30] transition-colors"
              >
                <Crosshair className="w-3 h-3" /> Snap to trade
              </button>
            ) : (
              <button
                onClick={goFree}
                className="flex items-center gap-1.5 px-2 py-1 bg-[#1e2024]/90 border border-[#2a2c30] text-[#4e5166] rounded-lg text-[10px] font-medium backdrop-blur-sm hover:bg-[#2a2c30] hover:text-[#8d91a6] transition-colors"
              >
                <Maximize2 className="w-3 h-3" /> Free browse
              </button>
            )}
          </div>
        )}

        {status === 'loading' && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#161718]">
            <div className="flex items-center gap-2 text-[#4e5166] text-[12px]">
              <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" strokeDasharray="32" strokeLinecap="round" />
              </svg>
              Loading chart data…
            </div>
          </div>
        )}

        {status === 'error' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-[#161718]">
            <p className="text-[#4e5166] text-[12px]">Chart data unavailable</p>
            <p className="text-[#2a2d3a] text-[10px] font-mono max-w-xs text-center">{errorMsg}</p>
          </div>
        )}
      </div>

      {/* Legend strip */}
      {legendSegments.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 px-1 pt-1.5 text-[11px] text-[#4e5166]">
          {legendSegments.map((seg, i) => (
            <span key={seg.label} className="flex items-center gap-1">
              {i > 0 && <span className="text-[#2a2c30]">·</span>}
              {seg.label} <span style={{ color: seg.color }}>{seg.value}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
