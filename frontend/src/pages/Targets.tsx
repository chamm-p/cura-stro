import { useEffect, useState, useCallback } from 'react'
import { Loader2, MapPin, Calendar, Stars, ArrowUp, Clock, Check, Telescope as ScopeIcon, Cloud, Moon, AlertTriangle, Camera as CameraIcon, CalendarPlus, Crop, Info } from 'lucide-react'
import api from '../services/api'
import Layout from '../components/Layout'
import AltitudeCurve from '../components/AltitudeCurve'
import PlanetGlyph from '../components/PlanetGlyph'
import CalculatorModal from '../components/CalculatorModal'
import ObjectInfoModal from '../components/ObjectInfoModal'

interface Target {
  id: string; catalog: string; ident: string; name: string | null
  obj_type: string; broadband: boolean; magnitude: number | null; constellation: string | null
  size_major_arcmin: number | null; max_altitude: number | null; best_time_local: string | null
  azimuth_at_best: number | null; visible: boolean; altitude_track: number[]; photographed: boolean
  best_window_start: string | null; best_window_end: string | null; best_window_reason: string | null
  moon_separation_deg: number | null; moon_impact: string; moon_note: string | null
  status: string | null; rating: number | null
  capture_count: number; telescopes: string[]; preview_url: string
}

const STATUS_STYLE: Record<string, { cls: string; label: string }> = {
  geplant: { cls: 'bg-slate-500/80 text-white', label: 'geplant' },
  raw: { cls: 'bg-amber-500/80 text-white', label: 'RAW' },
  entwickelt: { cls: 'bg-emerald-500/85 text-white', label: 'entwickelt' },
}
interface Moon { illumination_pct: number; phase_name: string; up: boolean; max_altitude: number }
interface Weather {
  available: boolean; cloud_cover?: number; cloud_low?: number; cloud_mid?: number; cloud_high?: number
  precip_probability?: number; humidity?: number; wind?: number; verdict?: string; verdict_text?: string; note?: string
}
interface Loc { id: string; name: string }
interface Scope { id: string; name: string; limiting_magnitude: number | null; suggested_limiting_magnitude: number | null }
interface Resp {
  location: { id: string; name: string; bortle: number | null; timezone: string; seeing_available?: boolean }
  date: string; night_start: string; night_end: string
  time_grid: string[]; magnitude_limit: number | null; telescope: { name: string; limiting_magnitude: number | null } | null
  moon: Moon | null; weather: Weather | null
  count: number; targets: Target[]
}

const VERDICT_STYLE: Record<string, string> = {
  excellent: 'bg-emerald-500/20 text-emerald-200 border-emerald-400/30',
  good: 'bg-emerald-500/15 text-emerald-200 border-emerald-400/25',
  fair: 'bg-amber-500/20 text-amber-200 border-amber-400/30',
  bad: 'bg-red-500/20 text-red-200 border-red-400/30',
  unknown: 'bg-white/10 text-slate-300 border-white/15',
}

const TYPE_LABEL: Record<string, string> = {
  galaxy: 'Galaxie', open_cluster: 'Offener Sternhaufen', globular_cluster: 'Kugelsternhaufen',
  planetary_nebula: 'Planetarischer Nebel', emission_nebula: 'Emissionsnebel',
  reflection_nebula: 'Reflexionsnebel', supernova_remnant: 'Supernova-Überrest',
  cluster_nebulosity: 'Sternhaufen + Nebel', nebula: 'Nebel', planet: 'Planet',
}

const input = 'rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-indigo-400/60'

export default function Targets() {
  const [locs, setLocs] = useState<Loc[]>([])
  const [scopes, setScopes] = useState<Scope[]>([])
  const [locId, setLocId] = useState<string>('')
  const [scopeId, setScopeId] = useState<string>('')
  const [date, setDate] = useState<string>(() => new Date().toISOString().slice(0, 10))
  const [catalog, setCatalog] = useState('Messier')
  const [typeGroup, setTypeGroup] = useState('all')
  const [maxMag, setMaxMag] = useState('')
  const [minAlt, setMinAlt] = useState('30')
  const [sort, setSort] = useState('magnitude')
  const [data, setData] = useState<Resp | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [calcFor, setCalcFor] = useState<{ object: string; scopeId: string } | null>(null)
  const [infoFor, setInfoFor] = useState<string | null>(null)

  useEffect(() => {
    api.get('/api/locations').then((r) => setLocs(r.data))
    api.get('/api/equipment/telescopes').then((r) => {
      setScopes(r.data)
      // Immer mit einem Teleskop starten; letzte Wahl merken.
      const saved = localStorage.getItem('curastro-target-scope')
      const valid = r.data.find((s: Scope) => s.id === saved)
      setScopeId(valid ? saved! : r.data[0]?.id || '')
    })
  }, [])

  // Teleskop-Auswahl persistieren (nur echte Teleskope, nicht „ohne").
  useEffect(() => { if (scopeId) localStorage.setItem('curastro-target-scope', scopeId) }, [scopeId])

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try {
      const params: any = { date, catalog, type_group: typeGroup, min_altitude: minAlt, sort, visible_only: true }
      if (locId) params.location_id = locId
      if (scopeId) params.telescope_id = scopeId
      // Manuelle Magnitude nur senden, wenn KEIN Teleskop gewählt ist
      // (Teleskop liefert die Grenzgröße).
      if (maxMag && !scopeId) params.max_magnitude = maxMag
      const r = await api.get('/api/targets', { params })
      setData(r.data)
    } catch (e: any) {
      setErr(e.response?.data?.detail || 'Fehler beim Laden der Objektliste.')
      setData(null)
    } finally { setLoading(false) }
  }, [locId, scopeId, date, catalog, typeGroup, maxMag, minAlt, sort])

  useEffect(() => { load() }, [load])

  return (
    <Layout>
      <div className="flex items-center gap-2">
        <Stars className="h-6 w-6 text-indigo-300" />
        <h1 className="text-2xl font-bold">Objektliste</h1>
      </div>

      {/* Steuerung */}
      <div className="mt-5 flex flex-wrap items-end gap-3 rounded-2xl border border-white/10 bg-[#0c1024] p-4">
        <Ctl label="Standort" icon={MapPin}>
          <select className={input} value={locId} onChange={(e) => setLocId(e.target.value)}>
            <option value="">Standard</option>
            {locs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </Ctl>
        <Ctl label="Datum (Abend)" icon={Calendar}>
          <input type="date" className={input} value={date} onChange={(e) => setDate(e.target.value)} />
        </Ctl>
        <Ctl label="Teleskop" icon={ScopeIcon}>
          <select className={input} value={scopeId} onChange={(e) => setScopeId(e.target.value)}>
            <option value="">— ohne —</option>
            {scopes.map((s) => {
              const lim = s.limiting_magnitude ?? s.suggested_limiting_magnitude
              return <option key={s.id} value={s.id}>{s.name}{lim ? ` (≤ ${lim} mag)` : ''}</option>
            })}
          </select>
        </Ctl>
        <Ctl label="Typ">
          <select className={input} value={typeGroup} onChange={(e) => setTypeGroup(e.target.value)}>
            <option value="all">Alle</option>
            <option value="galaxy">Galaxien</option>
            <option value="cluster">Sternhaufen</option>
            <option value="nebula">Nebel</option>
            <option value="planet">Planeten</option>
          </select>
        </Ctl>
        <Ctl label="Katalog">
          <select className={input} value={catalog} onChange={(e) => setCatalog(e.target.value)}>
            <option value="all">Alle</option>
            <option value="Messier">Messier</option>
            <option value="NGC">NGC</option>
            <option value="IC">IC</option>
          </select>
        </Ctl>
        {!scopeId && (
          <Ctl label="max. Magnitude">
            <input className={`${input} w-24`} placeholder="z. B. 9" value={maxMag} onChange={(e) => setMaxMag(e.target.value)} />
          </Ctl>
        )}
        <Ctl label="min. Höhe °">
          <input className={`${input} w-20`} value={minAlt} onChange={(e) => setMinAlt(e.target.value)} />
        </Ctl>
        <Ctl label="Sortierung">
          <select className={input} value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="magnitude">Magnitude</option>
            <option value="altitude">Höhe</option>
          </select>
        </Ctl>
      </div>

      {data && <WeatherMoonBar weather={data.weather} moon={data.moon} />}
      {data?.location.seeing_available && <SeeingPanel locationId={data.location.id} />}

      {data && (
        <p className="mt-4 text-sm text-slate-400">
          <span className="text-slate-200">{data.count}</span> sichtbare Objekte für{' '}
          <span className="text-slate-200">{data.location.name}</span>
          {data.location.bortle ? ` (Bortle ${data.location.bortle})` : ''} · Nacht {data.night_start}–{data.night_end} · {data.date}
          {data.telescope ? (
            <span className="ml-1 text-slate-300">· {data.telescope.name}{data.magnitude_limit != null ? ` → ≤ ${data.magnitude_limit} mag` : ''}</span>
          ) : data.magnitude_limit != null ? (
            <span className="ml-1 text-slate-300">· ≤ {data.magnitude_limit} mag</span>
          ) : null}
        </p>
      )}
      {err && <div className="mt-4 rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{err}</div>}

      {loading ? (
        <div className="mt-16 flex flex-col items-center gap-3 text-slate-400">
          <Loader2 className="h-7 w-7 animate-spin" />
          <span className="text-sm">Berechne Sichtbarkeit …</span>
        </div>
      ) : (
        <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data?.targets.map((t) => (
            <Card key={t.id} t={t} grid={data.time_grid} minAlt={Number(minAlt)} scopeId={scopeId}
              onOpenCalc={() => setCalcFor({ object: t.ident, scopeId })}
              onOpenInfo={() => setInfoFor(t.ident)} />
          ))}
        </div>
      )}

      {calcFor && (
        <CalculatorModal object={calcFor.object} telescopeId={calcFor.scopeId || undefined} onClose={() => setCalcFor(null)} />
      )}
      {infoFor && <ObjectInfoModal ident={infoFor} onClose={() => setInfoFor(null)} />}
    </Layout>
  )
}

function SeeingPanel({ locationId }: { locationId: string }) {
  const [open, setOpen] = useState(false)
  const [src, setSrc] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const load = async (refresh = false) => {
    setLoading(true); setErr('')
    try {
      const r = await api.get('/api/seeing/image', {
        params: { location_id: locationId, refresh },
        responseType: 'blob',
      })
      setSrc((prev) => { if (prev) URL.revokeObjectURL(prev); return URL.createObjectURL(r.data) })
    } catch {
      setErr('Seeing-Vorschau konnte nicht geladen werden (Scraper/meteoblue nicht erreichbar).')
    } finally { setLoading(false) }
  }

  const toggle = () => {
    const next = !open
    setOpen(next)
    if (next && !src) load(false)
  }

  return (
    <div className="mt-3 rounded-xl border border-white/10 bg-[#0c1024]">
      <button onClick={toggle} className="flex w-full items-center justify-between px-4 py-2.5 text-sm text-slate-200">
        <span className="flex items-center gap-2"><Cloud className="h-4 w-4 text-indigo-300" /> meteoblue Seeing</span>
        <span className="text-xs text-slate-500">{open ? 'einklappen' : 'anzeigen'}</span>
      </button>
      {open && (
        <div className="border-t border-white/10 p-3">
          {loading && (
            <div className="flex items-center gap-2 py-6 text-sm text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" /> Lade Seeing von meteoblue … (erstmalig ~10 s)
            </div>
          )}
          {err && <div className="py-3 text-sm text-red-300">{err}</div>}
          {src && !loading && (
            <div className="space-y-2">
              <img src={src} alt="meteoblue Seeing" className="w-full rounded-lg border border-white/10" />
              <button onClick={() => load(true)} className="text-xs text-indigo-300 hover:underline">aktualisieren</button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function WeatherMoonBar({ weather, moon }: { weather: Weather | null; moon: Moon | null }) {
  const cloudBad = weather?.available && (weather.verdict === 'bad')
  const moonBright = moon?.up && moon.illumination_pct >= 50
  return (
    <div className="mt-4 space-y-3">
      <div className="flex flex-wrap gap-3">
        {weather?.available ? (
          <div className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-sm ${VERDICT_STYLE[weather.verdict || 'unknown']}`}>
            <Cloud className="h-4 w-4" />
            <span className="font-medium capitalize">{weather.verdict_text}</span>
            <span className="opacity-80">· {weather.cloud_cover}% Wolken</span>
            {weather.precip_probability ? <span className="opacity-80">· {weather.precip_probability}% Niederschlag</span> : null}
            {weather.wind != null ? <span className="opacity-70">· {weather.wind} km/h</span> : null}
          </div>
        ) : (
          <div className="flex items-center gap-2 rounded-xl border border-white/15 bg-white/10 px-3 py-2 text-sm text-slate-300">
            <Cloud className="h-4 w-4" /> {weather?.note || 'Keine Wetterdaten'}
          </div>
        )}
        {moon && (
          <div className="flex items-center gap-2 rounded-xl border border-white/15 bg-white/10 px-3 py-2 text-sm text-slate-200">
            <Moon className="h-4 w-4 text-slate-300" />
            <span className="font-medium">{moon.phase_name}</span>
            <span className="opacity-80">· {moon.illumination_pct}% beleuchtet</span>
            <span className="opacity-70">· {moon.up ? `bis ${moon.max_altitude}° hoch` : 'unter Horizont'}</span>
          </div>
        )}
      </div>
      {cloudBad && (
        <div className="flex items-center gap-2 rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          Heute Nacht vermutlich zu bewölkt — Aufnahmen werden schwierig.
        </div>
      )}
      {!cloudBad && moonBright && (
        <div className="flex items-center gap-2 rounded-xl border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
          <Moon className="h-4 w-4 shrink-0" />
          Heller Mond — Breitband (Galaxien, Sternhaufen) beeinträchtigt. Schmalband-Ziele (Emissionsnebel) bevorzugen.
        </div>
      )}
    </div>
  )
}

function Card({ t, grid, minAlt, scopeId, onOpenCalc, onOpenInfo }: { t: Target; grid: string[]; minAlt: number; scopeId: string; onOpenCalc: () => void; onOpenInfo: () => void }) {
  const best = t.best_time_local ? new Date(t.best_time_local).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' }) : '—'
  const [planned, setPlanned] = useState(false)
  const [planning, setPlanning] = useState(false)
  const plan = async (e: React.MouseEvent) => {
    e.preventDefault(); e.stopPropagation()
    setPlanning(true)
    try {
      const body: any = {}
      if (t.obj_type === 'planet') body.target_label = t.ident
      else body.catalog_object_id = t.id
      if (scopeId) body.telescope_id = scopeId
      await api.post('/api/observations/plan', body)
      setPlanned(true)
    } catch { /* ignore */ } finally { setPlanning(false) }
  }
  const clickable = t.obj_type !== 'planet'
  const outerProps: any = clickable
    ? { onClick: onOpenCalc, role: 'button', title: 'Framing & Belichtung berechnen',
        className: 'block cursor-pointer overflow-hidden rounded-2xl border border-white/10 bg-[#0c1024] transition hover:border-indigo-400/40' }
    : { className: 'block overflow-hidden rounded-2xl border border-white/10 bg-[#0c1024]' }
  return (
    <div {...outerProps}>
      <div className="relative aspect-video bg-black">
        {t.obj_type === 'planet' ? (
          <PlanetGlyph name={t.ident} />
        ) : (
          <img src={t.preview_url} alt={t.ident} loading="lazy" className="h-full w-full object-cover opacity-90" />
        )}
        <div className="absolute left-2 top-2 flex flex-wrap gap-1">
          <span className="rounded-md bg-black/60 px-2 py-0.5 text-xs font-medium text-white backdrop-blur">{t.ident}</span>
          {t.status && (
            <span
              className={`flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium backdrop-blur ${STATUS_STYLE[t.status]?.cls || 'bg-slate-500/80 text-white'}`}
              title={t.telescopes.length ? `Aufnahmen mit: ${t.telescopes.join(', ')}` : t.status}
            >
              {t.status === 'entwickelt' || t.status === 'raw' ? <Check className="h-3 w-3" /> : null}
              {STATUS_STYLE[t.status]?.label || t.status}
              {t.status === 'entwickelt' && t.rating ? ` · ${'★'.repeat(t.rating)}` : ''}
              {t.capture_count > 1 ? ` (${t.capture_count}×)` : ''}
            </span>
          )}
        </div>
        <span className={`absolute right-2 top-2 rounded-md px-2 py-0.5 text-[10px] font-medium backdrop-blur ${t.broadband ? 'bg-sky-500/70 text-white' : 'bg-fuchsia-500/70 text-white'}`}>
          {t.broadband ? 'Breitband' : 'Schmalband'}
        </span>
      </div>
      <div className="p-3">
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="truncate font-semibold">{t.name || t.ident}</h3>
          <span className="shrink-0 text-sm text-slate-400">{t.magnitude != null ? `${t.magnitude.toFixed(1)} mag` : '—'}</span>
        </div>
        <p className="text-xs text-slate-500">{TYPE_LABEL[t.obj_type] || t.obj_type}{t.constellation ? ` · ${t.constellation}` : ''}</p>
        <div className="mt-2 flex items-center gap-4 text-xs text-slate-400">
          <span className="flex items-center gap-1" title="maximale Höhe in der Nacht"><ArrowUp className="h-3.5 w-3.5 text-indigo-300" /> {t.max_altitude != null ? `${t.max_altitude.toFixed(0)}°` : '—'}</span>
          <span className="flex items-center gap-1" title="Zeitpunkt der größten Höhe"><Clock className="h-3.5 w-3.5 text-indigo-300" /> max {best}</span>
        </div>
        {t.best_window_start && (
          <div className="mt-1.5 flex items-center gap-1.5 rounded-md bg-indigo-500/15 px-2 py-1 text-[11px] text-indigo-100" title={t.best_window_reason || ''}>
            <CameraIcon className="h-3.5 w-3.5 shrink-0" />
            <span className="font-medium">{t.best_window_start}–{t.best_window_end}</span>
            {t.best_window_reason && <span className="text-indigo-300/80">· {t.best_window_reason}</span>}
          </div>
        )}
        {t.moon_impact !== 'none' && (
          <div
            className={`mt-2 flex items-start gap-1.5 rounded-md px-2 py-1 text-[11px] ${
              t.moon_impact === 'strong' ? 'bg-red-500/15 text-red-200' : 'bg-amber-500/15 text-amber-100'
            }`}
            title={t.moon_note || ''}
          >
            <Moon className="mt-0.5 h-3 w-3 shrink-0" />
            <span>{t.moon_note}</span>
          </div>
        )}
        <div className="mt-1.5">
          <AltitudeCurve track={t.altitude_track} labels={grid} minAltitude={minAlt} windowStart={t.best_window_start} windowEnd={t.best_window_end} />
        </div>
        <div className="mt-2 flex items-center gap-2">
          <button
            onClick={plan}
            disabled={planning || planned}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-white/10 px-2 py-1.5 text-xs font-medium text-slate-200 transition hover:bg-white/10 disabled:opacity-60"
          >
            {planned ? <><Check className="h-3.5 w-3.5 text-emerald-300" /> eingeplant</> : <><CalendarPlus className="h-3.5 w-3.5" /> einplanen</>}
          </button>
          {clickable && (
            <>
              <button
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); onOpenInfo() }}
                className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-white/10 px-2 py-1.5 text-xs font-medium text-slate-200 transition hover:bg-white/10"
              >
                <Info className="h-3.5 w-3.5" /> Info
              </button>
              <button
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); onOpenCalc() }}
                className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-indigo-400/30 bg-indigo-500/10 px-2 py-1.5 text-xs font-medium text-indigo-100 transition hover:bg-indigo-500/20"
              >
                <Crop className="h-3.5 w-3.5" /> Rechner
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function Ctl({ label, icon: Icon, children }: { label: string; icon?: any; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="flex items-center gap-1 text-[11px] font-medium text-slate-400">
        {Icon && <Icon className="h-3 w-3" />} {label}
      </span>
      {children}
    </label>
  )
}
