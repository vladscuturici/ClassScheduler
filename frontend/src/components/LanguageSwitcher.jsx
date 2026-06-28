// components/LanguageSwitcher.jsx
import { useStore } from '../store'
import { useT } from '../i18n'

export default function LanguageSwitcher() {
  const { lang, setLang } = useStore()
  const t = useT()

  return (
    <div style={{
      display: 'flex',
      gap: '4px',
      background: 'rgba(0,0,0,0.06)',
      borderRadius: '100px',
      padding: '3px',
    }}>
      {['en', 'ro'].map((l) => (
        <button
          key={l}
          onClick={() => setLang(l)}
          style={{
            border:        'none',
            cursor:        'pointer',
            padding:       '5px 14px',
            borderRadius:  '100px',
            fontFamily:    'var(--f-body)',
            fontSize:      '13px',
            fontWeight:    lang === l ? '500' : '400',
            background:    lang === l ? 'var(--c-surface)' : 'transparent',
            color:         lang === l ? 'var(--c-ink)' : 'var(--c-ink-3)',
            boxShadow:     lang === l ? '0 1px 3px rgba(0,0,0,0.12)' : 'none',
            transition:    'all 0.18s ease',
          }}
        >
          {t(`lang_${l}`)}
        </button>
      ))}
    </div>
  )
}
