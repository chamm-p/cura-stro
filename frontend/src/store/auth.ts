import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface User {
  id: string
  username: string
  email: string
  role: 'admin' | 'user'
  language?: 'de' | 'en'
  first_name?: string | null
  full_name?: string | null
  settings?: Record<string, unknown> | null
}

interface AuthState {
  user: User | null
  token: string | null
  refreshToken: string | null
  isAuthenticated: boolean
  _hasHydrated: boolean
  setAuth: (user: User, token: string, refreshToken?: string | null) => void
  logout: () => void
  setHasHydrated: (s: boolean) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      token: null,
      refreshToken: null,
      isAuthenticated: false,
      _hasHydrated: false,
      setAuth: (user, token, refreshToken = null) => {
        localStorage.setItem('auth-token', token)
        set({ user, token, refreshToken, isAuthenticated: true })
      },
      logout: () => {
        localStorage.removeItem('auth-token')
        set({ user: null, token: null, refreshToken: null, isAuthenticated: false })
      },
      setHasHydrated: (s) => set({ _hasHydrated: s }),
    }),
    {
      name: 'curastro-auth',
      partialize: (s) => ({
        user: s.user,
        token: s.token,
        refreshToken: s.refreshToken,
        isAuthenticated: s.isAuthenticated,
      }),
      onRehydrateStorage: () => (state) => state?.setHasHydrated(true),
    },
  ),
)
