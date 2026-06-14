import { useEffect, useState } from 'react'
import {
  MapPin, Crosshair, Search, Trash2, Plus, Star, Telescope, Camera as CamIcon,
  Filter as FilterIcon, Loader2, Save, Pencil, Server, Copy, RefreshCw, Check,
} from 'lucide-react'
import api from '../services/api'
import Layout from '../components/Layout'

// ─── Typen ───
interface Location {
  id: string; name: string; latitude: number; longitude: number
  elevation_m?: number | null; timezone?: string | null; bortle?: number | null
  meteoblue_url?: string | null; is_default: boolean
}
interface Scope { id: string; name: string; aperture_mm?: number | null; focal_length_mm?: number | null; focal_ratio?: number | null; limiting_magnitude?: number | null; suggested_limiting_magnitude?: number | null; notes?: string | null }
interface Cam { id: string; name: string; pixel_size_um?: number | null; res_x?: number | null; res_y?: number | null; sensor_type: string }
interface Filt { id: string; name: string; kind: string; bandwidth_nm?: number | null }
interface SetupT { id: string; name: string; telescope_id: string; camera_id: string; telescope_name: string; camera_name: string; filters: { id: string; name: string; kind: string }[] }
interface AppSettings { night_start: string; night_end: string; default_location_id?: string | null }

const inputCls = 'w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-500/20'
const btnPrimary = 'flex items-center justify-center gap-1.5 rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 px-3.5 py-2 text-sm font-medium text-white transition hover:from-indigo-400 hover:to-violet-500 disabled:opacity-40'
const btnGhost = 'flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-sm text-slate-300 transition hover:bg-white/10'
const card = 'rounded-2xl border border-white/10 bg-[#0c1024] p-5'

const TABS = [
  { id: 'locations', label: 'Standorte', icon: MapPin },
  { id: 'equipment', label: 'Equipment', icon: Telescope },
  { id: 'general', label: 'Allgemein', icon: Star },
  { id: 'mcp', label: 'MCP', icon: Server },
] as const

export default function Settings() {
  const [tab, setTab] = useState<(typeof TABS)[number]['id']>('locations')
  return (
    <Layout>
      <h1 className="text-2xl font-bold">Einstellungen</h1>
      <div className="mt-6 flex gap-1 border-b border-white/10">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm transition ${
              tab === t.id ? 'border-b-2 border-indigo-400 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <t.icon className="h-4 w-4" /> {t.label}
          </button>
        ))}
      </div>
      <div className="mt-6">
        {tab === 'locations' && <LocationsTab />}
        {tab === 'equipment' && <EquipmentTab />}
        {tab === 'general' && <GeneralTab />}
        {tab === 'mcp' && <McpTab />}
      </div>
    </Layout>
  )
}

// ─── Standorte ───
function LocationsTab() {
  const [items, setItems] = useState<Location[]>([])
  const [loading, setLoading] = useState(true)
  const [locating, setLocating] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<any[]>([])
  const [form, setForm] = useState<Partial<Location>>({ name: '', bortle: 5, is_default: false })

  const load = () => api.get('/api/locations').then((r) => setItems(r.data)).finally(() => setLoading(false))
  useEffect(() => { load() }, [])

  const useCurrentPosition = () => {
    setLocating(true)
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const { latitude, longitude } = pos.coords
        // Koordinaten sofort setzen, damit nichts verloren geht.
        setForm((f) => ({ ...f, latitude, longitude, timezone: tz }))
        // Ortsnamen + Höhe ermitteln; bei Fehler einmal kurz erneut versuchen
        // (Nominatim drosselt auf ~1 Anfrage/s und antwortet sonst gern mal nicht).
        const resolve = async () => {
          try {
            const r = await api.get('/api/geocode/reverse', { params: { lat: latitude, lon: longitude } })
            return r.data as { name?: string; elevation_m?: number | null }
          } catch {
            return null
          }
        }
        let data = await resolve()
        if (!data) {
          await new Promise((res) => setTimeout(res, 1100))
          data = await resolve()
        }
        setForm((f) => ({
          ...f,
          name: data?.name || f.name || `Standort ${latitude.toFixed(3)}, ${longitude.toFixed(3)}`,
          elevation_m: data?.elevation_m ?? f.elevation_m,
        }))
        setLocating(false)
      },
      () => { setLocating(false); alert('Standort konnte nicht ermittelt werden (Berechtigung?).') },
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  const doSearch = async () => {
    if (query.length < 2) return
    const r = await api.get('/api/geocode/search', { params: { q: query } })
    setResults(r.data)
  }

  const save = async () => {
    if (!form.name || form.latitude == null || form.longitude == null) {
      alert('Bitte Name und Koordinaten angeben (oder Auto-Ortung nutzen).')
      return
    }
    const payload = { ...form, timezone: form.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone }
    if (form.id) await api.patch(`/api/locations/${form.id}`, payload)
    else await api.post('/api/locations', payload)
    setForm({ name: '', bortle: 5, is_default: false })
    setResults([])
    setQuery('')
    load()
  }

  const del = async (id: string) => { await api.delete(`/api/locations/${id}`); load() }

  return (
    <div className="space-y-6">
      <div className={card}>
        <h3 className="mb-4 font-semibold">{form.id ? 'Standort bearbeiten' : 'Neuer Standort'}</h3>
        <div className="flex flex-wrap gap-2">
          <button onClick={useCurrentPosition} disabled={locating} className={btnGhost}>
            {locating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Crosshair className="h-4 w-4" />}
            Aktuellen Standort verwenden
          </button>
          <div className="flex flex-1 items-center gap-2">
            <input
              className={inputCls}
              placeholder="Ort suchen (z. B. Herrliberg)…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && doSearch()}
            />
            <button onClick={doSearch} className={btnGhost}><Search className="h-4 w-4" /></button>
          </div>
        </div>
        {results.length > 0 && (
          <div className="mt-2 space-y-1 rounded-lg border border-white/10 bg-black/30 p-2">
            {results.map((res, i) => (
              <button
                key={i}
                onClick={() => {
                  setForm((f) => ({ ...f, name: res.name, latitude: res.latitude, longitude: res.longitude, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }))
                  setResults([])
                }}
                className="block w-full truncate rounded px-2 py-1.5 text-left text-sm text-slate-300 hover:bg-white/10"
              >
                {res.display_name}
              </button>
            ))}
          </div>
        )}

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Name"><input className={inputCls} value={form.name || ''} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Bortle (1 dunkel – 9 Stadt)">
            <select className={inputCls} value={form.bortle ?? 5} onChange={(e) => setForm({ ...form, bortle: Number(e.target.value) })}>
              {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
          </Field>
          <Field label="Breite (°)"><input type="number" step="any" className={inputCls} value={form.latitude ?? ''} onChange={(e) => setForm({ ...form, latitude: parseFloat(e.target.value) })} /></Field>
          <Field label="Länge (°)"><input type="number" step="any" className={inputCls} value={form.longitude ?? ''} onChange={(e) => setForm({ ...form, longitude: parseFloat(e.target.value) })} /></Field>
        </div>
        <div className="mt-3">
          <Field label="meteoblue Seeing-URL (optional)">
            <input
              className={inputCls}
              placeholder="https://www.meteoblue.com/de/wetter/outdoorsports/seeing/…"
              value={form.meteoblue_url || ''}
              onChange={(e) => setForm({ ...form, meteoblue_url: e.target.value })}
            />
          </Field>
          <p className="mt-1 text-[11px] text-slate-500">Link zur meteoblue-Seeing-Seite dieses Orts — wird in der Objektliste als Seeing-Vorschau eingebunden.</p>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={!!form.is_default} onChange={(e) => setForm({ ...form, is_default: e.target.checked })} />
          Als Standard-Standort verwenden
        </label>
        <div className="mt-4 flex gap-2">
          <button onClick={save} className={btnPrimary}><Save className="h-4 w-4" /> Speichern</button>
          {form.id && <button onClick={() => setForm({ name: '', bortle: 5, is_default: false })} className={btnGhost}>Abbrechen</button>}
        </div>
      </div>

      <div className="space-y-2">
        {loading ? <Loader2 className="h-5 w-5 animate-spin text-slate-400" /> : items.length === 0 ? (
          <p className="text-sm text-slate-500">Noch keine Standorte. Lege oben einen an.</p>
        ) : items.map((l) => (
          <div key={l.id} className="flex items-center justify-between rounded-xl border border-white/10 bg-[#0c1024] px-4 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium">{l.name}</span>
                {l.is_default && <span className="flex items-center gap-1 rounded-full bg-indigo-500/20 px-2 py-0.5 text-[10px] text-indigo-200"><Star className="h-3 w-3" /> Standard</span>}
                <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-slate-300">Bortle {l.bortle ?? '–'}</span>
              </div>
              <div className="mt-0.5 text-xs text-slate-500">
                {l.latitude.toFixed(4)}°, {l.longitude.toFixed(4)}°{l.elevation_m != null ? ` · ${Math.round(l.elevation_m)} m` : ''}{l.timezone ? ` · ${l.timezone}` : ''}
              </div>
            </div>
            <div className="flex gap-1">
              <button onClick={() => setForm(l)} className="rounded-lg p-2 text-slate-400 hover:bg-white/10 hover:text-white"><Pencil className="h-4 w-4" /></button>
              <button onClick={() => del(l.id)} className="rounded-lg p-2 text-slate-400 hover:bg-red-500/20 hover:text-red-300"><Trash2 className="h-4 w-4" /></button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Equipment ───
function EquipmentTab() {
  const [scopes, setScopes] = useState<Scope[]>([])
  const [cams, setCams] = useState<Cam[]>([])
  const [filts, setFilts] = useState<Filt[]>([])
  const [setups, setSetups] = useState<SetupT[]>([])
  const [setupForm, setSetupForm] = useState<{ telescope_id: string; camera_id: string }>({ telescope_id: '', camera_id: '' })

  const loadAll = () => {
    api.get('/api/equipment/telescopes').then((r) => setScopes(r.data))
    api.get('/api/equipment/cameras').then((r) => setCams(r.data))
    api.get('/api/equipment/filters').then((r) => setFilts(r.data))
    api.get('/api/equipment/setups').then((r) => setSetups(r.data))
  }
  useEffect(() => { loadAll() }, [])

  const addSetup = async () => {
    if (!setupForm.telescope_id || !setupForm.camera_id) return
    await api.post('/api/equipment/setups', setupForm)
    setSetupForm({ telescope_id: '', camera_id: '' }); loadAll()
  }

  // Teleskop-Formular
  const [sf, setSf] = useState<{ name: string; aperture_mm?: string; focal_length_mm?: string }>({ name: '' })
  const addScope = async () => {
    if (!sf.name) return
    await api.post('/api/equipment/telescopes', {
      name: sf.name,
      aperture_mm: sf.aperture_mm ? Number(sf.aperture_mm) : null,
      focal_length_mm: sf.focal_length_mm ? Number(sf.focal_length_mm) : null,
    })
    setSf({ name: '' }); loadAll()
  }

  // Kamera-Formular
  const [cf, setCf] = useState<{ name: string; pixel_size_um?: string; res_x?: string; res_y?: string; sensor_type: string }>({ name: '', sensor_type: 'color' })
  const addCam = async () => {
    if (!cf.name) return
    await api.post('/api/equipment/cameras', {
      name: cf.name,
      pixel_size_um: cf.pixel_size_um ? Number(cf.pixel_size_um) : null,
      res_x: cf.res_x ? Number(cf.res_x) : null,
      res_y: cf.res_y ? Number(cf.res_y) : null,
      sensor_type: cf.sensor_type,
    })
    setCf({ name: '', sensor_type: 'color' }); loadAll()
  }

  // Filter-Formular
  const [ff, setFf] = useState<{ name: string; kind: string; bandwidth_nm?: string }>({ name: '', kind: 'broadband' })
  const addFilt = async () => {
    if (!ff.name) return
    await api.post('/api/equipment/filters', {
      name: ff.name,
      kind: ff.kind,
      bandwidth_nm: ff.kind === 'narrowband' && ff.bandwidth_nm ? Number(ff.bandwidth_nm) : null,
    })
    setFf({ name: '', kind: 'broadband' }); loadAll()
  }
  const setBandwidth = async (f: Filt, nm: string) => {
    await api.patch(`/api/equipment/filters/${f.id}`, {
      name: f.name, kind: f.kind, bandwidth_nm: nm ? Number(nm) : null,
    })
    loadAll()
  }

  return (
    <div className="space-y-6">
      {/* Teleskope */}
      <div className={card}>
        <h3 className="mb-3 flex items-center gap-2 font-semibold"><Telescope className="h-4.5 w-4.5 text-indigo-300" /> Teleskope</h3>
        <div className="space-y-2">
          {scopes.map((s) => <ScopeRow key={s.id} s={s} reload={loadAll} />)}
        </div>
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-4">
          <input className={inputCls} placeholder="Name (z. B. E127)" value={sf.name} onChange={(e) => setSf({ ...sf, name: e.target.value })} />
          <input className={inputCls} placeholder="Öffnung mm" value={sf.aperture_mm || ''} onChange={(e) => setSf({ ...sf, aperture_mm: e.target.value })} />
          <input className={inputCls} placeholder="Brennweite mm" value={sf.focal_length_mm || ''} onChange={(e) => setSf({ ...sf, focal_length_mm: e.target.value })} />
          <button onClick={addScope} className={btnPrimary}><Plus className="h-4 w-4" /> Hinzufügen</button>
        </div>
        <p className="mt-1.5 text-[11px] text-slate-500">Öffnung, Brennweite und Grenzgröße direkt in der Liste bearbeitbar. Die Grenzgröße steuert die Objektliste, wenn du dort das Teleskop wählst (Vorschlag = stellare Grenzgröße aus der Öffnung).</p>
      </div>

      {/* Kameras */}
      <div className={card}>
        <h3 className="mb-3 flex items-center gap-2 font-semibold"><CamIcon className="h-4.5 w-4.5 text-indigo-300" /> Kameras</h3>
        <div className="space-y-2">
          {cams.map((c) => (
            <Row key={c.id} onDelete={() => api.delete(`/api/equipment/cameras/${c.id}`).then(loadAll)}>
              <span className="font-medium">{c.name}</span>
              <span className="text-xs text-slate-500">
                {c.sensor_type} · {c.pixel_size_um ? `${c.pixel_size_um} µm` : '— µm'}{c.res_x ? ` · ${c.res_x}×${c.res_y ?? '?'}` : ''}
              </span>
            </Row>
          ))}
        </div>
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-7">
          <input className={`${inputCls} sm:col-span-2`} placeholder="Name" value={cf.name} onChange={(e) => setCf({ ...cf, name: e.target.value })} />
          <input className={inputCls} placeholder="Pixel µm" value={cf.pixel_size_um || ''} onChange={(e) => setCf({ ...cf, pixel_size_um: e.target.value })} />
          <input className={inputCls} placeholder="Px X" value={cf.res_x || ''} onChange={(e) => setCf({ ...cf, res_x: e.target.value })} />
          <input className={inputCls} placeholder="Px Y" value={cf.res_y || ''} onChange={(e) => setCf({ ...cf, res_y: e.target.value })} />
          <select className={inputCls} value={cf.sensor_type} onChange={(e) => setCf({ ...cf, sensor_type: e.target.value })}>
            <option value="color">Color</option>
            <option value="mono">Mono</option>
          </select>
          <button onClick={addCam} className={btnPrimary}><Plus className="h-4 w-4" /></button>
        </div>
        <p className="mt-1.5 text-[11px] text-slate-500">Pixelgröße (µm) + Auflösung X/Y in Pixeln — beides nötig für Bildfeld/Framing im Rechner.</p>
      </div>

      {/* Filter */}
      <div className={card}>
        <h3 className="mb-3 flex items-center gap-2 font-semibold"><FilterIcon className="h-4.5 w-4.5 text-indigo-300" /> Filter</h3>
        <div className="space-y-2">
          {filts.map((f) => (
            <Row key={f.id} onDelete={() => api.delete(`/api/equipment/filters/${f.id}`).then(loadAll)}>
              <span className="font-medium">{f.name}</span>
              <span className="text-xs text-slate-500">{f.kind === 'narrowband' ? 'Schmalband' : 'Breitband'}</span>
              {f.kind === 'narrowband' && (
                <span className="flex items-center gap-1 text-xs text-slate-400">
                  <input
                    type="number"
                    step="0.5"
                    defaultValue={f.bandwidth_nm ?? ''}
                    onBlur={(e) => { if (Number(e.target.value) !== (f.bandwidth_nm ?? 0)) setBandwidth(f, e.target.value) }}
                    className="w-16 rounded border border-white/10 bg-black/30 px-1.5 py-0.5 text-right text-xs text-white outline-none focus:border-indigo-400/60"
                  />
                  nm
                </span>
              )}
            </Row>
          ))}
        </div>
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-4">
          <input className={inputCls} placeholder="Name (z. B. Ha)" value={ff.name} onChange={(e) => setFf({ ...ff, name: e.target.value })} />
          <select className={inputCls} value={ff.kind} onChange={(e) => setFf({ ...ff, kind: e.target.value })}>
            <option value="broadband">Breitband (L/R/G/B)</option>
            <option value="narrowband">Schmalband (Ha/OIII/SII)</option>
          </select>
          {ff.kind === 'narrowband' ? (
            <input className={inputCls} placeholder="Bandbreite nm (z. B. 7)" value={ff.bandwidth_nm || ''} onChange={(e) => setFf({ ...ff, bandwidth_nm: e.target.value })} />
          ) : (
            <div className="hidden sm:block" />
          )}
          <button onClick={addFilt} className={btnPrimary}><Plus className="h-4 w-4" /> Hinzufügen</button>
        </div>
        <p className="mt-1.5 text-[11px] text-slate-500">Standard-Set ist vorbelegt. Bandbreite bei Schmalband-Filtern direkt in der Liste anpassbar (gängig: 3 / 6 / 7 / 12 nm).</p>
      </div>

      {/* Setups */}
      <div className={card}>
        <h3 className="mb-3 flex items-center gap-2 font-semibold"><Telescope className="h-4.5 w-4.5 text-indigo-300" /> Setups (Teleskop + Kamera)</h3>
        <div className="space-y-2">
          {setups.map((s) => <SetupRow key={s.id} s={s} allFilters={filts} reload={loadAll} />)}
        </div>
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
          <select className={inputCls} value={setupForm.telescope_id} onChange={(e) => setSetupForm({ ...setupForm, telescope_id: e.target.value })}>
            <option value="">Teleskop …</option>
            {scopes.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <select className={inputCls} value={setupForm.camera_id} onChange={(e) => setSetupForm({ ...setupForm, camera_id: e.target.value })}>
            <option value="">Kamera …</option>
            {cams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button onClick={addSetup} className={btnPrimary}><Plus className="h-4 w-4" /> Bündeln</button>
        </div>
        <p className="mt-1.5 text-[11px] text-slate-500">Feste optische Ketten bündeln (z. B. „RC71 + ASI2600MC"). Danach pro Setup die vorhandenen Filter antippen. Kein Filter = One-Shot-Farbe (OSC).</p>
      </div>
    </div>
  )
}

// ─── Allgemein ───
function GeneralTab() {
  const [s, setS] = useState<AppSettings>({ night_start: '22:00', night_end: '05:00', default_location_id: null })
  const [locs, setLocs] = useState<Location[]>([])
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.get('/api/settings').then((r) => setS(r.data))
    api.get('/api/locations').then((r) => setLocs(r.data))
  }, [])

  const save = async () => {
    await api.patch('/api/settings', s)
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  return (
    <div className={`${card} max-w-xl space-y-4`}>
      <h3 className="font-semibold">Beobachtungsfenster</h3>
      <p className="text-sm text-slate-400">Zeitraum, in dem Objekte als „sichtbar in der Nacht" gewertet werden.</p>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Nacht von"><input type="time" className={inputCls} value={s.night_start} onChange={(e) => setS({ ...s, night_start: e.target.value })} /></Field>
        <Field label="Nacht bis"><input type="time" className={inputCls} value={s.night_end} onChange={(e) => setS({ ...s, night_end: e.target.value })} /></Field>
      </div>
      <Field label="Standard-Standort">
        <select className={inputCls} value={s.default_location_id ?? ''} onChange={(e) => setS({ ...s, default_location_id: e.target.value || null })}>
          <option value="">— keiner —</option>
          {locs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
      </Field>
      <button onClick={save} className={btnPrimary}><Save className="h-4 w-4" /> {saved ? 'Gespeichert ✓' : 'Speichern'}</button>
    </div>
  )
}

// ─── MCP ───
function McpTab() {
  const [data, setData] = useState<{ enabled: boolean; token: string | null; header_name: string; path: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  const load = () => api.get('/api/me/mcp').then((r) => setData(r.data))
  useEffect(() => { load() }, [])

  const regenerate = async () => {
    if (data?.token && !confirm('Neuen Token erzeugen? Der alte wird sofort ungültig.')) return
    setBusy(true)
    try { const r = await api.post('/api/me/mcp/regenerate'); setData(r.data) } finally { setBusy(false) }
  }
  const disable = async () => {
    if (!confirm('MCP-Zugang deaktivieren (Token löschen)?')) return
    setBusy(true)
    try { const r = await api.delete('/api/me/mcp'); setData(r.data) } finally { setBusy(false) }
  }

  const origin = window.location.origin
  const snippet = data?.token
    ? JSON.stringify({
        mcpServers: {
          'cura-stro': {
            command: 'npx',
            args: ['mcp-remote', `${origin}${data.path}`, '--header', `${data.header_name}: ${data.token}`],
          },
        },
      }, null, 2)
    : ''

  const copy = () => { navigator.clipboard.writeText(snippet); setCopied(true); setTimeout(() => setCopied(false), 1500) }

  if (!data) return <Loader2 className="h-5 w-5 animate-spin text-slate-400" />

  return (
    <div className={`${card} space-y-4`}>
      <div>
        <h3 className="flex items-center gap-2 font-semibold"><Server className="h-4.5 w-4.5 text-indigo-300" /> MCP-Server</h3>
        <p className="mt-1 text-sm text-slate-400">Objektliste + Astrowetter + Objektinfos für andere LLM-Tools (z. B. curai) abrufbar. Mit Token absichern.</p>
      </div>

      <div className="flex flex-wrap gap-2">
        <button onClick={regenerate} disabled={busy} className={btnPrimary}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {data.token ? 'Token neu generieren' : 'Token generieren'}
        </button>
        {data.token && <button onClick={disable} disabled={busy} className={btnGhost}><Trash2 className="h-4 w-4" /> Deaktivieren</button>}
      </div>

      {data.token ? (
        <>
          <Field label="Token">
            <div className="flex items-center gap-2">
              <input readOnly value={data.token} className={`${inputCls} font-mono`} onFocus={(e) => e.target.select()} />
            </div>
          </Field>
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400">Connect-Snippet (mcp-remote)</span>
              <button onClick={copy} className="flex items-center gap-1 text-xs text-indigo-300 hover:underline">
                {copied ? <><Check className="h-3.5 w-3.5" /> kopiert</> : <><Copy className="h-3.5 w-3.5" /> kopieren</>}
              </button>
            </div>
            <pre className="overflow-x-auto rounded-xl border border-white/10 bg-black/40 p-3 text-xs text-slate-200">{snippet}</pre>
            <p className="mt-1.5 text-[11px] text-slate-500">Endpunkt: <span className="font-mono">{origin}{data.path}</span> · Header alternativ <span className="font-mono">Authorization: Bearer …</span>. Bei öffentlichem Betrieb die URL durch deinen Host ersetzen.</p>
          </div>
        </>
      ) : (
        <p className="text-sm text-slate-500">Noch kein Token — generiere einen, um den MCP-Zugang zu aktivieren.</p>
      )}
    </div>
  )
}

// ─── kleine Helfer ───
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-400">{label}</span>
      {children}
    </label>
  )
}

// Stellare Grenzgröße aus der Öffnung (spiegelt das Backend).
function suggestLimMag(aperture?: number | null): number | null {
  if (!aperture || aperture <= 0) return null
  return Math.round((2.7 + 5 * Math.log10(aperture)) * 10) / 10
}

function ScopeRow({ s, reload }: { s: Scope; reload: () => void }) {
  const [ap, setAp] = useState(s.aperture_mm?.toString() ?? '')
  const [fl, setFl] = useState(s.focal_length_mm?.toString() ?? '')
  const [lim, setLim] = useState(s.limiting_magnitude?.toString() ?? '')
  const suggestion = suggestLimMag(ap ? Number(ap) : s.aperture_mm)
  const ratio = ap && fl && Number(ap) > 0 ? (Number(fl) / Number(ap)).toFixed(1) : null

  const save = async () => {
    await api.patch(`/api/equipment/telescopes/${s.id}`, {
      name: s.name,
      aperture_mm: ap ? Number(ap) : null,
      focal_length_mm: fl ? Number(fl) : null,
      limiting_magnitude: lim ? Number(lim) : null,
    })
    reload()
  }

  const cell = 'w-20 rounded border border-white/10 bg-black/30 px-2 py-1 text-right text-xs text-white outline-none focus:border-indigo-400/60'

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-black/20 px-3 py-2">
      <span className="min-w-16 font-medium">{s.name}</span>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
        <label className="flex items-center gap-1">Ø
          <input className={cell} value={ap} placeholder="mm" onChange={(e) => setAp(e.target.value)} onBlur={save} /> mm
        </label>
        <label className="flex items-center gap-1">f
          <input className={cell} value={fl} placeholder="mm" onChange={(e) => setFl(e.target.value)} onBlur={save} /> mm
        </label>
        {ratio && <span className="text-slate-500">f/{ratio}</span>}
        <label className="flex items-center gap-1">Grenzgröße
          <input className={cell} value={lim} placeholder={suggestion ? String(suggestion) : 'mag'} onChange={(e) => setLim(e.target.value)} onBlur={save} /> mag
        </label>
        {!lim && suggestion && <span className="text-slate-500">(Vorschlag {suggestion})</span>}
      </div>
      <button onClick={() => api.delete(`/api/equipment/telescopes/${s.id}`).then(reload)} className="rounded-lg p-1.5 text-slate-400 hover:bg-red-500/20 hover:text-red-300"><Trash2 className="h-4 w-4" /></button>
    </div>
  )
}

function SetupRow({ s, allFilters, reload }: { s: SetupT; allFilters: Filt[]; reload: () => void }) {
  const active = new Set(s.filters.map((f) => f.id))
  const toggle = async (fid: string) => {
    const next = new Set(active)
    next.has(fid) ? next.delete(fid) : next.add(fid)
    await api.patch(`/api/equipment/setups/${s.id}`, { filter_ids: [...next] })
    reload()
  }
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2.5">
      <div className="flex items-center justify-between">
        <div>
          <span className="font-medium">{s.name}</span>
          <span className="ml-2 text-xs text-slate-500">{s.telescope_name} + {s.camera_name}</span>
        </div>
        <button onClick={() => api.delete(`/api/equipment/setups/${s.id}`).then(reload)} className="rounded-lg p-1.5 text-slate-400 hover:bg-red-500/20 hover:text-red-300"><Trash2 className="h-4 w-4" /></button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {allFilters.length === 0 && <span className="text-xs text-slate-500">Erst Filter anlegen.</span>}
        {allFilters.map((f) => {
          const on = active.has(f.id)
          return (
            <button key={f.id} onClick={() => toggle(f.id)}
              className={`rounded-full border px-2.5 py-0.5 text-xs transition ${on ? (f.kind === 'narrowband' ? 'border-fuchsia-400/40 bg-fuchsia-500/20 text-fuchsia-100' : 'border-sky-400/40 bg-sky-500/20 text-sky-100') : 'border-white/10 text-slate-400 hover:bg-white/10'}`}>
              {f.name}
            </button>
          )
        })}
        {active.size === 0 && allFilters.length > 0 && <span className="self-center text-[11px] text-slate-500">→ One-Shot (OSC, keine Wechsel)</span>}
      </div>
    </div>
  )
}

function Row({ children, onDelete }: { children: React.ReactNode; onDelete: () => void }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-white/10 bg-black/20 px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">{children}</div>
      <button onClick={onDelete} className="rounded-lg p-1.5 text-slate-400 hover:bg-red-500/20 hover:text-red-300"><Trash2 className="h-4 w-4" /></button>
    </div>
  )
}
