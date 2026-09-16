// pages/CustomizePage.jsx  (renamed: Visualize & Customize)

import { useState, useCallback } from 'react'

const autoRelevance = (sessions) =>
  sessions >= 4 ? 10 : sessions === 3 ? 8 : sessions === 2 ? 6 : 4

// Sort: grades 5–12 → non-numeric (PA, PB…) → grades 1–4 → grade 0
const sortClasses = (classes) =>
  [...classes].sort((a, b) => {
    const parse = name => {
      const m = String(name).match(/^(\d+)([A-Za-z]*)$/)
      if (!m) return { bucket: 1, grade: 0, variant: String(name).toUpperCase() }
      const grade = parseInt(m[1], 10)
      const variant = m[2].toUpperCase()
      // bucket 0 → grades 5–12  |  bucket 1 → non-numeric (PA, PB…)  |  bucket 2 → grades 1–4  |  bucket 3 → grade 0
      const bucket = grade >= 5 ? 0 : grade >= 1 ? 2 : 3
      return { bucket, grade, variant }
    }
    const A = parse(a.name), B = parse(b.name)
    if (A.bucket !== B.bucket) return A.bucket - B.bucket
    if (A.grade !== B.grade) return A.grade - B.grade
    return A.variant.localeCompare(B.variant)
  })

const gradeKey = name => {
  const m = String(name).match(/^(\d+)([A-Za-z]*)$/)
  if (!m) return { bucket: 1, grade: 0, variant: String(name).toUpperCase() }
  const grade = parseInt(m[1], 10)
  const variant = m[2].toUpperCase()
  const bucket = grade >= 5 ? 0 : grade >= 1 ? 2 : 3
  return { bucket, grade, variant }
}

const sortByClassName = (arr) =>
  [...arr].sort((a, b) => {
    const A = gradeKey(a.className), B = gradeKey(b.className)
    if (A.bucket !== B.bucket) return A.bucket - B.bucket
    if (A.grade !== B.grade) return A.grade - B.grade
    return A.variant.localeCompare(B.variant)
  })

// Sort subjects by sessions_per_week descending, then alphabetically
const sortSubjects = (subjects) =>
  [...subjects].sort((a, b) =>
    b.sessions_per_week !== a.sessions_per_week
      ? b.sessions_per_week - a.sessions_per_week
      : a.name.localeCompare(b.name)
  )

function CollapseCard({ header, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{
      background: 'var(--c-surface)', border: '1px solid var(--c-border)',
      borderRadius: 'var(--r-lg)', overflow: 'hidden',
    }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 14px', cursor: 'pointer', userSelect: 'none', gap: 8,
        }}
      >
        {header}
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          style={{ flexShrink: 0, color: 'var(--c-ink-3)', transition: 'transform .15s', transform: open ? 'rotate(180deg)' : 'none' }}>
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>
      {open && (
        <div style={{ borderTop: '1px solid var(--c-border)', padding: '12px 14px' }}>
          {children}
        </div>
      )}
    </div>
  )
}

const Badge = ({ children, color = 'blue' }) => {
  const map = {
    blue:  { bg: 'rgba(43,92,230,.08)',  text: 'var(--c-accent)' },
    green: { bg: 'rgba(30,124,77,.08)',  text: 'var(--c-success)' },
    gray:  { bg: 'rgba(0,0,0,.06)',      text: 'var(--c-ink-2)' },
    amber: { bg: 'rgba(180,120,20,.1)',  text: '#7a5100' },
    red:   { bg: 'rgba(192,57,43,.1)',   text: 'var(--c-danger)' },
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

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

// ─────────────────────────────────────────────────────────────────────────────
export default function CustomizePage({ classes: initialClasses, teachers, onContinue, onBack }) {

  const [classes, setClasses] = useState(() =>
    (initialClasses || DEMO_CLASSES).map(c => ({
      ...c,
      subjects: c.subjects.map(s => ({
        ...s,
        relevance: autoRelevance(s.sessions_per_week),
      })),
    }))
  )

  const resolvedTeachers = teachers || DEMO_TEACHERS

  // Build a lookup: teacher name → list of { className, subject, sessions }
  const teacherClassMap = {}
  classes.forEach(cls => {
    cls.subjects.forEach(s => {
      if (!teacherClassMap[s.teacher]) teacherClassMap[s.teacher] = []
      teacherClassMap[s.teacher].push({
        className: cls.name,
        subject: s.name,
        sessions: s.sessions_per_week,
      })
    })
  })

  const handleContinue = () => {
    const payload = {
      classes: sortClasses(classes).map(c => ({
        ...c,
        subjects: c.subjects.map(s => ({
          ...s,
          relevance: autoRelevance(s.sessions_per_week), // always recommended
        })),
      })),
      teachers: resolvedTeachers,
      use_balanced_difficulty: false, // option removed, always off
    }
    onContinue?.(payload)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>

      {/* header */}
      <div style={{
        padding: '24px 32px 0',
        borderBottom: '1px solid var(--c-border)',
        background: 'var(--c-surface)',
      }}>
        <h1 style={{ fontFamily: 'var(--f-display)', fontSize: 26, letterSpacing: '-0.5px', marginBottom: 4 }}>
          Visualize &amp; Customize
        </h1>
        <p style={{ fontSize: 14, color: 'var(--c-ink-2)', marginBottom: 20 }}>
          Review your imported data to verify it parsed correctly, then configure subject difficulty before generating the schedule.
        </p>
      </div>

      {/* body */}
      <div style={{ flex: 1, padding: '24px 32px', maxWidth: 860, width: '100%', margin: '0 auto' }}>

        {/* classes */}
        <SectionLabel>Classes &amp; subjects ({classes.length})</SectionLabel>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 24 }}>
          {sortClasses(classes).map((cls, ci) => {
            const total = cls.subjects.reduce((s, x) => s + x.sessions_per_week, 0)
            return (
              <CollapseCard
                key={cls.name}
                header={
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
                    <span style={{ fontWeight: 600, fontSize: 14 }}>{cls.name}</span>
                    <Badge color="blue">{cls.subjects.length} subjects</Badge>
                    <Badge color="gray">{total} sessions/wk</Badge>
                    <span style={{ fontSize: 12, color: 'var(--c-ink-3)', marginLeft: 'auto', marginRight: 8 }}>
                      {cls.min_daily}–{cls.max_daily}/day
                    </span>
                  </div>
                }
              >
                {/* column headers */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 140px 52px',
                  gap: 8, paddingBottom: 6,
                  borderBottom: '1px solid var(--c-border)', marginBottom: 4,
                  fontSize: 11, color: 'var(--c-ink-3)', fontWeight: 500,
                  textTransform: 'uppercase', letterSpacing: '.04em',
                }}>
                  <span>Subject</span>
                  <span>Teacher</span>
                  <span style={{ textAlign: 'center' }}>Sess.</span>
                </div>

                {sortSubjects(cls.subjects).map((s, si) => (
                  <div key={si} style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 140px 52px',
                    gap: 8, alignItems: 'center', padding: '6px 0',
                    borderBottom: si < cls.subjects.length - 1 ? '1px solid var(--c-border)' : 'none',
                  }}>
                    <span style={{ fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {s.name}
                    </span>
                    <span style={{ fontSize: 12, color: 'var(--c-ink-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {s.teacher}
                    </span>
                    <span style={{ fontSize: 13, textAlign: 'center', color: 'var(--c-ink-2)' }}>
                      {s.sessions_per_week}
                    </span>
                  </div>
                ))}
              </CollapseCard>
            )
          })}
        </div>

        {/* teachers */}
        <SectionLabel>Teachers ({resolvedTeachers.length})</SectionLabel>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 32 }}>
          {resolvedTeachers.map(t => {
            const availableDays = DAYS.filter(d => (t.availability[d] ?? 1) > 0)
            const assignments = teacherClassMap[t.name] || []
            const totalSessions = assignments.reduce((sum, a) => sum + a.sessions, 0)

            return (
              <CollapseCard
                key={t.name}
                header={
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
                    <span style={{ fontWeight: 500, fontSize: 14 }}>{t.name}</span>
                    <Badge color="green">{availableDays.length} days/wk</Badge>
                    {assignments.length > 0 && (
                      <Badge color="blue">{assignments.length} class{assignments.length !== 1 ? 'es' : ''}</Badge>
                    )}
                    {/* day pills */}
                    <div style={{ display: 'flex', gap: 3, marginLeft: 'auto', marginRight: 8 }}>
                      {DAYS.map(d => {
                        const available = (t.availability[d] ?? 1) > 0
                        return (
                          <span key={d} style={{
                            fontSize: 11, padding: '2px 5px', borderRadius: 4, fontWeight: 500,
                            background: available ? '#E1F5EE' : '#F2F2F2',
                            color: available ? '#0F6E56' : '#BFBFBF',
                            textDecoration: available ? 'none' : 'line-through',
                          }}>
                            {d}
                          </span>
                        )
                      })}
                    </div>
                  </div>
                }
              >
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

                  {/* availability row */}
                  <div>
                    <p style={{ fontSize: 11, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '.04em', color: 'var(--c-ink-3)', marginBottom: 8 }}>
                      Availability
                    </p>
                    <div style={{ display: 'flex', gap: 6 }}>
                      {DAYS.map(d => {
                        const available = (t.availability[d] ?? 1) > 0
                        return (
                          <div key={d} style={{
                            flex: 1, textAlign: 'center', padding: '8px 4px',
                            borderRadius: 'var(--r-md)',
                            background: available ? '#E1F5EE' : 'var(--c-surface-2)',
                            border: `1px solid ${available ? '#9FE1CB' : 'var(--c-border)'}`,
                          }}>
                            <div style={{ fontSize: 11, fontWeight: 500, color: available ? '#0F6E56' : 'var(--c-ink-3)', marginBottom: 2 }}>{d}</div>
                            <div style={{ fontSize: 10, color: available ? '#0F6E56' : 'var(--c-ink-3)' }}>
                              {available ? '✓' : '✗'}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>

                  {/* assignments table */}
                  {assignments.length > 0 ? (
                    <div>
                      <p style={{ fontSize: 11, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '.04em', color: 'var(--c-ink-3)', marginBottom: 8 }}>
                        Assigned classes · {totalSessions} sessions/wk
                      </p>
                      {/* header */}
                      <div style={{
                        display: 'grid', gridTemplateColumns: '60px 1fr 60px',
                        gap: 8, paddingBottom: 5,
                        borderBottom: '1px solid var(--c-border)', marginBottom: 2,
                        fontSize: 11, color: 'var(--c-ink-3)', fontWeight: 500,
                        textTransform: 'uppercase', letterSpacing: '.04em',
                      }}>
                        <span>Class</span>
                        <span>Subject</span>
                        <span style={{ textAlign: 'center' }}>Sess.</span>
                      </div>
                      {sortByClassName(assignments).map((a, ai) => (
                        <div key={ai} style={{
                          display: 'grid', gridTemplateColumns: '60px 1fr 60px',
                          gap: 8, alignItems: 'center', padding: '5px 0',
                          borderBottom: ai < assignments.length - 1 ? '1px solid var(--c-border)' : 'none',
                        }}>
                          <span style={{
                            fontSize: 12, fontWeight: 600, color: 'var(--c-accent)',
                            background: 'rgba(43,92,230,.07)', borderRadius: 4,
                            padding: '1px 6px', display: 'inline-block', textAlign: 'center',
                          }}>
                            {a.className}
                          </span>
                          <span style={{ fontSize: 13 }}>{a.subject}</span>
                          <span style={{ fontSize: 13, textAlign: 'center', color: 'var(--c-ink-2)' }}>{a.sessions}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p style={{ fontSize: 13, color: 'var(--c-ink-3)', fontStyle: 'italic' }}>
                      No classes assigned
                    </p>
                  )}

                </div>
              </CollapseCard>
            )
          })}
        </div>

        {/* nav buttons */}
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
              fontFamily: 'var(--f-body)', fontSize: 14, fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
            </svg>
            Back
          </button>

          <button onClick={handleContinue} style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '11px 28px', borderRadius: 100, border: 'none',
            background: 'var(--c-accent)', color: '#fff',
            fontFamily: 'var(--f-body)', fontSize: 14, fontWeight: 500,
            cursor: 'pointer',
          }}>
            Continue
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
            </svg>
          </button>
        </div>

      </div>
    </div>
  )
}

// ── helpers ───────────────────────────────────────────────────────────────────

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

// ── demo data ─────────────────────────────────────────────────────────────────
const DEMO_CLASSES = [
  { name: '10A', min_daily: 5, max_daily: 7, subjects: [
    { name: 'Mathematics',       sessions_per_week: 5, teacher: 'Prof. Ionescu',  relevance: 10 },
    { name: 'Romanian Language', sessions_per_week: 3, teacher: 'Prof. Popescu',  relevance: 8  },
    { name: 'Physics',           sessions_per_week: 4, teacher: 'Prof. Marin',    relevance: 10 },
    { name: 'Informatics',       sessions_per_week: 3, teacher: 'Prof. Petre',    relevance: 8  },
  ]},
  { name: '9A', min_daily: 4, max_daily: 7, subjects: [
    { name: 'Mathematics',       sessions_per_week: 4, teacher: 'Prof. Ionescu',  relevance: 10 },
    { name: 'Romanian Language', sessions_per_week: 3, teacher: 'Prof. Popescu',  relevance: 8  },
    { name: 'English',           sessions_per_week: 2, teacher: 'Prof. Smith',    relevance: 6  },
    { name: 'Physics',           sessions_per_week: 3, teacher: 'Prof. Marin',    relevance: 8  },
    { name: 'Biology',           sessions_per_week: 2, teacher: 'Prof. Dima',     relevance: 6  },
    { name: 'PE',                sessions_per_week: 2, teacher: 'Prof. Constantin',relevance: 4  },
  ]},
  { name: '9B', min_daily: 4, max_daily: 7, subjects: [
    { name: 'Mathematics',       sessions_per_week: 4, teacher: 'Prof. Ionescu',  relevance: 10 },
    { name: 'Romanian Language', sessions_per_week: 3, teacher: 'Prof. Popescu',  relevance: 8  },
    { name: 'Chemistry',         sessions_per_week: 2, teacher: 'Prof. Rusu',     relevance: 6  },
    { name: 'Geography',         sessions_per_week: 2, teacher: 'Prof. Gherasim', relevance: 6  },
    { name: 'Art',               sessions_per_week: 1, teacher: 'Prof. Florescu', relevance: 4  },
  ]},
]

const DEMO_TEACHERS = [
  { name: 'Prof. Ionescu',    availability: { Mon: 1, Tue: 1, Wed: 1, Thu: 1, Fri: 1 } },
  { name: 'Prof. Popescu',    availability: { Mon: 1, Tue: 1, Wed: 1, Thu: 1, Fri: 0 } },
  { name: 'Prof. Smith',      availability: { Mon: 1, Tue: 0, Wed: 1, Thu: 1, Fri: 1 } },
  { name: 'Prof. Marin',      availability: { Mon: 1, Tue: 1, Wed: 1, Thu: 1, Fri: 1 } },
  { name: 'Prof. Dima',       availability: { Mon: 0, Tue: 1, Wed: 1, Thu: 1, Fri: 1 } },
]