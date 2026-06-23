import { useEffect, useState } from 'react'
import { X, Radio, Loader2, Download, CheckCircle2, AlertTriangle, Search } from 'lucide-react'
import api from '../services/api'
import { useAuthStore } from '../store/auth'

interface Rig { id: string; name: string; host?: string | null; share?: string | null; telescope_id?: string | null; telescope_name?: string | null }
interface FilterAgg { filter: string; subs: number }
interface ScanObj {
  object: string; normalized: string; matched_ident: string | null; matched_name: string | null
  subs: number; filters: FilterAgg[]; nights: number
}
interface ScanResult { total_files: number; telescope: string | null; objects: ScanObj[] }

export default function AsiairImportModal({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const [rigs, setRigs] = useState<Rig[]>([])
  const [rigId, setRigId] = useState('')
  const [scanning, setScanning] = useState(false)
  const [scan, setScan] = useState<ScanResult | null>(null)
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [cleanup, setCleanup] = useState(false)
  const [importing, setImporting] = useState(false)
  const [progress, setProgress] = useState<{ phase: string; done?: number; total?: number; object?: string } | null>(null)
  const [result, setResult] = useState<any | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api.get('/api/asiair/rigs').then((r) => { setRigs(r.data); if (r.data[0]) setRigId(r.data[0].id) })
  }, [])
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [onClose])

  const rig = rigs.find((r) => r.id === rigId)

  const doScan = async () => {
    setScanning(true); setErr(''); setScan(null); setResult(null)
    try {
      const r = await api.get(`/api/asiair/rigs/${rigId}/scan`)
      setScan(r.data)
      setSel(new Set(r.data.objects.map((o: ScanObj) => o.normalized)))
    } catch (e: any) {
      setErr(e.response?.data?.detail || 'Scan fehlgeschlagen.')
    } finally { setScanning(false) }
  }

  const toggle = (k: string) => setSel((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })

  const doImport = async () => {
    setImporting(true); setErr(''); setResult(null); setProgress({ phase: 'scan' })
    const token = useAuthStore.getState().token || localStorage.getItem('auth-token')
    try {
      const resp = await fetch(`/api/asiair/rigs/${rigId}/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ objects: [...sel], cleanup }),
      })
      if (!resp.ok || !resp.body) throw new Error('HTTP ' + resp.status)
      const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        let nl
        while ((nl = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1)
          if (!line) continue
          let e: any
          try { e = JSON.parse(line) } catch { continue }
          if (e.type === 'scanning') setProgress({ phase: 'scan' })
          else if (e.type === 'scanned') setProgress({ phase: 'import', done: 0, total: e.files })
          else if (e.type === 'object') setProgress((p) => ({ ...(p || { phase: 'import' }), object: e.object }))
          else if (e.type === 'progress') setProgress({ phase: 'import', done: e.done, total: e.total, object: e.object })
          else if (e.type === 'error') setErr(e.message)
          else if (e.type === 'done') { setResult(e); onImported() }
        }
      }
    } catch (e: any) {
      setErr('Import fehlgeschlagen' + (e?.message ? ` (${e.message})` : '') + '.')
    } finally { setImporting(false); setProgress(null) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="max-h-[88vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-white/10 bg-[#0a0c18] p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold"><Radio className="h-5 w-5 text-indigo-300" /> Von ASIAir importieren</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10"><X className="h-5 w-5" /></button>
        </div>

        {rigs.length === 0 ? (
          <p className="text-sm text-slate-400">Noch keine ASIAir hinterlegt — in Einstellungen → Archiv &amp; ASIAir anlegen.</p>
        ) : (
          <>
            <div className="flex flex-wrap items-end gap-2">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-400">ASIAir</span>
                <select className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-indigo-400/60"
                  value={rigId} onChange={(e) => { setRigId(e.target.value); setScan(null); setResult(null) }}>
                  {rigs.map((r) => <option key={r.id} value={r.id}>{r.name}{r.telescope_name ? ` · ${r.telescope_name}` : ''}</option>)}
                </select>
              </label>
              <button onClick={doScan} disabled={scanning || !rigId} className="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 px-3.5 py-2 text-sm font-medium text-white hover:from-indigo-400 hover:to-violet-500 disabled:opacity-40">
                {scanning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} Scannen
              </button>
            </div>

            {rig && !rig.telescope_id && (
              <div className="mt-3 flex items-center gap-2 rounded-lg border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                <AlertTriangle className="h-4 w-4 shrink-0" /> Dieser ASIAir hat kein Teleskop zugeordnet — Import nicht möglich. In den Einstellungen setzen.
              </div>
            )}
            {err && <div className="mt-3 text-sm text-red-300">{err}</div>}

            {scanning && <div className="mt-6 flex justify-center"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>}

            {scan && (
              <div className="mt-4">
                <div className="mb-2 text-xs text-slate-400">{scan.total_files} Light-Subs gefunden · Gerät: {scan.telescope || '—'}</div>
                {scan.objects.length === 0 ? (
                  <p className="text-sm text-slate-500">Keine Light-Subs auf der ASIAir gefunden.</p>
                ) : (
                  <div className="space-y-1.5">
                    {scan.objects.map((o) => (
                      <label key={o.normalized} className="flex cursor-pointer items-center gap-3 rounded-lg border border-white/10 bg-white/5 px-3 py-2 hover:bg-white/10">
                        <input type="checkbox" checked={sel.has(o.normalized)} onChange={() => toggle(o.normalized)} />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-medium">{o.matched_ident || o.object}</span>
                            {o.matched_ident && o.matched_ident !== o.object && <span className="text-xs text-slate-500">({o.object})</span>}
                            {!o.matched_ident && <span className="rounded bg-amber-500/15 px-1.5 text-[10px] text-amber-200">Freitext</span>}
                          </div>
                          <div className="text-xs text-slate-500">
                            {o.subs} Subs · {o.filters.map((f) => `${f.filter} ${f.subs}`).join(' · ')} · {o.nights} Nacht/Nächte
                          </div>
                        </div>
                      </label>
                    ))}
                  </div>
                )}

                {scan.objects.length > 0 && (
                  <>
                    <label className="mt-3 flex items-start gap-2 text-sm text-slate-300">
                      <input type="checkbox" className="mt-0.5" checked={cleanup} onChange={(e) => setCleanup(e.target.checked)} />
                      <span>Nach Import auf der ASIAir aufräumen — <strong>nur bei 100 % fehlerfreiem Import</strong> und nur Dateien, die nachweislich im Archiv liegen. Bei Fehlern wird nichts gelöscht.</span>
                    </label>
                    <button onClick={doImport} disabled={importing || sel.size === 0 || (rig != null && !rig.telescope_id)}
                      className="mt-3 flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-500 to-violet-600 px-4 py-2.5 text-sm font-medium text-white hover:from-indigo-400 hover:to-violet-500 disabled:opacity-40">
                      {importing ? <><Loader2 className="h-4 w-4 animate-spin" /> Importiere …</> : <><Download className="h-4 w-4" /> {sel.size} Objekt(e) importieren</>}
                    </button>
                    {importing && progress && (
                      <div className="mt-3">
                        {progress.phase === 'scan' ? (
                          <div className="flex items-center gap-2 text-xs text-slate-400"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Scanne ASIAir …</div>
                        ) : (
                          <>
                            <div className="mb-1 flex justify-between text-[11px] text-slate-400">
                              <span className="truncate">{progress.object || '…'}</span>
                              <span>{progress.done ?? 0}/{progress.total ?? 0} Subs</span>
                            </div>
                            <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
                              <div className="h-full bg-indigo-500 transition-all"
                                style={{ width: `${progress.total ? Math.round(((progress.done || 0) / progress.total) * 100) : 0}%` }} />
                            </div>
                          </>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {result && (
              <div className="mt-4 rounded-xl border border-emerald-400/30 bg-emerald-500/10 p-3">
                <div className="flex items-center gap-2 text-sm font-medium text-emerald-200"><CheckCircle2 className="h-4 w-4" /> {result.total_filed} Subs importiert{result.cleaned ? ` · ${result.cleaned} auf ASIAir gelöscht` : ''}</div>
                <div className="mt-2 space-y-0.5 text-xs text-slate-300">
                  {result.imported.map((i: any, idx: number) => (
                    <div key={idx} className="flex justify-between gap-2">
                      <span>{i.matched_ident || i.object}</span>
                      <span className="text-slate-400">{i.filed} neu{i.duplicates ? ` · ${i.duplicates} Dubl.` : ''}{i.errors ? ` · ${i.errors} Fehler` : ''}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
