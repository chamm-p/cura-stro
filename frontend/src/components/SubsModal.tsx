import { useCallback, useEffect, useRef, useState } from 'react'
import { X, Upload, Trash2, Loader2, Layers, CheckCircle2, AlertTriangle, ChevronLeft, ChevronRight, Eye } from 'lucide-react'
import api from '../services/api'
import AuthImage from './AuthImage'

interface Frame {
  id: string; filename: string; frame_type: string; filter: string | null
  exposure_s: number | null; binning: number | null; captured_at: string | null
  sequence: number | null; verified: boolean; source: string | null
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
  const [viewIdx, setViewIdx] = useState<number | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

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
        if (e.key === 'Escape') setViewIdx(null)
        else if (e.key === 'ArrowLeft') setViewIdx((i) => (i === null ? i : Math.max(0, i - 1)))
        else if (e.key === 'ArrowRight') setViewIdx((i) => (i === null ? i : Math.min(frames.length - 1, i + 1)))
        return
      }
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [onClose, viewIdx, frames.length])

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
                <div key={f.filter} className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 px-3 py-2">
                  <span className="font-medium">{f.filter}</span>
                  <span className="text-xs text-slate-400">{f.subs} × {f.exposures_s.map((e) => `${e}s`).join(' / ')} · {fmtDur(f.integration_s)}</span>
                </div>
              ))}
            </div>

            <button onClick={() => setShowFrames((s) => !s)} className="mt-4 text-xs text-indigo-300 hover:underline">
              {showFrames ? 'Einzel-Subs ausblenden' : `Alle ${frames.length} Subs anzeigen`}
            </button>
            {showFrames && (
              <>
                <p className="mt-1 text-[11px] text-slate-500">Sub anklicken → gestreckte Vorschau (mit ←/→ blättern).</p>
                <div className="mt-1 max-h-64 space-y-1 overflow-y-auto rounded-lg border border-white/10 bg-black/30 p-2">
                  {frames.map((fr, i) => (
                    <div key={fr.id} className="flex items-center justify-between gap-2 rounded px-2 py-1 text-xs hover:bg-white/5">
                      <button onClick={() => setViewIdx(i)} className="flex min-w-0 items-center gap-1 text-left text-slate-300 hover:text-white" title="Gestreckte Vorschau">
                        <Eye className="h-3 w-3 shrink-0 text-slate-500" /><span className="truncate">{fr.filename}</span>
                      </button>
                      <span className="flex shrink-0 items-center gap-2 text-slate-500">
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

    {viewIdx !== null && frames[viewIdx] && (
      <div className="fixed inset-0 z-[60] flex flex-col bg-black/90" onClick={() => setViewIdx(null)}>
        <div className="flex items-center justify-between gap-3 px-4 py-2 text-sm text-slate-200" onClick={(e) => e.stopPropagation()}>
          <span className="truncate">{frames[viewIdx].filename}</span>
          <span className="flex shrink-0 items-center gap-3 text-xs text-slate-400">
            <span>{viewIdx + 1} / {frames.length}</span>
            {frames[viewIdx].filter && <span className="rounded bg-white/10 px-1.5">{frames[viewIdx].filter}</span>}
            {frames[viewIdx].exposure_s ? <span>{frames[viewIdx].exposure_s}s</span> : null}
            <button onClick={() => setViewIdx(null)} className="rounded-lg p-1.5 hover:bg-white/10"><X className="h-5 w-5" /></button>
          </span>
        </div>
        <div className="relative flex flex-1 items-center justify-center overflow-hidden" onClick={(e) => e.stopPropagation()}>
          <button onClick={() => setViewIdx((i) => (i === null ? i : Math.max(0, i - 1)))} disabled={viewIdx === 0}
            className="absolute left-2 z-10 rounded-full bg-white/10 p-2 text-white hover:bg-white/20 disabled:opacity-30"><ChevronLeft className="h-6 w-6" /></button>
          <AuthImage key={frames[viewIdx].id} src={`/api/observations/${observationId}/subframes/${frames[viewIdx].id}/preview`}
            alt={frames[viewIdx].filename} className="max-h-full max-w-full object-contain" />
          <button onClick={() => setViewIdx((i) => (i === null ? i : Math.min(frames.length - 1, i + 1)))} disabled={viewIdx === frames.length - 1}
            className="absolute right-2 z-10 rounded-full bg-white/10 p-2 text-white hover:bg-white/20 disabled:opacity-30"><ChevronRight className="h-6 w-6" /></button>
        </div>
        <div className="px-4 py-2 text-center text-[11px] text-slate-500">←/→ blättern · ESC schließen · gestreckt (Autostretch)</div>
      </div>
    )}
    </>
  )
}
