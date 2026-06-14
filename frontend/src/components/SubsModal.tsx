import { useCallback, useEffect, useRef, useState } from 'react'
import { X, Upload, Trash2, Loader2, Layers, CheckCircle2, AlertTriangle } from 'lucide-react'
import api from '../services/api'

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
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    setLoading(true)
    api.get(`/api/observations/${observationId}/subframes`)
      .then((r) => { setSummary(r.data.summary); setFrames(r.data.frames) })
      .finally(() => setLoading(false))
  }, [observationId])
  useEffect(() => { load() }, [load])

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [onClose])

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
              <div className="mt-2 max-h-64 space-y-1 overflow-y-auto rounded-lg border border-white/10 bg-black/30 p-2">
                {frames.map((fr) => (
                  <div key={fr.id} className="flex items-center justify-between gap-2 rounded px-2 py-1 text-xs hover:bg-white/5">
                    <span className="truncate text-slate-300" title={fr.filename}>{fr.filename}</span>
                    <span className="flex shrink-0 items-center gap-2 text-slate-500">
                      {fr.filter && <span className="rounded bg-white/10 px-1.5">{fr.filter}</span>}
                      {fr.exposure_s ? `${fr.exposure_s}s` : ''}
                      {fr.verified && <CheckCircle2 className="h-3 w-3 text-emerald-400" />}
                      <button onClick={() => del(fr.id)} className="rounded p-0.5 text-slate-500 hover:bg-red-500/20 hover:text-red-300"><Trash2 className="h-3.5 w-3.5" /></button>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="mt-6 text-center text-sm text-slate-500">Noch keine Subs. Zieh deine FITS hierher.</p>
        )}
      </div>
    </div>
  )
}
