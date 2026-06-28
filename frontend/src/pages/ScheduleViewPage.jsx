// pages/ScheduleViewPage.jsx
import { useState, useEffect, useCallback, useRef } from 'react'
import { useStore } from '../store'
import { getSchedule, performSwap, exportTeacherSchedule, exportClassSchedules, saveProjectFile, mergeConstraintsIntoPayload } from '../api'

const DAYS      = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
const DAY_FULL  = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
const HOURS     = 8
const ALL_TEACHERS = '__all__'

const SUBJECT_COLORS = [
  { bg: 'rgba(43,92,230,0.10)',  border: 'rgba(43,92,230,0.30)',  text: '#1a3a9a' },
  { bg: 'rgba(30,124,77,0.10)', border: 'rgba(30,124,77,0.30)',  text: '#0d5c38' },
  { bg: 'rgba(180,80,0,0.10)',  border: 'rgba(180,80,0,0.30)',   text: '#7a3600' },
  { bg: 'rgba(120,40,160,0.10)',border: 'rgba(120,40,160,0.30)', text: '#5a1a80' },
  { bg: 'rgba(0,130,150,0.10)', border: 'rgba(0,130,150,0.30)', text: '#005a6a' },
  { bg: 'rgba(180,30,60,0.10)', border: 'rgba(180,30,60,0.30)', text: '#7a1030' },
  { bg: 'rgba(100,100,0,0.10)', border: 'rgba(100,100,0,0.30)', text: '#4a4a00' },
  { bg: 'rgba(0,80,160,0.10)',  border: 'rgba(0,80,160,0.30)',  text: '#003880' },
]

function subjectColor(name) {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffff
  return SUBJECT_COLORS[h % SUBJECT_COLORS.length]
}
function abbrev(subject) {
  if (!subject) return ''
  const words = subject.trim().split(/\s+/)
  if (words.length === 1) {
    // Single word — check if it's already all-caps (abbreviation)
    const w = words[0]
    if (w === w.toUpperCase() && /^[A-Z]{2,}$/.test(w)) return w
    return w.slice(0, 3)
  }
  // Multiple words — check if already an abbreviation (all caps, no spaces, 2-5 chars)
  const full = subject.trim()
  if (full === full.toUpperCase() && /^[A-Z]{2,5}$/.test(full)) return full
  // Build abbreviation from first letter of each word
  return words.map(w => w[0].toUpperCase()).join('')
}

// ── grade helpers ─────────────────────────────────────────────────────────────
function classGrade(className) {
  const m = String(className).match(/^(\d+)/)
  return m ? parseInt(m[1], 10) : 99
}
function isLowGrade(className) { return classGrade(className) <= 4 }

// ── swap analysis ─────────────────────────────────────────────────────────────
// Simulates a swap and returns { warnings: string[], notes: string[] }
// where warnings → yellow, notes → blue.
// `grids`    = { class_schedules, teacher_schedules }
// `selected` = { className, day, hour, teacher? }
// `candidate`= { class_name, day, hour }
// `searchParams` may be null — we fall back to sensible defaults.
function analyzeSwap(grids, selected, candidate) {
  if (!grids || !selected || !candidate) return { warnings: [], notes: [] }

  const cs   = grids.class_schedules
  const ts   = grids.teacher_schedules
  const selCls  = selected.className
  const canCls  = candidate.class_name
  const selDay  = selected.day
  const selHour = selected.hour
  const canDay  = candidate.day
  const canHour = candidate.hour

  // ── build post-swap class schedule snapshots ──────────────────────────────
  // Returns a mutable deep copy of class sched for ONE day: slot[hour] = {subject,teacher}|null
  function clsDaySnap(cls, day) {
    const sched = cs[cls]
    return Array.from({ length: HOURS }, (_, h) => sched?.[day]?.[h] ?? null)
  }

  // The two slots that move: selected slot ↔ candidate slot
  // selected slot content (must exist, user clicked it)
  const selSlot  = cs[selCls]?.[selDay]?.[selHour] ?? null
  const canSlot  = cs[canCls]?.[canDay]?.[canHour] ?? null

  // Build post-swap snapshots for each affected (class, day)
  // Key: `cls-day` → slot[]
  const clsSnaps = {}

  function getClsSnap(cls, day) {
    const k = `${cls}-${day}`
    if (!clsSnaps[k]) clsSnaps[k] = clsDaySnap(cls, day)
    return clsSnaps[k]
  }

  if (selCls === canCls) {
    // Same class — swap two slots within it
    if (selDay === canDay) {
      const snap = [...getClsSnap(selCls, selDay)]
      const tmp = snap[selHour]; snap[selHour] = snap[canHour]; snap[canHour] = tmp
      clsSnaps[`${selCls}-${selDay}`] = snap
    } else {
      const snapSel = [...getClsSnap(selCls, selDay)]
      const snapCan = [...getClsSnap(selCls, canDay)]
      snapSel[selHour] = canSlot
      snapCan[canHour] = selSlot
      clsSnaps[`${selCls}-${selDay}`] = snapSel
      clsSnaps[`${selCls}-${canDay}`] = snapCan
    }
  } else {
    // Cross-class swap
    const snapSelDay = [...getClsSnap(selCls, selDay)]
    const snapCanDay = [...getClsSnap(canCls, canDay)]
    snapSelDay[selHour] = canSlot
    snapCanDay[canHour] = selSlot
    clsSnaps[`${selCls}-${selDay}`] = snapSelDay
    clsSnaps[`${canCls}-${canDay}`] = snapCanDay
  }

  // ── build post-swap teacher schedule snapshots ────────────────────────────
  // teacher_schedule slot = { class_name, subject } | null
  function tDaySnap(teacher, day) {
    const sched = ts[teacher]
    return Array.from({ length: HOURS }, (_, h) => sched?.[day]?.[h] ?? null)
  }

  // Find teachers involved: derive from the actual slot data, not from selected.teacher
  // (selected.teacher can be the row-context teacher from an empty-tile click, not the
  // teacher of the lesson that will actually move — selSlot.teacher is authoritative)
  const selTeacher  = selSlot?.teacher ?? null
  const canTeacher  = canSlot?.teacher ?? null
  const teachersAffected = new Set([selTeacher, canTeacher].filter(Boolean))

  // Post-swap teacher day snapshots
  // Key: `teacher-day` → slot[]
  const tSnaps = {}

  function getTSnap(teacher, day) {
    const k = `${teacher}-${day}`
    if (!tSnaps[k]) tSnaps[k] = tDaySnap(teacher, day)
    return tSnaps[k]
  }

  // Swap the teacher slots mirroring the class swap.
  // For cross-teacher swaps we must snapshot BOTH days for EACH teacher:
  //   selTeacher loses selDay/selHour AND gains canDay/canHour
  //   canTeacher loses canDay/canHour AND gains selDay/selHour
  if (selTeacher && canTeacher && selTeacher === canTeacher) {
    // Same teacher swaps their own two slots
    if (selDay === canDay) {
      const snap = [...getTSnap(selTeacher, selDay)]
      const tmp = snap[selHour]; snap[selHour] = snap[canHour]; snap[canHour] = tmp
      tSnaps[`${selTeacher}-${selDay}`] = snap
    } else {
      const snapA = [...getTSnap(selTeacher, selDay)]
      const snapB = [...getTSnap(selTeacher, canDay)]
      const tmp = snapA[selHour]
      snapA[selHour] = snapB[canHour]
      snapB[canHour] = tmp
      tSnaps[`${selTeacher}-${selDay}`] = snapA
      tSnaps[`${selTeacher}-${canDay}`]  = snapB
    }
  } else {
    if (selTeacher) {
      // selTeacher: remove lesson from selDay, receive canSlot on canDay
      const snapSel = [...getTSnap(selTeacher, selDay)]
      snapSel[selHour] = canSlot ? { class_name: canCls, subject: canSlot.subject } : null
      tSnaps[`${selTeacher}-${selDay}`] = snapSel

      if (selDay !== canDay) {
        // selTeacher also picks up a lesson on canDay (the slot that was canTeacher's)
        const snapCan = [...getTSnap(selTeacher, canDay)]
        // selTeacher doesn't teach canDay/canHour before the swap — no change needed
        // but we need the snapshot present so teacherGapAfterSwap uses post-swap data
        tSnaps[`${selTeacher}-${canDay}`] = snapCan
      }
    }
    if (canTeacher) {
      // canTeacher: remove lesson from canDay, receive selSlot on selDay
      const snapCan = [...getTSnap(canTeacher, canDay)]
      snapCan[canHour] = selSlot ? { class_name: selCls, subject: selSlot.subject } : null
      tSnaps[`${canTeacher}-${canDay}`] = snapCan

      if (selDay !== canDay) {
        // canTeacher also picks up a lesson on selDay (the slot that was selTeacher's)
        const snapSel = [...getTSnap(canTeacher, selDay)]
        // canTeacher doesn't teach selDay/selHour before the swap — no change needed
        tSnaps[`${canTeacher}-${selDay}`] = snapSel
      }
    }
  }

  // ── analysis helpers ──────────────────────────────────────────────────────
  const warnings = []
  const notes    = []

  // Helper: given a clsSnaps key, find the matching class name and day index.
  // Sort longest-first so "10A" is tried before "10" — prevents prefix ambiguity
  // when a class name itself contains a dash (e.g. "10-A").
  const knownClasses = [...new Set([selCls, canCls].filter(Boolean))].sort((a, b) => b.length - a.length)
  function parseClsKey(key) {
    for (const cls of knownClasses) {
      const prefix = `${cls}-`
      if (key.startsWith(prefix)) {
        const day = parseInt(key.slice(prefix.length), 10)
        if (!isNaN(day)) return { cls, day }
      }
    }
    return null
  }

  // 1. Compactness (high grades only: grade 5+)
  function hasGap(filled) {
    const first = filled.indexOf(true), last = filled.lastIndexOf(true)
    if (first === -1) return false
    for (let i = first; i <= last; i++) if (!filled[i]) return true
    return false
  }

  // Check all affected class-day pairs — only warn if the swap INTRODUCES a new gap
  for (const [key, snap] of Object.entries(clsSnaps)) {
    const parsed = parseClsKey(key)
    if (!parsed) continue
    if (isLowGrade(parsed.cls)) continue
    const priorFilled = clsDaySnap(parsed.cls, parsed.day).map(s => s !== null)
    const afterFilled = snap.map(s => s !== null)
    if (hasGap(afterFilled) && !hasGap(priorFilled)) {
      warnings.push(`Breaks compactness for class ${parsed.cls} on ${DAY_FULL[parsed.day]}`)
    }
  }

  // 2. Same subject non-consecutive in a day — only warn if swap INTRODUCES a new split
  function subjectSplits(snap) {
    // Returns a Set of subject names that appear in 2+ non-consecutive blocks
    const subjHours = {}
    snap.forEach((slot, h) => {
      if (!slot) return
      if (!subjHours[slot.subject]) subjHours[slot.subject] = []
      subjHours[slot.subject].push(h)
    })
    const splits = new Set()
    for (const [subj, hours] of Object.entries(subjHours)) {
      if (hours.length < 2) continue
      for (let i = 1; i < hours.length; i++) {
        if (hours[i] !== hours[i - 1] + 1) { splits.add(subj); break }
      }
    }
    return splits
  }

  for (const [key, snap] of Object.entries(clsSnaps)) {
    const parsed = parseClsKey(key)
    if (!parsed) continue
    const priorSnap  = clsDaySnap(parsed.cls, parsed.day)
    const before = subjectSplits(priorSnap)
    const after  = subjectSplits(snap)
    for (const subj of after) {
      if (!before.has(subj)) {
        warnings.push(`Class ${parsed.cls} now has ${subj} split across non-consecutive hours on ${DAY_FULL[parsed.day]}`)
      }
    }
  }

  // 3. Too many consecutive same-subject — only warn if swap INTRODUCES a new violation
  const MAX_CONSECUTIVE_SUBJ = 2
  function maxConsecRun(snap) {
    // Returns the longest run of the same subject (1 = single slot, 2 = two in a row, …)
    let prev = null, run = 0, best = 0
    for (const slot of snap) {
      if (slot && slot.subject === prev) {
        run++
      } else {
        prev = slot?.subject ?? null
        run = slot ? 1 : 0
      }
      best = Math.max(best, run)
    }
    return best
  }

  for (const [key, snap] of Object.entries(clsSnaps)) {
    const parsed = parseClsKey(key)
    if (!parsed) continue
    // Compare post-swap max run to pre-swap max run for the same (class, day)
    const priorSnap = clsDaySnap(parsed.cls, parsed.day) // original, before swap
    const before = maxConsecRun(priorSnap)
    const after  = maxConsecRun(snap)
    if (after > MAX_CONSECUTIVE_SUBJ && after > before) {
      // Find which subject is now running too long
      let prev = null, run = 0, worstSubj = null, worstRun = 0
      for (const slot of snap) {
        if (slot && slot.subject === prev) {
          run++
          if (run > worstRun) { worstRun = run; worstSubj = slot.subject }
        } else {
          prev = slot?.subject ?? null
          run = slot ? 1 : 0
          if (run > worstRun) { worstRun = run; worstSubj = prev }
        }
      }
      warnings.push(`Class ${parsed.cls} now has ${worstRun} consecutive ${worstSubj} on ${DAY_FULL[parsed.day]}`)
    }
  }

  // 4. Teacher gap exceeds their current max gap in the schedule
  // Current max gap = max gap they currently have across all days (pre-swap baseline)
  function teacherCurrentMaxGap(teacher) {
    let maxGap = 0
    const sched = ts[teacher]
    if (!sched) return 0
    for (let d = 0; d < 5; d++) {
      const slots = Array.from({ length: HOURS }, (_, h) => !!sched[d]?.[h])
      const first = slots.indexOf(true), last = slots.lastIndexOf(true)
      if (first === -1) continue
      let g = 0
      for (let h = first; h <= last; h++) {
        if (!slots[h]) { g++; maxGap = Math.max(maxGap, g) }
        else g = 0
      }
    }
    return maxGap
  }

  function teacherGapAfterSwap(teacher) {
    let maxGap = 0
    for (let d = 0; d < 5; d++) {
      const key = `${teacher}-${d}`
      const snap = tSnaps[key] ?? tDaySnap(teacher, d)
      const slots = snap.map(s => s !== null)
      const first = slots.indexOf(true), last = slots.lastIndexOf(true)
      if (first === -1) continue
      let g = 0
      for (let h = first; h <= last; h++) {
        if (!slots[h]) { g++; maxGap = Math.max(maxGap, g) }
        else g = 0
      }
    }
    return maxGap
  }

  for (const teacher of teachersAffected) {
    const before = teacherCurrentMaxGap(teacher)
    const after  = teacherGapAfterSwap(teacher)
    if (after > before) {
      notes.push(`${teacher}'s gap increases from ${before} to ${after} hour${after !== 1 ? 's' : ''}`)
    }
  }

  return { warnings, notes }
}

// ── annotate a swap candidate ─────────────────────────────────────────────────
// Returns a possibly-mutated copy of `candidate` with updated status/violations.
// `selected` may have isEmpty=true, in which case the candidate is the FILLED source
// and the empty slot is the destination.  We normalise into a consistent
// (source, destination) pair before calling analyzeSwap so selCls is never null.
function annotateCandidate(candidate, grids, selected) {
  if (!candidate || candidate.status === 'invalid') return candidate
  if (!grids || !selected) return candidate

  // Build the effective "selected" and "candidate" for analyzeSwap.
  // When an empty slot was clicked first, the candidate is the filled slot (source)
  // and selected is the empty destination — swap the perspective so analyzeSwap
  // always sees a filled selSlot.
  let effectiveSelected, effectiveCandidate
  if (selected.isEmpty) {
    // candidate = filled source; selected = empty target
    // Don't forward selected.teacher — analyzeSwap now reads teacher from selSlot directly
    effectiveSelected = {
      className: candidate.class_name,
      day:       candidate.day,
      hour:      candidate.hour,
    }
    effectiveCandidate = {
      ...candidate,
      class_name: candidate.class_name,
      day:        selected.day,
      hour:       selected.hour,
    }
  } else {
    effectiveSelected  = selected
    effectiveCandidate = candidate
  }

  // For valid candidates: run full swap analysis
  if (candidate.status === 'valid') {
    const { warnings, notes } = analyzeSwap(grids, effectiveSelected, effectiveCandidate)
    const allMessages = [...warnings, ...notes]
    if (warnings.length > 0) {
      return {
        ...candidate,
        status: 'compactness_warning',
        violated_constraints: [...(candidate.violated_constraints || []), ...allMessages],
      }
    }
    if (notes.length > 0) {
      return {
        ...candidate,
        status: 'teacher_gap_warning',
        violated_constraints: [...(candidate.violated_constraints || []), ...allMessages],
      }
    }
    // No new issues from analyzeSwap, but surface any existing backend violations
    if (candidate.violated_constraints?.length > 0) {
      return { ...candidate, status: 'soft_violation' }
    }
  }

  // For soft_violation candidates: run FULL analysis (not just notes) so compactness
  // warnings from this swap are also caught and escalate the status to yellow.
  if (candidate.status === 'soft_violation') {
    const { warnings, notes } = analyzeSwap(grids, effectiveSelected, effectiveCandidate)
    const allMessages = [...warnings, ...notes]
    if (warnings.length > 0) {
      return {
        ...candidate,
        status: 'compactness_warning',
        violated_constraints: [...(candidate.violated_constraints || []), ...allMessages],
      }
    }
    if (notes.length > 0) {
      return {
        ...candidate,
        violated_constraints: [...(candidate.violated_constraints || []), ...notes],
      }
    }
  }

  return candidate
}

const IconBack = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>
  </svg>
)
const IconExport = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
  </svg>
)
const IconEdit = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
  </svg>
)
const IconClose = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
  </svg>
)
const IconStats = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>
  </svg>
)
const IconSave = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
    <polyline points="17 21 17 13 7 13 7 21"/>
    <polyline points="7 3 7 8 15 8"/>
  </svg>
)

function Pill({ children, color = 'blue' }) {
  const map = {
    blue:  { bg: 'rgba(43,92,230,.10)',  text: 'var(--c-accent)' },
    green: { bg: 'rgba(30,124,77,.10)',  text: 'var(--c-success)' },
    gray:  { bg: 'rgba(0,0,0,.07)',      text: 'var(--c-ink-2)' },
    red:   { bg: 'rgba(192,57,43,.10)',  text: 'var(--c-danger)' },
    amber: { bg: 'rgba(180,120,0,.10)',  text: '#7a5000' },
  }
  const s = map[color] || map.gray
  return (
    <span style={{
      fontSize: 11, padding: '2px 8px', borderRadius: 100,
      fontWeight: 500, background: s.bg, color: s.text, whiteSpace: 'nowrap',
    }}>{children}</span>
  )
}

function Spinner({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="var(--c-accent)" strokeWidth="2.5" strokeLinecap="round">
      <style>{`@keyframes _sp{to{transform:rotate(360deg)}}`}</style>
      <circle cx="12" cy="12" r="9" strokeOpacity="0.2"/>
      <path d="M12 3a9 9 0 0 1 9 9" style={{ animation:'_sp 0.8s linear infinite', transformOrigin:'12px 12px' }}/>
    </svg>
  )
}

function ViolationTooltip({ violations, style, onClick, children }) {
  const [show, setShow] = useState(false)
  return (
    <td
      style={{ ...style, position: 'relative' }}
      onClick={onClick}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && violations?.length > 0 && (
        <div style={{
          position: 'absolute', bottom: 'calc(100% + 6px)', left: '50%',
          transform: 'translateX(-50%)', zIndex: 200,
          background: 'var(--c-ink)', color: '#fff',
          borderRadius: 6, padding: '6px 10px',
          fontSize: 11, lineHeight: 1.5,
          whiteSpace: 'nowrap', pointerEvents: 'none',
          boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
        }}>
          {violations.map((v, i) => <div key={i}>{v}</div>)}
          <div style={{
            position: 'absolute', top: '100%', left: '50%',
            transform: 'translateX(-50%)',
            borderLeft: '5px solid transparent',
            borderRight: '5px solid transparent',
            borderTop: '5px solid var(--c-ink)',
          }}/>
        </div>
      )}
    </td>
  )
}

// ── shared cell highlight logic ───────────────────────────────────────────────
function getCellStyle({ editMode, slot, selected, isSelected, isCandidate, candidate, hasContent }) {
  let cellExtra = {}
  let cursor = 'default'

  // In edit mode, any tile is clickable — filled tiles to select as source,
  // empty tiles to select as target (reverse-lookup candidates).
  if (editMode && !selected) cursor = 'pointer'
  if (isSelected) {
    cellExtra = { boxShadow: 'inset 0 0 0 3px var(--c-accent)', background: 'rgba(43,92,230,0.20)' }
    cursor = 'pointer'
  }
  if (editMode && selected && isCandidate) {
    cursor = 'pointer'
    if (candidate.status === 'compactness_warning') {
      cellExtra = { boxShadow: 'inset 0 0 0 3px #c8970a', background: 'rgba(200,151,10,0.22)' }
    } else if (candidate.status === 'teacher_gap_warning') {
      cellExtra = { boxShadow: 'inset 0 0 0 3px #7c3aed', background: 'rgba(124,58,237,0.18)' }
    } else if (candidate.status === 'valid') {
      cellExtra = { boxShadow: 'inset 0 0 0 3px var(--c-success)', background: 'rgba(30,124,77,0.38)' }
    } else if (candidate.status === 'soft_violation') {
      cellExtra = { boxShadow: 'inset 0 0 0 3px #e0a020', background: 'rgba(180,130,0,0.32)' }
    } else {
      cellExtra = { boxShadow: 'inset 0 0 0 3px var(--c-danger)', background: 'rgba(192,57,43,0.30)' }
    }
  }
  return { cellExtra, cursor }
}

// ── class schedule grid ───────────────────────────────────────────────────────
function ClassScheduleGrid({ schedule, className, editMode, selected, onSelect, swapCandidates, onSwap, grids }) {
  const candidateMap = {}
  if (swapCandidates) {
    swapCandidates.forEach(c => {
      if (c.class_name === className) candidateMap[`${c.day}-${c.hour}`] = c
    })
  }

  return (
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
                const slot        = schedule?.[di]?.[h]
                const key         = `${di}-${h}`
                const isSelected  = selected?.day === di && selected?.hour === h && selected?.className === className &&
                  (selected.isEmpty ? !slot : true)
                let candidate   = annotateCandidate(candidateMap[key], grids, selected)
                const isCandidate = !!candidate
                const { cellExtra, cursor } = getCellStyle({ editMode, slot, selected, isSelected, isCandidate, candidate, hasContent: !!slot })

                const handleClick = () => {
                  if (!editMode) return
                  if (isSelected) { onSelect(null); return }
                  if (selected && isCandidate) { if (candidate.status !== 'invalid') onSwap(candidate); return }
                  if (!selected) onSelect({ className, day: di, hour: h, isEmpty: !slot })
                }

                const col = slot ? subjectColor(slot.subject) : null
                const cellContent = slot ? (
                  <div style={{ background: col.bg, border: `1px solid ${col.border}`, borderRadius: 6, padding: '4px 6px', height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 1 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: col.text, lineHeight: 1.2 }}>{slot.subject}</div>
                    <div style={{ fontSize: 10, color: 'var(--c-ink-3)', lineHeight: 1.2 }}>{slot.teacher}</div>
                  </div>
                ) : (
                  <div style={{ height: '100%', background: 'var(--c-bg)', borderRadius: 6 }}/>
                )

                const tdStyle_ = { ...tdStyle, padding: 3, height: 52, cursor, transition: 'background 0.1s, box-shadow 0.1s', ...cellExtra }

                if (editMode && selected && isCandidate && candidate.violated_constraints?.length) {
                  return (
                    <ViolationTooltip key={di} violations={candidate.violated_constraints} style={tdStyle_} onClick={handleClick}>
                      {cellContent}
                    </ViolationTooltip>
                  )
                }
                return <td key={di} onClick={handleClick} style={tdStyle_}>{cellContent}</td>
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── teacher schedule grid (individual teacher view) ───────────────────────────
// slot is now { class_name, subject } — color by class_name, show both
function TeacherScheduleGrid({ schedule, teacherName, editMode, selected, onSelect, swapCandidates, onSwap, grids }) {
  const candidateMap = {}
  if (swapCandidates) {
    swapCandidates.forEach(c => { candidateMap[`${c.class_name}-${c.day}-${c.hour}`] = c })
  }

  return (
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
                // slot is { class_name, subject } or null
                const slot         = schedule?.[di]?.[h]
                const className    = slot?.class_name ?? null
                const isSelected   = selected?.day === di && selected?.hour === h && selected?.teacher === teacherName &&
                  (selected.isEmpty ? !slot : selected?.className === className)
                const candidateKey = `${className}-${di}-${h}`
                let candidate    = annotateCandidate(candidateMap[candidateKey], grids, selected)
                const isCandidate  = !!candidate && !!className
                const { cellExtra, cursor } = getCellStyle({ editMode, selected, isSelected, isCandidate, candidate, hasContent: !!slot })

                const handleClick = () => {
                  if (!editMode) return
                  if (isSelected) { onSelect(null); return }
                  if (selected && isCandidate) { if (candidate.status !== 'invalid') onSwap(candidate); return }
                  if (!selected) {
                    if (slot) onSelect({ className, day: di, hour: h, teacher: teacherName })
                    else      onSelect({ className: null, day: di, hour: h, teacher: teacherName, isEmpty: true })
                  }
                }

                // Color by class name; show class name (bold) + full subject name below
                const col = slot ? subjectColor(slot.class_name) : null
                const cellContent = slot ? (
                  <div style={{
                    background: col.bg, border: `1px solid ${col.border}`,
                    borderRadius: 6, padding: '4px 6px', height: '100%',
                    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 2,
                  }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: col.text, lineHeight: 1.2 }}>{slot.class_name}</span>
                    <span style={{ fontSize: 10, color: col.text, opacity: 0.8, lineHeight: 1.2, textAlign: 'center' }}>{slot.subject}</span>
                  </div>
                ) : (
                  <div style={{ height: '100%', background: 'var(--c-bg)', borderRadius: 6 }}/>
                )

                const tdStyle_ = { ...tdStyle, padding: 3, height: 56, cursor, transition: 'background 0.1s, box-shadow 0.1s', ...cellExtra }

                if (editMode && selected && isCandidate && candidate?.violated_constraints?.length) {
                  return (
                    <ViolationTooltip key={di} violations={candidate.violated_constraints} style={tdStyle_} onClick={handleClick}>
                      {cellContent}
                    </ViolationTooltip>
                  )
                }
                return <td key={di} onClick={handleClick} style={tdStyle_}>{cellContent}</td>
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── all teachers overview grid ────────────────────────────────────────────────
// slot is now { class_name, subject } — show class_name + first 3 chars of subject
function AllTeachersGrid({ grids, editMode, selected, onSelect, swapCandidates, onSwap }) {
  if (!grids) return null
  const teachers = Object.keys(grids.teacher_schedules).sort()

  // Build candidate lookup maps from swapCandidates.
  // When a FILLED slot is selected, candidates are filled slots of the same class
  // or empty slots of the same teacher.
  // When an EMPTY slot is selected (isEmpty), candidates are the teacher's own filled slots.
  const filledCandidateMap = {}  // key: `${class_name}-${day}-${hour}` → candidate (filled source/target)
  const emptyTargetMap    = {}   // key: `${teacher}-${day}-${hour}`    → candidate (empty target for same-teacher)
  const emptySourceMap    = {}   // key: `${class_name}-${day}-${hour}` → candidate (filled source when empty selected)

  if (swapCandidates && selected) {
    if (selected.isEmpty) {
      // Empty tile selected — candidates are the selecting teacher's filled slots
      swapCandidates.forEach(c => {
        emptySourceMap[`${c.class_name}-${c.day}-${c.hour}`] = c
      })
    } else {
      swapCandidates.forEach(c => {
        // Check if this candidate slot is filled (any teacher teaching at that day/hour for that class)
        let isFilledSlot = false
        for (const t of Object.keys(grids.teacher_schedules)) {
          const s = grids.teacher_schedules[t][c.day]?.[c.hour]
          if (s && s.class_name === c.class_name) { isFilledSlot = true; break }
        }

        if (isFilledSlot && c.class_name === selected.className) {
          filledCandidateMap[`${c.class_name}-${c.day}-${c.hour}`] = c
        } else if (!isFilledSlot && c.class_name === selected.className) {
          // Empty target slot for the same class — keyed by teacher+day+hour of the selected slot's teacher
          emptyTargetMap[`${selected.teacher}-${c.day}-${c.hour}`] = c
        }
      })
    }
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', tableLayout: 'fixed' }}>
        <thead>
          <tr>
            <th style={{ ...thStyle, width: 160, textAlign: 'left', paddingLeft: 8, position: 'sticky', left: 0, zIndex: 2, background: 'var(--c-bg)' }}>
              Teacher
            </th>
            <th style={{ ...thStyle, width: 44, textAlign: 'center' }}>Total</th>
            {DAYS.map((d, di) => (
              Array.from({ length: HOURS }, (_, h) => (
                <th key={`${di}-${h}`} style={{
                  ...thStyle, width: 42, textAlign: 'center',
                  borderLeft: h === 0 ? '2px solid var(--c-border)' : undefined,
                  paddingTop: h === 0 ? 4 : 8,
                }}>
                  {h === 0
                    ? <><div style={{ fontSize: 11, fontWeight: 600, color: 'var(--c-ink-2)' }}>{d}</div><div style={{ fontSize: 10, fontWeight: 400, color: 'var(--c-ink-3)' }}>H1</div></>
                    : <div style={{ fontSize: 10, color: 'var(--c-ink-3)' }}>H{h + 1}</div>
                  }
                </th>
              ))
            ))}
          </tr>
        </thead>
        <tbody>
          {teachers.map(teacher => {
            const sched = grids.teacher_schedules[teacher]
            let total = 0
            for (let d = 0; d < 5; d++) for (let h = 0; h < HOURS; h++) if (sched?.[d]?.[h]) total++

            const isSelectedTeacher = selected?.teacher === teacher

            return (
              <tr key={teacher}>
                <td style={{
                  ...tdStyle, padding: '4px 8px', fontSize: 12, fontWeight: 500,
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  maxWidth: 160, position: 'sticky', left: 0, zIndex: 1,
                  background: isSelectedTeacher && editMode && selected
                    ? 'rgba(43,92,230,0.06)'
                    : 'var(--c-surface)',
                }}>
                  {teacher}
                </td>
                <td style={{ ...tdStyle, textAlign: 'center', fontSize: 12, fontWeight: 600, color: 'var(--c-accent)', background: 'rgba(43,92,230,0.04)' }}>
                  {total}
                </td>
                {DAYS.map((_, di) =>
                  Array.from({ length: HOURS }, (__, h) => {
                    const slot = sched?.[di]?.[h]
                    const className = slot?.class_name ?? null

                    // isSelected: matches the currently selected tile (filled or empty)
                    const isSelected = selected?.day === di && selected?.hour === h && selected?.teacher === teacher &&
                      (selected.isEmpty ? !slot : selected?.className === className)

                    // Resolve candidate for this cell
                    let candidate = null
                    if (!isSelected && selected) {
                      if (selected.isEmpty) {
                        // Empty selected — highlight this teacher's filled slots as sources
                        if (slot && teacher === selected.teacher) {
                          candidate = annotateCandidate(emptySourceMap[`${className}-${di}-${h}`], grids, selected)
                        }
                      } else {
                        if (slot) {
                          // Filled slot — check if it's a same-class filled candidate
                          candidate = annotateCandidate(filledCandidateMap[`${className}-${di}-${h}`], grids, selected)
                        } else if (isSelectedTeacher) {
                          // Empty slot of the same teacher — check empty target map
                          candidate = annotateCandidate(emptyTargetMap[`${teacher}-${di}-${h}`], grids, selected)
                        }
                      }
                    }
                    const isCandidate = !!candidate

                    const { cellExtra, cursor } = getCellStyle({
                      editMode, selected, isSelected, isCandidate, candidate, hasContent: !!slot,
                    })

                    const handleClick = () => {
                      if (!editMode) return
                      if (isSelected) { onSelect(null); return }
                      if (selected && isCandidate) { if (candidate.status !== 'invalid') onSwap(candidate); return }
                      if (!selected) {
                        if (slot) onSelect({ className, day: di, hour: h, teacher })
                        else      onSelect({ className: null, day: di, hour: h, teacher, isEmpty: true })
                      }
                    }

                    // Color by class name; show class name + abbrev subject
                    const col = slot ? subjectColor(className) : null
                    const cellContent = slot ? (
                      <div style={{
                        background: col.bg, border: `1px solid ${col.border}`,
                        borderRadius: 4, height: '100%',
                        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 1,
                      }}>
                        <span style={{ fontSize: 10, fontWeight: 700, color: col.text, lineHeight: 1.1 }}>{className}</span>
                        <span style={{ fontSize: 9, color: col.text, opacity: 0.75, lineHeight: 1.1 }}>{abbrev(slot.subject)}</span>
                      </div>
                    ) : (
                      <div style={{ height: '100%', background: 'var(--c-bg)', borderRadius: 4 }}/>
                    )

                    const tdStyle_ = {
                      ...tdStyle, padding: 2, height: 38, width: 42,
                      cursor, transition: 'background 0.1s, box-shadow 0.1s',
                      ...cellExtra,
                      borderLeft: h === 0 ? '2px solid var(--c-border)' : undefined,
                    }

                    if (editMode && selected && isCandidate && candidate?.violated_constraints?.length) {
                      return (
                        <ViolationTooltip key={`${di}-${h}`} violations={candidate.violated_constraints} style={tdStyle_} onClick={handleClick}>
                          {cellContent}
                        </ViolationTooltip>
                      )
                    }
                    return <td key={`${di}-${h}`} onClick={handleClick} style={tdStyle_}>{cellContent}</td>
                  })
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── stats panel ───────────────────────────────────────────────────────────────
function StatsPanel({ grids }) {
  if (!grids) return null
  const { class_schedules } = grids

  const classStats = Object.entries(class_schedules).map(([name, sched]) => {
    let total = 0, perDay = []
    for (let d = 0; d < 5; d++) {
      let count = 0
      for (let h = 0; h < HOURS; h++) if (sched[d][h]) count++
      perDay.push(count)
      total += count
    }
    const min = Math.min(...perDay.filter(x => x > 0))
    const max = Math.max(...perDay)
    const avg = (total / perDay.filter(x => x > 0).length).toFixed(1)

    let maxConsec = 0
    for (let d = 0; d < 5; d++) {
      let run = 0, best = 0
      for (let h = 0; h < HOURS; h++) {
        if (sched[d][h]) { run++; best = Math.max(best, run) } else run = 0
      }
      maxConsec = Math.max(maxConsec, best)
    }

    const subjCount = {}
    for (let d = 0; d < 5; d++)
      for (let h = 0; h < HOURS; h++)
        if (sched[d][h]) subjCount[sched[d][h].subject] = (subjCount[sched[d][h].subject] || 0) + 1

    return { name, total, perDay, min, max, avg, maxConsec, subjCount }
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {classStats.map(st => (
        <div key={st.name} style={{ background: 'var(--c-surface)', border: '1px solid var(--c-border)', borderRadius: 'var(--r-lg)', overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', borderBottom: '1px solid var(--c-border)', background: 'var(--c-bg)' }}>
            <span style={{ fontWeight: 700, fontSize: 14 }}>{st.name}</span>
            <Pill color="blue">{st.total} sessions/wk</Pill>
            <Pill color="gray">avg {st.avg}/day</Pill>
            {st.maxConsec > 2 ? <Pill color="amber">max {st.maxConsec} consec</Pill> : <Pill color="green">✓ consecutive ok</Pill>}
          </div>
          <div style={{ padding: '12px 16px' }}>
            <div style={{ display: 'flex', gap: 6, marginBottom: 12, alignItems: 'flex-end' }}>
              {st.perDay.map((count, di) => (
                <div key={di} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--c-ink-2)' }}>{count}</div>
                  <div style={{ width: '100%', borderRadius: 3, height: Math.max(4, count * 10), background: count === st.max ? 'var(--c-accent)' : count === st.min && count > 0 ? 'var(--c-success)' : 'var(--c-border-h)', transition: 'height 0.3s' }}/>
                  <div style={{ fontSize: 10, color: 'var(--c-ink-3)' }}>{DAYS[di]}</div>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {Object.entries(st.subjCount).map(([subj, cnt]) => {
                const col = subjectColor(subj)
                return (
                  <span key={subj} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 100, background: col.bg, color: col.text, border: `1px solid ${col.border}`, fontWeight: 500 }}>
                    {subj} ×{cnt}
                  </span>
                )
              })}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── export helpers ────────────────────────────────────────────────────────────
function exportCSV(grids) {
  if (!grids) return
  const { class_schedules, teacher_schedules } = grids

  const classRows = ['Class,Day,Hour,Subject,Teacher']
  Object.entries(class_schedules).forEach(([cls, sched]) => {
    for (let d = 0; d < 5; d++)
      for (let h = 0; h < HOURS; h++) {
        const s = sched[d][h]
        if (s) classRows.push(`${cls},${DAY_FULL[d]},${h+1},${s.subject},${s.teacher}`)
      }
  })
  downloadBlob(classRows.join('\n'), 'class_schedules.csv', 'text/csv')

  // teacher_schedules slots are now { class_name, subject }
  const teacherRows = ['Teacher,Day,Hour,Class,Subject']
  Object.entries(teacher_schedules).forEach(([teacher, sched]) => {
    for (let d = 0; d < 5; d++)
      for (let h = 0; h < HOURS; h++) {
        const slot = sched[d][h]
        if (slot) teacherRows.push(`${teacher},${DAY_FULL[d]},${h+1},${slot.class_name},${slot.subject}`)
      }
  })
  downloadBlob(teacherRows.join('\n'), 'teacher_schedules.csv', 'text/csv')
}

function downloadBlob(content, filename, type) {
  const blob = new Blob([content], { type })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

// ── table style helpers ───────────────────────────────────────────────────────
const thStyle = {
  padding: '8px 4px',
  borderBottom: '1px solid var(--c-border)',
  background: 'var(--c-bg)',
  color: 'var(--c-ink-2)',
  fontWeight: 500,
  fontSize: 12,
  whiteSpace: 'nowrap',
}
const tdStyle = {
  border: '1px solid var(--c-border)',
  verticalAlign: 'top',
}

function SwapLegend() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14, fontSize: 11, color: 'var(--c-ink-3)', flexWrap: 'wrap' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <div style={{ width: 12, height: 12, borderRadius: 3, boxShadow: 'inset 0 0 0 2px var(--c-success)', background: 'rgba(30,124,77,0.38)' }}/>
        Valid swap
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <div style={{ width: 12, height: 12, borderRadius: 3, boxShadow: 'inset 0 0 0 2px #c8970a', background: 'rgba(200,151,10,0.22)' }}/>
        Schedule quality issue (hover for details)
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <div style={{ width: 12, height: 12, borderRadius: 3, boxShadow: 'inset 0 0 0 2px #7c3aed', background: 'rgba(124,58,237,0.18)' }}/>
        Teacher gap increases (hover for details)
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <div style={{ width: 12, height: 12, borderRadius: 3, boxShadow: 'inset 0 0 0 2px #e0a020', background: 'rgba(180,130,0,0.32)' }}/>
        Soft constraint violation (hover for details)
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <div style={{ width: 12, height: 12, borderRadius: 3, boxShadow: 'inset 0 0 0 2px var(--c-danger)', background: 'rgba(192,57,43,0.30)' }}/>
        Cannot swap
      </div>
    </div>
  )
}

// ── grade sort helper ─────────────────────────────────────────────────────────
function gradeKey(name) {
  const m = String(name).match(/^(\d+)([A-Za-z]*)$/)
  if (!m) return { bucket: 1, grade: 0, variant: String(name).toUpperCase() }
  const grade = parseInt(m[1], 10)
  const variant = m[2].toUpperCase()
  const bucket = grade >= 5 ? 0 : grade >= 1 ? 2 : 3
  return { bucket, grade, variant }
}

function sortClasses(names) {
  return [...names].sort((a, b) => {
    const A = gradeKey(a), B = gradeKey(b)
    if (A.bucket !== B.bucket) return A.bucket - B.bucket
    if (A.grade  !== B.grade)  return A.grade  - B.grade
    return A.variant.localeCompare(B.variant)
  })
}

// ── main page ─────────────────────────────────────────────────────────────────
export default function ScheduleViewPage({
  onBack,
  sessionId: sessionIdProp,
  customizePayload,
  classConstraintsPayload,
  teacherConstraintsPayload,
  searchParams,
}) {
  const { parsedData } = useStore()
  const sessionId = sessionIdProp ?? parsedData?.session_id
  const [saveState, setSaveState] = useState('idle') // idle | saved

  const [grids,         setGrids]         = useState(null)
  const [loading,       setLoading]       = useState(true)
  const [error,         setError]         = useState(null)
  const [viewMode,      setViewMode]      = useState('classes')
  const [activeClass,   setActiveClass]   = useState(null)
  const [activeTeacher, setActiveTeacher] = useState(ALL_TEACHERS)
  const [showStats,     setShowStats]     = useState(false)
  const [editMode,      setEditMode]      = useState(false)
  const [selected,      setSelected]      = useState(null)
  const [candidates,    setCandidates]    = useState(null)
  const [swapping,      setSwapping]      = useState(false)

  useEffect(() => {
    if (!sessionId) return
    getSchedule(sessionId)
      .then(data => {
        setGrids(data)
        const sorted = sortClasses(Object.keys(data.class_schedules))
        setActiveClass(sorted[0] ?? null)
        setActiveTeacher(ALL_TEACHERS)
        setLoading(false)
      })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [sessionId])

  useEffect(() => {
    if (!selected || !sessionId) { setCandidates(null); return }

    if (selected.isEmpty) {
      // Empty tile selected as move target.
      if (selected.teacher) {
        // Teacher view: all filled slots of this teacher are potential sources.
        // We list them as valid candidates; the backend will enforce actual constraints on performSwap.
        const teacherSched = grids?.teacher_schedules?.[selected.teacher]
        if (!teacherSched) { setCandidates(null); return }

        const syntheticCandidates = []
        for (let d = 0; d < 5; d++) {
          for (let h = 0; h < HOURS; h++) {
            const s = teacherSched[d]?.[h]
            if (s) syntheticCandidates.push({
              class_name: s.class_name,
              day: d,
              hour: h,
              status: 'valid',
              violated_constraints: [],
            })
          }
        }
        setCandidates(syntheticCandidates)
      } else {
        // Class view empty tile: all filled slots of that class are potential sources.
        const className = selected.className
        const sched = grids?.class_schedules?.[className]
        if (!sched) { setCandidates(null); return }

        const syntheticCandidates = []
        for (let d = 0; d < 5; d++) {
          for (let h = 0; h < HOURS; h++) {
            if (sched[d]?.[h]) syntheticCandidates.push({
              class_name: className,
              day: d,
              hour: h,
              status: 'valid',
              violated_constraints: [],
            })
          }
        }
        setCandidates(syntheticCandidates)
      }
      return
    }

    fetch('/api/swap/candidates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, class_name: selected.className, day: selected.day, hour: selected.hour }),
    })
      .then(r => r.json())
      .then(setCandidates)
      .catch(() => setCandidates([]))
  }, [selected, sessionId])

  const handleSelect = useCallback((sel) => {
    setSelected(sel)
    if (!sel) setCandidates(null)
  }, [])

  const handleSwap = useCallback(async (candidate) => {
    if (!selected || swapping) return
    setSwapping(true)
    try {
      let slotA, slotB
      if (selected.isEmpty) {
        // Empty tile was selected first — candidate is the filled source, selected is the empty target
        slotA = { className: candidate.class_name, day: candidate.day,  hour: candidate.hour }
        slotB = { className: candidate.class_name, day: selected.day,   hour: selected.hour  }
      } else {
        slotA = { className: selected.className,   day: selected.day,   hour: selected.hour  }
        slotB = { className: candidate.class_name, day: candidate.day,  hour: candidate.hour }
      }
      const updated = await performSwap(sessionId, slotA, slotB)
      setGrids(updated)
      setSelected(null)
      setCandidates(null)
    } catch (e) {
      console.error('Swap failed', e)
    }
    setSwapping(false)
  }, [selected, sessionId, swapping])

  const toggleEdit = () => {
    setEditMode(e => !e)
    setSelected(null)
    setCandidates(null)
  }

  const handleSaveProject = () => {
    if (!grids) return
    const baseClasses  = customizePayload?.classes  ?? parsedData?.classes  ?? []
    const baseTeachers = customizePayload?.teachers ?? parsedData?.teachers ?? []
    const { classes, teachers } = mergeConstraintsIntoPayload({
      classes:  baseClasses,
      teachers: baseTeachers,
      classConstraintsPayload,
      teacherConstraintsPayload,
    })
    saveProjectFile({
      classes,
      teachers,
      customizePayload,
      classConstraintsPayload,
      teacherConstraintsPayload,
      searchParams,
      grids,
    })
    setSaveState('saved')
    setTimeout(() => setSaveState('idle'), 1800)
  }

  const classList   = grids ? sortClasses(Object.keys(grids.class_schedules)) : []
  const teacherList = grids ? Object.keys(grids.teacher_schedules).sort() : []

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, minHeight: '60vh', flexDirection: 'column', gap: 12 }}>
      <Spinner size={28}/>
      <div style={{ fontSize: 13, color: 'var(--c-ink-3)' }}>Loading schedule…</div>
    </div>
  )

  if (error) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, minHeight: '60vh', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 14, color: 'var(--c-danger)' }}>Failed to load schedule: {error}</div>
      <button onClick={onBack} style={btnStyle('outline')}>← Back</button>
    </div>
  )

  const isAllTeachersView = viewMode === 'teachers' && activeTeacher === ALL_TEACHERS
  const editHint = swapping
    ? '⟳ Swapping…'
    : selected
      ? isAllTeachersView
        ? `Selected: ${selected.className} · ${DAYS[selected.day]} H${selected.hour + 1} — highlighted slots show same-class or same-teacher swaps`
        : selected.isEmpty
          ? `Empty slot selected: ${DAYS[selected.day]} H${selected.hour + 1} — click a highlighted filled slot to move it here`
          : `Selected: ${selected.className} · ${DAYS[selected.day]} H${selected.hour + 1} — click a highlighted slot to swap, or click the same slot to deselect`
      : isAllTeachersView
        ? '✎ Edit mode — click any slot to see valid same-class or same-teacher swaps'
        : '✎ Edit mode — click any slot (filled or empty) to select it, then click another to swap or move'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>

      {/* header */}
      <div style={{
        padding: '16px 24px', borderBottom: '1px solid var(--c-border)',
        background: 'var(--c-surface)', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
      }}>
        <button onClick={onBack} style={{ ...btnStyle('outline'), padding: '7px 14px', display: 'flex', alignItems: 'center', gap: 6 }}>
          <IconBack/> Back
        </button>

        <h1 style={{ fontFamily: 'var(--f-display)', fontSize: 22, letterSpacing: '-0.4px', margin: 0, flex: 1 }}>
          Schedule
        </h1>

        <div style={{ display: 'flex', gap: 0, border: '1px solid var(--c-border)', borderRadius: 8, overflow: 'hidden' }}>
          {[['classes','Classes'],['teachers','Teachers']].map(([k,l]) => (
            <button key={k} onClick={() => { setViewMode(k); setSelected(null); setCandidates(null) }} style={{
              padding: '7px 16px', border: 'none', fontSize: 13, fontWeight: 500,
              fontFamily: 'var(--f-body)', cursor: 'pointer',
              background: viewMode === k ? 'var(--c-accent)' : 'var(--c-surface)',
              color: viewMode === k ? '#fff' : 'var(--c-ink-2)',
              transition: 'all 0.15s',
            }}>{l}</button>
          ))}
        </div>

        <button
          onClick={() => setShowStats(s => !s)}
          style={{ ...btnStyle(showStats ? 'accent' : 'outline'), display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px' }}
        >
          <IconStats/> Stats
        </button>

        <button
          onClick={toggleEdit}
          style={{ ...btnStyle(editMode ? 'accent' : 'outline'), display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px' }}
        >
          <IconEdit/> {editMode ? 'Editing' : 'Edit'}
        </button>

        <button
          onClick={handleSaveProject}
          style={{ ...btnStyle(saveState === 'saved' ? 'accent' : 'outline'), display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px' }}
        >
          <IconSave/> {saveState === 'saved' ? 'Saved!' : 'Save project'}
        </button>

        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={() => exportCSV(grids)} style={{ ...btnStyle('outline'), display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', fontSize: 12 }}>
            <IconExport/> CSV
          </button>
          <button onClick={() => exportTeacherSchedule(sessionId)} style={{ ...btnStyle('outline'), display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', fontSize: 12 }}>
            <IconExport/> Teachers XLSX
          </button>
          <button onClick={() => exportClassSchedules(sessionId)} style={{ ...btnStyle('outline'), display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', fontSize: 12 }}>
            <IconExport/> Classes XLSX
          </button>
        </div>
      </div>

      {/* body */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

        {/* sidebar */}
        <div style={{
          width: 180, flexShrink: 0, borderRight: '1px solid var(--c-border)',
          background: 'var(--c-surface)', overflowY: 'auto', padding: '8px 0',
        }}>
          <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '.07em', textTransform: 'uppercase', color: 'var(--c-ink-3)', padding: '4px 14px 8px' }}>
            {viewMode === 'classes' ? 'Classes' : 'Teachers'}
          </div>

          {viewMode === 'teachers' && (
            <button
              onClick={() => { setActiveTeacher(ALL_TEACHERS); setSelected(null); setCandidates(null) }}
              style={{
                display: 'block', width: '100%', textAlign: 'left',
                padding: '7px 14px', border: 'none', fontFamily: 'var(--f-body)',
                fontSize: 13, fontWeight: activeTeacher === ALL_TEACHERS ? 600 : 400, cursor: 'pointer',
                background: activeTeacher === ALL_TEACHERS ? 'rgba(43,92,230,0.08)' : 'transparent',
                color: activeTeacher === ALL_TEACHERS ? 'var(--c-accent)' : 'var(--c-ink-2)',
                borderLeft: `3px solid ${activeTeacher === ALL_TEACHERS ? 'var(--c-accent)' : 'transparent'}`,
                borderBottom: '1px solid var(--c-border)',
                marginBottom: 4,
                transition: 'all 0.1s',
              }}
            >
              All teachers
            </button>
          )}

          {(viewMode === 'classes' ? classList : teacherList).map(name => {
            const active = viewMode === 'classes' ? activeClass === name : activeTeacher === name
            return (
              <button
                key={name}
                onClick={() => {
                  if (viewMode === 'classes') setActiveClass(name)
                  else setActiveTeacher(name)
                  setSelected(null); setCandidates(null)
                }}
                style={{
                  display: 'block', width: '100%', textAlign: 'left',
                  padding: '7px 14px', border: 'none', fontFamily: 'var(--f-body)',
                  fontSize: 13, fontWeight: active ? 600 : 400, cursor: 'pointer',
                  background: active ? 'rgba(43,92,230,0.08)' : 'transparent',
                  color: active ? 'var(--c-accent)' : 'var(--c-ink-2)',
                  borderLeft: `3px solid ${active ? 'var(--c-accent)' : 'transparent'}`,
                  transition: 'all 0.1s',
                }}
              >
                {name}
              </button>
            )
          })}
        </div>

        {/* main content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>

          {editMode && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
              padding: '10px 14px', borderRadius: 8, marginBottom: 16,
              background: selected ? 'rgba(43,92,230,0.06)' : 'rgba(180,130,0,0.06)',
              border: `1px solid ${selected ? 'rgba(43,92,230,0.2)' : 'rgba(180,130,0,0.25)'}`,
            }}>
              <div style={{ flex: 1, fontSize: 13, color: selected ? 'var(--c-accent)' : '#7a5800', fontWeight: 500 }}>
                {editHint}
              </div>
              {selected && (
                <button onClick={() => { setSelected(null); setCandidates(null) }} style={{ ...btnStyle('outline'), padding: '4px 10px', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <IconClose/> Deselect
                </button>
              )}
              {selected && candidates && <SwapLegend/>}
            </div>
          )}

          {showStats ? (
            <StatsPanel grids={grids}/>

          ) : viewMode === 'classes' && activeClass ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Class {activeClass}</h2>
                {grids?.class_schedules?.[activeClass] && (() => {
                  let total = 0
                  for (let d = 0; d < 5; d++) for (let h = 0; h < HOURS; h++) if (grids.class_schedules[activeClass][d][h]) total++
                  return <Pill color="blue">{total} sessions</Pill>
                })()}
              </div>
              <ClassScheduleGrid
                schedule={grids?.class_schedules?.[activeClass]}
                className={activeClass}
                editMode={editMode}
                selected={selected}
                onSelect={handleSelect}
                swapCandidates={candidates}
                onSwap={handleSwap}
                grids={grids}
              />
            </>

          ) : viewMode === 'teachers' && activeTeacher === ALL_TEACHERS ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>All Teachers</h2>
                <Pill color="gray">{teacherList.length} teachers</Pill>
                {editMode && <Pill color="blue">Same-class &amp; same-teacher swaps only</Pill>}
              </div>
              <AllTeachersGrid
                grids={grids}
                editMode={editMode}
                selected={selected}
                onSelect={handleSelect}
                swapCandidates={candidates}
                onSwap={handleSwap}
              />
            </>

          ) : viewMode === 'teachers' && activeTeacher ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>{activeTeacher}</h2>
                {grids?.teacher_schedules?.[activeTeacher] && (() => {
                  let total = 0
                  for (let d = 0; d < 5; d++) for (let h = 0; h < HOURS; h++) if (grids.teacher_schedules[activeTeacher][d][h]) total++
                  return <Pill color="green">{total} classes/wk</Pill>
                })()}
              </div>
              <TeacherScheduleGrid
                schedule={grids?.teacher_schedules?.[activeTeacher]}
                teacherName={activeTeacher}
                editMode={editMode}
                selected={selected}
                onSelect={handleSelect}
                swapCandidates={candidates}
                onSwap={handleSwap}
                grids={grids}
              />
            </>

          ) : null}

        </div>
      </div>
    </div>
  )
}

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