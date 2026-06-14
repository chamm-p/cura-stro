import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Layers, MapPin, Loader2, Crop, Clock } from 'lucide-react'
import api from '../services/api'

interface Setup { id: string; name: string; telescope_id: string; camera_id: string; telescope_name: string; camera_name: string; focal_ratio: number | null }
interface Loc { id: string; name: string; bortle?: number | null }
interface Resp {
  telescope: { name: string; aperture_mm: number | null; focal_length_mm: number; focal_ratio: number | null }
  camera: { name: string; pixel_size_um: number; res_x: number; res_y: number; sensor_type: string }
  framing: {
    image_scale: number; fov_width_arcmin: number; fov_height_arcmin: number
    fov_width_deg: number; fov_height_deg: number; sensor_aspect: number; sampling_note: string
    preview_url: string | null; preview_fov_deg: number | null
    object: { ident: string; name: string | null; size_major_arcmin: number | null; framing_pct: number | null; fits: boolean } | null
  }
  exposure: {
    bortle: number; sqm: number; read_noise: number; qe: number; aperture_known: boolean
    recommended_band: string | null; grand_total_min: number; note: string | null
    groups: { band: string; label: string; subs_per_filter: number; total_min: number
      filters: { name: string; bandwidth_nm: number | null; sub_length_s: number | null; sub_optimal_s: number | null; capped: boolean; subs: number; total_min: number }[] }[]
  }
}

const input = 'rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-indigo-400/60'
const fmtSub = (s: number | null) => (!s ? '—' : s % 60 === 0 ? `${s / 60} min` : `${s} s`)

export default function CalculatorPanel({
  initialObject = '', initialTelescopeId, initialSetupId,
}: { initialObject?: string; initialTelescopeId?: string; initialSetupId?: string }) {
  const [setups, setSetups] = useState<Setup[]>([])
  const [locs, setLocs] = useState<Loc[]>([])
  const [setupId, setSetupId] = useState('')
  const [locId, setLocId] = useState('')
  const [obj, setObj] = useState(initialObject)
  const [maxSub, setMaxSub] = useState(() => Number(localStorage.getItem('curastro-calc-maxsub')) || 300)
  const [data, setData] = useState<Resp | null>(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.get('/api/equipment/setups').then((r) => {
      const list: Setup[] = r.data
      setSetups(list)
      const match = (initialSetupId && list.find((s) => s.id === initialSetupId))
        || (initialTelescopeId && list.find((s) => s.telescope_id === initialTelescopeId))
        || list[0]
      if (match) setSetupId(match.id)
    })
    api.get('/api/locations').then((r) => setLocs(r.data))
  }, [])

  useEffect(() => { localStorage.setItem('curastro-calc-maxsub', String(maxSub)) }, [maxSub])

  const calc = useCallback(async () => {
    if (!setupId) return
    setLoading(true); setErr('')
    try {
      const p: any = { setup_id: setupId, max_sub_s: maxSub }
      if (locId) p.location_id = locId
      if (obj.trim()) p.object_ident = obj.trim().toUpperCase()
      const r = await api.get('/api/calculator', { params: p })
      setData(r.data)
    } catch (e: any) {
      setErr(e.response?.data?.detail || 'Berechnung fehlgeschlagen.')
      setData(null)
    } finally { setLoading(false) }
  }, [setupId, locId, obj, maxSub])
  useEffect(() => { const t = setTimeout(calc, 350); return () => clearTimeout(t) }, [calc])

  const fr = data?.framing
  const pf = fr?.preview_fov_deg || 1
  const relW = fr ? (fr.fov_width_deg / pf) * 100 : 100
  const relH = fr ? (fr.fov_height_deg / pf) * 100 : 100

  return (
    <div>
      {setups.length === 0 ? (
        <div className="rounded-2xl border border-white/10 bg-[#0c1024] p-6 text-sm text-slate-300">
          Noch kein Setup. Lege unter <Link to="/settings" className="text-indigo-300 hover:underline">Einstellungen → Equipment → Setups</Link> ein Teleskop+Kamera-Bundle an.
        </div>
      ) : (
        <div className="flex flex-wrap items-end gap-3 rounded-2xl border border-white/10 bg-[#0c1024] p-4">
          <Ctl label="Setup" icon={Layers}>
            <select className={input} value={setupId} onChange={(e) => setSetupId(e.target.value)}>
              {setups.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Ctl>
          <Ctl label="Standort (Bortle)" icon={MapPin}>
            <select className={input} value={locId} onChange={(e) => setLocId(e.target.value)}>
              <option value="">Standard</option>
              {locs.map((l) => <option key={l.id} value={l.id}>{l.name}{l.bortle ? ` (B${l.bortle})` : ''}</option>)}
            </select>
          </Ctl>
          <Ctl label="Objekt (optional)">
            <input className={`${input} w-32`} placeholder="z. B. M31" value={obj} onChange={(e) => setObj(e.target.value)} />
          </Ctl>
          <Ctl label="max. Sub">
            <select className={input} value={maxSub} onChange={(e) => setMaxSub(Number(e.target.value))}>
              <option value={60}>1 min</option>
              <option value={120}>2 min</option>
              <option value={180}>3 min</option>
              <option value={300}>5 min</option>
              <option value={600}>10 min</option>
            </select>
          </Ctl>
        </div>
      )}

      {err && <div className="mt-4 rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{err}</div>}
      {loading && <div className="mt-6 flex justify-center"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>}

      {data && fr && !loading && (
        <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-2">
          <div className="rounded-2xl border border-white/10 bg-[#0c1024] p-5">
            <h3 className="mb-1 flex items-center gap-2 font-semibold"><Crop className="h-4.5 w-4.5 text-indigo-300" /> Bildfeld & Framing</h3>
            <p className="mb-3 text-xs text-slate-400">{data.telescope.name} · {data.telescope.focal_length_mm} mm{data.telescope.focal_ratio ? ` f/${data.telescope.focal_ratio}` : ''} · {data.camera.name}</p>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <KV k="Bildmaßstab" v={`${fr.image_scale} "/px`} />
              <KV k="Bildfeld" v={`${fr.fov_width_arcmin}' × ${fr.fov_height_arcmin}'`} />
              <KV k="" v={`${fr.fov_width_deg}° × ${fr.fov_height_deg}°`} />
              <KV k="Sensor" v={data.camera.sensor_type === 'mono' ? 'Mono' : 'Farbe'} />
            </div>
            {fr.object && fr.preview_url && (
              <div className="mt-4">
                <div className="relative mx-auto aspect-square w-full max-w-sm overflow-hidden rounded-lg bg-black">
                  <img src={fr.preview_url} alt="Framing" className="h-full w-full object-cover opacity-90" />
                  <div className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 border-2 border-indigo-400 shadow-[0_0_0_2000px_rgba(0,0,0,0.45)]"
                    style={{ width: `${relW}%`, height: `${relH}%` }} />
                </div>
                <div className="mt-2 text-center text-sm">
                  <span className="font-medium">{fr.object.ident}</span>
                  {fr.object.size_major_arcmin ? <span className="text-slate-400"> · {fr.object.size_major_arcmin}' groß</span> : null}
                  {fr.object.framing_pct != null && (
                    <span className={fr.object.fits ? 'text-emerald-300' : 'text-amber-300'}> · füllt {fr.object.framing_pct}% {fr.object.fits ? '' : '(passt nicht ganz)'}</span>
                  )}
                </div>
                <p className="mt-1 text-center text-[11px] text-slate-500">Blauer Rahmen = dein Sensorausschnitt · simulierte Objektgröße (DSS)</p>
              </div>
            )}
            {!fr.object && <p className="mt-4 text-xs text-slate-500">Objekt eingeben (z. B. M31) für die simulierte Framing-Vorschau.</p>}
          </div>

          <div className="rounded-2xl border border-white/10 bg-[#0c1024] p-5">
            <h3 className="mb-1 flex items-center gap-2 font-semibold"><Clock className="h-4.5 w-4.5 text-indigo-300" /> Belichtung pro Filter</h3>
            <p className="mb-3 text-xs text-slate-400">Bortle {data.exposure.bortle} (SQM {data.exposure.sqm}) · RN {data.exposure.read_noise} e⁻ · QE {Math.round(data.exposure.qe * 100)}%</p>
            {!data.exposure.aperture_known ? (
              <div className="mb-3 rounded-lg border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">Öffnung am Teleskop ergänzen für Belichtungswerte.</div>
            ) : data.exposure.groups.length === 0 ? (
              <p className="text-sm text-slate-500">Keine passenden Filter angelegt.</p>
            ) : (
              <div className="space-y-4">
                {data.exposure.groups.map((g) => (
                  <div key={g.band} className="rounded-xl border border-white/10 bg-black/20 p-3">
                    <div className="mb-2 flex items-center justify-between">
                      <span className="text-sm font-semibold">{g.label}</span>
                      <span className="text-xs text-slate-400">{g.subs_per_filter} Subs je Filter · {Math.round(g.total_min / 60 * 10) / 10} h</span>
                    </div>
                    <table className="w-full text-sm">
                      <thead className="text-left text-xs text-slate-500"><tr><th className="py-1">Filter</th><th>Sub-Länge</th><th>#Subs</th><th>Dauer</th></tr></thead>
                      <tbody>
                        {g.filters.map((f) => (
                          <tr key={f.name} className="border-t border-white/5">
                            <td className="py-1.5">
                              <span className="font-medium">{f.name}</span>
                              {f.bandwidth_nm ? <span className="ml-1.5 rounded bg-fuchsia-500/20 px-1.5 py-0.5 text-[10px] text-fuchsia-200">{f.bandwidth_nm}nm</span> : null}
                            </td>
                            <td className="font-medium text-indigo-200">{fmtSub(f.sub_length_s)}{f.capped && <span className="ml-1 text-[10px] text-slate-500">(opt. {fmtSub(f.sub_optimal_s)})</span>}</td>
                            <td className="text-slate-300">{f.subs}</td>
                            <td className="text-slate-300">{Math.round(f.total_min / 60 * 10) / 10} h</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
                <div className="flex items-center justify-between rounded-xl border border-indigo-400/30 bg-indigo-500/10 px-4 py-2.5 text-sm">
                  <span className="font-medium">Gesamtdauer{data.framing.object ? ` für ${data.framing.object.ident}` : ''}</span>
                  <span className="text-lg font-semibold text-indigo-200">{Math.round(data.exposure.grand_total_min / 60 * 10) / 10} h</span>
                </div>
                {data.exposure.note && <div className="rounded-lg border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">{data.exposure.note}</div>}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function KV({ k, v }: { k: string; v: string }) {
  return <div><div className="text-xs text-slate-500">{k}</div><div className="font-medium">{v}</div></div>
}
function Ctl({ label, icon: Icon, children }: { label: string; icon?: any; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="flex items-center gap-1 text-[11px] font-medium text-slate-400">{Icon && <Icon className="h-3 w-3" />} {label}</span>
      {children}
    </label>
  )
}
