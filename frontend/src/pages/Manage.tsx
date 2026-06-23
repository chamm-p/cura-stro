import { useEffect, useState, useCallback, useMemo } from 'react'
import { ListChecks, Trash2, Plus, Loader2, Image as ImageIcon, ChevronUp, ChevronDown, StickyNote, X, Layers, Radio, AlertTriangle } from 'lucide-react'
import api from '../services/api'
import Layout from '../components/Layout'
import SubsModal from '../components/SubsModal'
import ResultsModal from '../components/ResultsModal'
import AsiairImportModal from '../components/AsiairImportModal'

interface Obs {
  id: string; catalog_object_id: string | null
  object_ident: string | null; object_name: string | null; object_type: string | null; object_catalog: string | null
  target_label: string | null; display_label: string; status: string
  telescope_id: string | null; telescope_name: string | null; planned_date: string | null
  rating: number | null; notes: string | null; is_new: boolean; image_count: number
  subframe_count: number; integration_s: number; result_count: number
}
interface Scope { id: string; name: string }

const STATUS = [
  { v: 'geplant', label: 'geplant', cls: 'bg-slate-500/20 text-slate-200' },
  { v: 'raw', label: 'RAW', cls: 'bg-amber-500/20 text-amber-200' },
  { v: 'entwickelt', label: 'entwickelt', cls: 'bg-emerald-500/20 text-emerald-200' },
]
const TYPE_LABEL: Record<string, string> = {
  galaxy: 'Galaxie', open_cluster: 'Offener Haufen', globular_cluster: 'Kugelhaufen',
  planetary_nebula: 'Planet. Nebel', emission_nebula: 'Emissionsnebel', reflection_nebula: 'Reflexionsnebel',
  supernova_remnant: 'SNR', cluster_nebulosity: 'Haufen+Nebel', nebula: 'Nebel', planet: 'Planet',
}
const input = 'rounded-lg border border-white/10 bg-black/30 px-2.5 py-1.5 text-sm text-white outline-none focus:border-indigo-400/60'

function fmtInteg(s: number) {
  if (!s) return ''
  const h = Math.floor(s / 3600); const m = Math.round((s % 3600) / 60)
  return h > 0 ? `${h}h${m > 0 ? ` ${m}m` : ''}` : `${m}m`
}

export default function Manage() {
  const [rows, setRows] = useState<Obs[]>([])
  const [scopes, setScopes] = useState<Scope[]>([])
  const [loading, setLoading] = useState(true)
  const [newLabel, setNewLabel] = useState('')
  const [resFor, setResFor] = useState<Obs | null>(null)
  const [subsFor, setSubsFor] = useState<Obs | null>(null)
  const [notesFor, setNotesFor] = useState<Obs | null>(null)
  const [deleteFor, setDeleteFor] = useState<Obs | null>(null)
  const [asiairOpen, setAsiairOpen] = useState(false)
  const [sortField, setSortField] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const RANK: Record<string, number> = { geplant: 1, raw: 2, entwickelt: 3 }
  const sortVal = (r: Obs, f: string): number | string => {
    if (f === 'status') return RANK[r.status] ?? 0
    if (f === 'rating') return r.rating ?? -1
    return (r.object_ident || r.target_label || '').toLowerCase()
  }
  const sorted = useMemo(() => {
    // Ohne aktive Sortierung: neue (frisch eingeplante) Einträge nach oben.
    if (!sortField) return [...rows].sort((a, b) => Number(b.is_new) - Number(a.is_new))
    const arr = [...rows]
    arr.sort((a, b) => {
      const va = sortVal(a, sortField), vb = sortVal(b, sortField)
      const c = va < vb ? -1 : va > vb ? 1 : 0
      return sortDir === 'asc' ? c : -c
    })
    return arr
  }, [rows, sortField, sortDir])
  const newCount = rows.filter((r) => r.is_new).length

  const toggleSort = (f: string) => {
    if (sortField === f) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortField(f); setSortDir(f === 'object' ? 'asc' : 'desc') }
  }

  const load = useCallback(() => {
    api.get('/api/observations').then((r) => setRows(r.data)).finally(() => setLoading(false))
  }, [])
  useEffect(() => {
    load()
    api.get('/api/equipment/telescopes').then((r) => setScopes(r.data))
  }, [load])

  const patch = async (id: string, data: any) => {
    await api.patch(`/api/observations/${id}`, data)
    load()
  }
  const del = async (id: string) => { await api.delete(`/api/observations/${id}`); load() }
  const addManual = async () => {
    if (!newLabel.trim()) return
    await api.post('/api/observations', { target_label: newLabel.trim(), status: 'geplant' })
    setNewLabel(''); load()
  }

  const counts = STATUS.map((s) => ({ ...s, n: rows.filter((r) => r.status === s.v).length }))

  return (
    <Layout wide>
      <div className="flex items-center gap-2">
        <ListChecks className="h-6 w-6 text-indigo-300" />
        <h1 className="text-2xl font-bold">Verwaltung</h1>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        {newCount > 0 && <span className="rounded-full bg-green-500/25 px-2.5 py-1 text-green-100">neu: {newCount}</span>}
        {counts.map((c) => (
          <span key={c.v} className={`rounded-full px-2.5 py-1 ${c.cls}`}>{c.label}: {c.n}</span>
        ))}
      </div>

      <div className="mt-5 flex gap-2">
        <input className={`${input} flex-1`} placeholder="Eigenes Ziel planen, z. B. Mosaik Cygnus …" value={newLabel}
          onChange={(e) => setNewLabel(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addManual()} />
        <button onClick={addManual} className="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 px-3.5 py-2 text-sm font-medium text-white hover:from-indigo-400 hover:to-violet-500">
          <Plus className="h-4 w-4" /> Planen
        </button>
        <button onClick={() => setAsiairOpen(true)} className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3.5 py-2 text-sm text-slate-200 hover:bg-white/10" title="Subs direkt von der ASIAir importieren">
          <Radio className="h-4 w-4" /> Von ASIAir
        </button>
      </div>

      {loading ? (
        <div className="mt-10 flex justify-center"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>
      ) : rows.length === 0 ? (
        <p className="mt-10 text-sm text-slate-500">Noch keine Aufnahmen. Plane Objekte aus der Objektliste („einplanen") oder oben manuell.</p>
      ) : (
        <div className="mt-5 overflow-x-auto rounded-2xl border border-white/10 bg-[#0c1024]">
          <table className="w-full text-sm">
            <thead className="bg-[#0c1024] text-left text-xs text-slate-400">
              <tr>
                <SortTh label="Objekt" field="object" active={sortField} dir={sortDir} onClick={toggleSort} />
                <th className="px-3 py-2.5">Typ</th>
                <SortTh label="Status" field="status" active={sortField} dir={sortDir} onClick={toggleSort} />
                <th className="px-3 py-2.5">Teleskop</th>
                <th className="px-3 py-2.5">Subs</th>
                <th className="px-3 py-2.5">Datum</th>
                <SortTh label="Bewertung" field="rating" active={sortField} dir={sortDir} onClick={toggleSort} />
                <th className="px-3 py-2.5">Ergebnis</th>
                <th className="px-3 py-2.5">Notiz</th>
                <th className="px-3 py-2.5"></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr key={r.id} className={`border-t border-white/5 hover:bg-white/[0.03] ${r.is_new ? 'bg-green-500/10' : ''}`}>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{r.object_ident || r.target_label}</span>
                      {r.is_new && (
                        <button onClick={() => patch(r.id, {})} title="Als gesehen markieren"
                          className="rounded bg-green-500/30 px-1.5 py-0.5 text-[10px] font-semibold text-green-100 hover:bg-green-500/50">
                          NEU ✓
                        </button>
                      )}
                    </div>
                    {r.object_name && <div className="text-xs text-slate-500">{r.object_name}</div>}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-400">{r.object_type ? (TYPE_LABEL[r.object_type] || r.object_type) : '—'}</td>
                  <td className="px-3 py-2">
                    <select className={input} value={r.status} onChange={(e) => patch(r.id, { status: e.target.value })}>
                      {STATUS.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <select className={input} value={r.telescope_id || ''} onChange={(e) => patch(r.id, { telescope_id: e.target.value || null })}>
                      <option value="">—</option>
                      {scopes.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <button onClick={() => setSubsFor(r)} title="Subs einsortieren / ansehen"
                      className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-slate-200 hover:bg-white/10">
                      <Layers className="h-3.5 w-3.5" />
                      {r.subframe_count > 0 ? `${r.subframe_count} · ${fmtInteg(r.integration_s)}` : 'Subs'}
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    <input type="date" className={input} value={r.planned_date || ''} onChange={(e) => patch(r.id, { planned_date: e.target.value || null })} />
                  </td>
                  <td className="px-3 py-2">
                    <select className={input} value={r.rating ?? ''} onChange={(e) => patch(r.id, { rating: e.target.value ? Number(e.target.value) : null })}>
                      <option value="">—</option>
                      {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{'★'.repeat(n)}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <button onClick={() => setResFor(r)} title="PixInsight-Ergebnis" className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-slate-200 hover:bg-white/10">
                      <ImageIcon className="h-3.5 w-3.5" /> {r.result_count > 0 ? r.result_count : 'Ergebnis'}
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    <button onClick={() => setNotesFor(r)}
                      title={r.notes || 'Notiz hinzufügen'}
                      className={`flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs transition hover:bg-white/10 ${r.notes ? 'text-slate-200' : 'text-slate-600'}`}>
                      <StickyNote className="h-3.5 w-3.5" />
                      Notiz
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    <button onClick={() => setDeleteFor(r)} title="Aufnahme löschen" className="rounded-lg p-1.5 text-slate-400 hover:bg-red-500/20 hover:text-red-300"><Trash2 className="h-4 w-4" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {resFor && (
        <ResultsModal
          observationId={resFor.id}
          label={resFor.display_label}
          telescopeName={resFor.telescope_name}
          onClose={() => setResFor(null)}
          onChanged={load}
        />
      )}
      {subsFor && (
        <SubsModal
          observationId={subsFor.id}
          label={subsFor.display_label}
          telescopeName={subsFor.telescope_name}
          onClose={() => setSubsFor(null)}
          onChanged={load}
        />
      )}
      {asiairOpen && <AsiairImportModal onClose={() => setAsiairOpen(false)} onImported={load} />}
      {deleteFor && (
        <DeleteModal
          obs={deleteFor}
          onClose={() => setDeleteFor(null)}
          onConfirm={async () => { await del(deleteFor.id); setDeleteFor(null) }}
        />
      )}
      {notesFor && (
        <NotesModal
          obs={notesFor}
          onClose={() => setNotesFor(null)}
          onSave={async (text) => { await patch(notesFor.id, { notes: text }); setNotesFor(null) }}
        />
      )}
    </Layout>
  )
}

function NotesModal({ obs, onClose, onSave }: { obs: Obs; onClose: () => void; onSave: (text: string) => void }) {
  const [text, setText] = useState(obs.notes || '')
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#0a0c18] p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">Notiz · {obs.display_label}</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10"><X className="h-5 w-5" /></button>
        </div>
        <textarea
          autoFocus
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={8}
          placeholder="z. B. Guiding lief unruhig, Filter Ha bei dünnen Wolken, nochmal R nachlegen …"
          className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white outline-none focus:border-indigo-400/60"
        />
        <div className="mt-3 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-300 hover:bg-white/10">Abbrechen</button>
          <button onClick={() => onSave(text)} className="rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 px-4 py-2 text-sm font-medium text-white hover:from-indigo-400 hover:to-violet-500">Speichern</button>
        </div>
      </div>
    </div>
  )
}

function DeleteModal({ obs, onClose, onConfirm }: { obs: Obs; onClose: () => void; onConfirm: () => void }) {
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [onClose])
  const subs = obs.subframe_count || 0
  const imgs = obs.image_count || 0
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-2xl border border-red-400/30 bg-[#0a0c18] p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <h2 className="flex items-center gap-2 font-semibold text-red-200"><AlertTriangle className="h-5 w-5" /> Aufnahme löschen?</h2>
        <p className="mt-3 text-sm text-slate-300">
          <span className="font-medium text-white">{obs.object_ident || obs.target_label || obs.display_label}</span>
          {obs.telescope_name ? <span className="text-slate-400"> · {obs.telescope_name}</span> : null}
        </p>
        <div className="mt-3 rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-100">
          Das löscht die Aufnahme <strong>unwiderruflich</strong> — inklusive:
          <ul className="mt-1.5 list-disc pl-5 text-red-100/90">
            <li><strong>{subs}</strong> hochgeladene{subs === 1 ? 'r' : ''} Sub{subs === 1 ? '' : 's'}{obs.integration_s ? ` (${fmtInteg(obs.integration_s)})` : ''} aus dem <strong>Archiv</strong></li>
            {imgs > 0 && <li><strong>{imgs}</strong> Ergebnis-Bild{imgs === 1 ? '' : 'er'}</li>}
            <li>alle zugehörigen Daten in der App</li>
          </ul>
          <p className="mt-2 text-xs text-red-200/80">Hinweis: Auf der ASIAir wird nichts angefasst — nur das Archiv (NAS/lokal).</p>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-300 hover:bg-white/10">Abbrechen</button>
          <button onClick={async () => { setBusy(true); try { await onConfirm() } finally { setBusy(false) } }} disabled={busy}
            className="flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-50">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />} Endgültig löschen
          </button>
        </div>
      </div>
    </div>
  )
}

function SortTh({ label, field, active, dir, onClick }: { label: string; field: string; active: string | null; dir: 'asc' | 'desc'; onClick: (f: string) => void }) {
  const on = active === field
  return (
    <th className="px-3 py-2.5">
      <button onClick={() => onClick(field)} className={`flex items-center gap-1 transition hover:text-slate-200 ${on ? 'text-slate-200' : ''}`}>
        {label}
        {on && (dir === 'asc' ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />)}
      </button>
    </th>
  )
}
