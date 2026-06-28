// api.js — all calls to the FastAPI backend

const BASE = '/api'

export async function downloadTemplate() {
  const res = await fetch(`${BASE}/template`)
  if (!res.ok) throw new Error('Template download failed')
  const blob = await res.blob()
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = 'schedule_template.xlsx'
  a.click()
  URL.revokeObjectURL(url)
}

export async function uploadExcel(file) {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`${BASE}/upload`, { method: 'POST', body: fd })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Upload failed')
  }
  return res.json()   // ParsedData
}

export function solveStream(payload, onMessage) {
  // Returns a controller so caller can abort
  const ctrl = new AbortController()
  fetch(`${BASE}/solve/stream`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(payload),
    signal:  ctrl.signal,
  }).then(async (res) => {
    const reader = res.body.getReader()
    const dec    = new TextDecoder()
    let buf      = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop()
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try { onMessage(JSON.parse(line.slice(6))) } catch {}
        }
      }
    }
  }).catch((e) => { if (e.name !== 'AbortError') onMessage({ type: 'error', message: String(e) }) })
  return ctrl
}



export async function getSchedule(sessionId) {
  const res = await fetch(`${BASE}/schedule/${sessionId}`)
  if (!res.ok) throw new Error('Could not fetch schedule')
  return res.json()
}

export async function getSwapCandidates(sessionId, className, day, hour) {
  const res = await fetch(`${BASE}/swap/candidates`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ session_id: sessionId, class_name: className, day, hour }),
  })
  if (!res.ok) throw new Error('Could not fetch swap candidates')
  return res.json()
}

export async function performSwap(sessionId, a, b) {
  const res = await fetch(`${BASE}/swap`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({
      session_id:   sessionId,
      class_name_a: a.className, day_a: a.day, hour_a: a.hour,
      class_name_b: b.className, day_b: b.day, hour_b: b.hour,
    }),
  })
  if (!res.ok) throw new Error('Swap failed')
  return res.json()
}

export function exportTeacherSchedule(sessionId) {
  window.open(`${BASE}/export/teacher/${sessionId}`, '_blank')
}

export function exportClassSchedules(sessionId) {
  window.open(`${BASE}/export/classes/${sessionId}`, '_blank')
}

export async function restoreSession(classes, teachers, grids) {
  const res = await fetch(`${BASE}/session/restore`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ classes, teachers, grids }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Could not restore project')
  }
  return res.json()   // { session_id, classes, teachers, grids }
}

// ── shared constraint-merge helper ───────────────────────────────────────────
// Mirrors the merge SearchingPage performs before calling /solve/stream: bakes
// the customized class/subject constraints and teacher unavailability into
// plain `classes`/`teachers` arrays. Used both when sending a solve request
// and when saving a project file, so a saved/restored project reflects the
// constraints that actually produced the schedule — not just the raw
// customize-step values.
export function mergeConstraintsIntoPayload({
  classes,
  teachers,
  classConstraintsPayload,
  teacherConstraintsPayload,
}) {
  const mergedClasses = (classes ?? []).map((cls) => {
    const ccList = classConstraintsPayload?.classConstraints?.[cls.name] ?? []
    const scMap  = classConstraintsPayload?.subjectConstraints ?? {}

    const minCC = ccList.find(c => c.enabled && c.id === 'MinDailyClassCount')
    const maxCC = ccList.find(c => c.enabled && c.id === 'MaxDailyClassCount')
    const total = cls.subjects.reduce((s, x) => s + x.sessions_per_week, 0)

    return {
      ...cls,
      min_daily: minCC?.params?.min_classes ?? cls.min_daily ?? Math.floor(total / 5),
      max_daily: maxCC?.params?.max_classes ?? cls.max_daily ?? Math.floor(total / 5) + 1,
      subjects: cls.subjects.map((s) => {
        const key       = `${cls.name}::${s.name}`
        const scList    = scMap[key] ?? []
        const maxConsec = scList.find(c => c.enabled && c.id === 'MaxConsecutiveClassesConstraint')
        return {
          ...s,
          max_consecutive: maxConsec?.params?.max_classes ?? s.max_consecutive ?? null,
        }
      }),
    }
  })

  const mergedTeachers = (teachers ?? []).map((t) => {
    const tc = (teacherConstraintsPayload ?? []).find(x => x.name === t.name)
    return {
      ...t,
      unavailable_slots: tc?.unavailable_slots ?? t.unavailable_slots ?? [],
      max_gap:           tc?.max_gap ?? t.max_gap ?? 2,
    }
  })

  return { classes: mergedClasses, teachers: mergedTeachers }
}

// ── full-project save / load (separate from the teacher/class xlsx export) ──
// Captures everything needed to resume exactly where you left off: the wizard
// payloads (so Customize / constraints pages would show the same choices if
// ever revisited) plus the solved+edited schedule grid itself.

const PROJECT_FILE_VERSION = 1

export function saveProjectFile({
  classes,
  teachers,
  customizePayload,
  classConstraintsPayload,
  teacherConstraintsPayload,
  searchParams,
  grids,
  fileName,
}) {
  const project = {
    type:       'class-scheduler-project',
    version:    PROJECT_FILE_VERSION,
    saved_at:   new Date().toISOString(),
    classes,
    teachers,
    customizePayload,
    classConstraintsPayload,
    teacherConstraintsPayload,
    searchParams,
    grids,
  }
  const blob = new Blob([JSON.stringify(project, null, 2)], { type: 'application/json' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = fileName || `schedule_project_${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

export function loadProjectFile(file) {
  return new Promise((resolve, reject) => {
    if (!file) { reject(new Error('No file selected')); return }
    const reader = new FileReader()
    reader.onload = () => {
      try {
        const data = JSON.parse(reader.result)
        if (data?.type !== 'class-scheduler-project') {
          reject(new Error('This file is not a recognized schedule project file.'))
          return
        }
        resolve(data)
      } catch (e) {
        reject(new Error('Could not read project file — it may be corrupted.'))
      }
    }
    reader.onerror = () => reject(new Error('Could not read project file.'))
    reader.readAsText(file)
  })
}