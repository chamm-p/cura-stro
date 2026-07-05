import { useEffect, useState, useRef, useCallback } from 'react'
import { X, ChevronLeft, ChevronRight, Pause, Play, Loader2, ImageOff, Star } from 'lucide-react'
import api from '../services/api'

interface Slide { image_id: string; jpg_url: string; label: string; name: string | null; telescope: string | null; rating: number }

const INTERVAL = 4000

export default function Slideshow({ onClose }: { onClose: () => void }) {
  const [slides, setSlides] = useState<Slide[] | null>(null)
  const [i, setI] = useState(0)
  const [paused, setPaused] = useState(false)
  const [urls, setUrls] = useState<Record<string, string>>({})
  const rootRef = useRef<HTMLDivElement>(null)
  const urlsRef = useRef<Record<string, string>>({})

  useEffect(() => {
    api.get('/api/slideshow').then((r) => setSlides(r.data.slides)).catch(() => setSlides([]))
  }, [])

  // Bilder als Blobs laden (authentifiziert) und cachen — für weiche Überblendung
  // müssen das aktuelle + Nachbar-Bilder bereits geladen sein.
  const ensure = useCallback(async (s: Slide) => {
    if (!s || urlsRef.current[s.image_id]) return
    try {
      const r = await api.get(s.jpg_url, { responseType: 'blob' })
      const u = URL.createObjectURL(r.data)
      urlsRef.current[s.image_id] = u
      setUrls({ ...urlsRef.current })
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    if (!slides || slides.length === 0) return
    const m = slides.length
    ;[i, (i + 1) % m, (i - 1 + m) % m].forEach((k) => ensure(slides[k]))
  }, [slides, i, ensure])

  useEffect(() => () => { Object.values(urlsRef.current).forEach((u) => URL.revokeObjectURL(u)) }, [])

  // Fullscreen anfordern; beim Verlassen (ESC im Vollbild) schließen.
  useEffect(() => {
    const el = rootRef.current
    el?.requestFullscreen?.().catch(() => {})
    const onFsChange = () => { if (!document.fullscreenElement) onClose() }
    document.addEventListener('fullscreenchange', onFsChange)
    return () => {
      document.removeEventListener('fullscreenchange', onFsChange)
      if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {})
    }
  }, [onClose])

  const n = slides?.length ?? 0
  const next = useCallback(() => setI((x) => (n ? (x + 1) % n : 0)), [n])
  const prev = useCallback(() => setI((x) => (n ? (x - 1 + n) % n : 0)), [n])

  // Tastatur.
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowRight') next()
      else if (e.key === 'ArrowLeft') prev()
      else if (e.key === 'p' || e.key === 'P' || e.key === ' ') { e.preventDefault(); setPaused((p) => !p) }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [next, prev, onClose])

  // Auto-Advance.
  useEffect(() => {
    if (paused || n < 2) return
    const t = setInterval(next, INTERVAL)
    return () => clearInterval(t)
  }, [paused, n, next, i])

  const cur = slides && n ? slides[i] : null

  return (
    <div ref={rootRef} className="fixed inset-0 z-[60] flex items-center justify-center bg-black">
      {/* Schließen */}
      <button onClick={onClose} className="absolute right-4 top-4 z-10 rounded-full bg-white/10 p-2 text-white hover:bg-white/20"><X className="h-6 w-6" /></button>

      {slides === null ? (
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      ) : n === 0 ? (
        <div className="flex flex-col items-center gap-3 text-slate-400">
          <ImageOff className="h-10 w-10" />
          <p>Keine finalen Ergebnisse markiert — setze im Ergebnis-Fenster das Häkchen „Final (Slideshow)".</p>
          <button onClick={onClose} className="mt-2 rounded-lg border border-white/15 px-4 py-2 text-sm text-slate-200 hover:bg-white/10">Schließen</button>
        </div>
      ) : (
        <>
          {/* Gestapelte Layer → weiche Überblendung; Bild auf Bildschirm eingepasst */}
          {slides!.map((s, idx) => (
            urls[s.image_id] ? (
              <img
                key={s.image_id}
                src={urls[s.image_id]}
                alt={s.label}
                className="pointer-events-none absolute inset-0 m-auto max-h-full max-w-full object-contain transition-opacity duration-700 ease-in-out"
                style={{ opacity: idx === i ? 1 : 0 }}
              />
            ) : null
          ))}
          {cur && !urls[cur.image_id] && <Loader2 className="h-8 w-8 animate-spin text-slate-500" />}

          {/* Navigation */}
          <button onClick={prev} className="absolute left-3 top-1/2 -translate-y-1/2 rounded-full bg-white/10 p-3 text-white hover:bg-white/20"><ChevronLeft className="h-7 w-7" /></button>
          <button onClick={next} className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full bg-white/10 p-3 text-white hover:bg-white/20"><ChevronRight className="h-7 w-7" /></button>

          {/* Info-Leiste unten */}
          <div className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/80 to-transparent px-6 pb-5 pt-12 text-white">
            <div>
              <div className="text-lg font-semibold">{cur?.name || cur?.label} <span className="text-sm font-normal text-slate-400">{cur?.name ? cur?.label : ''}</span></div>
              <div className="mt-0.5 flex items-center gap-2 text-sm text-slate-300">
                {cur?.telescope && <span>{cur.telescope}</span>}
                <span className="flex items-center text-amber-300">{Array.from({ length: cur?.rating || 0 }).map((_, k) => <Star key={k} className="h-3.5 w-3.5 fill-current" />)}</span>
              </div>
            </div>
            <div className="flex items-center gap-3 text-sm text-slate-300">
              <button onClick={() => setPaused((p) => !p)} className="flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 hover:bg-white/20">
                {paused ? <><Play className="h-4 w-4" /> Weiter</> : <><Pause className="h-4 w-4" /> Pause</>}
              </button>
              <span className="tabular-nums">{i + 1} / {n}</span>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
