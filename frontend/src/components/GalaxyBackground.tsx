import { useEffect, useRef } from 'react'

/**
 * Animierter Galaxy-Hintergrund auf Canvas — keine externen Assets nötig,
 * läuft offline, ist GPU-schonend. Zeichnet:
 *  - tiefen Farbverlauf (Deep-Space)
 *  - eine logarithmische Spiralgalaxie aus Partikeln, langsam rotierend
 *  - funkelnde Hintergrundsterne mit Parallaxe
 *  - gelegentliche Sternschnuppen
 *
 * Optional kann zusätzlich ein Video-Loop (public/galaxy.mp4) eingeblendet
 * werden — siehe Login.tsx. Dieser Canvas ist der robuste Default/Fallback.
 */
export default function GalaxyBackground({
  showGalaxy = true,
  fixed = false,
}: { showGalaxy?: boolean; fixed?: boolean } = {}) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let raf = 0
    let w = 0
    let h = 0
    let dpr = Math.min(window.devicePixelRatio || 1, 2)

    type Star = { x: number; y: number; r: number; tw: number; sp: number }
    type GalPt = { dist: number; ang: number; size: number; hue: number; a: number }
    type Shooter = { x: number; y: number; vx: number; vy: number; life: number; max: number }

    let stars: Star[] = []
    let galaxy: GalPt[] = []
    let shooters: Shooter[] = []

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      w = canvas.clientWidth
      h = canvas.clientHeight
      canvas.width = Math.floor(w * dpr)
      canvas.height = Math.floor(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      build()
    }

    const build = () => {
      const starCount = Math.floor((w * h) / 1400)
      stars = Array.from({ length: starCount }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        r: Math.random() * 1.3 + 0.2,
        tw: Math.random() * Math.PI * 2,
        sp: Math.random() * 0.02 + 0.005,
      }))

      // Spiralgalaxie: zwei Arme, logarithmische Spirale.
      const arms = 2
      const ptCount = 2200
      galaxy = []
      for (let i = 0; i < ptCount; i++) {
        const arm = i % arms
        const t = Math.pow(Math.random(), 0.6) // mehr Partikel außen
        const dist = t * Math.min(w, h) * 0.42
        const spin = dist * 0.018
        const base = (arm * (Math.PI * 2)) / arms
        const scatter = (Math.random() - 0.5) * (0.5 - t * 0.35)
        const ang = base + spin + scatter
        // Kern bläulich-weiß, Außen rosa/violett.
        const hue = 210 + t * 110 + (Math.random() - 0.5) * 30
        galaxy.push({
          dist,
          ang,
          size: Math.random() * 1.6 + 0.3,
          hue,
          a: 0.5 + Math.random() * 0.5,
        })
      }
    }

    const drawNebula = (cx: number, cy: number) => {
      const blobs = [
        { x: cx, y: cy, r: Math.min(w, h) * 0.5, c: 'rgba(99,102,241,0.16)' },
        { x: cx - w * 0.18, y: cy + h * 0.1, r: Math.min(w, h) * 0.35, c: 'rgba(236,72,153,0.10)' },
        { x: cx + w * 0.2, y: cy - h * 0.12, r: Math.min(w, h) * 0.4, c: 'rgba(56,189,248,0.10)' },
      ]
      for (const b of blobs) {
        const g = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.r)
        g.addColorStop(0, b.c)
        g.addColorStop(1, 'rgba(0,0,0,0)')
        ctx.fillStyle = g
        ctx.fillRect(0, 0, w, h)
      }
    }

    let frame = 0
    const render = () => {
      frame++
      // Deep-Space-Verlauf.
      const bg = ctx.createLinearGradient(0, 0, w, h)
      bg.addColorStop(0, '#05060f')
      bg.addColorStop(0.55, '#080a1a')
      bg.addColorStop(1, '#0b0717')
      ctx.fillStyle = bg
      ctx.fillRect(0, 0, w, h)

      const cx = w * 0.62
      const cy = h * 0.42
      if (showGalaxy) drawNebula(cx, cy)

      // Hintergrundsterne (Funkeln).
      for (const s of stars) {
        s.tw += s.sp
        const a = 0.35 + Math.sin(s.tw) * 0.35 + 0.3
        ctx.globalAlpha = Math.max(0, Math.min(1, a))
        ctx.fillStyle = '#dbe4ff'
        ctx.beginPath()
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.globalAlpha = 1

      // Spiralgalaxie + Kern (nur in der Voll-Variante, z. B. Login).
      if (showGalaxy) {
        const rot = frame * 0.0009
        ctx.globalCompositeOperation = 'lighter'
        for (const p of galaxy) {
          const a = p.ang + rot * (1 - p.dist / (Math.min(w, h) * 0.5)) // innen schneller
          const x = cx + Math.cos(a) * p.dist
          const y = cy + Math.sin(a) * p.dist * 0.62 // leicht geneigt
          ctx.fillStyle = `hsla(${p.hue}, 80%, 70%, ${p.a})`
          ctx.beginPath()
          ctx.arc(x, y, p.size, 0, Math.PI * 2)
          ctx.fill()
        }
        const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.min(w, h) * 0.14)
        core.addColorStop(0, 'rgba(255,255,255,0.9)')
        core.addColorStop(0.25, 'rgba(214,224,255,0.5)')
        core.addColorStop(1, 'rgba(120,140,255,0)')
        ctx.fillStyle = core
        ctx.beginPath()
        ctx.arc(cx, cy, Math.min(w, h) * 0.14, 0, Math.PI * 2)
        ctx.fill()
        ctx.globalCompositeOperation = 'source-over'
      }

      // Sternschnuppen.
      if (Math.random() < 0.006 && shooters.length < 3) {
        const sx = Math.random() * w * 0.8
        shooters.push({ x: sx, y: -10, vx: 4 + Math.random() * 3, vy: 3 + Math.random() * 2, life: 0, max: 60 + Math.random() * 30 })
      }
      shooters = shooters.filter((sh) => sh.life < sh.max)
      for (const sh of shooters) {
        sh.life++
        sh.x += sh.vx
        sh.y += sh.vy
        const tailX = sh.x - sh.vx * 6
        const tailY = sh.y - sh.vy * 6
        const grad = ctx.createLinearGradient(sh.x, sh.y, tailX, tailY)
        grad.addColorStop(0, 'rgba(255,255,255,0.9)')
        grad.addColorStop(1, 'rgba(255,255,255,0)')
        ctx.strokeStyle = grad
        ctx.lineWidth = 2
        ctx.beginPath()
        ctx.moveTo(sh.x, sh.y)
        ctx.lineTo(tailX, tailY)
        ctx.stroke()
      }

      raf = requestAnimationFrame(render)
    }

    resize()
    render()
    window.addEventListener('resize', resize)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
    }
  }, [])

  return (
    <canvas
      ref={ref}
      className={`${fixed ? 'fixed pointer-events-none' : 'absolute'} inset-0 h-full w-full`}
    />
  )
}
