import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useState } from 'react'
import { Stars, CloudMoon, ListChecks, Cloud, Moon, Images } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import api from '../services/api'
import Layout from '../components/Layout'
import Slideshow from '../components/Slideshow'

const VERDICT_STYLE: Record<string, string> = {
  excellent: 'text-emerald-300', good: 'text-emerald-300', fair: 'text-amber-300', bad: 'text-red-300', unknown: 'text-slate-400',
}

interface Conditions {
  available: boolean
  location?: { name: string }
  moon?: { illumination_pct: number; phase_name: string; up: boolean }
  weather?: { available: boolean; cloud_cover?: number; verdict?: string; verdict_text?: string }
}

export default function Dashboard() {
  const { user } = useAuthStore()
  const [health, setHealth] = useState<string>('…')
  const [showSlides, setShowSlides] = useState(false)

  useEffect(() => {
    api.get('/api/health').then((r) => setHealth(r.data?.status ?? 'unknown')).catch(() => setHealth('offline'))
  }, [])

  const cls = 'block rounded-2xl border border-white/10 bg-white/5 p-6 transition hover:border-indigo-400/40 hover:bg-white/[0.07]'

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
  useEffect(() => {
    api.get('/api/targets/conditions').then((r) => setC(r.data)).catch(() => setC({ available: false }))
  }, [])

  const cls = 'block rounded-2xl border border-white/10 bg-white/5 p-6'

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
            <Cloud className="h-4 w-4 text-slate-400" />
            {c.weather?.available ? (
              <span className={VERDICT_STYLE[c.weather.verdict || 'unknown']}>
                {c.weather.verdict_text} · {c.weather.cloud_cover}% Wolken
              </span>
            ) : (
              <span className="text-slate-500">keine Wetterdaten</span>
            )}
          </div>
          <div className="flex items-center gap-2 text-slate-300">
            <Moon className="h-4 w-4 text-slate-400" />
            {c.moon?.phase_name} · {c.moon?.illumination_pct}% {c.moon?.up ? '' : '(unter Horizont)'}
          </div>
          <p className="pt-1 text-xs text-slate-500">{c.location?.name} · heute Nacht</p>
        </div>
      )}
    </div>
  )
}
