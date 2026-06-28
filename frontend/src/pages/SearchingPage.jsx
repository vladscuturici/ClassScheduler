// pages/SearchingPage.jsx
import { useState, useEffect, useRef } from 'react'
import { useStore } from '../store'
import { solveStream, mergeConstraintsIntoPayload } from '../api'

const DAYS  = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
const HOURS = 8

// ── helpers ───────────────────────────────────────────────────────────────────

function buildSolveRequest({
  parsedData,
  customizePayload,
  classConstraintsPayload,
  teacherConstraintsPayload,
  searchParams,
}) {
  const sessionId = parsedData?.session_id
  const classes   = customizePayload?.classes ?? parsedData?.classes ?? []
  const teachers  = customizePayload?.teachers ?? parsedData?.teachers ?? []

  const { classes: mergedClasses, teachers: mergedTeachers } = mergeConstraintsIntoPayload({
    classes,
    teachers,
    classConstraintsPayload,
    teacherConstraintsPayload,
  })

  return {
    session_id:              sessionId,
    classes:                 mergedClasses,
    teachers:                mergedTeachers,
    max_solutions:           searchParams?.max_solutions   ?? 1,
    use_balanced_difficulty: searchParams?.use_balanced_difficulty ?? false,
  }
}

// ── tiny components ───────────────────────────────────────────────────────────

function Spinner({ size = 20, color = 'var(--c-accent)' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round">
      <style>{`@keyframes _spin{to{transform:rotate(360deg)}}`}</style>
      <circle cx="12" cy="12" r="9" strokeOpacity="0.2" />
      <path d="M12 3a9 9 0 0 1 9 9" style={{ animation: '_spin 0.8s linear infinite', transformOrigin: '12px 12px' }} />
    </svg>
  )
}

function StatusDot({ status }) {
  const colors = {
    running: 'var(--c-accent)',
    done:    'var(--c-success)',
    error:   'var(--c-danger)',
    idle:    'var(--c-border-h)',
  }
  return (
    <span style={{
      display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
      background: colors[status] ?? colors.idle, flexShrink: 0,
      boxShadow: status === 'running' ? `0 0 0 3px rgba(43,92,230,0.15)` : 'none',
    }} />
  )
}

function StatCard({ label, value, sub, color = 'var(--c-ink)' }) {
  return (
    <div style={{
      background: 'var(--c-surface)', border: '1px solid var(--c-border)',
      borderRadius: 'var(--r-md)', padding: '12px 16px', flex: 1,
    }}>
      <div style={{ fontSize: 11, color: 'var(--c-ink-3)', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 500, color, lineHeight: 1.1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--c-ink-3)', marginTop: 3 }}>{sub}</div>}
    </div>
  )
}

// ── log line parser ───────────────────────────────────────────────────────────
// Tries to extract meaning from the scheduler's print output for visual hints

function classifyLog(msg) {
  if (!msg) return 'info'
  const m = msg.toLowerCase()
  if (m.includes('solution') && (m.includes('found') || m.includes('best'))) return 'success'
  if (m.includes('error') || m.includes('fail') || m.includes('no solution')) return 'error'
  if (m.includes('backtrack') || m.includes('conflict')) return 'warn'
  if (m.includes('class') || m.includes('placing') || m.includes('assign')) return 'progress'
  return 'info'
}

const LOG_COLORS = {
  success:  { bg: 'rgba(30,124,77,0.06)',  text: 'var(--c-success)',  border: 'rgba(30,124,77,0.15)'  },
  error:    { bg: 'rgba(192,57,43,0.06)',  text: 'var(--c-danger)',   border: 'rgba(192,57,43,0.15)'  },
  warn:     { bg: 'rgba(180,130,0,0.06)',  text: '#7a5800',           border: 'rgba(180,130,0,0.15)'  },
  progress: { bg: 'rgba(43,92,230,0.04)',  text: 'var(--c-accent)',   border: 'rgba(43,92,230,0.12)'  },
  info:     { bg: 'transparent',           text: 'var(--c-ink-2)',    border: 'transparent'           },
}

// ── main page ─────────────────────────────────────────────────────────────────

export default function SearchingPage({
  customizePayload,
  classConstraintsPayload,
  teacherConstraintsPayload,
  searchParams,
  onDone,
  onBack,
}) {
  const { parsedData } = useStore()

  const [status,       setStatus]       = useState('idle')   // idle | running | done | error
  const [logs,         setLogs]         = useState([])
  const [solutions,    setSolutions]    = useState(0)
  const [elapsed,      setElapsed]      = useState(0)
  const [resultMsg,    setResultMsg]    = useState('')

  const ctrlRef      = useRef(null)
  const logEndRef    = useRef(null)
  const startTimeRef = useRef(null)
  const timerRef     = useRef(null)

  // auto-scroll log
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  // elapsed timer
  useEffect(() => {
    if (status === 'running') {
      startTimeRef.current = Date.now()
      timerRef.current = setInterval(() => {
        setElapsed(((Date.now() - startTimeRef.current) / 1000).toFixed(1))
      }, 100)
    } else {
      clearInterval(timerRef.current)
    }
    return () => clearInterval(timerRef.current)
  }, [status])

  function addLog(msg, type) {
    setLogs(prev => [...prev, { msg, type: type ?? classifyLog(msg), ts: Date.now() }])
  }

  function startSolve() {
    if (status === 'running') return

    setStatus('running')
    setLogs([])
    setSolutions(0)
    setElapsed(0)
    setResultMsg('')

    const req = buildSolveRequest({
      parsedData,
      customizePayload,
      classConstraintsPayload,
      teacherConstraintsPayload,
      searchParams,
    })

    addLog(`Starting solver · ${req.classes.length} classes · ${req.teachers.length} teachers · max ${req.max_solutions} solution(s)`, 'info')

    ctrlRef.current = solveStream(req, (event) => {
      if (event.type === 'log') {
        addLog(event.message)
      } else if (event.type === 'progress') {
        if (event.solutions !== undefined) setSolutions(event.solutions)
      } else if (event.type === 'done') {
        clearInterval(timerRef.current)
        setElapsed(((Date.now() - startTimeRef.current) / 1000).toFixed(1))
        if (event.success) {
          setStatus('done')
          setResultMsg('Schedule found successfully.')
          addLog('✓ Schedule found!', 'success')
        } else {
          setStatus('error')
          setResultMsg('No valid schedule could be found with these constraints.')
          addLog('✗ No solution found.', 'error')
        }
      } else if (event.type === 'error') {
        clearInterval(timerRef.current)
        setStatus('error')
        setResultMsg(event.message ?? 'An unexpected error occurred.')
        addLog(`Error: ${event.message}`, 'error')
      }
    })
  }

  function handleAbort() {
    ctrlRef.current?.abort()
    clearInterval(timerRef.current)
    setStatus('error')
    setResultMsg('Search aborted by user.')
    addLog('Search aborted.', 'warn')
  }

  const isRunning = status === 'running'
  const isDone    = status === 'done'
  const isError   = status === 'error'

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>

      {/* page header */}
      <div style={{
        padding: '24px 32px 0',
        borderBottom: '1px solid var(--c-border)',
        background: 'var(--c-surface)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          {isRunning && <Spinner size={18} />}
          <h1 style={{
            fontFamily: 'var(--f-display)', fontSize: 26,
            letterSpacing: '-0.5px', color: 'var(--c-ink)', margin: 0,
          }}>
            {isRunning ? 'Searching…' : isDone ? 'Schedule found' : isError ? 'Search failed' : 'Ready to search'}
          </h1>
        </div>
        <p style={{ fontSize: 14, color: 'var(--c-ink-2)', marginBottom: 20 }}>
          {isRunning
            ? 'The solver is exploring possible schedules. This may take a moment.'
            : isDone
            ? 'A valid schedule was found. You can view it on the next step.'
            : isError
            ? resultMsg
            : 'Press Start to begin searching for a valid schedule.'}
        </p>
      </div>

      {/* body */}
      <div style={{ flex: 1, padding: '24px 32px', maxWidth: 860, width: '100%', margin: '0 auto' }}>

        {/* stat cards */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 24 }}>
          <StatCard
            label="Status"
            value={
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <StatusDot status={status} />
                {status === 'idle' ? 'Idle' : status === 'running' ? 'Running' : isDone ? 'Done' : 'Failed'}
              </span>
            }
          />
          <StatCard
            label="Elapsed"
            value={`${elapsed}s`}
            sub={isRunning ? 'still running…' : status !== 'idle' ? 'total time' : '—'}
            color={isRunning ? 'var(--c-accent)' : 'var(--c-ink)'}
          />
          <StatCard
            label="Solutions"
            value={solutions}
            sub={`of ${searchParams?.max_solutions ?? 1} requested`}
            color={solutions > 0 ? 'var(--c-success)' : 'var(--c-ink)'}
          />
          <StatCard
            label="Log lines"
            value={logs.length}
          />
        </div>

        {/* result banner */}
        {(isDone || isError) && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '12px 16px', borderRadius: 'var(--r-md)', marginBottom: 20,
            background: isDone ? 'rgba(30,124,77,0.06)' : 'rgba(192,57,43,0.06)',
            border: `1px solid ${isDone ? 'rgba(30,124,77,0.2)' : 'rgba(192,57,43,0.2)'}`,
            fontSize: 13,
            color: isDone ? 'var(--c-success)' : 'var(--c-danger)',
          }}>
            <span style={{ fontSize: 16 }}>{isDone ? '✓' : '✗'}</span>
            <span>{resultMsg}</span>
          </div>
        )}

        {/* log window */}
        <div style={{
          background: 'var(--c-surface)', border: '1px solid var(--c-border)',
          borderRadius: 'var(--r-lg)', overflow: 'hidden', marginBottom: 24,
        }}>
          {/* log toolbar */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '10px 16px', borderBottom: '1px solid var(--c-border)',
            background: 'var(--c-bg)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {isRunning && <Spinner size={14} />}
              <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--c-ink-2)' }}>
                Solver log
              </span>
              {logs.length > 0 && (
                <span style={{
                  fontSize: 11, padding: '1px 6px', borderRadius: 100,
                  background: 'var(--c-border)', color: 'var(--c-ink-3)',
                }}>
                  {logs.length}
                </span>
              )}
            </div>
            {logs.length > 0 && (
              <button
                onClick={() => setLogs([])}
                style={{
                  fontSize: 11, padding: '2px 8px',
                  border: '1px solid var(--c-border-h)', borderRadius: 'var(--r-sm)',
                  background: 'transparent', color: 'var(--c-ink-3)',
                  cursor: 'pointer', fontFamily: 'var(--f-body)',
                }}
              >
                Clear
              </button>
            )}
          </div>

          {/* log entries */}
          <div style={{
            height: 320, overflowY: 'auto', padding: '8px 0',
            fontFamily: 'monospace',
          }}>
            {logs.length === 0 ? (
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                height: '100%', fontSize: 13, color: 'var(--c-ink-3)', fontFamily: 'var(--f-body)',
              }}>
                {status === 'idle' ? 'Logs will appear here once you start.' : 'Waiting for output…'}
              </div>
            ) : (
              logs.map((entry, i) => {
                const c = LOG_COLORS[entry.type] ?? LOG_COLORS.info
                return (
                  <div key={i} style={{
                    display: 'flex', alignItems: 'baseline', gap: 10,
                    padding: '3px 14px',
                    background: c.bg,
                    borderLeft: `2px solid ${c.border}`,
                    marginBottom: 1,
                  }}>
                    <span style={{ fontSize: 10, color: 'var(--c-ink-3)', flexShrink: 0, minWidth: 40, fontFamily: 'monospace' }}>
                      {String(i + 1).padStart(3, '0')}
                    </span>
                    <span style={{ fontSize: 12, color: c.text, lineHeight: 1.6, wordBreak: 'break-word' }}>
                      {entry.msg}
                    </span>
                  </div>
                )
              })
            )}
            <div ref={logEndRef} />
          </div>
        </div>

        {/* action buttons */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          borderTop: '1px solid var(--c-border)', paddingTop: 20,
        }}>
          <button
            onClick={onBack}
            disabled={isRunning}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '11px 24px', borderRadius: 100,
              border: '1px solid var(--c-border-h)',
              background: 'var(--c-surface)', color: isRunning ? 'var(--c-ink-3)' : 'var(--c-ink-2)',
              fontFamily: 'var(--f-body)', fontSize: 14, fontWeight: 500,
              cursor: isRunning ? 'not-allowed' : 'pointer',
              opacity: isRunning ? 0.5 : 1,
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
            </svg>
            Back
          </button>

          <div style={{ display: 'flex', gap: 10 }}>
            {/* abort */}
            {isRunning && (
              <button
                onClick={handleAbort}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '11px 22px', borderRadius: 100,
                  border: '1px solid rgba(192,57,43,0.3)',
                  background: 'rgba(192,57,43,0.06)', color: 'var(--c-danger)',
                  fontFamily: 'var(--f-body)', fontSize: 14, fontWeight: 500, cursor: 'pointer',
                }}
              >
                ■ Stop
              </button>
            )}

            {/* start / retry */}
            {!isDone && (
              <button
                onClick={startSolve}
                disabled={isRunning}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '11px 28px', borderRadius: 100, border: 'none',
                  cursor: isRunning ? 'not-allowed' : 'pointer',
                  fontFamily: 'var(--f-body)', fontSize: 14, fontWeight: 500,
                  background: isRunning ? 'var(--c-border)' : 'var(--c-accent)',
                  color: isRunning ? 'var(--c-ink-3)' : '#fff',
                  boxShadow: isRunning ? 'none' : '0 4px 18px rgba(43,92,230,0.28)',
                  transition: 'background 0.2s',
                }}
                onMouseEnter={(e) => { if (!isRunning) e.currentTarget.style.background = 'var(--c-accent-h)' }}
                onMouseLeave={(e) => { if (!isRunning) e.currentTarget.style.background = 'var(--c-accent)' }}
              >
                {isRunning ? (
                  <><Spinner size={16} color="#fff" /> Searching…</>
                ) : isError ? (
                  <>↺ Retry</>
                ) : (
                  <>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polygon points="5 3 19 12 5 21 5 3" />
                    </svg>
                    Start search
                  </>
                )}
              </button>
            )}

            {/* view schedule */}
            {isDone && (
              <button
                onClick={onDone}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '11px 28px', borderRadius: 100, border: 'none',
                  cursor: 'pointer', fontFamily: 'var(--f-body)', fontSize: 14, fontWeight: 500,
                  background: 'var(--c-success)', color: '#fff',
                  boxShadow: '0 4px 18px rgba(30,124,77,0.28)', transition: 'background 0.2s',
                }}
              >
                View schedule
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
                </svg>
              </button>
            )}
          </div>
        </div>

      </div>
    </div>
  )
}