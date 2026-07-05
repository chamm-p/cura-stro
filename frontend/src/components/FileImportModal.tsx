import { useEffect, useRef, useState } from 'react'
import {
  X, Loader2, CheckCircle2, AlertTriangle, FolderOpen, UploadCloud, Telescope,
} from 'lucide-react'
import api from '../services/api'

// Datei-Import per Drag & Drop: Ordnerstruktur …/<Objekt>/<Gerät>/*.fit
// (gleiches Namensschema wie ASIAir). Upload läuft Datei für Datei über
// POST /api/import/file — dieselbe Pipeline wie der ASIAir-Import.

interface Picked { file: File; path: string }
interface Group {
  key: string; object: string; device: string; files: Picked[]
  matched_ident: string | null; matched_name: string | null; matched_telescope: string | null
  filters: { filter: string; subs: number }[]; nights: number; warnings: string[]
  sel: boolean
}

const FIT_RE = /\.(fit|fits|fts)$/i

function splitGroup(path: string): { obj: string; dev: string } {
  const segs = path.split('/').filter(Boolean)
  if (segs.length >= 3) return { obj: segs[segs.length - 3], dev: segs[segs.length - 2] }
  if (segs.length === 2) return { obj: segs[0], dev: '' }
  return { obj: '', dev: '' }
}

// Verzeichnis-Traversierung für Drag & Drop (webkitGetAsEntry).
// readEntries liefert Batches (~100) — so lange lesen, bis leer.
function walkEntry(entry: any, prefix: string, out: Picked[]): Promise<void> {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((f: File) => { out.push({ file: f, path: prefix + entry.name }); resolve() }, () => resolve())
    } else if (entry.isDirectory) {
      const reader = entry.createReader()
      const readBatch = () => {
        reader.readEntries(async (entries: any[]) => {
          if (!entries.length) { resolve(); return }
          for (const e of entries) await walkEntry(e, prefix + entry.name + '/', out)
          readBatch()
        }, () => resolve())
      }
      readBatch()
    } else resolve()
  })
}

export default function FileImportModal({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const [groups, setGroups] = useState<Group[]>([])
  const [skipped, setSkipped] = useState(0)
  const [analyzing, setAnalyzing] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [importing, setImporting] = useState(false)
  const [progress, setProgress] = useState<{ done: number; total: number; current: string } | null>(null)
  const [result, setResult] = useState<{ filed: number; duplicates: number; errors: number } | null>(null)
  const [errorDetails, setErrorDetails] = useState<string[]>([])
  const [err, setErr] = useState('')
  const dirRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef(false)

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape' && !importing) onClose() }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [onClose, importing])

  const addFiles = async (picked: Picked[]) => {
    setErr(''); setResult(null)
    const fits = picked.filter((p) => FIT_RE.test(p.path))
    setSkipped((s) => s + (picked.length - fits.length))
    if (!fits.length) { if (!picked.length) setErr('Keine Dateien gefunden.'); return }
    setAnalyzing(true)
    try {
      // Client-seitig gruppieren (letzte zwei Ordner = Objekt/Gerät) …
      const map = new Map<string, Picked[]>()
      for (const p of fits) {
        const { obj, dev } = splitGroup(p.path)
        const key = `${obj}|${dev}`
        if (!map.has(key)) map.set(key, [])
        map.get(key)!.push(p)
      }
      // … und vom Backend Katalog-/Teleskop-Matching holen.
      const r = await api.post('/api/import/preview', { paths: fits.map((p) => p.path) })
      const info = new Map<string, any>()
      for (const g of r.data.groups || []) info.set(`${g.object}|${g.device}`, g)

      setGroups((old) => {
        const next = [...old]
        for (const [key, files] of map) {
          const [obj, dev] = key.split('|')
          const meta = info.get(key)
          const existing = next.find((g) => g.key === key)
          if (existing) { existing.files = [...existing.files, ...files]; continue }
          next.push({
            key, object: obj, device: dev, files,
            matched_ident: meta?.matched_ident ?? null,
            matched_name: meta?.matched_name ?? null,
            matched_telescope: meta?.matched_telescope ?? null,
            filters: meta?.filters ?? [], nights: meta?.nights ?? 0,
            warnings: meta?.warnings ?? [], sel: true,
          })
        }
        return next
      })
    } catch (e: any) {
      setErr(e.response?.data?.detail || 'Vorschau fehlgeschlagen.')
    } finally { setAnalyzing(false) }
  }

  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false)
    // Entries synchron einsammeln — nach dem ersten await ist dataTransfer leer.
    const items = Array.from(e.dataTransfer.items || [])
    const entries = items.map((it) => (it as any).webkitGetAsEntry?.()).filter(Boolean)
    const looseFiles = entries.length ? [] : Array.from(e.dataTransfer.files || [])
    const out: Picked[] = []
    for (const entry of entries) await walkEntry(entry, '', out)
    for (const f of looseFiles) out.push({ file: f, path: f.name })
    await addFiles(out)
  }

  const onPickDir = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    await addFiles(files.map((f) => ({ file: f, path: (f as any).webkitRelativePath || f.name })))
    if (dirRef.current) dirRef.current.value = ''
  }

  const patchGroup = (key: string, data: Partial<Group>) =>
    setGroups((gs) => gs.map((g) => (g.key === key ? { ...g, ...data } : g)))

  const doImport = async () => {
    const selected = groups.filter((g) => g.sel)
    const invalid = selected.find((g) => !g.object.trim())
    if (invalid) { setErr('Bitte für alle gewählten Gruppen einen Objektnamen eintragen.'); return }
    const total = selected.reduce((n, g) => n + g.files.length, 0)
    setImporting(true); setErr(''); setResult(null); setErrorDetails([]); abortRef.current = false
    let done = 0, filed = 0, duplicates = 0, errors = 0
    // Fehlermeldungen sammeln (dedupliziert mit Zähler) — sonst sieht man
    // nur "N Fehler" und rät im Dunkeln.
    const errMsgs = new Map<string, number>()
    const noteError = (msg: unknown) => {
      errors++
      const m = String(msg || 'unbekannter Fehler').slice(0, 300)
      errMsgs.set(m, (errMsgs.get(m) || 0) + 1)
    }
    try {
      for (const g of selected) {
        for (const p of g.files) {
          if (abortRef.current) break
          setProgress({ done, total, current: `${g.object}${g.device ? '/' + g.device : ''} · ${p.file.name}` })
          const fd = new FormData()
          fd.append('file', p.file, p.file.name)
          fd.append('object_name', g.object.trim())
          fd.append('device_name', g.device.trim())
          try {
            const r = await api.post('/api/import/file', fd, { timeout: 300000 })
            if (r.data.status === 'filed') filed++
            else if (r.data.status === 'duplicate') duplicates++
            else noteError(r.data.error || `Status „${r.data.status}“`)
          } catch (e: any) {
            noteError(e.response?.data?.detail || (e.response?.status ? `HTTP ${e.response.status}` : e.message))
          }
          done++
        }
        if (abortRef.current) break
      }
      setProgress({ done, total, current: '' })
      setResult({ filed, duplicates, errors })
      setErrorDetails(
        [...errMsgs.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3)
          .map(([m, n]) => (n > 1 ? `${n}× ${m}` : m))
      )
      if (filed > 0) onImported()
    } finally { setImporting(false) }
  }

  const totalFiles = groups.filter((g) => g.sel).reduce((n, g) => n + g.files.length, 0)
  const pct = progress && progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => !importing && onClose()}>
      <div className="max-h-[88vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-white/10 bg-[#0a0c18] p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold"><UploadCloud className="h-5 w-5 text-indigo-300" /> Dateien importieren</h2>
          <button onClick={() => !importing && onClose()} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10"><X className="h-5 w-5" /></button>
        </div>

        {/* Drop-Zone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className={`flex flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition ${
            dragOver ? 'border-indigo-400 bg-indigo-500/10' : 'border-white/15 bg-white/[0.03]'
          }`}
        >
          <FolderOpen className="h-8 w-8 text-indigo-300" />
          <div className="text-sm text-slate-200">Ordner hierher ziehen — Struktur <span className="font-mono text-indigo-200">…/&lt;Objekt&gt;/&lt;Gerät&gt;/*.fit</span></div>
          <div className="text-xs text-slate-500">z. B. <span className="font-mono">Raw-Files/C4/RC71/Light_C4_300.0s_….fit</span></div>
          <button
            onClick={() => dirRef.current?.click()}
            disabled={importing}
            className="mt-1 flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/10 disabled:opacity-50"
          >
            <FolderOpen className="h-3.5 w-3.5" /> … oder Ordner wählen
          </button>
          <input ref={dirRef} type="file" multiple className="hidden" onChange={onPickDir} {...({ webkitdirectory: '' } as any)} />
        </div>

        {analyzing && (
          <div className="mt-3 flex items-center gap-2 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /> Analysiere Dateien …</div>
        )}
        {skipped > 0 && (
          <div className="mt-2 text-xs text-slate-500">{skipped} Datei(en) übersprungen (keine .fit/.fits/.fts).</div>
        )}

        {/* Gruppen */}
        {groups.length > 0 && (
          <div className="mt-4 space-y-2">
            {groups.map((g) => (
              <div key={g.key} className={`rounded-xl border p-3 ${g.sel ? 'border-indigo-400/30 bg-indigo-500/5' : 'border-white/10 bg-white/[0.03] opacity-60'}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <input type="checkbox" checked={g.sel} disabled={importing} onChange={(e) => patchGroup(g.key, { sel: e.target.checked })} className="h-4 w-4 accent-indigo-500" />
                  <input
                    value={g.object} disabled={importing} placeholder="Objekt"
                    onChange={(e) => patchGroup(g.key, { object: e.target.value })}
                    className="w-32 rounded-lg border border-white/10 bg-black/30 px-2 py-1 text-sm text-white outline-none focus:border-indigo-400/60"
                  />
                  <span className="text-slate-500">/</span>
                  <input
                    value={g.device} disabled={importing} placeholder="Gerät"
                    onChange={(e) => patchGroup(g.key, { device: e.target.value })}
                    className="w-28 rounded-lg border border-white/10 bg-black/30 px-2 py-1 text-sm text-white outline-none focus:border-indigo-400/60"
                  />
                  <span className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] text-slate-300">{g.files.length} Subs</span>
                  {g.nights > 0 && <span className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] text-slate-300">{g.nights} Nacht/Nächte</span>}
                  {g.matched_ident && (
                    <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[11px] text-emerald-300">✓ {g.matched_ident}{g.matched_name ? ` — ${g.matched_name}` : ''}</span>
                  )}
                  {g.matched_telescope && (
                    <span className="flex items-center gap-1 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[11px] text-emerald-300"><Telescope className="h-3 w-3" /> {g.matched_telescope}</span>
                  )}
                </div>
                {g.filters.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {g.filters.map((f) => (
                      <span key={f.filter} className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] text-slate-300">{f.filter}: {f.subs}×</span>
                    ))}
                  </div>
                )}
                {g.warnings.map((w, i) => (
                  <div key={i} className="mt-1.5 flex items-start gap-1.5 text-[11px] text-amber-300">
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" /> {w}
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}

        {/* Fortschritt */}
        {progress && (
          <div className="mt-4">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span className="truncate">{importing ? progress.current : 'Fertig'}</span>
              <span>{progress.done}/{progress.total}</span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-white/10">
              <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 transition-all" style={{ width: `${pct}%` }} />
            </div>
          </div>
        )}

        {result && (
          <div className={`mt-3 flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
            result.errors > 0 && result.filed === 0
              ? 'border-red-400/30 bg-red-500/10 text-red-200'
              : 'border-emerald-400/30 bg-emerald-500/10 text-emerald-200'
          }`}>
            {result.errors > 0 && result.filed === 0 ? <AlertTriangle className="h-4 w-4 shrink-0" /> : <CheckCircle2 className="h-4 w-4 shrink-0" />}
            {result.filed} importiert{result.duplicates > 0 ? `, ${result.duplicates} Duplikat(e) übersprungen` : ''}{result.errors > 0 ? `, ${result.errors} Fehler` : ''}.
          </div>
        )}
        {errorDetails.length > 0 && (
          <div className="mt-2 space-y-1 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
            <div className="font-medium">Fehlerdetails:</div>
            {errorDetails.map((m, i) => (
              <div key={i} className="break-words font-mono">{m}</div>
            ))}
          </div>
        )}
        {err && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
            <AlertTriangle className="h-4 w-4 shrink-0" /> {err}
          </div>
        )}

        {/* Aktionen */}
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            onClick={doImport}
            disabled={importing || totalFiles === 0}
            className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 px-4 py-2 text-sm font-medium text-white hover:from-indigo-400 hover:to-violet-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
            {importing ? 'Importiere …' : `Import starten (${totalFiles} Dateien)`}
          </button>
          {importing && (
            <button onClick={() => { abortRef.current = true }} className="rounded-lg border border-white/10 px-3.5 py-2 text-sm text-slate-200 hover:bg-white/10">
              Abbrechen
            </button>
          )}
          {!importing && groups.length > 0 && (
            <button onClick={() => { setGroups([]); setSkipped(0); setResult(null); setProgress(null) }} className="rounded-lg border border-white/10 px-3.5 py-2 text-sm text-slate-200 hover:bg-white/10">
              Liste leeren
            </button>
          )}
        </div>
        <p className="mt-2 text-[11px] text-slate-500">
          Ablage im NAS-Archiv unter <span className="font-mono">RAW/&lt;Objekt&gt;/&lt;Gerät&gt;/</span> — Duplikate (gleicher Dateiname pro Aufnahme) werden übersprungen. Objekt/Gerät sind vor dem Start editierbar.
        </p>
      </div>
    </div>
  )
}
