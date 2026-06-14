import { useState, useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Telescope, KeyRound, LogIn, Sparkles, Loader2 } from 'lucide-react'
import api from '../services/api'
import { useAuthStore } from '../store/auth'
import GalaxyBackground from '../components/GalaxyBackground'

// Optionaler Video-Loop: lege eine Datei unter public/galaxy.mp4 ab, dann
// wird sie über dem Canvas eingeblendet. Fehlt sie, bleibt der animierte
// Canvas-Hintergrund (Default).
const VIDEO_SRC = '/galaxy.mp4'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [oidcEnabled, setOidcEnabled] = useState(false)
  const [oidcLabel, setOidcLabel] = useState('SSO')
  const [hasVideo, setHasVideo] = useState(false)

  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const setAuth = useAuthStore((s) => s.setAuth)
  const exchangedRef = useRef<string | null>(null)

  // OIDC-Sichtbarkeit prüfen.
  useEffect(() => {
    api
      .get('/api/auth/oidc/config')
      .then((res) => {
        setOidcEnabled(!!res.data?.enabled)
        if (res.data?.label) setOidcLabel(res.data.label)
      })
      .catch(() => {})
  }, [])

  // Optionales Hintergrundvideo nur einblenden, wenn vorhanden.
  useEffect(() => {
    fetch(VIDEO_SRC, { method: 'HEAD' })
      .then((r) => {
        if (r.ok && (r.headers.get('content-type') || '').startsWith('video')) {
          setHasVideo(true)
        }
      })
      .catch(() => {})
  }, [])

  const finishLogin = async (accessToken: string, refreshToken?: string) => {
    const userRes = await api.get('/api/users/me', {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
    setAuth(userRes.data, accessToken, refreshToken ?? null)
    navigate('/')
  }

  // OIDC-Callback (code → token).
  useEffect(() => {
    const code = searchParams.get('code')
    const stateParam = searchParams.get('state')
    const errorParam = searchParams.get('error')
    const key = code
    if (key && exchangedRef.current === key) return
    if (key) exchangedRef.current = key

    if (errorParam) {
      setError('Anmeldung beim Identity-Provider fehlgeschlagen.')
      return
    }
    if (code) {
      setIsLoading(true)
      try {
        window.history.replaceState({}, '', window.location.pathname)
      } catch {}
      api
        .post('/api/auth/oidc/token', { code, state: stateParam })
        .then((res) => finishLogin(res.data.access_token, res.data.refresh_token))
        .catch(() => setError('OIDC-Authentifizierung fehlgeschlagen.'))
        .finally(() => setIsLoading(false))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    setError('')
    try {
      const res = await api.post('/api/auth/login', { username, password })
      await finishLogin(res.data.access_token, res.data.refresh_token)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Anmeldung fehlgeschlagen.')
    } finally {
      setIsLoading(false)
    }
  }

  const startOidc = async () => {
    setError('')
    try {
      const res = await api.get('/api/auth/oidc/login')
      window.location.href = res.data.url
    } catch {
      setError('OIDC-Login konnte nicht gestartet werden.')
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#05060f]">
      {/* Hintergrund: Canvas-Galaxie (Default) + optionaler Video-Loop */}
      <GalaxyBackground />
      {hasVideo && (
        <video
          className="absolute inset-0 h-full w-full object-cover opacity-60 mix-blend-screen"
          src={VIDEO_SRC}
          autoPlay
          loop
          muted
          playsInline
        />
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-black/30" />

      <motion.div
        initial={{ opacity: 0, y: 24, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.7, ease: 'easeOut' }}
        className="relative z-10 w-full max-w-md px-6"
      >
        <div className="rounded-3xl border border-white/10 bg-white/5 p-9 shadow-2xl backdrop-blur-2xl">
          <div className="mb-8 flex flex-col items-center text-center">
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-tr from-indigo-500 via-violet-500 to-fuchsia-500 shadow-lg shadow-indigo-500/30">
              <Telescope className="h-9 w-9 text-white" />
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-white">cura-stro</h1>
            <p className="mt-2 flex items-center gap-2 text-sm text-slate-300/80">
              <Sparkles className="h-4 w-4 text-indigo-300" />
              Dein Astrofotografie-Begleiter
            </p>
          </div>

          {error && (
            <div className="mb-5 rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
              {error}
            </div>
          )}

          {oidcEnabled && (
            <>
              <button
                onClick={startOidc}
                disabled={isLoading}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-500 to-violet-600 px-4 py-3 font-medium text-white shadow-lg shadow-indigo-600/25 transition hover:from-indigo-400 hover:to-violet-500 disabled:opacity-50"
              >
                <KeyRound className="h-5 w-5" />
                Anmelden mit {oidcLabel}
              </button>
              <div className="my-6 flex items-center gap-3 text-xs text-slate-400">
                <div className="h-px flex-1 bg-white/10" />
                oder lokal
                <div className="h-px flex-1 bg-white/10" />
              </div>
            </>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-300">Benutzername</label>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                className="w-full rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-white placeholder-slate-500 outline-none transition focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-500/30"
                placeholder="astro"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-300">Passwort</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                className="w-full rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-white placeholder-slate-500 outline-none transition focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-500/30"
                placeholder="••••••••"
              />
            </div>
            <button
              type="submit"
              disabled={isLoading || !username || !password}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-white/15 bg-white/10 px-4 py-3 font-medium text-white transition hover:bg-white/15 disabled:opacity-40"
            >
              {isLoading ? <Loader2 className="h-5 w-5 animate-spin" /> : <LogIn className="h-5 w-5" />}
              Anmelden
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-slate-500">
          Klare Nächte und gutes Seeing. 🔭
        </p>
      </motion.div>
    </div>
  )
}
