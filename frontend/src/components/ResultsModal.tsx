import { useEffect, useRef, useState, useCallback } from 'react'
import {
  X, Upload, Trash2, Download, Loader2, FolderSearch, ImageOff,
  CheckCircle2, Radio, AlertTriangle, Cpu, Clock, RefreshCw, FileCheck2,
  Activity, Files, HardDrive, Wifi, WifiOff, Layers, Zap,
} from 'lucide-react'
import api from '../services/api'
import AuthImage from './AuthImage'

interface Res {
  id: string; filename: string; file_size: number | null; width: number | null; height: number | null
  source: string | null; created_at: string | null; preview_url: string; download_url: string
}

type PiStatus = 'idle' | 'prechecking' | 'ready' | 'starting' | 'running' | 'polling' | 'done' | 'error'
type ProcessMode = 'wbpp' | 'fastbatch' | 'shell_sim'

interface PrecheckResult {
  can_start: boolean
  frame_counts: {
    lights: number; darks: number; flats: number; bias: number; darkflats: number; total: number
  }
  missing_archive_count: number
  estimated_size_mb: number
  calibration_dir: { configured: boolean; flats_dir: string | null; darks_dir: string | null; bias_dir: string | null }
  agent: {
    available: boolean; pixinsight_found: boolean; pixinsight_running: boolean
    shell_sim_available: boolean; wbpp_script_found: boolean; fastbatch_script_found: boolean
    active_jobs: number
  }
  frame_info: {
    object_name: string; device_name: string; total_subs: number
    filters: { filter: string; subs: number; exposures_s: number[] }[]
    frame_types: Record<string, number>
  }
  warnings: { level: string; code: string; message: string }[]
  errors: { level: string; code: string; message: string }[]
}

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

  // PixInsight-Batch-Status
  const [piStatus, setPiStatus] = useState<PiStatus>('idle')
  const [piJobId, setPiJobId] = useState<string | null>(null)
  const [piMsg, setPiMsg] = useState('')
  const [piResultCount, setPiResultCount] = useState<number | null>(null)
  const [processMode, setProcessMode] = useState<ProcessMode>('shell_sim')
  const [precheck, setPrecheck] = useState<PrecheckResult | null>(null)
  const [precheckLoading, setPrecheckLoading] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    api.get(`/api/observations/${observationId}/results`).then((r) => setItems(r.data)).finally(() => setLoading(false))
  }, [observationId])

  useEffect(() => { load() }, [load])

  // Pre-Flight-Check automatisch beim Öffnen (nur wenn status === 'raw')
  useEffect(() => {
    if (status === 'raw' && piStatus === 'idle') {
      setPiStatus('prechecking')
      setPrecheckLoading(true)
      api.get(`/api/observations/${observationId}/precheck`)
        .then((r) => {
          setPrecheck(r.data)
          setPiStatus('ready')
        })
        .catch(() => {
          setPiStatus('ready')
        })
        .finally(() => setPrecheckLoading(false))
    }
  }, [observationId, status]) // eslint-disable-line

  // Polling aufräumen
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [onClose])

  // ─── Pre-Flight-Check manuell aktualisieren ───
  const refreshPrecheck = async () => {
    setPrecheckLoading(true)
    try {
      const r = await api.get(`/api/observations/${observationId}/precheck`)
      setPrecheck(r.data)
    } catch { /* ignore */ }
    finally { setPrecheckLoading(false) }
  }

  // ─── PixInsight Batch starten ───
  const startBatch = async () => {
    setPiStatus('starting'); setPiMsg('Job wird gestartet …'); setErr('')
    try {
      const r = await api.post(`/api/observations/${observationId}/process`, { mode: processMode }, { timeout: 30000 })
      setPiJobId(r.data.job_id)
      setPiStatus('running')
      const modeLabel = processMode === 'shell_sim' ? 'Shell-Simulation' : processMode === 'fastbatch' ? 'FastBatch' : 'WBPP'
      setPiMsg(`${modeLabel} gestartet — RAW-Dateien werden an den Mac-Agent übertragen …`)
      startPolling(r.data.job_id)
    } catch (e: any) {
      setPiStatus('error')
      const detail = e.response?.data?.detail || 'Batch konnte nicht gestartet werden.'
      setErr(detail)
      setPiMsg('')
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
          if (pollRef.current) clearInterval(pollRef.current)
          setPiStatus('polling')
          setPiMsg('Batch abgeschlossen — hole Ergebnisse vom Mac …')
          try {
            const poll = await api.post(`/api/observations/${observationId}/poll`, { job_id: jobId }, { timeout: 120000 })
            if (poll.data.status === 'vorbereitet') {
              setPiStatus('done')
              setPiResultCount(poll.data.result_count || 0)
              setPiMsg(
                poll.data.result_count > 0
                  ? `${poll.data.result_count} Ergebnis-Datei(en) ins Prepared-Verzeichnis geschrieben. Status → „vorbereitet".`
                  : 'Batch abgeschlossen, aber keine Ergebnis-Dateien gefunden.'
              )
              onChanged()
            } else if (poll.data.status === 'failed') {
              setPiStatus('error')
              setErr(poll.data.error || 'Batch fehlgeschlagen.')
            } else {
              setPiStatus('running')
              setPiMsg(`Job-Status: ${poll.data.status || 'unbekannt'}`)
            }
          } catch (e: any) {
            setPiStatus('error')
            setErr(e.response?.data?.detail || 'Ergebnisse konnten nicht abgeholt werden.')
          }
        } else if (st === 'failed') {
          if (pollRef.current) clearInterval(pollRef.current)
          setPiStatus('error')
          setErr(r.data.error || 'PixInsight-Batch fehlgeschlagen.')
        } else if (st === 'starting') {
          setPiMsg('RAW-Dateien werden gesammelt und an den Mac-Agent gesendet …')
        } else {
          // running / queued / sent
          const detail = r.data.input_files ? ` (${r.data.input_files} Dateien)` : ''
          setPiMsg(`PixInsight läuft … (${st}${detail})`)
        }
      } catch {
        // Netzwerkfehler — weiter pollen
      }
      if (pollCount > 360) {
        if (pollRef.current) clearInterval(pollRef.current)
        setPiStatus('error')
        setErr('Timeout: Batch nach 30 Minuten noch nicht fertig.')
      }
    }, 5000)
  }

  // ─── Manuelles Ergebnis abholen ───
  const pollNow = async () => {
    if (!piJobId) return
    setPiStatus('polling'); setErr('')
    try {
      const poll = await api.post(`/api/observations/${observationId}/poll`, { job_id: piJobId }, { timeout: 120000 })
      if (poll.data.status === 'vorbereitet') {
        setPiStatus('done')
        setPiResultCount(poll.data.result_count || 0)
        setPiMsg(`${poll.data.result_count || 0} Ergebnis-Datei(en) ins Prepared-Verzeichnis geschrieben.`)
        onChanged()
      } else if (poll.data.status === 'failed') {
        setPiStatus('error')
        setErr(poll.data.error || 'Batch fehlgeschlagen.')
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

  const fileRef = useRef<HTMLInputElement>(null)

  // ─── PixInsight-Sektion anzeigen? ───
  const showPiSection = status === 'raw' || status === 'in_bearbeitung' || status === 'vorbereitet' || piStatus !== 'idle'
  const canStartBatch = status === 'raw' && (piStatus === 'ready' || piStatus === 'prechecking')

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
              <Cpu className="h-4 w-4" /> PixInsight-Batch
            </div>

            {/* ─── Pre-Flight-Check Panel ─── */}
            {canStartBatch && (
              <div className="mt-3 space-y-3">
                {precheckLoading && (
                  <div className="flex items-center gap-2 text-sm text-slate-400">
                    <Loader2 className="h-4 w-4 animate-spin" /> Pre-Flight-Check läuft …
                  </div>
                )}

                {precheck && !precheckLoading && (
                  <>
                    {/* Frame-Zusammenfassung */}
                    <div className="rounded-lg border border-white/10 bg-black/30 p-3">
                      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-300">
                        <Layers className="h-3.5 w-3.5" /> Frames
                      </div>
                      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                        {([
                          { label: 'Lights', value: precheck.frame_counts.lights, icon: '💡', highlight: true },
                          { label: 'Darks', value: precheck.frame_counts.darks, icon: '🌑' },
                          { label: 'Flats', value: precheck.frame_counts.flats, icon: '🔲' },
                          { label: 'Bias', value: precheck.frame_counts.bias, icon: '⚡' },
                          { label: 'DarkFlats', value: precheck.frame_counts.darkflats, icon: '🌓' },
                          { label: 'Total', value: precheck.frame_counts.total, icon: '📊', highlight: true },
                        ]).map((f) => (
                          <div key={f.label} className={`rounded-lg border px-2 py-1.5 text-center ${f.highlight ? 'border-indigo-400/30 bg-indigo-500/10' : 'border-white/5 bg-white/5'}`}>
                            <div className="text-lg font-bold text-white">{f.value}</div>
                            <div className="text-[10px] text-slate-400">{f.icon} {f.label}</div>
                          </div>
                        ))}
                      </div>

                      {/* Filter-Aufschlüsselung */}
                      {precheck.frame_info?.filters?.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {precheck.frame_info.filters.map((f) => (
                            <span key={f.filter} className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] text-slate-300">
                              {f.filter}: {f.subs}× {f.exposures_s.length > 0 && `(${f.exposures_s.join('/')}s)`}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* Geschätzte Größe */}
                      {precheck.estimated_size_mb > 0 && (
                        <div className="mt-2 flex items-center gap-1.5 text-[11px] text-slate-500">
                          <HardDrive className="h-3 w-3" /> Geschätzte Übertragungsgröße: ~{precheck.estimated_size_mb} MB
                        </div>
                      )}
                    </div>

                    {/* Agent-Status */}
                    <div className="rounded-lg border border-white/10 bg-black/30 p-3">
                      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-300">
                        {precheck.agent.available ? <Wifi className="h-3.5 w-3.5 text-emerald-400" /> : <WifiOff className="h-3.5 w-3.5 text-red-400" />}
                        Mac-Agent
                      </div>
                      <div className="flex flex-wrap gap-2 text-[11px]">
                        <span className={`rounded-full px-2 py-0.5 ${precheck.agent.available ? 'bg-emerald-500/20 text-emerald-300' : 'bg-red-500/20 text-red-300'}`}>
                          {precheck.agent.available ? '✓ Erreichbar' : '✗ Nicht erreichbar'}
                        </span>
                        {precheck.agent.available && (
                          <>
                            <span className={`rounded-full px-2 py-0.5 ${precheck.agent.pixinsight_found ? 'bg-emerald-500/20 text-emerald-300' : 'bg-amber-500/20 text-amber-300'}`}>
                              {precheck.agent.pixinsight_found ? '✓ PixInsight' : '✗ PixInsight'}
                            </span>
                            {precheck.agent.wbpp_script_found && (
                              <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-emerald-300">✓ WBPP</span>
                            )}
                            {precheck.agent.fastbatch_script_found && (
                              <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-emerald-300">✓ FastBatch</span>
                            )}
                            {precheck.agent.shell_sim_available && (
                              <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-emerald-300">✓ Shell-Sim</span>
                            )}
                            {precheck.agent.active_jobs > 0 && (
                              <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-amber-300">
                                <Activity className="mr-1 inline h-3 w-3" />{precheck.agent.active_jobs} aktive Job(s)
                              </span>
                            )}
                          </>
                        )}
                      </div>
                    </div>

                    {/* Calibration-Directories */}
                    <div className="rounded-lg border border-white/10 bg-black/30 p-3">
                      <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-slate-300">
                        <Files className="h-3.5 w-3.5" /> Calibration-Frames (NAS-Pfade)
                      </div>
                      {precheck.calibration_dir.configured ? (
                        <div className="space-y-1">
                          {precheck.calibration_dir.flats_dir && (
                            <div className="text-[11px] text-emerald-300">
                              ✓ Flats: <span className="font-mono">{precheck.calibration_dir.flats_dir}</span>
                            </div>
                          )}
                          {precheck.calibration_dir.darks_dir && (
                            <div className="text-[11px] text-emerald-300">
                              ✓ Darks: <span className="font-mono">{precheck.calibration_dir.darks_dir}</span>
                            </div>
                          )}
                          {precheck.calibration_dir.bias_dir && (
                            <div className="text-[11px] text-emerald-300">
                              ✓ Bias: <span className="font-mono">{precheck.calibration_dir.bias_dir}</span>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="text-[11px] text-amber-300">
                          ⚠ Keine Calibration-Verzeichnisse für dieses Setup konfiguriert.
                          Flats/Darks/Bias müssen im ZIP enthalten sein oder manuell geladen werden.
                        </div>
                      )}
                    </div>

                    {/* Warnungen */}
                    {precheck.warnings.length > 0 && (
                      <div className="space-y-1.5">
                        {precheck.warnings.map((w, i) => (
                          <div key={i} className="flex items-start gap-2 rounded-lg border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {w.message}
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Errors */}
                    {precheck.errors.length > 0 && (
                      <div className="space-y-1.5">
                        {precheck.errors.map((e, i) => (
                          <div key={i} className="flex items-start gap-2 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {e.message}
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Processing-Modus-Auswahl + Start-Button */}
                    <div className="flex flex-wrap items-center gap-3 pt-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <label className="text-xs text-slate-400">Modus:</label>
                        <div className="flex gap-1.5">
                          {([
                            { v: 'shell_sim', label: 'Shell-Sim', title: 'Test-Modus — kein PixInsight nötig' },
                            { v: 'wbpp', label: 'WBPP', title: 'WeightedBatchPreProcessing — vollständig' },
                            { v: 'fastbatch', label: 'FastBatch', title: 'FastBatchProcessing — schneller' },
                          ] as { v: ProcessMode; label: string; title: string }[]).map((opt) => {
                            const disabled = opt.v !== 'shell_sim' && !precheck.agent.pixinsight_found
                            return (
                              <button
                                key={opt.v}
                                onClick={() => !disabled && setProcessMode(opt.v)}
                                title={opt.title}
                                disabled={disabled}
                                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                                  processMode === opt.v
                                    ? 'bg-indigo-500/30 text-indigo-200 ring-1 ring-indigo-400/50'
                                    : disabled
                                      ? 'border border-white/5 text-slate-600'
                                      : 'border border-white/10 text-slate-400 hover:bg-white/5'
                                }`}
                              >
                                {opt.label}
                              </button>
                            )
                          })}
                        </div>
                      </div>

                      <button
                        onClick={refreshPrecheck}
                        disabled={precheckLoading}
                        className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-slate-300 hover:bg-white/5 disabled:opacity-50"
                      >
                        <RefreshCw className={`h-3.5 w-3.5 ${precheckLoading ? 'animate-spin' : ''}`} /> Aktualisieren
                      </button>
                    </div>

                    {/* Start / Abbrechen */}
                    <div className="flex flex-wrap gap-2 pt-1">
                      <button
                        onClick={startBatch}
                        disabled={!precheck.can_start}
                        className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 px-4 py-2 text-sm font-medium text-white hover:from-indigo-400 hover:to-violet-500 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        <Zap className="h-4 w-4" /> Batch starten
                      </button>
                      {!precheck.can_start && (
                        <span className="self-center text-xs text-red-300">
                          Start blockiert — siehe Fehler oben
                        </span>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* Status-Anzeige während Batch */}
            {piStatus === 'starting' && (
              <div className="mt-2 flex items-center gap-2 text-sm text-blue-200">
                <Loader2 className="h-4 w-4 animate-spin" /> {piMsg || 'Sende RAW-Dateien an Mac-Agent …'}
              </div>
            )}
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
              <div className="mt-2 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                <AlertTriangle className="mr-1.5 inline h-4 w-4 shrink-0 align-text-bottom" /> {err}
              </div>
            )}

            {/* Buttons während/nach Batch */}
            <div className="mt-3 flex flex-wrap gap-2">
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
