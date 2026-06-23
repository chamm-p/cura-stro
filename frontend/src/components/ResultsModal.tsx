import { useEffect, useRef, useState } from 'react'
import { X, Upload, Trash2, Download, Loader2, FolderSearch, ImageOff, CheckCircle2, Radio, AlertTriangle } from 'lucide-react'
import api from '../services/api'
import AuthImage from './AuthImage'

interface Res {
  id: string; filename: string; file_size: number | null; width: number | null; height: number | null
  source: string | null; created_at: string | null; preview_url: string; download_url: string
}

function fmtSize(b: number | null) {
  if (!b) return ''
  const mb = b / (1024 * 1024)
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(b / 1024)} KB`
}

export default function ResultsModal({
  observationId, label, telescopeName, onClose, onChanged,
}: { observationId: string; label: string; telescopeName?: string | null; onClose: () => void; onChanged: () => void }) {
  const [items, setItems] = useState<Res[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const load = () => {
    setLoading(true)
    api.get(`/api/observations/${observationId}/results`).then((r) => setItems(r.data)).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [observationId])
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [onClose])

  const upload = async (file: File) => {
    setBusy(true); setErr(''); setMsg('')
    const fd = new FormData(); fd.append('file', file)
    try {
      await api.post(`/api/observations/${observationId}/result`, fd)
      setMsg(`„${file.name}" hochgeladen.`); load(); onChanged()
    } catch (e: any) {
      setErr(e.response?.data?.detail || 'Upload fehlgeschlagen.')
    } finally { setBusy(false); if (fileRef.current) fileRef.current.value = '' }
  }

  const scan = async () => {
    setBusy(true); setErr(''); setMsg('')
    try {
      const r = await api.post(`/api/observations/${observationId}/results/scan`)
      setItems(r.data.results); setMsg(r.data.added > 0 ? `${r.data.added} neue(s) Ergebnis(se) gefunden.` : 'Keine neuen Dateien im Developer-Ordner.')
      onChanged()
    } catch (e: any) {
      setErr(e.response?.data?.detail || 'Einlesen fehlgeschlagen.')
    } finally { setBusy(false) }
  }

  const download = async (it: Res) => {
    const r = await api.get(it.download_url, { responseType: 'blob' })
    const u = URL.createObjectURL(r.data); const a = document.createElement('a')
    a.href = u; a.download = it.filename; a.click(); URL.revokeObjectURL(u)
  }

  const del = async (id: string) => { await api.delete(`/api/observations/${observationId}/results/${id}`); load(); onChanged() }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="max-h-[88vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-white/10 bg-[#0a0c18] p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Ergebnis · {label}</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10"><X className="h-5 w-5" /></button>
        </div>

        {!telescopeName && (
          <div className="mb-3 flex items-center gap-2 rounded-lg border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            <AlertTriangle className="h-4 w-4 shrink-0" /> Kein Teleskop gesetzt — Ergebnisse landen im Ordner „Unbekannt".
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <input ref={fileRef} type="file" accept=".xisf,.tif,.tiff,.fit,.fits,.fts,.jpg,.jpeg,.png" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f) }} />
          <button onClick={() => fileRef.current?.click()} disabled={busy}
            className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 px-3.5 py-2 text-sm font-medium text-white hover:from-indigo-400 hover:to-violet-500 disabled:opacity-50">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Ergebnis hochladen
          </button>
          <button onClick={scan} disabled={busy} className="flex items-center gap-2 rounded-lg border border-white/10 px-3.5 py-2 text-sm text-slate-200 hover:bg-white/10 disabled:opacity-50">
            <FolderSearch className="h-4 w-4" /> Aus Developer-Ordner einlesen
          </button>
        </div>
        <p className="mt-1.5 text-[11px] text-slate-500">Upload landet im NAS-Archiv unter <span className="font-mono">Developer/&lt;Objekt&gt;/&lt;Gerät&gt;/</span>. „Einlesen" sucht dort nach neuen Mastern (XISF/TIFF/FITS/JPG/PNG). Der Watch-Folder macht das auch automatisch.</p>
        {msg && <div className="mt-2 text-sm text-emerald-300">{msg}</div>}
        {err && <div className="mt-2 text-sm text-red-300">{err}</div>}

        <div className="mt-5 space-y-4">
          {loading ? (
            <div className="flex justify-center py-6"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-8 text-slate-500"><ImageOff className="h-7 w-7" /><span className="text-sm">Noch kein Ergebnis.</span></div>
          ) : items.map((it) => (
            <div key={it.id} className="flex flex-col gap-3 rounded-xl border border-white/10 bg-white/5 p-3 sm:flex-row">
              <AuthImage src={it.preview_url} alt={it.filename} className="h-44 w-full rounded-lg object-contain sm:w-64" />
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{it.filename}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
                      {it.width && it.height ? <span>{it.width}×{it.height}</span> : null}
                      <span>{fmtSize(it.file_size)}</span>
                      <span className="flex items-center gap-1 rounded-full bg-white/10 px-1.5">
                        {it.source === 'watch' ? <><Radio className="h-3 w-3" /> Watch</> : <><CheckCircle2 className="h-3 w-3" /> Upload</>}
                      </span>
                    </div>
                  </div>
                  <div className="flex gap-1">
                    <button onClick={() => download(it)} title="Herunterladen" className="rounded-lg p-1.5 text-slate-300 hover:bg-white/10"><Download className="h-4 w-4" /></button>
                    <button onClick={() => del(it.id)} title="Aus der App entfernen (Datei bleibt im Developer-Ordner)" className="rounded-lg p-1.5 text-slate-400 hover:bg-red-500/20 hover:text-red-300"><Trash2 className="h-4 w-4" /></button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
