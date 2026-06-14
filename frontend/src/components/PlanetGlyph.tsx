/**
 * Stilisierte Planeten-Darstellung als SVG (offline, lizenzfrei). Pro Planet
 * charakteristische Farben/Merkmale: Jupiter mit Bändern + Rotem Fleck,
 * Saturn mit Ring, Mars rötlich usw. Wird in der Objektliste statt eines
 * DSS-Previews für Planeten gezeigt.
 */
type Spec = { base: string; light: string; dark: string; rings?: boolean; bands?: boolean; spot?: boolean }

const PLANETS: Record<string, Spec> = {
  Merkur: { base: '#9a8f86', light: '#cfc6bd', dark: '#5c534c' },
  Venus: { base: '#d8b977', light: '#f3e3b0', dark: '#a07f3e' },
  Mars: { base: '#c1502e', light: '#e88a5a', dark: '#7d2d16', spot: true },
  Jupiter: { base: '#c9a06a', light: '#e7cfa3', dark: '#9b6b3e', bands: true, spot: true },
  Saturn: { base: '#d8c08a', light: '#f0deb0', dark: '#a8884f', rings: true, bands: true },
  Uranus: { base: '#9fd6da', light: '#cdeef0', dark: '#5fa3a8' },
  Neptun: { base: '#3b6fd4', light: '#7ea2ee', dark: '#22408a' },
}

export default function PlanetGlyph({ name }: { name: string }) {
  const p = PLANETS[name] || PLANETS.Mars
  const id = name.toLowerCase()
  const cx = 80
  const cy = 50
  const r = 30

  return (
    <svg viewBox="0 0 160 100" className="h-full w-full" preserveAspectRatio="xMidYMid meet">
      <defs>
        <radialGradient id={`g-${id}`} cx="38%" cy="34%" r="75%">
          <stop offset="0%" stopColor={p.light} />
          <stop offset="55%" stopColor={p.base} />
          <stop offset="100%" stopColor={p.dark} />
        </radialGradient>
        <clipPath id={`c-${id}`}>
          <circle cx={cx} cy={cy} r={r} />
        </clipPath>
        <linearGradient id={`sky-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#0b1024" />
          <stop offset="100%" stopColor="#10081c" />
        </linearGradient>
      </defs>

      <rect width="160" height="100" fill={`url(#sky-${id})`} />
      {/* ein paar Sterne */}
      {[[20, 18], [140, 26], [30, 80], [128, 78], [12, 52], [150, 60]].map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={i % 2 ? 0.8 : 1.2} fill="#fff" opacity="0.7" />
      ))}

      {/* Ring hinter dem Planeten */}
      {p.rings && (
        <ellipse cx={cx} cy={cy} rx={r * 1.7} ry={r * 0.5} fill="none" stroke={p.light} strokeOpacity="0.55" strokeWidth="5" transform={`rotate(-18 ${cx} ${cy})`} />
      )}

      <circle cx={cx} cy={cy} r={r} fill={`url(#g-${id})`} />

      <g clipPath={`url(#c-${id})`}>
        {p.bands && (
          <g opacity="0.35">
            <rect x={cx - r} y={cy - 18} width={2 * r} height="6" fill={p.dark} />
            <rect x={cx - r} y={cy - 6} width={2 * r} height="5" fill={p.light} />
            <rect x={cx - r} y={cy + 4} width={2 * r} height="7" fill={p.dark} />
            <rect x={cx - r} y={cy + 14} width={2 * r} height="5" fill={p.light} />
          </g>
        )}
        {p.spot && <ellipse cx={cx + 8} cy={cy + 7} rx="6" ry="4" fill="#b5462f" opacity="0.7" />}
        {/* Terminator/Schattenseite */}
        <ellipse cx={cx + r * 0.7} cy={cy} rx={r} ry={r} fill="#000" opacity="0.28" />
      </g>

      {/* Ring vor dem Planeten (vordere Hälfte) */}
      {p.rings && (
        <path
          d={`M ${cx - r * 1.7} ${cy} A ${r * 1.7} ${r * 0.5} 0 0 0 ${cx + r * 1.7} ${cy}`}
          fill="none" stroke={p.light} strokeOpacity="0.8" strokeWidth="5"
          transform={`rotate(-18 ${cx} ${cy})`}
        />
      )}
    </svg>
  )
}
