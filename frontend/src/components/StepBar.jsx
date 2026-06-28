// components/StepBar.jsx
import { useT } from '../i18n'
import { useStore } from '../store'

const STEP_KEYS = [
  'step_start', 'step_customize', 'step_classes',
  'step_teachers', 'step_review', 'step_searching', 'step_result',
]

export default function StepBar() {
  const t    = useT()
  const step = useStore(s => s.step)

  return (
    <nav style={{
      display:        'flex',
      alignItems:     'center',
      gap:            '0',
      padding:        '0 32px',
      height:         '52px',
      borderBottom:   '1px solid var(--c-border)',
      background:     'var(--c-surface)',
      overflowX:      'auto',
    }}>
      {STEP_KEYS.map((key, i) => {
        const done    = i < step
        const current = i === step
        return (
          <div key={key} style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{
              display:    'flex',
              alignItems: 'center',
              gap:        '7px',
              padding:    '4px 10px',
              borderRadius: 'var(--r-sm)',
              background: current ? 'rgba(43,92,230,0.08)' : 'transparent',
              transition: 'background 0.2s',
            }}>
              {/* circle */}
              <div style={{
                width:      '20px',
                height:     '20px',
                borderRadius: '50%',
                display:    'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize:   '11px',
                fontWeight: '500',
                flexShrink: 0,
                background: done    ? 'var(--c-success)'
                          : current ? 'var(--c-accent)'
                          :           'var(--c-border)',
                color:      done || current ? '#fff' : 'var(--c-ink-3)',
                transition: 'background 0.25s',
              }}>
                {done ? '✓' : i + 1}
              </div>
              <span style={{
                fontSize:   '12px',
                fontWeight: current ? '500' : '400',
                color:      current ? 'var(--c-accent)'
                          : done    ? 'var(--c-ink-2)'
                          :           'var(--c-ink-3)',
                whiteSpace: 'nowrap',
              }}>
                {t(key)}
              </span>
            </div>

            {/* connector */}
            {i < STEP_KEYS.length - 1 && (
              <div style={{
                width:      '24px',
                height:     '1px',
                background: done ? 'var(--c-success)' : 'var(--c-border)',
                flexShrink: 0,
                transition: 'background 0.25s',
              }} />
            )}
          </div>
        )
      })}
    </nav>
  )
}
