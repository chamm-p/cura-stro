import axios from 'axios'
import { useAuthStore } from '../store/auth'

// Gleiche Origin: nginx (prod) bzw. Vite-Proxy (dev) leiten /api ans Backend.
// Optional über VITE_API_URL überschreibbar.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '',
})

// Token aus dem Auth-Store (Single Source of Truth, deckungsgleich mit dem,
// was ProtectedRoute vertraut) — Fallback auf das Legacy-localStorage-Feld.
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token || localStorage.getItem('auth-token')
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Bei 401 (z. B. abgelaufenes oder verwaistes Token nach DB-Reset) sauber
// ausloggen und zum Login leiten — statt still mit ungültiger Sitzung
// weiterzulaufen. Login-/Auth-Requests selbst sind ausgenommen, damit eine
// fehlgeschlagene Anmeldung ihre Fehlermeldung normal anzeigen kann.
api.interceptors.response.use(
  (res) => res,
  (error) => {
    const status = error?.response?.status
    const url: string = error?.config?.url || ''
    const isAuthCall = url.includes('/api/auth/')
    if (status === 401 && !isAuthCall) {
      useAuthStore.getState().logout()
      if (!window.location.pathname.startsWith('/login')) {
        window.location.assign('/login')
      }
    }
    return Promise.reject(error)
  },
)

export default api
