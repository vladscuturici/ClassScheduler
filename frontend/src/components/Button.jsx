// Button.jsx — reusable button component
export default function Button({ children, onClick, disabled, variant = 'primary', style = {} }) {
  const base = {
    display: 'inline-flex', alignItems: 'center', gap: '8px',
    padding: '11px 24px', borderRadius: '100px', border: 'none',
    fontFamily: 'var(--f-body)', fontSize: '15px', fontWeight: '500',
    cursor: disabled ? 'not-allowed' : 'pointer', transition: 'all 0.18s ease',
    ...style,
  }
  const variants = {
    primary:  { background: 'var(--c-accent)',  color: '#fff' },
    outline:  { background: 'transparent', color: 'var(--c-accent)', border: '1px solid var(--c-accent)' },
    ghost:    { background: 'transparent', color: 'var(--c-ink-2)' },
  }
  return (
    <button onClick={onClick} disabled={disabled} style={{ ...base, ...variants[variant] }}>
      {children}
    </button>
  )
}
