import { useEffect, useState } from 'react'
import { X, Loader2, ExternalLink, BookOpen } from 'lucide-react'
import api from '../services/api'

interface Detail {
  ident: string; name: string | null; obj_type: string; constellation: string | null
  preview_url: string; facts: Record<string, string>
  background: { source: string | null; title: string | null; text: string | null; url: string | null }
}

export default function ObjectInfoModal({ ident, onClose }: { ident: string; onClose: () => void }) {
  const [d, setD] = useState<Detail | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  useEffect(() => {
    setLoading(true)
    api.get(`/api/objects/${encodeURIComponent(ident)}`).then((r) => setD(r.data)).finally(() => setLoading(false))
  }, [ident])

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 sm:p-8" onClick={onClose}>
      <div className="my-auto w-full max-w-2xl rounded-2xl border border-white/10 bg-[#0a0c18] shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <h2 className="flex items-center gap-2 font-semibold">
            <BookOpen className="h-5 w-5 text-indigo-300" />
            {d?.name || ident}{d?.name ? <span className="text-sm font-normal text-slate-500">· {ident}</span> : null}
          </h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-white"><X className="h-5 w-5" /></button>
        </div>

        {loading ? (
          <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>
        ) : d ? (
          <div className="p-5">
            <img src={d.preview_url} alt={ident} className="mb-4 max-h-72 w-full rounded-xl object-cover" />
            <div className="mb-4 flex flex-wrap gap-2">
              {Object.entries(d.facts).map(([k, v]) => (
                <span key={k} className="rounded-lg bg-white/5 px-2.5 py-1 text-xs">
                  <span className="text-slate-500">{k}: </span><span className="text-slate-200">{v}</span>
                </span>
              ))}
            </div>
            {d.background.text ? (
              <>
                <p className="whitespace-pre-line text-sm leading-relaxed text-slate-300">{d.background.text}</p>
                {d.background.url && (
                  <a href={d.background.url} target="_blank" rel="noreferrer"
                    className="mt-3 inline-flex items-center gap-1 text-xs text-indigo-300 hover:underline">
                    <ExternalLink className="h-3.5 w-3.5" /> Quelle: Wikipedia ({d.background.title})
                  </a>
                )}
              </>
            ) : (
              <p className="text-sm text-slate-500">Kein Hintergrundartikel gefunden.</p>
            )}
          </div>
        ) : (
          <div className="p-8 text-center text-sm text-slate-500">Konnte nicht geladen werden.</div>
        )}
      </div>
    </div>
  )
}
