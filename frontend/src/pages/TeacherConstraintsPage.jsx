// pages/TeacherConstraintsPage.jsx
import { useState } from 'react'

const DAYS     = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
const HOURS    = 8

function buildDefaultUnavailability(teachers) {
  const result = {}
  teachers.forEach((t) => {
    const blocked = new Set()
    DAYS.forEach((d) => {
      const val = t.availability?.[d]
      if (val === 0 || val === false) {
        for (let h = 0; h < HOURS; h++) blocked.add(`${d}-${h}`)
      }
    })
    result[t.name] = blocked
  })
  return result
}

function buildDefaultMaxGaps(teachers) {
  const result = {}
  teachers.forEach((t) => { result[t.name] = 2 })
  return result
}

function blockedToPayload(blocked) {
  return [...blocked].map((key) => {
    const [d, h] = key.split('-')
    return [DAYS.indexOf(d), parseInt(h, 10)]
  })
}

function cloneState(state) {
  return Object.fromEntries(
    Object.entries(state).map(([k, v]) => [k, new Set(v)])
  )
}

function IconArrowLeft() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
    </svg>
  )
}

function IconArrowRight() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
    </svg>
  )
}

function GapStepper({ value, onChange, disabled }) {
  return (
    <div
      onClick={(e) => e.stopPropagation()}
      style={{ display: 'flex', alignItems: 'center', gap: 4 }}
    >
      <span style={{ fontSize: 12, color: 'var(--c-ink-3)', marginRight: 2 }}>
        Max gap
      </span>
      <button
        onClick={() => onChange(Math.max(0, value - 1))}
        disabled={disabled || value <= 0}
        style={{
          width: 22, height: 22, borderRadius: 'var(--r-sm)',
          border: '1px solid var(--c-border-h)', background: 'var(--c-bg)',
          cursor: disabled || value <= 0 ? 'default' : 'pointer',
          fontSize: 14, display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'var(--c-ink-2)', fontFamily: 'var(--f-body)',
          opacity: disabled || value <= 0 ? 0.4 : 1,
        }}
      >−</button>
      <span style={{
        fontSize: 13, fontWeight: 500, minWidth: 18, textAlign: 'center',
        color: 'var(--c-ink)',
      }}>
        {value}
      </span>
      <button
        onClick={() => onChange(Math.min(7, value + 1))}
        disabled={disabled || value >= 7}
        style={{
          width: 22, height: 22, borderRadius: 'var(--r-sm)',
          border: '1px solid var(--c-border-h)', background: 'var(--c-bg)',
          cursor: disabled || value >= 7 ? 'default' : 'pointer',
          fontSize: 14, display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'var(--c-ink-2)', fontFamily: 'var(--f-body)',
          opacity: disabled || value >= 7 ? 0.4 : 1,
        }}
      >+</button>
    </div>
  )
}

function AvailabilityGrid({ blocked, onChange, readOnly }) {
  const [dragging, setDragging]   = useState(false)
  const [dragValue, setDragValue] = useState(null)

  const isBlocked    = (d, h) => blocked.has(`${d}-${h}`)
  const isDayBlocked = (d) => Array.from({ length: HOURS }, (_, h) => blocked.has(`${d}-${h}`)).every(Boolean)
  const isHourBlocked = (h) => DAYS.every((d) => blocked.has(`${d}-${h}`))

  const toggle = (d, h, forceValue) => {
    if (readOnly) return
    const key  = `${d}-${h}`
    const next = new Set(blocked)
    const val  = forceValue !== undefined ? forceValue : !blocked.has(key)
    if (val) next.add(key); else next.delete(key)
    onChange(next)
  }

  const toggleDay = (d) => {
    if (readOnly) return
    const allBlocked = Array.from({ length: HOURS }, (_, h) => blocked.has(`${d}-${h}`)).every(Boolean)
    const next = new Set(blocked)
    for (let h = 0; h < HOURS; h++) {
      const key = `${d}-${h}`
      if (allBlocked) next.delete(key); else next.add(key)
    }
    onChange(next)
  }

  const toggleHour = (h) => {
    if (readOnly) return
    const allBlocked = DAYS.every((d) => blocked.has(`${d}-${h}`))
    const next = new Set(blocked)
    DAYS.forEach((d) => {
      const key = `${d}-${h}`
      if (allBlocked) next.delete(key); else next.add(key)
    })
    onChange(next)
  }

  const blockedCount = blocked.size
  const totalSlots   = DAYS.length * HOURS

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, fontSize: 13, color: 'var(--c-ink-3)' }}>
        <span>
          {totalSlots - blockedCount} <span style={{ color: 'var(--c-success)', fontWeight: 500 }}>available</span>
          {' '}· {blockedCount} <span style={{ color: 'var(--c-danger)', fontWeight: 500 }}>blocked</span>
          {' '}of {totalSlots} slots
        </span>
        {!readOnly && blockedCount > 0 && (
          <button
            onClick={() => onChange(new Set())}
            style={{
              fontSize: 12, padding: '2px 9px',
              border: '1px solid var(--c-border-h)', borderRadius: 'var(--r-sm)',
              background: 'transparent', color: 'var(--c-ink-3)',
              cursor: 'pointer', fontFamily: 'var(--f-body)',
            }}
          >Clear all</button>
        )}
      </div>

      <div style={{ userSelect: 'none' }} onMouseLeave={() => setDragging(false)} onMouseUp={() => setDragging(false)}>
        <div style={{ display: 'grid', gridTemplateColumns: `32px repeat(${DAYS.length}, 1fr)`, gap: 3, marginBottom: 3 }}>
          <div />
          {DAYS.map((d) => {
            const dayBlocked = isDayBlocked(d)
            return (
              <button key={d} onClick={() => toggleDay(d)} style={{
                fontSize: 12, fontWeight: 500, padding: '5px 2px',
                borderRadius: 'var(--r-sm)',
                border: `1px solid ${dayBlocked ? 'rgba(192,57,43,0.3)' : 'var(--c-border)'}`,
                background: dayBlocked ? 'rgba(192,57,43,0.08)' : 'var(--c-surface)',
                color: dayBlocked ? 'var(--c-danger)' : 'var(--c-ink-2)',
                cursor: readOnly ? 'default' : 'pointer', textAlign: 'center',
                fontFamily: 'var(--f-body)', transition: 'all 0.1s', opacity: readOnly ? 0.7 : 1,
              }}>{d}</button>
            )
          })}
        </div>

        {Array.from({ length: HOURS }, (_, h) => {
          const hourBlocked = isHourBlocked(h)
          return (
            <div key={h} style={{ display: 'grid', gridTemplateColumns: `32px repeat(${DAYS.length}, 1fr)`, gap: 3, marginBottom: 3 }}>
              <button onClick={() => toggleHour(h)} style={{
                fontSize: 11, fontWeight: 500, padding: '0 2px',
                borderRadius: 'var(--r-sm)',
                border: `1px solid ${hourBlocked ? 'rgba(192,57,43,0.3)' : 'var(--c-border)'}`,
                background: hourBlocked ? 'rgba(192,57,43,0.08)' : 'var(--c-surface)',
                color: hourBlocked ? 'var(--c-danger)' : 'var(--c-ink-3)',
                cursor: readOnly ? 'default' : 'pointer', textAlign: 'center',
                fontFamily: 'var(--f-body)', height: 32, transition: 'all 0.1s', opacity: readOnly ? 0.7 : 1,
              }}>H{h + 1}</button>
              {DAYS.map((d) => {
                const isBlk = isBlocked(d, h)
                return (
                  <div key={d}
                    onMouseDown={() => { if (readOnly) return; const val = !isBlocked(d, h); setDragging(true); setDragValue(val); toggle(d, h, val) }}
                    onMouseEnter={() => { if (dragging && !readOnly) toggle(d, h, dragValue) }}
                    style={{
                      height: 32, borderRadius: 'var(--r-sm)',
                      border: `1px solid ${isBlk ? 'rgba(192,57,43,0.25)' : 'var(--c-border)'}`,
                      background: isBlk ? 'rgba(192,57,43,0.12)' : 'rgba(30,124,77,0.07)',
                      cursor: readOnly ? 'default' : 'pointer',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      transition: 'background 0.1s, border-color 0.1s', fontSize: 14,
                    }}
                  >
                    {isBlk
                      ? <span style={{ color: 'var(--c-danger)', opacity: 0.7 }}>✕</span>
                      : <span style={{ color: 'var(--c-success)', opacity: 0.5 }}>✓</span>
                    }
                  </div>
                )
              })}
            </div>
          )
        })}

        <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 12, color: 'var(--c-ink-3)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{ width: 14, height: 14, borderRadius: 3, background: 'rgba(30,124,77,0.07)', border: '1px solid var(--c-border)' }} />
            Available
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{ width: 14, height: 14, borderRadius: 3, background: 'rgba(192,57,43,0.12)', border: '1px solid rgba(192,57,43,0.25)' }} />
            Blocked
          </div>
          {!readOnly && <span style={{ fontStyle: 'italic' }}>Click or drag to toggle · Click day/hour headers to toggle row/column</span>}
        </div>
      </div>
    </div>
  )
}

function TeacherSection({ teacher, blocked, maxGap, readOnly, onBlockedChange, onGapChange }) {
  const [expanded, setExpanded] = useState(false)

  const blockedCount  = blocked.size
  const totalSlots    = DAYS.length * HOURS

  return (
    <div style={{ border: '1px solid var(--c-border)', borderRadius: 'var(--r-lg)', marginBottom: 8, overflow: 'hidden' }}>
      <button
        onClick={() => setExpanded((e) => !e)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', padding: '12px 18px',
          border: 'none', background: 'var(--c-surface)',
          cursor: 'pointer', textAlign: 'left', fontFamily: 'var(--f-body)',
          borderBottom: expanded ? '1px solid var(--c-border)' : 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 0 }}>
          <span style={{ fontSize: 14, fontWeight: 500, color: 'var(--c-ink)' }}>
            {teacher.name}
          </span>

          {/* day pills */}
          <div style={{ display: 'flex', gap: 3 }}>
            {DAYS.map((d) => {
              const dayBlocked = Array.from({ length: HOURS }, (_, h) => blocked.has(`${d}-${h}`)).every(Boolean)
              return (
                <span key={d} style={{
                  fontSize: 11, padding: '2px 5px', borderRadius: 4, fontWeight: 500,
                  background: dayBlocked ? 'rgba(192,57,43,0.08)' : 'rgba(30,124,77,0.08)',
                  color: dayBlocked ? 'var(--c-danger)' : 'var(--c-success)',
                  textDecoration: dayBlocked ? 'line-through' : 'none',
                }}>{d}</span>
              )
            })}
          </div>

          {/* slot count */}
          <span style={{ fontSize: 12, color: 'var(--c-ink-3)' }}>
            {totalSlots - blockedCount}/{totalSlots} slots
          </span>

          {/* gap stepper — always visible in header */}
          <div style={{ marginLeft: 'auto', marginRight: 8 }}>
            <GapStepper value={maxGap} onChange={onGapChange} disabled={readOnly} />
          </div>
        </div>
        <span style={{ fontSize: 14, color: 'var(--c-ink-3)', lineHeight: 1, flexShrink: 0 }}>
          {expanded ? '▴' : '▾'}
        </span>
      </button>

      {expanded && (
        <div style={{ padding: 18, background: 'var(--c-bg)' }}>
          {/* max gap explanation when expanded */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '8px 12px', borderRadius: 'var(--r-md)',
            background: 'rgba(43,92,230,0.04)', border: '1px solid rgba(43,92,230,0.12)',
            fontSize: 12, color: 'var(--c-ink-2)', marginBottom: 14,
          }}>
            <span>Max gap:</span>
            <strong>{maxGap}</strong>
            <span style={{ color: 'var(--c-ink-3)' }}>
              — at most {maxGap} free hour{maxGap !== 1 ? 's' : ''} between lessons per day
            </span>
          </div>
          <AvailabilityGrid
            blocked={blocked}
            onChange={onBlockedChange}
            readOnly={readOnly}
          />
        </div>
      )}
    </div>
  )
}

export default function TeacherConstraintsPage({ teachers = [], onContinue, onBack }) {
  const [mode, setMode]       = useState('recommended')
  const [recommended]         = useState(() => buildDefaultUnavailability(teachers))
  const [custom, setCustom]   = useState(() => buildDefaultUnavailability(teachers))

  // max gap state — always editable regardless of mode
  const [maxGaps, setMaxGaps] = useState(() => buildDefaultMaxGaps(teachers))

  const readOnly    = mode === 'recommended'
  const activeState = readOnly ? recommended : custom

  function handleBlockedChange(teacherName, nextBlocked) {
    if (readOnly) return
    setCustom((prev) => ({ ...prev, [teacherName]: nextBlocked }))
  }

  function handleGapChange(teacherName, value) {
    setMaxGaps((prev) => ({ ...prev, [teacherName]: value }))
  }

  function handleContinue() {
    const payload = teachers.map((t) => ({
      name: t.name,
      unavailable_slots: blockedToPayload(activeState[t.name] ?? new Set()),
      max_gap: maxGaps[t.name] ?? 6,
    }))
    onContinue?.(payload)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>

      <div style={{ padding: '24px 32px 0', borderBottom: '1px solid var(--c-border)', background: 'var(--c-surface)' }}>
        <h1 style={{ fontFamily: 'var(--f-display)', fontSize: 26, letterSpacing: '-0.5px', marginBottom: 4, color: 'var(--c-ink)' }}>
          Teacher constraints
        </h1>
        <p style={{ fontSize: 14, color: 'var(--c-ink-2)', marginBottom: 20 }}>
          Set availability and maximum scheduling gap for each teacher.
        </p>
      </div>

      <div style={{ flex: 1, padding: '24px 32px', maxWidth: 860, width: '100%', margin: '0 auto' }}>

        <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
          {[
            { key: 'recommended', label: '✦ Use imported' },
            { key: 'custom',      label: '⚙ Customize'   },
          ].map(({ key, label }) => (
            <button key={key} onClick={() => {
              if (key === 'custom' && mode === 'recommended') setCustom(cloneState(recommended))
              setMode(key)
            }} style={{
              padding: '8px 20px', borderRadius: 'var(--r-lg)',
              border: mode === key ? 'none' : '1px solid var(--c-border-h)',
              background: mode === key ? 'var(--c-accent)' : 'var(--c-surface)',
              color: mode === key ? '#fff' : 'var(--c-ink-2)',
              cursor: 'pointer', fontSize: 13, fontWeight: 500,
              fontFamily: 'var(--f-body)', transition: 'all .15s',
            }}>{label}</button>
          ))}
        </div>

        {readOnly ? (
          <div style={{
            display: 'flex', gap: 10, alignItems: 'flex-start',
            padding: '10px 14px', borderRadius: 'var(--r-md)',
            background: 'rgba(43,92,230,.05)', border: '1px solid rgba(43,92,230,.15)',
            fontSize: 13, color: 'var(--c-ink-2)', marginBottom: 20,
          }}>
            <span style={{ fontSize: 16, marginTop: 1 }}>ℹ</span>
            <span>
              Availability is imported from your Excel file. Switch to <strong>Customize</strong> to override slots.
              Max gap can be adjusted for any teacher regardless of mode.
            </span>
          </div>
        ) : (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '10px 14px',
            background: 'rgba(180,130,0,0.07)', border: '1px solid rgba(180,130,0,0.25)',
            borderRadius: 'var(--r-md)', marginBottom: 20, gap: 10,
          }}>
            <span style={{ fontSize: 13, color: '#7a5800' }}>
              ✎ Editing custom availability — click or drag slots to toggle.
            </span>
            <button
              onClick={() => setCustom(cloneState(recommended))}
              style={{
                fontSize: 12, padding: '4px 11px',
                border: '1px solid rgba(180,130,0,0.3)', borderRadius: 'var(--r-sm)',
                background: 'transparent', color: '#7a5800',
                cursor: 'pointer', whiteSpace: 'nowrap', fontWeight: 500,
                fontFamily: 'var(--f-body)',
              }}
            >↺ Reset to imported</button>
          </div>
        )}

        {teachers.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '3rem 0', color: 'var(--c-ink-3)', fontSize: 14 }}>
            No teachers loaded. Upload an Excel file first.
          </div>
        ) : (
          teachers.map((t) => (
            <TeacherSection
              key={t.name}
              teacher={t}
              blocked={activeState[t.name] ?? new Set()}
              maxGap={maxGaps[t.name] ?? 2}
              readOnly={readOnly}
              onBlockedChange={(next) => handleBlockedChange(t.name, next)}
              onGapChange={(val) => handleGapChange(t.name, val)}
            />
          ))
        )}

        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          borderTop: '1px solid var(--c-border)', paddingTop: 20, marginTop: 40,
        }}>
          <button onClick={onBack} style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '11px 24px', borderRadius: 100,
            border: '1px solid var(--c-border-h)',
            background: 'var(--c-surface)', color: 'var(--c-ink-2)',
            fontFamily: 'var(--f-body)', fontSize: 14, fontWeight: 500, cursor: 'pointer',
          }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--c-ink-3)')}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--c-border-h)')}
          >
            <IconArrowLeft /> Back
          </button>

          <button onClick={handleContinue} style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '11px 28px', borderRadius: 100, border: 'none',
            cursor: 'pointer', fontFamily: 'var(--f-body)', fontSize: 14, fontWeight: 500,
            background: 'var(--c-accent)', color: '#fff',
            boxShadow: '0 4px 18px rgba(43,92,230,0.28)', transition: 'background 0.2s',
          }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--c-accent-h)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--c-accent)')}
          >
            Continue <IconArrowRight />
          </button>
        </div>

      </div>
    </div>
  )
}