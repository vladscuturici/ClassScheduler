import { useState, useEffect, useCallback } from 'react'
import { useStore } from '../store'
import { initManual, getManualCandidates, placeManual, clearManual, mergeConstraintsIntoPayload } from '../api'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
const DAY_FULL = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
const HOURS = 8

function subjectColorFor(name) {
  const COLORS = [
    { bg: 'rgba(43,92,230,0.10)', border: 'rgba(43,92,230,0.30)', text: '#1a3a9a' },
    { bg: 'rgba(30,124,77,0.10)', border: 'rgba(30,124,77,0.30)', text: '#0d5c38' },
    { bg: 'rgba(180,80,0,0.10)', border: 'rgba(180,80,0,0.30)', text: '#7a3600' },
    { bg: 'rgba(120,40,160,0.10)', border: 'rgba(120,40,160,0.30)', text: '#5a1a80' },
  ]
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffff
  return COLORS[h % COLORS.length]
}

function Spinner({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="var(--c-accent)" strokeWidth="2.5" strokeLinecap="round">
      <style>{`@keyframes _sp2{to{transform:rotate(360deg)}}`}</style>
      <circle cx="12" cy="12" r="9" strokeOpacity="0.2" />
      <path d="M12 3a9 9 0 0 1 9 9" style={{ animation: '_sp2 0.8s linear infinite', transformOrigin: '12px 12px' }} />
    </svg>
  )
}

const thStyle = {
  padding: '8px 4px', borderBottom: '1px solid var(--c-border)',
  background: 'var(--c-bg)', color: 'var(--c-ink-2)', fontWeight: 500,
  fontSize: 12, whiteSpace: 'nowrap',
}
const tdStyle = { border: '1px solid var(--c-border)', verticalAlign: 'top' }

function btnStyle(variant) {
  const base = {
    borderRadius: 8, fontSize: 13, fontWeight: 500,
    fontFamily: 'var(--f-body)', cursor: 'pointer',
    padding: '8px 16px', transition: 'all 0.15s',
  }
  if (variant === 'outline') return { ...base, border: '1px solid var(--c-border-h)', background: 'var(--c-surface)', color: 'var(--c-ink-2)' }
  if (variant === 'accent')  return { ...base, border: 'none', background: 'var(--c-accent)', color: '#fff' }
  return base
}

export default function ManualPlacementPage({
  sessionId: sessionIdProp,
  customizePayload,
  classConstraintsPayload,
  teacherConstraintsPayload,
  onBack,
  onGenerateFromPartial,
}) {
  const { parsedData } = useStore()
  const sessionId = sessionIdProp ?? parsedData?.session_id

  const [grids, setGrids] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [activeTeacher, setActiveTeacher] = useState(null)
  const [picker, setPicker] = useState(null)       // { day, hour } | null
  const [candidates, setCandidates] = useState([])
  const [candLoading, setCandLoading] = useState(false)
  const [actionError, setActionError] = useState(null)

  // build merged classes/teachers exactly like SearchingPage does
  const baseClasses  = customizePayload?.classes  ?? parsedData?.classes  ?? []
  const baseTeachers = customizePayload?.teachers ?? parsedData?.teachers ?? []
  const { classes: mergedClasses, teachers: mergedTeachers } = mergeConstraintsIntoPayload({
    classes: baseClasses,
    teachers: baseTeachers,
    classConstraintsPayload,
    teacherConstraintsPayload,
  })

  useEffect(() => {
    if (!sessionId) return
    initManual(sessionId, mergedClasses, mergedTeachers)
      .then(data => {
        setGrids(data)
        const sorted = Object.keys(data.teacher_schedules).sort()
        setActiveTeacher(sorted[0] ?? null)
        setLoading(false)
      })
      .catch(e => { setError(e.message); setLoading(false) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  const teacherList = grids ? Object.keys(grids.teacher_schedules).sort() : []

  const openPicker = useCallback((day, hour) => {
    if (!activeTeacher) return
    setPicker({ day, hour })
    setCandLoading(true)
    setActionError(null)
    getManualCandidates(sessionId, activeTeacher, day, hour)
      .then(list => setCandidates(list))
      .catch(e => { setActionError(e.message); setCandidates([]) })
      .finally(() => setCandLoading(false))
  }, [activeTeacher, sessionId])

  const handlePlace = async (cand) => {
    if (!picker) return
    try {
      const updated = await placeManual(sessionId, cand.class_name, cand.subject, activeTeacher, picker.day, picker.hour)
      setGrids(updated)
      setPicker(null)
    } catch (e) {
      setActionError(e.message)
    }
  }

  const handleClear = async (day, hour) => {
    try {
      const updated = await clearManual(sessionId, activeTeacher, day, hour)
      setGrids(updated)
    } catch (e) {
      setActionError(e.message)
    }
  }

  const handleGenerate = () => {
    onGenerateFromPartial?.({ max_solutions: 1, use_balanced_difficulty: false })
  }

  const placedCount = grids
    ? Object.values(grids.teacher_schedules).reduce(
        (sum, sched) => sum + sched.flat().filter(Boolean).length, 0
      )
    : 0

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', flexDirection: 'column', gap: 12 }}>
      <Spinner size={28} />
      <div style={{ fontSize: 13, color: 'var(--c-ink-3)' }}>Setting up empty schedule…</div>
    </div>
  )

  if (error) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 14, color: 'var(--c-danger)' }}>Failed to start: {error}</div>
      <button onClick={onBack} style={btnStyle('outline')}>← Back</button>
    </div>
  )

  const sched = grids?.teacher_schedules?.[activeTeacher]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>

      {/* header */}
      <div style={{
        padding: '16px 24px', borderBottom: '1px solid var(--c-border)',
        background: 'var(--c-surface)', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
      }}>
        <button onClick={onBack} style={{ ...btnStyle('outline'), padding: '7px 14px' }}>
          ← Back
        </button>
        <h1 style={{ fontFamily: 'var(--f-display)', fontSize: 22, letterSpacing: '-0.4px', margin: 0, flex: 1 }}>
          Place slots yourself
        </h1>
        <span style={{ fontSize: 13, color: 'var(--c-ink-3)' }}>{placedCount} placed</span>
        <button onClick={handleGenerate} style={{ ...btnStyle('accent'), padding: '9px 18px' }}>
          Generate schedule from this partial schedule →
        </button>
      </div>

      {actionError && (
        <div style={{ padding: '10px 24px', background: 'rgba(192,57,43,0.06)', borderBottom: '1px solid rgba(192,57,43,0.2)', color: 'var(--c-danger)', fontSize: 13 }}>
          ⚠ {actionError}
          <button onClick={() => setActionError(null)} style={{ marginLeft: 12, ...btnStyle('outline'), padding: '2px 8px', fontSize: 11 }}>Dismiss</button>
        </div>
      )}

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

        {/* sidebar: teachers */}
        <div style={{ width: 180, flexShrink: 0, borderRight: '1px solid var(--c-border)', background: 'var(--c-surface)', overflowY: 'auto', padding: '8px 0' }}>
          <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '.07em', textTransform: 'uppercase', color: 'var(--c-ink-3)', padding: '4px 14px 8px' }}>
            Teachers
          </div>
          {teacherList.map(name => {
            const active = activeTeacher === name
            const count = grids.teacher_schedules[name].flat().filter(Boolean).length
            return (
              <button
                key={name}
                onClick={() => { setActiveTeacher(name); setPicker(null) }}
                style={{
                  display: 'flex', justifyContent: 'space-between', width: '100%', textAlign: 'left',
                  padding: '7px 14px', border: 'none', fontFamily: 'var(--f-body)',
                  fontSize: 13, fontWeight: active ? 600 : 400, cursor: 'pointer',
                  background: active ? 'rgba(43,92,230,0.08)' : 'transparent',
                  color: active ? 'var(--c-accent)' : 'var(--c-ink-2)',
                  borderLeft: `3px solid ${active ? 'var(--c-accent)' : 'transparent'}`,
                }}
              >
                <span>{name}</span>
                <span style={{ fontSize: 11, color: 'var(--c-ink-3)' }}>{count}</span>
              </button>
            )
          })}
        </div>

        {/* main grid */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, margin: '0 0 14px' }}>{activeTeacher}</h2>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 560, tableLayout: 'fixed' }}>
              <thead>
                <tr>
                  <th style={{ width: 52, ...thStyle }}></th>
                  {DAYS.map((d, di) => (
                    <th key={d} style={{ ...thStyle, textAlign: 'center', fontWeight: 600 }}>
                      <div style={{ fontSize: 12 }}>{d}</div>
                      <div style={{ fontSize: 10, fontWeight: 400, color: 'var(--c-ink-3)' }}>{DAY_FULL[di]}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: HOURS }, (_, h) => (
                  <tr key={h}>
                    <td style={{ ...tdStyle, textAlign: 'center', fontSize: 11, color: 'var(--c-ink-3)', fontWeight: 500, width: 52 }}>
                      H{h + 1}
                    </td>
                    {DAYS.map((_, di) => {
                      const slot = sched?.[di]?.[h]
                      const isPicking = picker?.day === di && picker?.hour === h
                      const col = slot ? subjectColorFor(slot.class_name) : null

                      const cellContent = slot ? (
                        <div style={{
                          background: col.bg, border: `1px solid ${col.border}`, borderRadius: 6,
                          padding: '4px 6px', height: '100%', display: 'flex', flexDirection: 'column',
                          justifyContent: 'center', gap: 1, position: 'relative',
                        }}>
                          <div style={{ fontSize: 11, fontWeight: 700, color: col.text }}>{slot.class_name}</div>
                          <div style={{ fontSize: 10, color: 'var(--c-ink-3)' }}>{slot.subject}</div>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleClear(di, h) }}
                            title="Remove"
                            style={{
                              position: 'absolute', top: 2, right: 2, width: 16, height: 16,
                              border: 'none', background: 'rgba(0,0,0,0.08)', borderRadius: 4,
                              fontSize: 10, lineHeight: '16px', cursor: 'pointer', color: 'var(--c-ink-2)',
                            }}
                          >✕</button>
                        </div>
                      ) : (
                        <div style={{
                          height: '100%', background: isPicking ? 'rgba(43,92,230,0.10)' : 'var(--c-bg)',
                          borderRadius: 6, boxShadow: isPicking ? 'inset 0 0 0 2px var(--c-accent)' : 'none',
                        }} />
                      )

                      return (
                        <td
                          key={di}
                          onClick={() => { if (!slot) openPicker(di, h) }}
                          style={{ ...tdStyle, padding: 3, height: 56, cursor: slot ? 'default' : 'pointer' }}
                        >
                          {cellContent}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* candidate picker modal */}
      {picker && (
        <div
          style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={() => setPicker(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ background: 'var(--c-surface)', borderRadius: 12, padding: 20, width: 380, maxWidth: '90vw', maxHeight: '70vh', overflowY: 'auto', boxShadow: '0 12px 32px rgba(0,0,0,0.25)' }}
          >
            <h3 style={{ margin: '0 0 4px', fontSize: 15, fontWeight: 700 }}>
              {activeTeacher} · {DAYS[picker.day]} H{picker.hour + 1}
            </h3>
            <p style={{ margin: '0 0 14px', fontSize: 12, color: 'var(--c-ink-3)' }}>
              Choose a class to place here
            </p>

            {candLoading ? (
              <div style={{ display: 'flex', justifyContent: 'center', padding: 20 }}><Spinner /></div>
            ) : candidates.length === 0 ? (
              <p style={{ fontSize: 13, color: 'var(--c-ink-3)' }}>No classes available at this slot.</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {candidates.map((c, i) => (
                  <button
                    key={i}
                    disabled={!c.valid}
                    onClick={() => handlePlace(c)}
                    style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      padding: '9px 12px', borderRadius: 8, textAlign: 'left',
                      border: `1px solid ${c.valid ? 'var(--c-border-h)' : 'rgba(192,57,43,0.2)'}`,
                      background: c.valid ? 'var(--c-bg)' : 'rgba(192,57,43,0.05)',
                      cursor: c.valid ? 'pointer' : 'not-allowed',
                      fontFamily: 'var(--f-body)', fontSize: 13,
                      color: c.valid ? 'var(--c-ink)' : 'var(--c-ink-3)',
                    }}
                  >
                    <span><strong>{c.class_name}</strong> — {c.subject}</span>
                    {!c.valid && <span style={{ fontSize: 11 }}>{c.reason}</span>}
                  </button>
                ))}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
              <button onClick={() => setPicker(null)} style={btnStyle('outline')}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}