import { Link, useLocation } from 'react-router-dom'
import { Telescope, LogOut, LayoutDashboard, Settings as SettingsIcon, Stars, ListChecks } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import GalaxyBackground from './GalaxyBackground'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/targets', label: 'Objektliste', icon: Stars },
  { to: '/manage', label: 'Verwaltung', icon: ListChecks },
  { to: '/settings', label: 'Einstellungen', icon: SettingsIcon },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuthStore()
  const { pathname } = useLocation()

  return (
    <div className="relative min-h-screen bg-transparent text-slate-100">
      <GalaxyBackground showGalaxy={false} fixed />
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-white/10 bg-[#05060f]/80 px-6 py-3 backdrop-blur">
        <div className="flex items-center gap-6">
          <Link to="/" className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-tr from-indigo-500 to-fuchsia-500">
              <Telescope className="h-4.5 w-4.5 text-white" />
            </div>
            <span className="font-semibold">cura-stro</span>
          </Link>
          <nav className="flex items-center gap-1">
            {NAV.map((n) => {
              const active = pathname === n.to
              return (
                <Link
                  key={n.to}
                  to={n.to}
                  className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition ${
                    active ? 'bg-white/10 text-white' : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
                  }`}
                >
                  <n.icon className="h-4 w-4" />
                  {n.label}
                </Link>
              )
            })}
          </nav>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <span className="hidden text-slate-400 sm:inline">
            {user?.full_name || user?.first_name || user?.username}
          </span>
          <button
            onClick={logout}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-slate-300 hover:bg-white/10"
          >
            <LogOut className="h-4 w-4" /> Abmelden
          </button>
        </div>
      </header>
      <main className="relative z-10 mx-auto max-w-5xl px-6 py-10">{children}</main>
    </div>
  )
}
