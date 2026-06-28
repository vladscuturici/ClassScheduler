// pages/StartPage.jsx
import { useState, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useStore } from '../store'
import { useT } from '../i18n'
import { downloadTemplate, uploadExcel, restoreSession, loadProjectFile } from '../api'
import LanguageSwitcher from '../components/LanguageSwitcher'

// ── tiny icon components (inline SVG, no external dep) ────────────────────────
function IconDownload() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <polyline points="7 10 12 15 17 10"/>
      <line x1="12" y1="15" x2="12" y2="3"/>
    </svg>
  )
}

function IconUpload() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <polyline points="17 8 12 3 7 8"/>
      <line x1="12" y1="3" x2="12" y2="15"/>
    </svg>
  )
}

function IconFile() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
    </svg>
  )
}

function IconCheck() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12"/>
    </svg>
  )
}

function IconArrow() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="5" y1="12" x2="19" y2="12"/>
      <polyline points="12 5 19 12 12 19"/>
    </svg>
  )
}

function IconFolder() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
    </svg>
  )
}

// ── stagger animation presets ─────────────────────────────────────────────────
const fadeUp = (delay = 0) => ({
  initial:   { opacity: 0, y: 24 },
  animate:   { opacity: 1, y: 0 },
  transition: { duration: 0.55, ease: [0.16, 1, 0.3, 1], delay },
})

// ─────────────────────────────────────────────────────────────────────────────
export default function StartPage({ onContinue, onImportProject }) {
  const t           = useT()
  const setSession  = useStore(s => s.setSession)

  const [uploadState, setUploadState] = useState('idle') // idle | uploading | done | error
  const [fileName,    setFileName]    = useState(null)
  const [errorMsg,    setErrorMsg]    = useState('')
  const [isDragging,  setIsDragging]  = useState(false)
  const [downloading, setDownloading] = useState(false)

  const [projectState,   setProjectState]   = useState('idle') // idle | loading | error
  const [projectFileName, setProjectFileName] = useState(null)
  const [projectError,    setProjectError]    = useState('')

  const fileInputRef    = useRef(null)
  const projectInputRef = useRef(null)

  // ── import a saved project (.json) and jump straight to the schedule view ──
  const handleProjectFile = useCallback(async (file) => {
    if (!file) return
    if (!file.name.match(/\.json$/i)) {
      setProjectState('error')
      setProjectError('Please choose a .json project file.')
      return
    }
    setProjectFileName(file.name)
    setProjectState('loading')
    setProjectError('')
    try {
      const project = await loadProjectFile(file)
      const restored = await restoreSession(project.classes, project.teachers, project.grids)
      setSession(restored.session_id, {
        session_id: restored.session_id,
        classes:    restored.classes,
        teachers:   restored.teachers,
      }, file.name)
      onImportProject?.({
        customizePayload:          project.customizePayload,
        classConstraintsPayload:   project.classConstraintsPayload,
        teacherConstraintsPayload: project.teacherConstraintsPayload,
        searchParams:              project.searchParams,
      })
    } catch (e) {
      setProjectState('error')
      setProjectError(e.message || 'Could not import project.')
    }
  }, [setSession, onImportProject])

  const onProjectFileInput = (e) => handleProjectFile(e.target.files[0])
  const onProjectDrop = (e) => {
    e.preventDefault()
    handleProjectFile(e.dataTransfer.files[0])
  }

  // ── file handling ──────────────────────────────────────────────────────────
  const handleFile = useCallback(async (file) => {
    if (!file) return
    if (!file.name.match(/\.(xlsx|xls)$/i)) {
      setUploadState('error')
      setErrorMsg(t('upload_error'))
      return
    }
    setFileName(file.name)
    setUploadState('uploading')
    setErrorMsg('')
    try {
      const data = await uploadExcel(file)
      setSession(data.session_id, data, file.name)
      setUploadState('done')
    } catch (e) {
      setUploadState('error')
      setErrorMsg(e.message || t('upload_error'))
    }
  }, [t, setSession])

  const onFileInput = (e) => handleFile(e.target.files[0])

  const onDrop = (e) => {
    e.preventDefault()
    setIsDragging(false)
    handleFile(e.dataTransfer.files[0])
  }

  const onDragOver = (e) => { e.preventDefault(); setIsDragging(true) }
  const onDragLeave = ()  => setIsDragging(false)

  // ── download template ──────────────────────────────────────────────────────
  const handleDownload = async () => {
    setDownloading(true)
    try { await downloadTemplate() } catch {}
    setTimeout(() => setDownloading(false), 1200)
  }

  // ── continue ───────────────────────────────────────────────────────────────
  // App.jsx owns the step; we just call onContinue when ready
  const handleContinue = () => {
    if (uploadState !== 'done') return
    onContinue?.()
  }

  const canContinue = uploadState === 'done'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>

      {/* ── top bar ──────────────────────────────────────────────────────── */}
      <header style={{
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'space-between',
        padding:        '0 32px',
        height:         '56px',
        background:     'var(--c-surface)',
        borderBottom:   '1px solid var(--c-border)',
      }}>
        <span style={{
          fontFamily: 'var(--f-display)',
          fontSize:   '18px',
          color:      'var(--c-ink)',
          letterSpacing: '-0.3px',
        }}>
          ClassScheduler
        </span>
        <LanguageSwitcher />
      </header>

      {/* ── main content ─────────────────────────────────────────────────── */}
      <main style={{
        flex:           1,
        display:        'flex',
        flexDirection:  'column',
        alignItems:     'center',
        justifyContent: 'center',
        padding:        '48px 24px 80px',
      }}>

        {/* hero text */}
        <motion.div {...fadeUp(0)} style={{ textAlign: 'center', marginBottom: '56px' }}>
          <h1 style={{
            fontFamily:    'var(--f-display)',
            fontSize:      'clamp(36px, 5vw, 58px)',
            lineHeight:    '1.1',
            letterSpacing: '-1.5px',
            color:         'var(--c-ink)',
            marginBottom:  '14px',
          }}>
            {t('welcome')}
          </h1>
          <p style={{
            fontSize:  '17px',
            color:     'var(--c-ink-2)',
            maxWidth:  '440px',
            margin:    '0 auto',
          }}>
            {t('welcome_sub')}
          </p>
        </motion.div>

        {/* action cards */}
        <div style={{
          display:       'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap:           '16px',
          width:         '100%',
          maxWidth:      '960px',
          marginBottom:  '40px',
        }}>

          {/* card 1 — download template */}
          <motion.div {...fadeUp(0.08)}>
            <ActionCard
              icon={<IconDownload />}
              label={t('btn_download')}
              sub={t('btn_download_sub')}
              loading={downloading}
              variant="outline"
              onClick={handleDownload}
            />
          </motion.div>

          {/* card 2 — import file (drop zone) */}
          <motion.div {...fadeUp(0.16)}>
            <div
              onClick={() => fileInputRef.current?.click()}
              onDrop={onDrop}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              style={{
                cursor:       'pointer',
                borderRadius: 'var(--r-lg)',
                border:       isDragging
                                ? '2px dashed var(--c-accent)'
                                : uploadState === 'done'
                                  ? '2px solid var(--c-success)'
                                  : uploadState === 'error'
                                    ? '2px solid var(--c-danger)'
                                    : '2px dashed var(--c-border-h)',
                background:   isDragging
                                ? 'rgba(43,92,230,0.04)'
                                : uploadState === 'done'
                                  ? 'rgba(30,124,77,0.04)'
                                  : 'var(--c-surface)',
                padding:      '28px 24px',
                transition:   'all 0.18s ease',
                userSelect:   'none',
              }}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.xls"
                style={{ display: 'none' }}
                onChange={onFileInput}
              />

              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '14px' }}>
                {/* icon area */}
                <div style={{
                  width:          '44px',
                  height:         '44px',
                  borderRadius:   'var(--r-md)',
                  background:     uploadState === 'done'
                                    ? 'rgba(30,124,77,0.12)'
                                    : 'rgba(43,92,230,0.08)',
                  display:        'flex',
                  alignItems:     'center',
                  justifyContent: 'center',
                  color:          uploadState === 'done' ? 'var(--c-success)' : 'var(--c-accent)',
                  flexShrink:     0,
                }}>
                  {uploadState === 'done' ? <IconCheck /> : <IconUpload />}
                </div>

                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: '500', fontSize: '15px', marginBottom: '3px' }}>
                    {isDragging
                      ? t('drop_active')
                      : uploadState === 'uploading'
                        ? t('uploading')
                        : t('btn_import')}
                  </div>

                  <div style={{ fontSize: '13px', color: 'var(--c-ink-3)', marginBottom: '10px' }}>
                    {t('btn_import_sub')}
                  </div>

                  {/* status pill */}
                  <AnimatePresence mode="wait">
                    {uploadState === 'idle' && (
                      <motion.div key="hint" {...fadeUp(0)} style={pillStyle('neutral')}>
                        {t('upload_hint')}
                      </motion.div>
                    )}
                    {uploadState === 'uploading' && (
                      <motion.div key="uploading" {...fadeUp(0)} style={pillStyle('neutral')}>
                        <Spinner /> {t('uploading')}
                      </motion.div>
                    )}
                    {uploadState === 'done' && (
                      <motion.div key="done" {...fadeUp(0)} style={pillStyle('success')}>
                        <IconFile /> {t('file_ready')} {fileName}
                      </motion.div>
                    )}
                    {uploadState === 'error' && (
                      <motion.div key="error" {...fadeUp(0)} style={pillStyle('error')}>
                        {errorMsg}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </div>
            </div>
          </motion.div>

          {/* card 3 — import a previously saved project (.json) */}
          <motion.div {...fadeUp(0.24)}>
            <div
              onClick={() => projectInputRef.current?.click()}
              onDrop={onProjectDrop}
              onDragOver={(e) => e.preventDefault()}
              style={{
                cursor:       'pointer',
                borderRadius: 'var(--r-lg)',
                border:       projectState === 'idle' && projectFileName
                                ? '2px solid var(--c-success)'
                                : projectState === 'error'
                                  ? '2px solid var(--c-danger)'
                                  : '2px dashed var(--c-border-h)',
                background:   'var(--c-surface)',
                padding:      '28px 24px',
                transition:   'all 0.18s ease',
                userSelect:   'none',
              }}
            >
              <input
                ref={projectInputRef}
                type="file"
                accept=".json"
                style={{ display: 'none' }}
                onChange={onProjectFileInput}
              />

              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '14px' }}>
                <div style={{
                  width:          '44px',
                  height:         '44px',
                  borderRadius:   'var(--r-md)',
                  background:     'rgba(43,92,230,0.08)',
                  display:        'flex',
                  alignItems:     'center',
                  justifyContent: 'center',
                  color:          'var(--c-accent)',
                  flexShrink:     0,
                }}>
                  {projectState === 'loading' ? <Spinner /> : <IconFolder />}
                </div>

                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: '500', fontSize: '15px', marginBottom: '3px' }}>
                    {projectState === 'loading' ? 'Importing project…' : 'Import a saved project'}
                  </div>

                  <div style={{ fontSize: '13px', color: 'var(--c-ink-3)', marginBottom: '10px' }}>
                    Pick up exactly where you left off, including any edits you made
                  </div>

                  <AnimatePresence mode="wait">
                    {projectState === 'idle' && !projectFileName && (
                      <motion.div key="hint" {...fadeUp(0)} style={pillStyle('neutral')}>
                        Drop a .json project file, or click to browse
                      </motion.div>
                    )}
                    {projectState === 'loading' && (
                      <motion.div key="loading" {...fadeUp(0)} style={pillStyle('neutral')}>
                        <Spinner /> {projectFileName}
                      </motion.div>
                    )}
                    {projectState === 'error' && (
                      <motion.div key="error" {...fadeUp(0)} style={pillStyle('error')}>
                        {projectError}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </div>
            </div>
          </motion.div>
        </div>

        {/* continue button */}
        <motion.div {...fadeUp(0.28)}>
          <button
            onClick={handleContinue}
            disabled={!canContinue}
            style={{
              display:        'flex',
              alignItems:     'center',
              gap:            '10px',
              padding:        '14px 36px',
              borderRadius:   '100px',
              border:         'none',
              cursor:         canContinue ? 'pointer' : 'not-allowed',
              fontFamily:     'var(--f-body)',
              fontSize:       '16px',
              fontWeight:     '500',
              background:     canContinue ? 'var(--c-accent)' : 'var(--c-border)',
              color:          canContinue ? '#fff' : 'var(--c-ink-3)',
              transition:     'all 0.2s ease',
              boxShadow:      canContinue ? '0 4px 18px rgba(43,92,230,0.28)' : 'none',
            }}
            onMouseEnter={e => { if (canContinue) e.currentTarget.style.background = 'var(--c-accent-h)' }}
            onMouseLeave={e => { if (canContinue) e.currentTarget.style.background = 'var(--c-accent)' }}
          >
            {t('btn_continue')}
            <IconArrow />
          </button>

          {!canContinue && (
            <p style={{
              textAlign: 'center',
              marginTop: '10px',
              fontSize:  '13px',
              color:     'var(--c-ink-3)',
            }}>
              {t('no_file_yet')}
            </p>
          )}
        </motion.div>

      </main>
    </div>
  )
}

// ── sub-components ─────────────────────────────────────────────────────────────

function ActionCard({ icon, label, sub, onClick, loading, variant = 'filled' }) {
  const [hovered, setHovered] = useState(false)

  return (
    <button
      onClick={onClick}
      disabled={loading}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        width:        '100%',
        textAlign:    'left',
        cursor:       loading ? 'wait' : 'pointer',
        borderRadius: 'var(--r-lg)',
        border:       '1px solid var(--c-border)',
        background:   hovered ? 'rgba(43,92,230,0.03)' : 'var(--c-surface)',
        padding:      '28px 24px',
        transition:   'all 0.18s ease',
        fontFamily:   'var(--f-body)',
        display:      'block',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '14px' }}>
        <div style={{
          width:          '44px',
          height:         '44px',
          borderRadius:   'var(--r-md)',
          background:     'rgba(43,92,230,0.08)',
          display:        'flex',
          alignItems:     'center',
          justifyContent: 'center',
          color:          'var(--c-accent)',
          flexShrink:     0,
          transition:     'background 0.18s',
          ...(hovered ? { background: 'rgba(43,92,230,0.14)' } : {}),
        }}>
          {loading ? <Spinner /> : icon}
        </div>
        <div>
          <div style={{ fontWeight: '500', fontSize: '15px', marginBottom: '3px', color: 'var(--c-ink)' }}>
            {label}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--c-ink-3)' }}>
            {sub}
          </div>
        </div>
      </div>
    </button>
  )
}

function Spinner() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      <circle cx="12" cy="12" r="9" strokeOpacity="0.25"/>
      <path d="M12 3a9 9 0 0 1 9 9" style={{ animation: 'spin 0.75s linear infinite', transformOrigin: '12px 12px' }}/>
    </svg>
  )
}

const pillStyle = (type) => ({
  display:      'inline-flex',
  alignItems:   'center',
  gap:          '6px',
  fontSize:     '12px',
  padding:      '4px 10px',
  borderRadius: '100px',
  maxWidth:     '100%',
  overflow:     'hidden',
  textOverflow: 'ellipsis',
  whiteSpace:   'nowrap',
  background:   type === 'success' ? 'rgba(30,124,77,0.1)'
              : type === 'error'   ? 'rgba(192,57,43,0.1)'
              :                      'rgba(0,0,0,0.05)',
  color:        type === 'success' ? 'var(--c-success)'
              : type === 'error'   ? 'var(--c-danger)'
              :                      'var(--c-ink-3)',
})