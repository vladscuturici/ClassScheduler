// pages/FinalCheckPage.jsx
import { useState } from 'react'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
const HOURS = 8

// ── icons ─────────────────────────────────────────────────────────────────────

function IconArrowLeft() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
    </svg>
  )
}

function IconPlay() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  )
}

function IconChevron({ open }) {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      style={{ transition: 'transform .15s', transform: open ? 'rotate(180deg)' : 'none', flexShrink: 0, color: 'var(--c-ink-3)' }}>
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

// ── small shared components ───────────────────────────────────────────────────

function SectionLabel({ children }) {
  return (
    <p style={{
      fontSize: 11, fontWeight: 500, letterSpacing: '.06em',
      textTransform: 'uppercase', color: 'var(--c-ink-3)', marginBottom: 10,
    }}>
      {children}
    </p>
  )
}

function Badge({ children, color = 'blue' }) {
  const map = {
    blue:  { bg: 'rgba(43,92,230,.08)',   text: 'var(--c-accent)' },
    green: { bg: 'rgba(30,124,77,.08)',   text: 'var(--c-success)' },
    gray:  { bg: 'rgba(0,0,0,.06)',       text: 'var(--c-ink-2)' },
    amber: { bg: 'rgba(180,120,20,.1)',   text: '#7a5100' },
    red:   { bg: 'rgba(192,57,43,.1)',    text: 'var(--c-danger)' },
  }
  const { bg, text } = map[color] || map.gray
  return (
    <span style={{
      fontSize: 11, padding: '2px 7px', borderRadius: 100,
      fontWeight: 500, background: bg, color: text, whiteSpace: 'nowrap',
    }}>
      {children}
    </span>
  )
}

function HardBadge() {
  return <Badge color="red">hard</Badge>
}
function SoftBadge() {
  return (
    <span style={{
      fontSize: 11, padding: '2px 7px', borderRadius: 100,
      fontWeight: 500, background: 'rgba(180,130,0,0.1)', color: '#8a6000', whiteSpace: 'nowrap',
    }}>soft</span>
  )
}

function CollapseCard({ header, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{
      background: 'var(--c-surface)', border: '1px solid var(--c-border)',
      borderRadius: 'var(--r-lg)', overflow: 'hidden', marginBottom: 8,
    }}>
      <div onClick={() => setOpen(o => !o)} style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '11px 16px', cursor: 'pointer', userSelect: 'none', gap: 8,
        borderBottom: open ? '1px solid var(--c-border)' : 'none',
      }}>
        {header}
        <IconChevron open={open} />
      </div>
      {open && (
        <div style={{ padding: '12px 16px', background: 'var(--c-bg)' }}>
          {children}
        </div>
      )}
    </div>
  )
}

// ── summary panels ────────────────────────────────────────────────────────────

function ClassesSummary({ customizePayload, classConstraintsPayload }) {
  const classes = customizePayload?.classes ?? []
  if (!classes.length) return <p style={{ fontSize: 13, color: 'var(--c-ink-3)' }}>No class data.</p>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {classes.map((cls) => {
        const total = cls.subjects.reduce((s, x) => s + x.sessions_per_week, 0)
        const minC = Math.floor(total / 5)
        const maxC = minC + 1

        const ccList = classConstraintsPayload?.classConstraints?.[cls.name] ?? []
        const scMap  = classConstraintsPayload?.subjectConstraints ?? {}

        return (
          <CollapseCard
            key={cls.name}
            header={
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>{cls.name}</span>
                <Badge color="blue">{cls.subjects.length} subjects</Badge>
                <Badge color="gray">{total} sess/wk</Badge>
                <span style={{ fontSize: 12, color: 'var(--c-ink-3)', marginLeft: 'auto', marginRight: 8 }}>
                  {minC}–{maxC}/day
                </span>
              </div>
            }
          >
            {/* subjects table */}
            <div style={{ marginBottom: ccList.length ? 14 : 0 }}>
              <div style={{
                display: 'grid', gridTemplateColumns: '1fr 130px 48px 80px',
                gap: 6, paddingBottom: 5,
                borderBottom: '1px solid var(--c-border)', marginBottom: 4,
                fontSize: 11, color: 'var(--c-ink-3)', fontWeight: 500,
                textTransform: 'uppercase', letterSpacing: '.04em',
              }}>
                <span>Subject</span><span>Teacher</span><span style={{ textAlign: 'center' }}>Sess.</span><span>Difficulty</span>
              </div>
              {cls.subjects.map((s, si) => (
                <div key={si} style={{
                  display: 'grid', gridTemplateColumns: '1fr 130px 48px 80px',
                  gap: 6, alignItems: 'center', padding: '5px 0',
                  borderBottom: si < cls.subjects.length - 1 ? '1px solid var(--c-border)' : 'none',
                  fontSize: 13,
                }}>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
                  <span style={{ fontSize: 12, color: 'var(--c-ink-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.teacher}</span>
                  <span style={{ textAlign: 'center', color: 'var(--c-ink-2)' }}>{s.sessions_per_week}</span>
                  <span style={{ color: 'var(--c-ink-2)' }}>{s.relevance}/10</span>
                </div>
              ))}
            </div>

            {/* class constraints */}
            {ccList.filter(c => c.enabled).length > 0 && (
              <div style={{ marginTop: 10 }}>
                <p style={{ fontSize: 11, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '.04em', color: 'var(--c-ink-3)', marginBottom: 6 }}>
                  Class constraints
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {ccList.filter(c => c.enabled).map((c, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--c-ink-2)' }}>
                      <span style={{ color: 'var(--c-success)', fontSize: 10 }}>●</span>
                      <span style={{ fontWeight: 500 }}>{c.id.replace(/Constraint$/, '').replace(/([A-Z])/g, ' $1').trim()}</span>
                      {Object.entries(c.params ?? {}).map(([k, v]) => (
                        <span key={k} style={{ color: 'var(--c-ink-3)' }}>· {k.replace(/_/g, ' ')}: <strong style={{ color: 'var(--c-ink-2)' }}>{v}</strong></span>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* subject constraints */}
            {cls.subjects.some(s => {
              const key = `${cls.name}::${s.name}`
              return (scMap[key] ?? []).some(c => c.enabled)
            }) && (
              <div style={{ marginTop: 10 }}>
                <p style={{ fontSize: 11, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '.04em', color: 'var(--c-ink-3)', marginBottom: 6 }}>
                  Subject constraints
                </p>
                {cls.subjects.map((s) => {
                  const key = `${cls.name}::${s.name}`
                  const active = (scMap[key] ?? []).filter(c => c.enabled)
                  if (!active.length) return null
                  return (
                    <div key={s.name} style={{ marginBottom: 6 }}>
                      <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--c-ink-2)' }}>{s.name}</span>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 3 }}>
                        {active.map((c, i) => (
                          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--c-ink-2)', paddingLeft: 10 }}>
                            <span style={{ color: 'var(--c-accent)', fontSize: 10 }}>●</span>
                            <span style={{ fontWeight: 500 }}>{c.id.replace(/Constraint$/, '').replace(/([A-Z])/g, ' $1').trim()}</span>
                            {Object.entries(c.params ?? {}).map(([k, v]) => (
                              <span key={k} style={{ color: 'var(--c-ink-3)' }}>· {k.replace(/_/g, ' ')}: <strong style={{ color: 'var(--c-ink-2)' }}>{v}</strong></span>
                            ))}
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </CollapseCard>
        )
      })}
    </div>
  )
}

function TeachersSummary({ customizePayload, teacherConstraintsPayload }) {
  const teachers = customizePayload?.teachers ?? []
  if (!teachers.length) return <p style={{ fontSize: 13, color: 'var(--c-ink-3)' }}>No teacher data.</p>

  // build blocked lookup from payload
  // build blocked + gap lookup from payload
  const blockedMap = {}
  const maxGapMap  = {}
  ;(teacherConstraintsPayload ?? []).forEach(({ name, unavailable_slots, max_gap }) => {
    blockedMap[name] = new Set(unavailable_slots.map(([d, h]) => `${d}-${h}`))
    maxGapMap[name]  = max_gap ?? 2
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {teachers.map((t) => {
        const blocked    = blockedMap[t.name] ?? new Set()
        const available  = DAYS.length * HOURS - blocked.size
        const maxGap     = maxGapMap[t.name] ?? 2          // ← add this
        const blockedDays = DAYS.filter((d, di) =>
          Array.from({ length: HOURS }, (_, h) => blocked.has(`${di}-${h}`)).every(Boolean)
        )

        return (
          <CollapseCard
            key={t.name}
            header={
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
                <span style={{ fontWeight: 500, fontSize: 13 }}>{t.name}</span>
                <Badge color="green">{available}/{DAYS.length * HOURS} slots</Badge>
                {blockedDays.length > 0 && <Badge color="red">{blockedDays.join(', ')} off</Badge>}
                <Badge color="gray">max gap {maxGap}</Badge>   {/* ← add */}
              </div>
            }
          >
            <div style={{ display: 'grid', gridTemplateColumns: `32px repeat(${DAYS.length}, 1fr)`, gap: 3 }}>
              <div />
              {DAYS.map(d => (
                <div key={d} style={{ fontSize: 11, fontWeight: 500, textAlign: 'center', padding: '4px 0', color: 'var(--c-ink-3)' }}>{d}</div>
              ))}
              {Array.from({ length: HOURS }, (_, h) => (
                <>
                  <div key={`h${h}`} style={{ fontSize: 11, color: 'var(--c-ink-3)', textAlign: 'right', paddingRight: 4, display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>
                    {h + 8}:00
                  </div>
                  {DAYS.map((d, di) => {
                    const isBlocked = blocked.has(`${di}-${h}`)
                    return (
                      <div key={d} style={{
                        height: 24, borderRadius: 4,
                        background: isBlocked ? 'rgba(192,57,43,0.1)' : 'rgba(30,124,77,0.07)',
                        border: `1px solid ${isBlocked ? 'rgba(192,57,43,0.2)' : 'var(--c-border)'}`,
                        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11,
                      }}>
                        {isBlocked
                          ? <span style={{ color: 'var(--c-danger)', opacity: 0.6 }}>✕</span>
                          : <span style={{ color: 'var(--c-success)', opacity: 0.4 }}>✓</span>
                        }
                      </div>
                    )
                  })}
                </>
              ))}
            </div>
          </CollapseCard>
        )
      })}
    </div>
  )
}

// ── search params panel ───────────────────────────────────────────────────────

function SearchParams({ value, onChange }) {
  return (
    <div style={{
      background: 'var(--c-surface)', border: '1px solid var(--c-border)',
      borderRadius: 'var(--r-lg)', padding: '16px 20px',
      display: 'flex', flexDirection: 'column', gap: 16,
    }}>
      {/* max solutions */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--c-ink)', marginBottom: 2 }}>
            Solutions to find
          </div>
          <div style={{ fontSize: 12, color: 'var(--c-ink-3)' }}>
            Solver stops after finding this many valid schedules
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            onClick={() => onChange({ ...value, max_solutions: Math.max(1, value.max_solutions - 1) })}
            style={{
              width: 28, height: 28, borderRadius: 'var(--r-sm)',
              border: '1px solid var(--c-border-h)', background: 'var(--c-bg)',
              cursor: 'pointer', fontSize: 16, display: 'flex', alignItems: 'center',
              justifyContent: 'center', color: 'var(--c-ink-2)', fontFamily: 'var(--f-body)',
            }}
          >−</button>
          <span style={{ fontSize: 15, fontWeight: 500, minWidth: 24, textAlign: 'center', color: 'var(--c-ink)' }}>
            {value.max_solutions}
          </span>
          <button
            onClick={() => onChange({ ...value, max_solutions: Math.min(10, value.max_solutions + 1) })}
            style={{
              width: 28, height: 28, borderRadius: 'var(--r-sm)',
              border: '1px solid var(--c-border-h)', background: 'var(--c-bg)',
              cursor: 'pointer', fontSize: 16, display: 'flex', alignItems: 'center',
              justifyContent: 'center', color: 'var(--c-ink-2)', fontFamily: 'var(--f-body)',
            }}
          >+</button>
        </div>
      </div>

      {/* balanced difficulty */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, paddingTop: 12, borderTop: '1px solid var(--c-border)' }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--c-ink)', marginBottom: 2 }}>
            Balanced daily difficulty
          </div>
          <div style={{ fontSize: 12, color: 'var(--c-ink-3)' }}>
            Spread hard subjects evenly across the week
          </div>
        </div>
        <button
          role="switch"
          aria-checked={value.use_balanced_difficulty}
          onClick={() => onChange({ ...value, use_balanced_difficulty: !value.use_balanced_difficulty })}
          style={{
            width: 36, height: 20, borderRadius: 10, border: 'none', cursor: 'pointer',
            padding: 2, flexShrink: 0, outline: 'none',
            background: value.use_balanced_difficulty ? 'var(--c-accent)' : 'var(--c-border-h)',
            transition: 'background 0.15s',
            display: 'flex', alignItems: 'center',
          }}
        >
          <span style={{
            width: 16, height: 16, borderRadius: '50%', background: '#fff', display: 'block', flexShrink: 0,
            transform: value.use_balanced_difficulty ? 'translateX(16px)' : 'translateX(0)',
            transition: 'transform 0.15s',
          }} />
        </button>
      </div>
    </div>
  )
}

// ── main page ─────────────────────────────────────────────────────────────────

export default function FinalCheckPage({
  customizePayload,
  classConstraintsPayload,
  teacherConstraintsPayload,
  onGenerate,
  onManualPlacement, 
  onBack,
}) {
  const [searchParams, setSearchParams] = useState({
    max_solutions: 1,
    use_balanced_difficulty: customizePayload?.use_balanced_difficulty ?? false,
  })

  function handleGenerate() {
    onGenerate?.({ ...searchParams })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>

      {/* page header */}
      <div style={{
        padding: '24px 32px 0',
        borderBottom: '1px solid var(--c-border)',
        background: 'var(--c-surface)',
      }}>
        <h1 style={{
          fontFamily: 'var(--f-display)', fontSize: 26,
          letterSpacing: '-0.5px', marginBottom: 4, color: 'var(--c-ink)',
        }}>
          Review &amp; generate
        </h1>
        <p style={{ fontSize: 14, color: 'var(--c-ink-2)', marginBottom: 20 }}>
          Verify everything looks correct, set solver parameters, then generate your schedule.
        </p>
      </div>

      {/* body */}
      <div style={{ flex: 1, padding: '24px 32px', maxWidth: 860, width: '100%', margin: '0 auto' }}>

        {/* classes */}
        <SectionLabel>Classes &amp; subjects ({customizePayload?.classes?.length ?? 0})</SectionLabel>
        <div style={{ marginBottom: 24 }}>
          <ClassesSummary
            customizePayload={customizePayload}
            classConstraintsPayload={classConstraintsPayload}
          />
        </div>

        {/* teachers */}
        <SectionLabel>Teachers ({customizePayload?.teachers?.length ?? 0})</SectionLabel>
        <div style={{ marginBottom: 24 }}>
          <TeachersSummary
            customizePayload={customizePayload}
            teacherConstraintsPayload={teacherConstraintsPayload}
          />
        </div>

        {/* search params */}
        <SectionLabel>Solver settings</SectionLabel>
        <div style={{ marginBottom: 32 }}>
          <SearchParams value={searchParams} onChange={setSearchParams} />
        </div>

        {/* nav */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          borderTop: '1px solid var(--c-border)', paddingTop: 20,
        }}>
          <button
            onClick={onBack}
            style={{
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
          {/* <button
            onClick={() => onManualPlacement?.()}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '11px 22px', borderRadius: 100,
              border: '1px solid var(--c-border-h)',
              background: 'var(--c-surface)', color: 'var(--c-ink-2)',
              fontFamily: 'var(--f-body)', fontSize: 14, fontWeight: 500, cursor: 'pointer',
            }}
          >
            ✎ Place slots myself
          </button> */}
          <button
            onClick={handleGenerate}
            style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '13px 32px', borderRadius: 100, border: 'none',
              cursor: 'pointer', fontFamily: 'var(--f-body)', fontSize: 15, fontWeight: 500,
              background: 'var(--c-accent)', color: '#fff',
              boxShadow: '0 4px 18px rgba(43,92,230,0.28)', transition: 'background 0.2s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--c-accent-h)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--c-accent)')}
          >
            <IconPlay />
            Generate schedule
          </button>
        </div>

      </div>
    </div>
  )
}