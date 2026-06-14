import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Stars, CloudMoon, ListChecks, Cloud, Moon, Images, Clock, AlertTriangle, Wind } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import api from '../services/api'
import Layout from '../components/Layout'
import Slideshow from '../components/Slideshow'

const VERDICT_STYLE: Record<string, string> = {
  excellent: 'text-emerald-300', good: 'text-emerald-300', fair: 'text-amber-300', bad: 'text-red-300', unknown: 'text-slate-400',
}

interface Conditions {
  available: boolean
  location?: { name: string; id?: string }
  clouds?: { source: string; fetched_at?: string | null; can_refresh: boolean }
  moon?: { illumination_pct: number; phase_name: string; up: boolean; best_window?: { start: string | null; end: string | null; reason: string } | null }
  weather?: { available: boolean; cloud_cover?: number; cloud_low?: number | null; cloud_mid?: number | null; cloud_high?: number | null; verdict?: string; verdict_text?: string; wind_gusts?: number; storm?: boolean; windy?: boolean }
}

function ageText(iso: string): string {
  const h = (Date.now() - new Date(iso).getTime()) / 3.6e6
  if (h < 1) return 'gerade aktualisiert'
  if (h < 24) return `vor ${Math.round(h)} h`
  return `vor ${Math.round(h / 24)} d`
}

export default function Dashboard() {
  const { user } = useAuthStore()
  const [health, setHealth] = useState<string>('…')
  const [showSlides, setShowSlides] = useState(false)

  useEffect(() => {
    api.get('/api/health').then((r) => setHealth(r.data?.status ?? 'unknown')).catch(() => setHealth('offline'))
  }, [])

  const cls = 'block rounded-2xl border border-white/10 bg-[#0c1024] p-6 transition hover:border-indigo-400/40 hover:bg-white/[0.07]'

  return (
    <Layout>
      <h1 className="text-2xl font-bold">Willkommen zurück, {user?.first_name || user?.username} 👋</h1>
      <p className="mt-2 text-slate-400">
        Backend-Status: <span className="font-mono text-indigo-300">{health}</span>
      </p>

      <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Link to="/targets" className={cls}>
          <Stars className="mb-3 h-7 w-7 text-indigo-300" />
          <h3 className="font-semibold">Objektliste</h3>
          <p className="mt-1 text-sm text-slate-400">Gute Ziele für deinen Standort & die Nacht.</p>
        </Link>

        <ConditionsCard />

        <Link to="/manage" className={cls}>
          <ListChecks className="mb-3 h-7 w-7 text-indigo-300" />
          <h3 className="font-semibold">Verwaltung</h3>
          <p className="mt-1 text-sm text-slate-400">Geplant · RAW · entwickelt — pro Teleskop, inkl. Foto-Upload.</p>
        </Link>

        <button onClick={() => setShowSlides(true)} className={`${cls} text-left`}>
          <Images className="mb-3 h-7 w-7 text-indigo-300" />
          <h3 className="font-semibold">Slideshow</h3>
          <p className="mt-1 text-sm text-slate-400">Deine besten Astrofotos im Vollbild (Rating ≥ 3).</p>
        </button>
      </div>

      {showSlides && <Slideshow onClose={() => setShowSlides(false)} />}
    </Layout>
  )
}

function ConditionsCard() {
  const [c, setC] = useState<Conditions | null>(null)
  const [busy, setBusy] = useState(false)
  const load = () => api.get('/api/targets/conditions').then((r) => setC(r.data)).catch(() => setC({ available: false }))
  useEffect(() => { load() }, [])

  const refresh = async () => {
    if (!c?.location?.id) return
    setBusy(true)
    try { await api.post(`/api/clouds/refresh?location_id=${c.location.id}`); await load() }
    finally { setBusy(false) }
  }

  const cls = 'block rounded-2xl border border-white/10 bg-[#0c1024] p-6'

  return (
    <div className={cls}>
      <CloudMoon className="mb-3 h-7 w-7 text-indigo-300" />
      <h3 className="font-semibold">Astrowetter & Mond</h3>
      {!c ? (
        <p className="mt-1 text-sm text-slate-500">lädt …</p>
      ) : !c.available ? (
        <p className="mt-1 text-sm text-slate-400">Bewölkung, Seeing und Mondeinfluss — bitte zuerst einen Standort anlegen.</p>
      ) : (
        <div className="mt-2 space-y-1.5 text-sm">
          <div className="flex items-center gap-2">
            <Cloud className={`h-4 w-4 ${(c.weather?.cloud_cover ?? 0) >= 50 ? 'text-amber-300' : 'text-slate-400'}`} />
            {c.weather?.available ? (
              <span className={VERDICT_STYLE[c.weather.verdict || 'unknown']}>
                {c.weather.verdict_text} · {c.weather.cloud_cover}% Wolken
              </span>
            ) : (
              <span className="text-slate-500">keine Wetterdaten</span>
            )}
          </div>
          {c.weather?.available && (c.weather.cloud_low != null || c.weather.cloud_mid != null || c.weather.cloud_high != null) && (
            <div className="pl-6 text-xs text-slate-500">
              Schichten — tief {c.weather.cloud_low ?? '–'} · mittel {c.weather.cloud_mid ?? '–'} · hoch {c.weather.cloud_high ?? '–'} %
            </div>
          )}
          {c.weather?.available && (c.weather.windy || c.weather.storm) && (
            <div className={`flex items-center gap-2 ${c.weather.storm ? 'text-red-300' : 'text-amber-300'}`}>
              <Wind className="h-4 w-4" />
              {c.weather.storm ? 'Sturm' : 'böig'} · Böen bis {c.weather.wind_gusts} km/h
            </div>
          )}
          {(() => {
            const pct = c.moon?.illumination_pct ?? 0
            const up = !!c.moon?.up
            const unfav = up && pct > 70           // hell & über Horizont → stört
            const good = !up || pct < 20           // unten oder fast dunkel → optimal
            const txt = unfav ? 'text-amber-300' : good ? 'text-emerald-300' : 'text-slate-300'
            const ic = unfav ? 'text-amber-300' : good ? 'text-emerald-300' : 'text-slate-400'
            return (
              <div className={`flex items-center gap-2 ${txt}`}>
                <Moon className={`h-4 w-4 ${ic}`} />
                {c.moon?.phase_name} · {pct}% {up ? '' : '(unter Horizont)'}
                {unfav && (
                  <span className="flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] text-amber-200">
                    <AlertTriangle className="h-3 w-3" /> ungünstig
                  </span>
                )}
                {good && (
                  <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] text-emerald-200">günstig</span>
                )}
              </div>
            )
          })()}
          {c.moon?.best_window && (
            c.moon.best_window.start ? (
              <div className="flex items-center gap-2 text-slate-300">
                <Clock className="h-4 w-4 text-slate-400" />
                Beste Bedingungen: <span className="font-medium text-slate-200">{c.moon.best_window.start}–{c.moon.best_window.end}</span>
                <span className="text-xs text-slate-500">({c.moon.best_window.reason})</span>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-red-300">
                <AlertTriangle className="h-4 w-4" />
                Kein gutes Fenster heute Nacht <span className="text-xs text-red-300/70">({c.moon.best_window.reason})</span>
              </div>
            )
          )}
          {c.clouds && (
            <div className="flex items-center gap-1.5 pt-1 text-[11px] text-slate-500">
              <span>Wolken: {c.clouds.source === 'meteoblue' ? 'meteoblue' : 'Open-Meteo (Modell)'}</span>
              {c.clouds.source === 'meteoblue' && c.clouds.fetched_at && <span>· {ageText(c.clouds.fetched_at)}</span>}
              {c.clouds.can_refresh && (
                <button onClick={refresh} disabled={busy} title="meteoblue-Wolken jetzt aktualisieren" className="ml-0.5 text-indigo-300 hover:text-indigo-200 disabled:opacity-50">
                  {busy ? '… lädt' : '↻'}
                </button>
              )}
            </div>
          )}
          <p className="pt-1 text-xs text-slate-500">{c.location?.name} · heute Nacht</p>
        </div>
      )}
    </div>
  )
}
