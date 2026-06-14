import { useEffect } from 'react'
import { X, Calculator as CalcIcon } from 'lucide-react'
import CalculatorPanel from './CalculatorPanel'

/** Rechner als Overlay über der Objektliste (kein Seitenwechsel). */
export default function CalculatorModal({
  object, telescopeId, onClose,
}: { object: string; telescopeId?: string; onClose: () => void }) {
  // ESC schließt.
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 sm:p-8" onClick={onClose}>
      <div className="my-auto w-full max-w-5xl rounded-2xl border border-white/10 bg-[#0a0c18] p-5 shadow-2xl sm:p-6" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold"><CalcIcon className="h-5 w-5 text-indigo-300" /> Framing & Belichtung{object ? ` · ${object}` : ''}</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-white"><X className="h-5 w-5" /></button>
        </div>
        <CalculatorPanel initialObject={object} initialTelescopeId={telescopeId} />
      </div>
    </div>
  )
}
