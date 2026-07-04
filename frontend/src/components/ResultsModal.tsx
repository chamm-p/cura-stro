import { useEffect, useRef, useState, useCallback } from 'react'
import { X, Upload, Trash2, Download, Loader2, FolderSearch, ImageOff, CheckCircle2, Radio, AlertTriangle, Cpu, Clock, RefreshCw, FileCheck2 } from 'lucide-react'
import api from '../services/api'
import AuthImage from './AuthImage'

interface Res {
  id: string; filename: string; file_size: number | null; width: number | null; height: number | null
  source: string | null; created_at: string | null; preview_url: string; download_url: string
}

type PiStatus = 'idle' | 'starting' | 'running' | 'polling' | 'done' | 'error'

function fmtSize(b: number | null) {
  if (!b) return ''
  const mb = b / (1024 * 1024)
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(b / 1024)} KB`
}

export default function ResultsModal({
  observationId, label, telescopeName, status, onClose, onChanged,
}: {
  observationId: string; label: string; telescopeName?: string | null
  status?: string; onClose: () => void; onChanged: () => void
}) {
  const [items, setItems] = useState<Res[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  // PixInsight-Batch-Status
  const [piStatus, setPiStatus] = useState<PiStatus>('idle')
  const [piJobId, setPiJobId] = useState<string | null>(null)
  const [piMsg, setPiMsg] = useState('')
  const [piResultCount, setPiResultCount] = useState<number | null>(null)
  const [agentHealth, setAgentHealth] = useState<{ available: boolean; pixinsight_found?: boolean } | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    api.get(`/api/observations/${observationId}/results`).then((r) => setItems(r.data)).finally(() => setLoading(false))
  }, [observationId])

  useEffect(() => { load() }, [load])

  // Agent-Health beim Öffnen prüfen
  useEffect(() => {
    api.get('/api/pixinsight/health').then((r) => setAgentHealth(r.data)).catch(() => setAgentHealth({ available: false }))
  }, [])

  // Polling aufräumen
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [onClose])

  // ─── PixInsight Batch starten ───
  const startBatch = async () => {
    setPiStatus('starting'); setPiMsg(''); setErr('')
    try {
      const r = await api.post(`/api/observations/${observationId}/process`)
      setPiJobId(r.data.job_id)
      setPiStatus('running')
      setPiMsg(`Batch gestartet — ${r.data.input_files || 0} RAW-Dateien an Mac-Agent übertragen.`)
      // Polling starten
      startPolling(r.data.job_id)
    } catch (e: any) {
      setPiStatus('error')
      setErr(e.response?.data?.detail || 'Batch konnte nicht gestartet werden.')
    }
  }

  // ─── Polling: Status abfragen, bei "completed" Ergebnisse abholen ───
  const startPolling = (jobId: string) => {
    if (pollRef.current) clearInterval(pollRef.current)
    let pollCount = 0
    pollRef.current = setInterval(async () => {
      pollCount++
      try {
        const r = await api.get(`/api/pixinsight/status/${jobId}`)
        const st = r.data.status
        if (st === 'completed') {
          // Ergebnis abholen
          if (pollRef.current) clearInterval(pollRef.current)
          setPiStatus('polling')
          setPiMsg('Batch abgeschlossen — hole Ergebnisse vom Mac …')
          try {
            const poll = await api.post(`/api/observations/${observationId}/poll`, { job_id: jobId })
            setPiStatus('done')
            setPiResultCount(poll.data.result_count || 0)
            setPiMsg(
              poll.data.result_count > 0
                ? `${poll.data.result_count} Ergebnis-Datei(en) ins Prepared-Verzeichnis geschrieben. Status → „vorbereitet".`
                : 'Batch abgeschlossen, aber keine Ergebnis-Dateien gefunden.'
            )
            onChanged()
          } catch (e: any) {
            setPiStatus('error')
            setErr(e.response?.data?.detail || 'Ergebnisse konnten nicht abgeholt werden.')
          }
        } else if (st === 'failed') {
          if (pollRef.current) clearInterval(pollRef.current)
          setPiStatus('error')
          setErr(r.data.error || 'PixInsight-Batch fehlgeschlagen.')
        } else {
          // running / queued
          setPiMsg(`PixInsight läuft … (${st})`)
        }
      } catch {
        // Netzwerkfehler — weiter pollen
      }
      // Nach 30 Minuten aufgeben
      if (pollCount > 360) {
        if (pollRef.current) clearInterval(pollRef.current)
        setPiStatus('error')
        setErr('Timeout: Batch nach 30 Minuten noch nicht fertig.')
      }
    }, 5000)
  }

  // ─── Manuelles Ergebnis abholen (falls Polling abgebrochen) ───
  const pollNow = async () => {
    if (!piJobId) return
    setPiStatus('polling'); setErr('')
    try {
      const poll = await api.post(`/api/observations/${observationId}/poll`, { job_id: piJobId })
      if (poll.data.status === 'vorbereitet') {
        setPiStatus('done')
        setPiResultCount(poll.data.result_count || 0)
        setPiMsg(`${poll.data.result_count || 0} Ergebnis-Datei(en) ins Prepared-Verzeichnis geschrieben.`)
        onChanged()
      } else {
        setPiStatus('running')
        setPiMsg(`Job-Status: ${poll.data.status || 'unbekannt'}`)
      }
    } catch (e: any) {
      setPiStatus('error')
      setErr(e.response?.data?.detail || 'Abholen fehlgeschlagen.')
    }
  }

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

  // ─── PixInsight-Sektion anzeigen? ───
  const showPiSection = status === 'raw' || status === 'in_bearbeitung' || status === 'vorbereitet' || piStatus !== 'idle'
  const canStartBatch = status === 'raw' && piStatus === 'idle'

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

        {/* ─── PixInsight Batch-Sektion ─── */}
        {showPiSection && (
          <div className="mb-4 rounded-xl border border-indigo-400/20 bg-indigo-500/5 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-indigo-200">
              <Cpu className="h-4 w-4" /> PixInsight-Batch (WBPP)
            </div>

            {/* Agent-Status */}
            {agentHealth && !agentHealth.available && (
              <div className="mt-2 flex items-center gap-2 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" /> Mac-Agent nicht erreichbar — ist der Agent auf dem Mac gestartet?
              </div>
            )}
            {agentHealth?.available && !agentHealth.pixinsight_found && (
              <div className="mt-2 flex items-center gap-2 rounded-lg border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" /> Agent erreichbar, aber PixInsight nicht gefunden.
              </div>
            )}

            {/* Status-Anzeige */}
            {piStatus === 'running' && (
              <div className="mt-2 flex items-center gap-2 text-sm text-blue-200">
                <Loader2 className="h-4 w-4 animate-spin" /> {piMsg || 'PixInsight läuft …'}
              </div>
            )}
            {piStatus === 'polling' && (
              <div className="mt-2 flex items-center gap-2 text-sm text-cyan-200">
                <Loader2 className="h-4 w-4 animate-spin" /> {piMsg}
              </div>
            )}
            {piStatus === 'done' && (
              <div className="mt-2 flex items-center gap-2 text-sm text-emerald-300">
                <FileCheck2 className="h-4 w-4" /> {piMsg}
                {piResultCount !== null && piResultCount > 0 && (
                  <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-xs">{piResultCount} Dateien</span>
                )}
              </div>
            )}
            {piStatus === 'error' && err && (
              <div className="mt-2 text-sm text-red-300">{err}</div>
            )}

            {/* Buttons */}
            <div className="mt-3 flex flex-wrap gap-2">
              {canStartBatch && (
                <button
                  onClick={startBatch}
                  disabled={!agentHealth?.available}
                  className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 px-3.5 py-2 text-sm font-medium text-white hover:from-indigo-400 hover:to-violet-500 disabled:opacity-50"
                >
                  <Cpu className="h-4 w-4" /> In PixInsight verarbeiten
                </button>
              )}
              {piStatus === 'running' && piJobId && (
                <button
                  onClick={pollNow}
                  className="flex items-center gap-2 rounded-lg border border-white/10 px-3.5 py-2 text-sm text-slate-200 hover:bg-white/10"
                >
                  <RefreshCw className="h-4 w-4" /> Jetzt abholen
                </button>
              )}
              {piStatus === 'done' && (
                <button
                  onClick={() => { setPiStatus('idle'); setPiMsg(''); setPiResultCount(null); setErr('') }}
                  className="flex items-center gap-2 rounded-lg border border-white/10 px-3.5 py-2 text-sm text-slate-200 hover:bg-white/10"
                >
                  <RefreshCw className="h-4 w-4" /> Zurücksetzen
                </button>
              )}
            </div>

            {/* Info-Text je nach Status */}
            {status === 'in_bearbeitung' && piStatus === 'idle' && (
              <p className="mt-2 text-xs text-slate-400">
                <Clock className="mr-1 inline h-3 w-3" />
                Batch läuft auf dem Mac. Klicke „Jetzt abholen", sobald PixInsight fertig ist.
              </p>
            )}
            {status === 'vorbereitet' && (
              <p className="mt-2 text-xs text-cyan-200/80">
                <FileCheck2 className="mr-1 inline h-3 w-3" />
                WBPP abgeschlossen — Master-Files liegen im <span className="font-mono">Prepared/</span>-Ordner.
                Entwickle das Bild manuell in PixInsight und lade das Ergebnis hoch oder lege es in den <span className="font-mono">Developer/</span>-Ordner.
              </p>
            )}
          </div>
        )}

        {/* ─── Upload / Scan ─── */}
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
        {err && piStatus !== 'error' && <div className="mt-2 text-sm text-red-300">{err}</div>}

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
