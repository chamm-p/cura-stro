import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { X, Upload, Trash2, Loader2, Layers, CheckCircle2, AlertTriangle, ChevronLeft, ChevronRight, Eye, ThumbsUp, ThumbsDown } from 'lucide-react'
import api from '../services/api'
import { useAuthStore } from '../store/auth'

type Quality = 'ok' | 'nok' | null
interface Frame {
  id: string; filename: string; frame_type: string; filter: string | null
  exposure_s: number | null; binning: number | null; captured_at: string | null
  sequence: number | null; verified: boolean; source: string | null; quality?: Quality
}
interface FilterAgg { filter: string; subs: number; integration_s: number; exposures_s: number[] }
interface Summary { filters: FilterAgg[]; total_subs: number; total_integration_s: number; nights: string[]; verified: number }

function fmtDur(s: number) {
  if (!s) return '0 min'
  const h = Math.floor(s / 3600); const m = Math.round((s % 3600) / 60)
  return h > 0 ? `${h} h ${m} min` : `${m} min`
}

export default function SubsModal({
  observationId, label, telescopeName, onClose, onChanged,
}: { observationId: string; label: string; telescopeName?: string | null; onClose: () => void; onChanged: () => void }) {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [frames, setFrames] = useState<Frame[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState<string>('')
  const [err, setErr] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [showFrames, setShowFrames] = useState(false)
  const [activeFilter, setActiveFilter] = useState<string | null>(null)
  const [viewIdx, setViewIdx] = useState<number | null>(null)
  const [shownUrl, setShownUrl] = useState<string | null>(null)
  const [vLoading, setVLoading] = useState(false)
  const blobCache = useRef<Map<string, string>>(new Map())
  const curId = useRef<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  // Vorschau-JPG (auth) holen + als Blob-URL cachen.
  const loadPreview = useCallback(async (frameId: string): Promise<string | null> => {
    const hit = blobCache.current.get(frameId)
    if (hit) return hit
    const token = useAuthStore.getState().token || localStorage.getItem('auth-token')
    try {
      const r = await fetch(`/api/observations/${observationId}/subframes/${frameId}/preview`, { headers: { Authorization: `Bearer ${token}` } })
      if (!r.ok) return null
      const url = URL.createObjectURL(await r.blob())
      blobCache.current.set(frameId, url)
      return url
    } catch { return null }
  }, [observationId])

  // Angezeigte (ggf. nach Filter eingeschränkte) Sub-Liste.
  const viewFrames = useMemo(
    () => (activeFilter ? frames.filter((f) => (f.filter || '—') === activeFilter) : frames),
    [frames, activeFilter],
  )

  // Qualitäts-Flag setzen (optimistisch + PATCH).
  const setQuality = useCallback((frameId: string, q: Quality) => {
    setFrames((prev) => prev.map((f) => (f.id === frameId ? { ...f, quality: q } : f)))
    api.patch(`/api/observations/${observationId}/subframes/${frameId}`, { quality: q }).catch(() => {})
  }, [observationId])

  // Beim Blättern: gecachtes sofort zeigen, sonst altes Bild stehen lassen +
  // im Hintergrund laden; Nachbarn vorausladen (Daumenkino ohne Schwarz).
  useEffect(() => {
    if (viewIdx === null) return
    const fr = viewFrames[viewIdx]
    if (!fr) return
    curId.current = fr.id
    const hit = blobCache.current.get(fr.id)
    if (hit) { setShownUrl(hit); setVLoading(false) } else { setVLoading(true) }
    loadPreview(fr.id).then((url) => {
      if (url && curId.current === fr.id) { setShownUrl(url); setVLoading(false) }
    })
    ;[viewIdx + 1, viewIdx - 1, viewIdx + 2].forEach((j) => {
      const n = viewFrames[(j + viewFrames.length) % viewFrames.length]
      if (n) loadPreview(n.id)
    })
  }, [viewIdx, viewFrames, loadPreview])

  // Filterwechsel → Viewer schließen (Index passt sonst nicht mehr).
  useEffect(() => { setViewIdx(null) }, [activeFilter])

  // Blob-URLs beim Schließen freigeben.
  useEffect(() => () => { blobCache.current.forEach((u) => URL.revokeObjectURL(u)); blobCache.current.clear() }, [])

  const load = useCallback(() => {
    setLoading(true)
    api.get(`/api/observations/${observationId}/subframes`)
      .then((r) => { setSummary(r.data.summary); setFrames(r.data.frames) })
      .finally(() => setLoading(false))
  }, [observationId])
  useEffect(() => { load() }, [load])

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (viewIdx !== null) {
        const n = viewFrames.length
        if (e.key === 'Escape') setViewIdx(null)
        else if (e.key === 'ArrowLeft') setViewIdx((i) => (i === null ? i : (i - 1 + n) % n))   // loopt
        else if (e.key === 'ArrowRight') setViewIdx((i) => (i === null ? i : (i + 1) % n))        // loopt
        else if (e.key === 'o' || e.key === 'O') { const f = viewFrames[viewIdx]; if (f) { setQuality(f.id, 'ok'); setViewIdx((i) => (i === null ? i : (i + 1) % n)) } }
        else if (e.key === 'p' || e.key === 'P') { const f = viewFrames[viewIdx]; if (f) { setQuality(f.id, 'nok'); setViewIdx((i) => (i === null ? i : (i + 1) % n)) } }
        return
      }
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [onClose, viewIdx, viewFrames, setQuality])

  const upload = async (files: FileList | File[]) => {
    const arr = Array.from(files)
    if (!arr.length) return
    setUploading(true); setErr(''); setProgress(`${arr.length} Datei(en) werden hochgeladen …`)
    const fd = new FormData()
    arr.forEach((f) => fd.append('files', f))
    try {
      const r = await api.post(`/api/observations/${observationId}/subframes/upload`, fd)
      const d = r.data
      setProgress(`${d.filed} einsortiert, ${d.duplicates} Dublette(n) übersprungen.`)
      load(); onChanged()
    } catch (e: any) {
      setErr(e.response?.data?.detail || 'Upload fehlgeschlagen.')
      setProgress('')
    } finally { setUploading(false); if (fileRef.current) fileRef.current.value = '' }
  }

  const del = async (id: string) => {
    await api.delete(`/api/observations/${observationId}/subframes/${id}`); load(); onChanged()
  }

  return (
    <>
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="max-h-[88vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-white/10 bg-[#0a0c18] p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold"><Layers className="h-5 w-5 text-indigo-300" /> Subs · {label}</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10"><X className="h-5 w-5" /></button>
        </div>

        {!telescopeName && (
          <div className="mb-3 flex items-center gap-2 rounded-lg border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            <AlertTriangle className="h-4 w-4 shrink-0" /> Kein Teleskop gesetzt — Subs landen im Ordner „Unbekannt". Setze in der Verwaltung das Teleskop für die korrekte Geräte-Ablage.
          </div>
        )}

        <input ref={fileRef} type="file" multiple accept=".fits,.fit,.fts,.xisf" className="hidden"
          onChange={(e) => { if (e.target.files) upload(e.target.files) }} />
        <div
          onClick={() => !uploading && fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files) upload(e.dataTransfer.files) }}
          className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-4 py-7 text-sm transition ${dragOver ? 'border-indigo-400/70 bg-indigo-500/10 text-indigo-100' : 'border-white/20 bg-white/5 text-slate-300 hover:bg-white/10'} ${uploading ? 'opacity-60' : ''}`}>
          {uploading ? <><Loader2 className="h-5 w-5 animate-spin" /> {progress || 'Lade hoch …'}</>
            : <><Upload className="h-5 w-5" /> FITS/XISF hierher ziehen oder klicken — mehrere Subs auf einmal</>}
        </div>
        {progress && !uploading && <div className="mt-2 text-xs text-emerald-300">{progress}</div>}
        {err && <div className="mt-2 text-sm text-red-300">{err}</div>}

        {/* Zusammenfassung */}
        {loading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>
        ) : summary && summary.total_subs > 0 ? (
          <div className="mt-5">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="rounded-full bg-indigo-500/20 px-3 py-1 text-indigo-100">{summary.total_subs} Subs · {fmtDur(summary.total_integration_s)}</span>
              <span className="flex items-center gap-1 rounded-full bg-emerald-500/15 px-3 py-1 text-xs text-emerald-200"><CheckCircle2 className="h-3.5 w-3.5" /> {summary.verified} verifiziert</span>
              {summary.nights.length > 0 && <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-300">{summary.nights.length} Nacht/Nächte</span>}
            </div>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {summary.filters.map((f) => (
                <button key={f.filter} onClick={() => { setActiveFilter((p) => (p === f.filter ? null : f.filter)); setShowFrames(true) }}
                  className={`flex items-center justify-between rounded-lg border px-3 py-2 text-left transition ${activeFilter === f.filter ? 'border-indigo-400/60 bg-indigo-500/20' : 'border-white/10 bg-white/5 hover:bg-white/10'}`}>
                  <span className="font-medium">{f.filter}</span>
                  <span className="text-xs text-slate-400">{f.subs} × {f.exposures_s.map((e) => `${e}s`).join(' / ')} · {fmtDur(f.integration_s)}</span>
                </button>
              ))}
            </div>

            <div className="mt-4 flex items-center gap-2 text-xs">
              <button onClick={() => setShowFrames((s) => !s)} className="text-indigo-300 hover:underline">
                {showFrames ? 'Einzel-Subs ausblenden' : `Alle ${frames.length} Subs anzeigen`}
              </button>
              {activeFilter && (
                <span className="flex items-center gap-1 rounded-full bg-indigo-500/20 px-2 py-0.5 text-indigo-100">
                  Filter: {activeFilter}
                  <button onClick={() => setActiveFilter(null)} className="hover:text-white"><X className="h-3 w-3" /></button>
                </span>
              )}
            </div>
            {showFrames && (
              <>
                <p className="mt-1 text-[11px] text-slate-500">Sub anklicken → gestreckte Vorschau · ←/→ blättern (loopt) · <strong>O</strong> = OK, <strong>P</strong> = Problem.</p>
                <div className="mt-1 max-h-64 space-y-1 overflow-y-auto rounded-lg border border-white/10 bg-black/30 p-2">
                  {viewFrames.map((fr, i) => (
                    <div key={fr.id} className="flex items-center justify-between gap-2 rounded px-2 py-1 text-xs hover:bg-white/5">
                      <button onClick={() => setViewIdx(i)} className="flex min-w-0 items-center gap-1 text-left text-slate-300 hover:text-white" title="Gestreckte Vorschau">
                        <Eye className="h-3 w-3 shrink-0 text-slate-500" /><span className="truncate">{fr.filename}</span>
                      </button>
                      <span className="flex shrink-0 items-center gap-2 text-slate-500">
                        {fr.quality === 'ok' && <span className="rounded bg-emerald-500/20 px-1.5 text-emerald-200">OK</span>}
                        {fr.quality === 'nok' && <span className="rounded bg-red-500/20 px-1.5 text-red-200">NOK</span>}
                        {fr.filter && <span className="rounded bg-white/10 px-1.5">{fr.filter}</span>}
                        {fr.exposure_s ? `${fr.exposure_s}s` : ''}
                        {fr.verified && <CheckCircle2 className="h-3 w-3 text-emerald-400" />}
                        <button onClick={() => del(fr.id)} className="rounded p-0.5 text-slate-500 hover:bg-red-500/20 hover:text-red-300"><Trash2 className="h-3.5 w-3.5" /></button>
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        ) : (
          <p className="mt-6 text-center text-sm text-slate-500">Noch keine Subs. Zieh deine FITS hierher.</p>
        )}
      </div>
    </div>

    {viewIdx !== null && viewFrames[viewIdx] && (() => {
      const cur = viewFrames[viewIdx]
      const n = viewFrames.length
      return (
        <div className="fixed inset-0 z-[60] flex flex-col bg-black/90" onClick={() => setViewIdx(null)}>
          <div className="flex items-center justify-between gap-3 px-4 py-2 text-sm text-slate-200" onClick={(e) => e.stopPropagation()}>
            <span className="truncate">{cur.filename}</span>
            <span className="flex shrink-0 items-center gap-3 text-xs text-slate-400">
              {cur.quality === 'ok' && <span className="rounded bg-emerald-500/25 px-2 py-0.5 text-emerald-100">OK</span>}
              {cur.quality === 'nok' && <span className="rounded bg-red-500/25 px-2 py-0.5 text-red-100">Problem</span>}
              <span>{viewIdx + 1} / {n}</span>
              {cur.filter && <span className="rounded bg-white/10 px-1.5">{cur.filter}{activeFilter ? '' : ''}</span>}
              {cur.exposure_s ? <span>{cur.exposure_s}s</span> : null}
              <button onClick={() => setViewIdx(null)} className="rounded-lg p-1.5 hover:bg-white/10"><X className="h-5 w-5" /></button>
            </span>
          </div>
          <div className="relative flex flex-1 items-center justify-center overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <button onClick={() => setViewIdx((i) => (i === null ? i : (i - 1 + n) % n))}
              className="absolute left-2 z-10 rounded-full bg-white/10 p-2 text-white hover:bg-white/20"><ChevronLeft className="h-6 w-6" /></button>
            {shownUrl && <img src={shownUrl} alt={cur.filename} className="max-h-full max-w-full object-contain" />}
            {vLoading && (
              <div className="absolute right-3 top-3 flex items-center gap-1 rounded bg-black/60 px-2 py-1 text-[11px] text-slate-300">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> lädt …
              </div>
            )}
            <div className="pointer-events-none absolute bottom-3 left-3 max-w-[70%] truncate rounded bg-black/55 px-2 py-1 text-xs text-slate-100">
              {cur.filename}
            </div>
            <button onClick={() => setViewIdx((i) => (i === null ? i : (i + 1) % n))}
              className="absolute right-2 z-10 rounded-full bg-white/10 p-2 text-white hover:bg-white/20"><ChevronRight className="h-6 w-6" /></button>
          </div>
          <div className="flex items-center justify-center gap-3 px-4 py-2" onClick={(e) => e.stopPropagation()}>
            <button onClick={() => { setQuality(cur.id, 'ok'); setViewIdx((i) => (i === null ? i : (i + 1) % n)) }}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm ${cur.quality === 'ok' ? 'bg-emerald-500/30 text-emerald-100' : 'bg-white/10 text-slate-200 hover:bg-emerald-500/20'}`}>
              <ThumbsUp className="h-4 w-4" /> OK <span className="opacity-60">(O)</span>
            </button>
            <button onClick={() => { setQuality(cur.id, 'nok'); setViewIdx((i) => (i === null ? i : (i + 1) % n)) }}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm ${cur.quality === 'nok' ? 'bg-red-500/30 text-red-100' : 'bg-white/10 text-slate-200 hover:bg-red-500/20'}`}>
              <ThumbsDown className="h-4 w-4" /> Problem <span className="opacity-60">(P)</span>
            </button>
            {cur.quality && (
              <button onClick={() => setQuality(cur.id, null)} className="rounded-lg px-2 py-1.5 text-xs text-slate-400 hover:bg-white/10">Flag löschen</button>
            )}
          </div>
          <div className="px-4 pb-2 text-center text-[11px] text-slate-500">←/→ blättern (loopt) · O = OK · P = Problem · ESC schließen · gestreckt</div>
        </div>
      )
    })()}
    </>
  )
}
