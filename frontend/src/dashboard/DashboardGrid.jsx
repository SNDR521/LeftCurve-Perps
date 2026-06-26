import { useState } from 'react'
import useIsMobile from '../lib/useIsMobile'
import { Responsive, WidthProvider } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import { Plus, Lock, Unlock, X, RotateCcw, GripVertical } from 'lucide-react'

const ResponsiveGrid = WidthProvider(Responsive)

// ── Layout persistence helpers (keyed by props) ───────────────────
function loadLayout(storageKey) {
  try {
    const raw = localStorage.getItem(storageKey)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}
function saveLayout(storageKey, layout) {
  try { localStorage.setItem(storageKey, JSON.stringify(layout)) } catch {}
}
function loadWidgets(widgetsKey) {
  try {
    const raw = localStorage.getItem(widgetsKey)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}
function saveWidgets(widgetsKey, widgets) {
  try { localStorage.setItem(widgetsKey, JSON.stringify(widgets)) } catch {}
}

/**
 * DashboardGrid — reusable grid shell.
 *
 * Props:
 *   registry       — array of widget descriptors ({ id, label, icon, component, defaultW, defaultH, minW, minH, props })
 *   defaultLayout  — default lg layout array
 *   defaultWidgets — default widget id array
 *   storageKey     — localStorage key for layout
 *   widgetsKey     — localStorage key for active widgets list
 */
export default function DashboardGrid({ registry, defaultLayout, defaultWidgets, storageKey, widgetsKey, headerLeft }) {
  const isMobile = useIsMobile()
  const [editing, setEditing] = useState(false)
  const [showPicker, setShowPicker] = useState(false)

  const [activeWidgets, setActiveWidgets] = useState(() => loadWidgets(widgetsKey) || [...defaultWidgets])
  const [layouts, setLayouts] = useState(() => {
    const saved = loadLayout(storageKey)
    return saved || { lg: [...defaultLayout] }
  })

  // ── Widget management ─────────────────────────────────────────
  function handleLayoutChange(newLayout) {
    const updated = { lg: newLayout }
    setLayouts(updated)
    saveLayout(storageKey, updated)
  }

  function removeWidget(widgetId) {
    const next = activeWidgets.filter(w => w !== widgetId)
    setActiveWidgets(next)
    saveWidgets(widgetsKey, next)
    const nextLayout = { lg: (layouts.lg || []).filter(l => l.i !== widgetId) }
    setLayouts(nextLayout)
    saveLayout(storageKey, nextLayout)
  }

  function addWidget(widgetId) {
    if (activeWidgets.includes(widgetId)) return
    const def = registry.find(w => w.id === widgetId)
    if (!def) return
    const maxY = Math.max(0, ...(layouts.lg || []).map(l => l.y + l.h))
    const newItem = { i: widgetId, x: 0, y: maxY, w: def.defaultW, h: def.defaultH }
    const next = [...activeWidgets, widgetId]
    const nextLayout = { lg: [...(layouts.lg || []), newItem] }
    setActiveWidgets(next)
    setLayouts(nextLayout)
    saveWidgets(widgetsKey, next)
    saveLayout(storageKey, nextLayout)
    // Keep the picker open so the user can add several widgets in a row; it
    // closes when they exit edit mode (padlock) or hit the X.
  }

  function resetLayout() {
    setActiveWidgets([...defaultWidgets])
    setLayouts({ lg: [...defaultLayout] })
    saveWidgets(widgetsKey, [...defaultWidgets])
    saveLayout(storageKey, { lg: [...defaultLayout] })
  }

  // Available widgets not yet on dashboard
  const availableWidgets = registry.filter(w => !activeWidgets.includes(w.id))

  return (
    <div className="space-y-3">
      {/* ── Header row: headerLeft slot + Edit / Add / Reset controls ── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">{headerLeft}</div>
        <div className="flex items-center gap-2">
          {editing && (
            <>
              <button onClick={() => setShowPicker(!showPicker)}
                className="flex items-center gap-1.5 px-3 py-2 bg-[#00d4aa]/10 text-[#00d4aa] text-[12px] font-medium rounded-lg hover:bg-[#00d4aa]/20 transition-all">
                <Plus className="w-3.5 h-3.5" /> Add Widget
              </button>
              <button onClick={resetLayout}
                className="p-2 bg-[#1e2024] border border-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6] rounded-lg transition-all"
                title="Reset to default layout">
                <RotateCcw className="w-4 h-4" />
              </button>
            </>
          )}
          {/* Lock stays rightmost so it doesn't shift under the cursor when Add/Reset appear */}
          <button onClick={() => { const next = !editing; setEditing(next); if (!next) setShowPicker(false) }}
            className={`p-2 rounded-lg transition-all ${editing ? 'bg-[var(--accent)] text-white' : 'bg-[#1e2024] border border-[#2a2c30] text-[#4e5166] hover:text-[#8d91a6]'}`}>
            {editing ? <Unlock className="w-4 h-4" /> : <Lock className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* ── Widget Picker Drawer ──────────────────────────── */}
      {showPicker && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-[13px] font-semibold text-white">Add Widget</h3>
            <button onClick={() => setShowPicker(false)} className="p-1 hover:bg-[#2a2c30] rounded-md">
              <X className="w-4 h-4 text-[#4e5166]" />
            </button>
          </div>
          {availableWidgets.length === 0 ? (
            <p className="text-[12px] text-[#4e5166]">All widgets are already on your dashboard.</p>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2">
              {availableWidgets.map(w => (
                <button key={w.id} onClick={() => addWidget(w.id)}
                  className="flex items-center gap-2 p-2.5 bg-[#161718] border border-[#2a2c30] rounded-lg
                             text-left hover:border-[rgb(var(--accent-rgb)/0.3)] hover:bg-[#1e2024] transition-all group">
                  <w.icon className="w-4 h-4 text-[#4e5166] group-hover:text-[var(--accent)] transition-colors shrink-0" />
                  <span className="text-[11px] text-[#8d91a6] group-hover:text-white transition-colors truncate">
                    {w.label}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Widget Grid ───────────────────────────────────── */}
      <ResponsiveGrid
        className="layout"
        layouts={layouts}
        breakpoints={{ lg: 0 }}
        cols={{ lg: isMobile ? 1 : 12 }}
        rowHeight={72}
        isDraggable={editing && !isMobile}
        isResizable={editing && !isMobile}
        onLayoutChange={(layout) => handleLayoutChange(layout)}
        draggableHandle=".widget-drag-handle"
        compactType="vertical"
        margin={[12, 12]}
      >
        {activeWidgets.map(widgetId => {
          const def = registry.find(w => w.id === widgetId)
          if (!def) return null
          const Widget = def.component
          const widgetProps = def.props || {}

          // Find layout item or create default
          const layoutItem = (layouts.lg || []).find(l => l.i === widgetId)

          return (
            <div
              key={widgetId}
              data-grid={layoutItem || { x: 0, y: 0, w: def.defaultW, h: def.defaultH, minW: def.minW, minH: def.minH }}
              className="card p-3 overflow-hidden relative group"
            >
              {/* Edit mode overlay */}
              {editing && (
                <div className="absolute top-1 right-1 left-1 flex items-center justify-between z-10">
                  <div className="widget-drag-handle cursor-grab active:cursor-grabbing p-1 rounded bg-[#2a2c30]/80 hover:bg-[#3a3c42]">
                    <GripVertical className="w-3.5 h-3.5 text-[#4e5166]" />
                  </div>
                  <button onClick={() => removeWidget(widgetId)}
                    className="p-1 rounded bg-[#2a2c30]/80 hover:bg-[#de576f]/20 transition-colors">
                    <X className="w-3.5 h-3.5 text-[#4e5166] hover:text-[#de576f]" />
                  </button>
                </div>
              )}
              <Widget {...widgetProps} />
            </div>
          )
        })}
      </ResponsiveGrid>
    </div>
  )
}
