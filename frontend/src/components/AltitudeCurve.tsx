import { useState } from 'react'

/**
 * Mini-Höhenkurve über das Nachtfenster. X = Zeit (Raster), Y = Höhe 0–90°.
 * Zeigt die Bahn des Objekts: steigt es, kulminiert es, geht es früh unter?
 * Eine gestrichelte Linie markiert die Mindesthöhe. Hover blendet eine
 * Hilfslinie + Tooltip mit Uhrzeit und Höhe an der Position ein.
 */
export default function AltitudeCurve({
  track,
  labels,
  minAltitude = 30,
  windowStart,
  windowEnd,
}: {
  track: number[]
  labels: string[]
  minAltitude?: number
  windowStart?: string | null
  windowEnd?: string | null
}) {
  const [hover, setHover] = useState<number | null>(null)
  const W = 280
  const H = 64
  const pad = { l: 2, r: 2, t: 4, b: 12 }
  if (!track || track.length < 2) return null

  const n = track.length
  const x = (i: number) => pad.l + (i / (n - 1)) * (W - pad.l - pad.r)
  const y = (alt: number) => {
    const a = Math.max(0, Math.min(90, alt))
    return pad.t + (1 - a / 90) * (H - pad.t - pad.b)
  }

  const line = track.map((a, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(a).toFixed(1)}`).join(' ')
  const area = `${line} L${x(n - 1).toFixed(1)},${y(0).toFixed(1)} L${x(0).toFixed(1)},${y(0).toFixed(1)} Z`
  const yMin = y(minAltitude)

  let peakI = 0
  for (let i = 1; i < n; i++) if (track[i] > track[peakI]) peakI = i

  // Aufnahmefenster als Index-Bereich (für die Schattierung).
  const wsi = windowStart ? labels.indexOf(windowStart) : -1
  const wei = windowEnd ? labels.indexOf(windowEnd) : -1
  const hasWin = wsi >= 0 && wei >= wsi

  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const frac = (e.clientX - rect.left) / rect.width
    setHover(Math.max(0, Math.min(n - 1, Math.round(frac * (n - 1)))))
  }

  return (
    <div className="relative" onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-16 w-full" preserveAspectRatio="none">
        <defs>
          <linearGradient id="altfill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgb(129,140,248)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="rgb(129,140,248)" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {hasWin && (
          <rect x={x(wsi)} y={pad.t} width={Math.max(1, x(wei) - x(wsi))} height={H - pad.t - pad.b} fill="rgba(129,140,248,0.18)" />
        )}
        <line x1={pad.l} y1={yMin} x2={W - pad.r} y2={yMin} stroke="rgba(255,255,255,0.18)" strokeWidth="1" strokeDasharray="3 3" />
        <path d={area} fill="url(#altfill)" />
        <path d={line} fill="none" stroke="rgb(165,180,252)" strokeWidth="1.6" />
        {hover === null && <circle cx={x(peakI)} cy={y(track[peakI])} r="2.4" fill="#fff" />}
        {hover !== null && (
          <>
            <line x1={x(hover)} y1={pad.t} x2={x(hover)} y2={H - pad.b} stroke="rgba(255,255,255,0.5)" strokeWidth="1" />
            <circle cx={x(hover)} cy={y(track[hover])} r="2.8" fill="#fff" />
          </>
        )}
        {hover === null && (
          <>
            <text x={pad.l} y={H - 2} fontSize="8" fill="rgba(255,255,255,0.45)">{labels[0] ?? ''}</text>
            <text x={x(peakI)} y={H - 2} fontSize="8" fill="rgba(255,255,255,0.6)" textAnchor="middle">{labels[peakI] ?? ''}</text>
            <text x={W - pad.r} y={H - 2} fontSize="8" fill="rgba(255,255,255,0.45)" textAnchor="end">{labels[labels.length - 1] ?? ''}</text>
          </>
        )}
      </svg>
      {hover !== null && (
        <div
          className="pointer-events-none absolute -top-1 z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-white/15 bg-black/85 px-2 py-1 text-[11px] text-white shadow-lg"
          style={{ left: `${(hover / (n - 1)) * 100}%` }}
        >
          <span className="font-medium">{labels[hover]}</span>
          <span className="mx-1 text-slate-500">·</span>
          <span className={track[hover] >= minAltitude ? 'text-indigo-300' : 'text-slate-400'}>
            {track[hover] < 0 ? 'unter Horizont' : `${Math.round(track[hover])}°`}
          </span>
        </div>
      )}
    </div>
  )
}
