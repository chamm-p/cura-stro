import { useEffect, useState, useCallback } from 'react'
import { X, Cpu, Loader2, Zap, AlertTriangle, CheckCircle2, Layers } from 'lucide-react'
import api from '../services/api'

// Stapel-Verarbeitung: mehrere Aufnahmen mit demselben PixInsight-Script
// (Modus) und Agent nacheinander anstoßen. Der Reihenfolge-Ablauf selbst
// passiert im Backend (Transfer-Lock je Agent) + Agent (serielles Stacking) —
// hier werden die Jobs nur nacheinander getriggert.

type ProcessMode = 'wbpp' | 'fastbatch' | 'shell_sim'
interface Target { id: string; label: string; status: string }
interface Pre {
  lights: number; can_start: boolean; agent_ok: boolean; pi_found: boolean
  err: string | null; loading: boolean; started?: boolean; jobId?: string; startErr?: string
}

export default function BatchProcessModal({
  targets, onClose, onStarted,
}: {
  targets: Target[]; onClose: () => void; onStarted: () => void
}) {
  const [agents, setAgents] = useState<{ id: string; name: string }[]>([])
  const [agent, setAgent] = useState('1')
  const [mode, setMode] = useState<ProcessMode>('wbpp')
  const [pre, setPre] = useState<Record<string, Pre>>({})
  const [starting, setStarting] = useState(false)
  const [done, setDone] = useState(false)

  useEffect(() => {
    api.get('/api/pixinsight/agents').then((r) => setAgents(r.data.agents || [])).catch(() => {})
  }, [])
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape' && !starting) onClose() }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [onClose, starting])

  // Pre-Flight pro Aufnahme (beim Öffnen + Agent-Wechsel)
  const runPrechecks = useCallback(async () => {
    for (const t of targets) {
      setPre((p) => ({ ...p, [t.id]: { ...(p[t.id] || {} as Pre), loading: true } }))
      try {
        const r = await api.get(`/api/observations/${t.id}/precheck`, { params: { agent } })
        const d = r.data
        setPre((p) => ({ ...p, [t.id]: {
          lights: d.frame_counts?.lights ?? 0,
          can_start: !!d.can_start,
          agent_ok: !!d.agent?.available,
          pi_found: !!d.agent?.pixinsight_found,
          err: (d.errors && d.errors[0]?.message) || null,
          loading: false,
        } }))
      } catch {
        setPre((p) => ({ ...p, [t.id]: { lights: 0, can_start: false, agent_ok: false, pi_found: false, err: 'Precheck fehlgeschlagen', loading: false } }))
      }
    }
  }, [targets, agent])

  useEffect(() => { runPrechecks() }, [runPrechecks])

  // shell_sim braucht kein PixInsight; wbpp/fastbatch schon.
  const modeStartable = (t: Target) => {
    const p = pre[t.id]
    if (!p) return false
    if (mode === 'shell_sim') return p.agent_ok && p.lights > 0
    return p.can_start
  }
  const startable = targets.filter(modeStartable)

  const startAll = async () => {
    setStarting(true)
    for (const t of targets) {
      if (!modeStartable(t)) continue
      try {
        const r = await api.post(`/api/observations/${t.id}/process`, { mode, agent }, { timeout: 30000 })
        setPre((p) => ({ ...p, [t.id]: { ...p[t.id], started: true, jobId: r.data.job_id } }))
      } catch (e: any) {
        setPre((p) => ({ ...p, [t.id]: { ...p[t.id], startErr: e.response?.data?.detail || 'Start fehlgeschlagen' } }))
      }
    }
    setStarting(false)
    setDone(true)
    onStarted()
  }

  const modes: { v: ProcessMode; label: string; title: string }[] = [
    { v: 'wbpp', label: 'WBPP', title: 'WeightedBatchPreProcessing — vollständig' },
    { v: 'fastbatch', label: 'FastBatch', title: 'FastBatchProcessing — schneller' },
    { v: 'shell_sim', label: 'Shell-Sim', title: 'Test-Modus — kein PixInsight nötig' },
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => !starting && onClose()}>
      <div className="max-h-[88vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-white/10 bg-[#0a0c18] p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold"><Cpu className="h-5 w-5 text-indigo-300" /> Stapel-Verarbeitung · {targets.length} Objekte</h2>
          <button onClick={() => !starting && onClose()} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10"><X className="h-5 w-5" /></button>
        </div>

        {/* Agent + Modus */}
        <div className="mb-4 flex flex-wrap items-center gap-4 rounded-xl border border-white/10 bg-white/[0.03] p-3">
          {agents.length > 1 && (
            <div className="flex items-center gap-2">
              <label className="text-xs text-slate-400">Rechner:</label>
              <div className="flex gap-1.5">
                {agents.map((a) => (
                  <button key={a.id} onClick={() => setAgent(a.id)} disabled={starting}
                    className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${agent === a.id ? 'bg-indigo-500/30 text-indigo-200 ring-1 ring-indigo-400/50' : 'border border-white/10 text-slate-400 hover:bg-white/5'}`}>
                    {a.name}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-400">Script:</label>
            <div className="flex gap-1.5">
              {modes.map((m) => (
                <button key={m.v} onClick={() => setMode(m.v)} title={m.title} disabled={starting}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${mode === m.v ? 'bg-indigo-500/30 text-indigo-200 ring-1 ring-indigo-400/50' : 'border border-white/10 text-slate-400 hover:bg-white/5'}`}>
                  {m.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Objektliste mit Precheck-Status */}
        <div className="space-y-1.5">
          {targets.map((t) => {
            const p = pre[t.id]
            const ok = modeStartable(t)
            return (
              <div key={t.id} className={`flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
                p?.started ? 'border-emerald-400/40 bg-emerald-500/5' : ok ? 'border-white/10 bg-white/[0.03]' : 'border-amber-400/20 bg-amber-500/5'
              }`}>
                <span className="font-medium text-slate-200">{t.label}</span>
                {p?.loading ? (
                  <span className="flex items-center gap-1 text-xs text-slate-500"><Loader2 className="h-3 w-3 animate-spin" /> prüfe …</span>
                ) : p ? (
                  <>
                    <span className="flex items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 text-[11px] text-slate-300"><Layers className="h-3 w-3" /> {p.lights} Lights</span>
                    {p.started ? (
                      <span className="flex items-center gap-1 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[11px] text-emerald-300"><CheckCircle2 className="h-3 w-3" /> gestartet</span>
                    ) : p.startErr ? (
                      <span className="flex items-center gap-1 rounded-full bg-red-500/20 px-2 py-0.5 text-[11px] text-red-300"><AlertTriangle className="h-3 w-3" /> {p.startErr}</span>
                    ) : ok ? (
                      <span className="rounded-full bg-indigo-500/15 px-2 py-0.5 text-[11px] text-indigo-200">bereit</span>
                    ) : (
                      <span className="flex items-center gap-1 text-[11px] text-amber-300" title={p.err || ''}><AlertTriangle className="h-3 w-3" /> {p.err || (mode !== 'shell_sim' && !p.pi_found ? 'PixInsight nicht gefunden' : 'nicht startbar')}</span>
                    )}
                  </>
                ) : null}
              </div>
            )
          })}
        </div>

        {/* Aktionen */}
        <div className="mt-5 flex flex-wrap items-center gap-3">
          {!done ? (
            <button onClick={startAll} disabled={starting || startable.length === 0}
              className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 px-4 py-2 text-sm font-medium text-white hover:from-indigo-400 hover:to-violet-500 disabled:cursor-not-allowed disabled:opacity-40">
              {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
              {startable.length} Objekt(e) verarbeiten
            </button>
          ) : (
            <button onClick={onClose} className="rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 px-4 py-2 text-sm font-medium text-white hover:from-indigo-400 hover:to-violet-500">
              Schließen
            </button>
          )}
          {startable.length < targets.length && !done && (
            <span className="text-xs text-amber-300">{targets.length - startable.length} Objekt(e) werden übersprungen (siehe oben).</span>
          )}
        </div>
        <p className="mt-2 text-[11px] text-slate-500">
          Die Jobs laufen der Reihe nach: pro Rechner überträgt immer nur einer, PixInsight stackt seriell. Du kannst das Fenster schließen — der Fortschritt steht in der Warteschlange oben.
        </p>
      </div>
    </div>
  )
}
