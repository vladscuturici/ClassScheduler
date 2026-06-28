// pages/ClassConstraintsPage.jsx
import { useState, useRef } from 'react'
// ── constraint definitions ────────────────────────────────────────────────────

const CLASS_CONSTRAINTS = [
  {
    id: 'MinDailyClassCount',
    label: 'Min daily classes',
    description: 'Each day with lessons must have at least this many sessions.',
    params: [{ key: 'min_classes', label: 'Minimum', min: 1, max: 8, default: 3 }],
  },
  {
    id: 'MaxDailyClassCount',
    label: 'Max daily classes',
    description: 'A class cannot have more than this many sessions in one day.',
    params: [{ key: 'max_classes', label: 'Maximum', min: 1, max: 8, default: 6 }],
  },
  {
    id: 'BalancedDailyDifficultyConstraint',
    label: 'Balanced daily difficulty',
    description: 'Spreads subject difficulty (relevance scores) evenly across the week.',
    params: [],
    softOnly: true,
  },
]

const SUBJECT_CONSTRAINTS = [
  {
    id: 'MaxConsecutiveClassesConstraint',
    label: 'Max consecutive classes',
    description: 'Limits back-to-back sessions of the same subject per day.',
    params: [{ key: 'max_classes', label: 'Max consecutive', min: 1, max: 10, default: 1 }],
  },
  {
    id: 'MaxClassesPerDayConstraint',
    label: 'Max classes per day',
    description: 'Caps how many times a subject appears in a single day.',
    params: [{ key: 'max_classes', label: 'Max per day', min: 1, max: 8, default: 2 }],
  },
  {
    id: 'EarlyClassesPreferenceConstraint',
    label: 'Prefer early slots',
    description: 'Scores higher when this subject is scheduled in the first two hours.',
    params: [],
    softOnly: true,
  },
  {
    id: 'LateClassesPreferenceConstraint',
    label: 'Prefer late slots',
    description: 'Scores higher when this subject is scheduled in the last two hours.',
    params: [],
    softOnly: true,
  },
  {
    id: 'LastClassConstraint',
    label: 'Must be last (hard)',
    description: 'This subject must always occupy the final slot of the day.',
    params: [],
  },
  {
    id: 'LastClassPreferenceConstraint',
    label: 'Prefer last slot',
    description: 'Soft preference: score is higher when placed last in the day.',
    params: [],
    softOnly: true,
  },
]

// ── recommended logic ─────────────────────────────────────────────────────────

function getRecommendedSubjectConstraints(subject) {
  const { sessions_per_week, relevance } = subject
  const mc = sessions_per_week < 6 ? 2 : 7
  return [
    { id: 'MaxConsecutiveClassesConstraint', enabled: true, params: { max_classes: mc } },
    {
      id: relevance > 6 ? 'EarlyClassesPreferenceConstraint' : 'LateClassesPreferenceConstraint',
      enabled: true,
      params: {},
    },
  ]
}

function getRecommendedClassConstraints(cls) {
  const totalSessions = cls.subjects.reduce((sum, s) => sum + s.sessions_per_week, 0)
  const minClasses = Math.floor(totalSessions / 5)
  const maxClasses = minClasses + 1

  return [
    { id: 'MinDailyClassCount', enabled: true, params: { min_classes: minClasses } },
    { id: 'MaxDailyClassCount', enabled: true, params: { max_classes: maxClasses } },
  ]
}

function buildDefaultState(classes) {
  const classConstraints = {}
  const subjectConstraints = {}
  classes.forEach((cls) => {
    classConstraints[cls.name] = getRecommendedClassConstraints(cls)
    cls.subjects.forEach((subj) => {
      subjectConstraints[`${cls.name}::${subj.name}`] = getRecommendedSubjectConstraints(subj)
    })
  })
  return { classConstraints, subjectConstraints }
}

// ── small components ──────────────────────────────────────────────────────────

function Toggle({ checked, onChange }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      style={{
        width: 36,
        height: 20,
        borderRadius: 10,
        border: 'none',
        cursor: 'pointer',
        padding: 2,
        background: checked ? 'var(--c-accent)' : 'var(--c-border-h)',
        transition: 'background 0.15s',
        display: 'flex',
        alignItems: 'center',
        flexShrink: 0,
        outline: 'none',
      }}
    >
      <span
        style={{
          width: 16,
          height: 16,
          borderRadius: '50%',
          background: '#fff',
          transform: checked ? 'translateX(16px)' : 'translateX(0)',
          transition: 'transform 0.15s',
          display: 'block',
          flexShrink: 0,
        }}
      />
    </button>
  )
}

function HardBadge() {
  return (
    <span style={{
      fontSize: 11, padding: '2px 7px', borderRadius: 'var(--r-sm)',
      background: 'rgba(192,57,43,0.1)', color: 'var(--c-danger)',
      fontWeight: 500, flexShrink: 0,
    }}>hard</span>
  )
}

function SoftBadge() {
  return (
    <span style={{
      fontSize: 11, padding: '2px 7px', borderRadius: 'var(--r-sm)',
      background: 'rgba(180,130,0,0.1)', color: '#8a6000',
      fontWeight: 500, flexShrink: 0,
    }}>soft</span>
  )
}

function RecBadge() {
  return (
    <span style={{
      fontSize: 11, padding: '2px 7px', borderRadius: 'var(--r-sm)',
      background: 'rgba(30,124,77,0.1)', color: 'var(--c-success)',
      fontWeight: 500, flexShrink: 0,
    }}>recommended</span>
  )
}

// ── constraint row ────────────────────────────────────────────────────────────

function ConstraintRow({ def, state, isRecommended, onChange }) {
  const enabled = state?.enabled ?? false
  const params  = state?.params  ?? {}

  return (
    <div style={{
      display: 'flex',
      alignItems: 'flex-start',
      gap: 12,
      padding: '11px 14px',
      borderRadius: 'var(--r-md)',
      background: enabled ? 'var(--c-surface)' : 'transparent',
      border: `1px solid ${enabled ? 'var(--c-border-h)' : 'var(--c-border)'}`,
      transition: 'background 0.12s, border-color 0.12s',
      opacity: enabled ? 1 : 0.55,
    }}>
      <div style={{ paddingTop: 1, flexShrink: 0 }}>
        <Toggle checked={enabled} onChange={(v) => onChange({ ...state, enabled: v })} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 3 }}>
          <span style={{ fontSize: 14, fontWeight: 500, color: 'var(--c-ink)' }}>{def.label}</span>
          {def.softOnly ? <SoftBadge /> : <HardBadge />}
          {isRecommended && <RecBadge />}
        </div>
        <p style={{ fontSize: 13, color: 'var(--c-ink-3)', margin: 0, lineHeight: 1.55 }}>
          {def.description}
        </p>
        {enabled && def.params.length > 0 && (
          <div style={{ display: 'flex', gap: 16, marginTop: 9, flexWrap: 'wrap', alignItems: 'center' }}>
            {def.params.map((p) => (
              <label key={p.key} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 13, color: 'var(--c-ink-2)' }}>
                {p.label}
                <input
                  type="number"
                  value={params[p.key] ?? p.default}
                  min={p.min}
                  max={p.max}
                  onChange={(e) => onChange({ ...state, params: { ...params, [p.key]: Number(e.target.value) } })}
                  style={{
                    width: 58, padding: '3px 6px', fontSize: 13,
                    border: '1px solid var(--c-border-h)',
                    borderRadius: 'var(--r-sm)',
                    background: 'var(--c-bg)',
                    color: 'var(--c-ink)',
                    textAlign: 'center',
                    fontFamily: 'var(--f-body)',
                    outline: 'none',
                  }}
                />
              </label>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── add constraint dropdown ───────────────────────────────────────────────────

function AddConstraintMenu({ existingIds, allDefs, onAdd, disabled }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const btnRef = useRef(null)
  const available = allDefs.filter((d) => !existingIds.includes(d.id))
  if (available.length === 0) return null

  const handleOpen = () => {
    if (disabled) return
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect()
      setPos({ top: r.bottom + 5, left: r.left })  // ← no scrollY/scrollX
    }
    setOpen(o => !o)
  }

  return (
    <div style={{ position: 'relative', alignSelf: 'flex-start' }}>
      <button
        ref={btnRef}
        onClick={handleOpen}
        style={{
          fontSize: 13, padding: '5px 12px',
          border: `1px dashed ${disabled ? 'var(--c-border)' : 'var(--c-border-h)'}`,
          borderRadius: 'var(--r-sm)',
          background: 'transparent',
          color: disabled ? 'var(--c-ink-3)' : 'var(--c-ink-2)',
          cursor: disabled ? 'default' : 'pointer',
          display: 'flex', alignItems: 'center', gap: 6,
          fontFamily: 'var(--f-body)',
        }}
      >
        <span style={{ fontSize: 18, lineHeight: 1, marginTop: -1 }}>+</span>
        Add constraint
      </button>
      {open && !disabled && (
        <>
          <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 40 }} />
          <div style={{
            position: 'fixed',
            top: pos.top,
            left: pos.left,
            zIndex: 50,
            background: 'var(--c-surface)',
            border: '1px solid var(--c-border-h)',
            borderRadius: 'var(--r-md)',
            minWidth: 230, padding: 6,
            boxShadow: '0 6px 20px rgba(0,0,0,0.10)',
          }}>
            {available.map((d) => (
              <button
                key={d.id}
                onClick={() => {
                  const dp = {}
                  d.params.forEach((p) => { dp[p.key] = p.default })
                  onAdd({ id: d.id, enabled: true, params: dp })
                  setOpen(false)
                }}
                style={{
                  display: 'block', width: '100%', textAlign: 'left',
                  padding: '8px 10px', border: 'none', background: 'transparent',
                  borderRadius: 'var(--r-sm)', cursor: 'pointer',
                  fontSize: 13, color: 'var(--c-ink)', fontFamily: 'var(--f-body)',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--c-bg)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                {d.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// ── class section ─────────────────────────────────────────────────────────────

function SectionLabel({ children }) {
  return (
    <p style={{
      fontSize: 11, fontWeight: 500, color: 'var(--c-ink-3)',
      textTransform: 'uppercase', letterSpacing: '0.07em',
      margin: '0 0 8px 0',
    }}>
      {children}
    </p>
  )
}

function ClassSection({ cls, classConstraints, subjectConstraints, recommendedState, readOnly, onChange, onSubjectChange }) {
  const [expanded, setExpanded]           = useState(true)
  const [activeSubject, setActiveSubject] = useState(cls.subjects[0]?.name ?? null)

  const activeSubj      = cls.subjects.find((s) => s.name === activeSubject)
  const subjKey         = activeSubj ? `${cls.name}::${activeSubj.name}` : null
  const subjConstraints = subjKey ? (subjectConstraints[subjKey] ?? []) : []
  const recCC           = recommendedState.classConstraints[cls.name] ?? []
  const recSC           = subjKey ? (recommendedState.subjectConstraints[subjKey] ?? []) : []

  return (
    <div style={{
      border: '1px solid var(--c-border)',
      borderRadius: 'var(--r-lg)',
      marginBottom: 10,
    }}>
      {/* header */}
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
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--c-ink)' }}>
            {cls.name}
          </span>
          <span style={{ fontSize: 12, color: 'var(--c-ink-3)' }}>
            {cls.subjects.length} subject{cls.subjects.length !== 1 ? 's' : ''}
          </span>
        </div>
        <span style={{ fontSize: 14, color: 'var(--c-ink-3)', lineHeight: 1 }}>
          {expanded ? '▴' : '▾'}
        </span>
      </button>

      {expanded && (
        <div style={{ padding: 18, background: 'var(--c-bg)' }}>
          {/* class constraints */}
          <SectionLabel>Class constraints</SectionLabel>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 20 }}>
            {classConstraints.map((cs, i) => {
              const def = CLASS_CONSTRAINTS.find((d) => d.id === cs.id)
              if (!def) return null
              return (
                <ConstraintRow
                  key={cs.id}
                  def={def}
                  state={cs}
                  isRecommended={recCC.some((r) => r.id === cs.id)}
                  onChange={(updated) => {
                    const next = [...classConstraints]
                    next[i] = updated
                    onChange(cls.name, next)
                  }}
                />
              )
            })}
            <AddConstraintMenu
              existingIds={classConstraints.map((c) => c.id)}
              allDefs={CLASS_CONSTRAINTS}
              disabled={readOnly}
              onAdd={(nc) => onChange(cls.name, [...classConstraints, nc])}
            />
          </div>

          {/* subject constraints */}
          {cls.subjects.length > 0 && (
            <>
              <SectionLabel>Subject constraints</SectionLabel>

              {/* subject tabs */}
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
                {cls.subjects.map((s) => {
                  const active = activeSubject === s.name
                  return (
                    <button
                      key={s.name}
                      onClick={() => setActiveSubject(s.name)}
                      style={{
                        fontSize: 13, padding: '5px 12px',
                        borderRadius: 'var(--r-sm)',
                        border: `1px solid ${active ? 'var(--c-border-h)' : 'var(--c-border)'}`,
                        background: active ? 'var(--c-surface)' : 'transparent',
                        color: active ? 'var(--c-ink)' : 'var(--c-ink-3)',
                        cursor: 'pointer',
                        fontWeight: active ? 500 : 400,
                        fontFamily: 'var(--f-body)',
                        boxShadow: active ? '0 1px 3px rgba(0,0,0,0.06)' : 'none',
                        transition: 'all 0.15s',
                      }}
                    >
                      {s.name}
                      <span style={{ marginLeft: 5, opacity: 0.5, fontWeight: 400 }}>·{s.sessions_per_week}×</span>
                    </button>
                  )
                })}
              </div>

              {activeSubj && subjKey && (
                <div>
                  <div style={{ display: 'flex', gap: 16, marginBottom: 10, fontSize: 13, color: 'var(--c-ink-3)' }}>
                    <span>Sessions/week: <strong style={{ color: 'var(--c-ink-2)' }}>{activeSubj.sessions_per_week}</strong></span>
                    <span>Relevance: <strong style={{ color: 'var(--c-ink-2)' }}>{activeSubj.relevance}</strong></span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {subjConstraints.map((cs, i) => {
                      const def = SUBJECT_CONSTRAINTS.find((d) => d.id === cs.id)
                      if (!def) return null
                      return (
                        <ConstraintRow
                          key={cs.id}
                          def={def}
                          state={cs}
                          isRecommended={recSC.some((r) => r.id === cs.id)}
                          onChange={(updated) => {
                            const next = [...subjConstraints]
                            next[i] = updated
                            onSubjectChange(subjKey, next)
                          }}
                        />
                      )
                    })}
                    <AddConstraintMenu
                      existingIds={subjConstraints.map((c) => c.id)}
                      allDefs={SUBJECT_CONSTRAINTS}
                      disabled={readOnly}
                      onAdd={(nc) => onSubjectChange(subjKey, [...subjConstraints, nc])}
                    />
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── back arrow (matches StartPage / other pages) ──────────────────────────────

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

// ── main page ─────────────────────────────────────────────────────────────────

export default function ClassConstraintsPage({ classes = [], onContinue, onBack }) {
  const [mode, setMode]               = useState('recommended')
  const [recommendedState]            = useState(() => buildDefaultState(classes))
  const [customState, setCustomState] = useState(() => buildDefaultState(classes))

  const readOnly    = mode === 'recommended'
  const activeState = readOnly ? recommendedState : customState

  function handleModeChange(m) {
    if (m === 'custom' && mode === 'recommended') {
      setCustomState(JSON.parse(JSON.stringify(recommendedState)))
    }
    setMode(m)
  }

  function handleClassChange(className, next) {
    if (readOnly) return
    setCustomState((prev) => ({
      ...prev,
      classConstraints: { ...prev.classConstraints, [className]: next },
    }))
  }

  function handleSubjectChange(key, next) {
    if (readOnly) return
    setCustomState((prev) => ({
      ...prev,
      subjectConstraints: { ...prev.subjectConstraints, [key]: next },
    }))
  }

  // REPLACE the return(...) root div + main in ClassConstraintsPage with:

return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      
      {/* ── page header — matches CustomizePage ── */}
      <div style={{
        padding: '24px 32px 0',
        borderBottom: '1px solid var(--c-border)',
        background: 'var(--c-surface)',
      }}>
        <h1 style={{
          fontFamily: 'var(--f-display)',
          fontSize: 26,
          letterSpacing: '-0.5px',
          marginBottom: 4,
          color: 'var(--c-ink)',
        }}>
          Constraint settings
        </h1>
        <p style={{ fontSize: 14, color: 'var(--c-ink-2)', marginBottom: 20 }}>
          Control how sessions are distributed across the week for each class and subject.
        </p>
      </div>

      {/* ── body — matches CustomizePage ── */}
      <div style={{ flex: 1, padding: '24px 32px', maxWidth: 860, width: '100%', margin: '0 auto' }}>

        {/* mode switcher */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
          {[
            { key: 'recommended', label: '✦ Recommended' },
            { key: 'custom',      label: '⚙ Customize'   },
          ].map(({ key, label }) => (
            <button
              key={key}
              onClick={() => handleModeChange(key)}
              style={{
                padding: '8px 20px',
                borderRadius: 'var(--r-lg)',
                border: mode === key ? 'none' : '1px solid var(--c-border-h)',
                background: mode === key ? 'var(--c-accent)' : 'var(--c-surface)',
                color: mode === key ? '#fff' : 'var(--c-ink-2)',
                cursor: 'pointer', fontSize: 13, fontWeight: 500,
                fontFamily: 'var(--f-body)', transition: 'all .15s',
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {/* info / warning banner */}
        {readOnly ? (
          <div style={{
            display: 'flex', gap: 10, alignItems: 'flex-start',
            padding: '10px 14px', borderRadius: 'var(--r-md)',
            background: 'rgba(43,92,230,.05)', border: '1px solid rgba(43,92,230,.15)',
            fontSize: 13, color: 'var(--c-ink-2)', marginBottom: 20,
          }}>
            <span style={{ fontSize: 16, marginTop: 1 }}>ℹ</span>
            <span>
              Constraints are set automatically based on sessions per week and relevance score.
              Switch to <strong>Customize</strong> to override individual settings.
            </span>
          </div>
        ) : (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '10px 14px',
            background: 'rgba(180,130,0,0.07)',
            border: '1px solid rgba(180,130,0,0.25)',
            borderRadius: 'var(--r-md)',
            marginBottom: 20, gap: 10,
          }}>
            <span style={{ fontSize: 13, color: '#7a5800' }}>
              ✎ Editing custom constraints — toggle each on/off or adjust parameters.
            </span>
            <button
              onClick={() => setCustomState(JSON.parse(JSON.stringify(recommendedState)))}
              style={{
                fontSize: 12, padding: '4px 11px',
                border: '1px solid rgba(180,130,0,0.3)',
                borderRadius: 'var(--r-sm)',
                background: 'transparent', color: '#7a5800',
                cursor: 'pointer', whiteSpace: 'nowrap', fontWeight: 500,
                fontFamily: 'var(--f-body)',
              }}
            >
              ↺ Reset to recommended
            </button>
          </div>
        )}

        {/* legend */}
        <div style={{ display: 'flex', gap: 14, marginBottom: 18, flexWrap: 'wrap', alignItems: 'center' }}>
          {[
            [<HardBadge key="h" />, 'hard — must not be violated'],
            [<SoftBadge key="s" />, 'soft — scored, not enforced'],
            [<RecBadge  key="r" />, 'auto-selected for this config'],
          ].map(([badge, text], i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--c-ink-3)' }}>
              {badge}<span>{text}</span>
            </div>
          ))}
        </div>

        {/* classes */}
        {classes.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '3rem 0', color: 'var(--c-ink-3)', fontSize: 14 }}>
            No classes loaded. Upload an Excel file first.
          </div>
        ) : (
          classes.map((cls) => (
            <ClassSection
              key={cls.name}
              cls={cls}
              classConstraints={activeState.classConstraints[cls.name] ?? []}
              subjectConstraints={activeState.subjectConstraints}
              recommendedState={recommendedState}
              readOnly={readOnly}
              onChange={handleClassChange}
              onSubjectChange={handleSubjectChange}
            />
          ))
        )}

        {/* nav buttons */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          borderTop: '1px solid var(--c-border)', paddingTop: 20, marginTop: 40,
        }}>
          <button
            onClick={onBack}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '11px 24px', borderRadius: 100,
              border: '1px solid var(--c-border-h)',
              background: 'var(--c-surface)', color: 'var(--c-ink-2)',
              fontFamily: 'var(--f-body)', fontSize: 14, fontWeight: 500,
              cursor: 'pointer',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--c-ink-3)')}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--c-border-h)')}
          >
            <IconArrowLeft />
            Back
          </button>

          <button
            onClick={() => onContinue?.(activeState)}
            style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '11px 28px', borderRadius: 100, border: 'none',
              cursor: 'pointer',
              fontFamily: 'var(--f-body)', fontSize: 14, fontWeight: 500,
              background: 'var(--c-accent)', color: '#fff',
              boxShadow: '0 4px 18px rgba(43,92,230,0.28)',
              transition: 'background 0.2s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--c-accent-h)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--c-accent)')}
          >
            Continue
            <IconArrowRight />
          </button>
        </div>

      </div>
    </div>
  )
}