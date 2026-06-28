// App.jsx — wizard router
import { useState } from 'react'
import { useStore } from './store'
import StartPage from './pages/StartPage'
import CustomizePage from './pages/CustomizePage'
import ClassConstraintsPage from './pages/ClassConstraintsPage'
import TeacherConstraintsPage from './pages/TeacherConstraintsPage'
import FinalCheckPage from './pages/FinalCheckPage'
import SearchingPage from './pages/SearchingPage'
import StepBar from './components/StepBar'
import ScheduleViewPage from './pages/ScheduleViewPage'

const PlaceholderPage = ({ name, onBack }) => (
  <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, flexDirection: 'column', gap: 24 }}>
      <div style={{ fontFamily: 'var(--f-display)', fontSize: '32px', color: 'var(--c-ink-3)' }}>
        {name} — coming soon
      </div>
      {onBack && (
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
      )}
    </div>
  </div>
)

const TOTAL_STEPS = 7

export default function App() {
  const { step, setStep, parsedData } = useStore()

  const [customizePayload,          setCustomizePayload]          = useState(null)
  const [classConstraintsPayload,   setClassConstraintsPayload]   = useState(null)
  const [teacherConstraintsPayload, setTeacherConstraintsPayload] = useState(null)
  const [searchParams,              setSearchParams]              = useState(null)

  const goNext = () => setStep(Math.min(step + 1, TOTAL_STEPS - 1))
  const goBack = () => setStep(Math.max(step - 1, 0))

  const renderPage = () => {
    switch (step) {
      case 0:
        return (
          <StartPage
            onContinue={goNext}
            onImportProject={({ customizePayload: cp, classConstraintsPayload: ccp, teacherConstraintsPayload: tcp, searchParams: sp }) => {
              setCustomizePayload(cp ?? null)
              setClassConstraintsPayload(ccp ?? null)
              setTeacherConstraintsPayload(tcp ?? null)
              setSearchParams(sp ?? null)
              setStep(6)
            }}
          />
        )

      case 1:
        return (
          <CustomizePage
            classes={parsedData?.classes}
            teachers={parsedData?.teachers}
            onContinue={(payload) => {
              setCustomizePayload(payload)
              goNext()
            }}
            onBack={goBack}
          />
        )

      case 2:
        return (
          <ClassConstraintsPage
            classes={customizePayload?.classes ?? parsedData?.classes}
            onContinue={(payload) => {
              setClassConstraintsPayload(payload)
              goNext()
            }}
            onBack={goBack}
          />
        )

      case 3:
        return (
          <TeacherConstraintsPage
            teachers={customizePayload?.teachers ?? parsedData?.teachers}
            onContinue={(payload) => {
              setTeacherConstraintsPayload(payload)
              goNext()
            }}
            onBack={goBack}
          />
        )

      case 4:
        return (
          <FinalCheckPage
            customizePayload={customizePayload}
            classConstraintsPayload={classConstraintsPayload}
            teacherConstraintsPayload={teacherConstraintsPayload}
            onGenerate={(params) => {
              setSearchParams(params)
              goNext()
            }}
            onBack={goBack}
          />
        )

      case 5:
        return (
          <SearchingPage
            customizePayload={customizePayload}
            classConstraintsPayload={classConstraintsPayload}
            teacherConstraintsPayload={teacherConstraintsPayload}
            searchParams={searchParams}
            onDone={goNext}
            onBack={goBack}
          />
        )

      case 6:
        return (
          <ScheduleViewPage
            onBack={goBack}
            sessionId={parsedData?.session_id}
            customizePayload={customizePayload}
            classConstraintsPayload={classConstraintsPayload}
            teacherConstraintsPayload={teacherConstraintsPayload}
            searchParams={searchParams}
          />
        )

      default:
        return <PlaceholderPage name="Not found" onBack={goBack} />
    }
  }

  return (
    <>
      <StepBar />
      {renderPage()}
    </>
  )
}