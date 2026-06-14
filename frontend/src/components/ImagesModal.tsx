import { useEffect, useRef, useState } from 'react'
import { X, Upload, Trash2, Download, Loader2, ImageOff } from 'lucide-react'
import api from '../services/api'
import AuthImage from './AuthImage'

interface Img {
  id: string; original_format: string; original_filename: string; file_size: number | null
  width: number | null; height: number | null; channels: number | null
  meta_summary: Record<string, any>; jpg_url: string; download_url: string
}

function fmtSize(b: number | null) {
  if (!b) return ''
  const mb = b / (1024 * 1024)
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(b / 1024)} KB`
}

export default function ImagesModal({
  observationId, label, onClose, onChanged,
}: { observationId: string; label: string; onClose: () => void; onChanged: () => void }) {
  const [imgs, setImgs] = useState<Img[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [err, setErr] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const load = () => {
    setLoading(true)
    api.get(`/api/observations/${observationId}/images`).then((r) => setImgs(r.data)).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [observationId])

  const upload = async (file: File) => {
    setUploading(true); setErr('')
    const fd = new FormData()
    fd.append('file', file)
    try {
      await api.post(`/api/observations/${observationId}/images`, fd)
      load(); onChanged()
    } catch (e: any) {
      setErr(e.response?.data?.detail || 'Upload fehlgeschlagen.')
    } finally { setUploading(false); if (fileRef.current) fileRef.current.value = '' }
  }

  const download = async (img: Img) => {
    const r = await api.get(img.download_url, { responseType: 'blob' })
    const u = URL.createObjectURL(r.data)
    const a = document.createElement('a')
    a.href = u
    a.download = img.original_filename.replace(/\.[^.]+$/, '') + '.jpg'
    a.click()
    URL.revokeObjectURL(u)
  }

  const del = async (id: string) => { await api.delete(`/api/images/${id}`); load(); onChanged() }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="max-h-[88vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-white/10 bg-[#0a0c18] p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Fotos · {label}</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10"><X className="h-5 w-5" /></button>
        </div>

        <input ref={fileRef} type="file" accept=".fits,.fit,.fts,.xisf,.tif,.tiff" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f) }} />
        <button onClick={() => fileRef.current?.click()} disabled={uploading}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-white/20 bg-white/5 px-4 py-4 text-sm text-slate-300 transition hover:bg-white/10 disabled:opacity-60">
          {uploading ? <><Loader2 className="h-4 w-4 animate-spin" /> Lade hoch & analysiere …</> : <><Upload className="h-4 w-4" /> FITS / XISF / TIFF hochladen</>}
        </button>
        {err && <div className="mt-2 text-sm text-red-300">{err}</div>}

        <div className="mt-5 space-y-4">
          {loading ? (
            <div className="flex justify-center py-6"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>
          ) : imgs.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-8 text-slate-500">
              <ImageOff className="h-7 w-7" /> <span className="text-sm">Noch keine Fotos.</span>
            </div>
          ) : imgs.map((img) => (
            <div key={img.id} className="flex flex-col gap-3 rounded-xl border border-white/10 bg-white/5 p-3 sm:flex-row">
              <AuthImage src={img.jpg_url} alt={img.original_filename} className="h-40 w-full rounded-lg object-cover sm:w-56" />
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{img.original_filename}</div>
                    <div className="text-xs text-slate-500">
                      {img.original_format.toUpperCase()} · {img.width}×{img.height}{img.channels === 1 ? ' · mono' : img.channels === 3 ? ' · Farbe' : ''} · {fmtSize(img.file_size)}
                    </div>
                  </div>
                  <div className="flex gap-1">
                    <button onClick={() => download(img)} title="JPG herunterladen" className="rounded-lg p-1.5 text-slate-300 hover:bg-white/10"><Download className="h-4 w-4" /></button>
                    <button onClick={() => del(img.id)} title="Löschen" className="rounded-lg p-1.5 text-slate-400 hover:bg-red-500/20 hover:text-red-300"><Trash2 className="h-4 w-4" /></button>
                  </div>
                </div>
                {Object.keys(img.meta_summary || {}).length > 0 && (
                  <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-slate-400">
                    {Object.entries(img.meta_summary).map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-2"><span className="text-slate-500">{k}</span><span className="truncate text-slate-300">{String(v)}</span></div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
