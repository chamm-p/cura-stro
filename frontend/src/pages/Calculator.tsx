import { useSearchParams } from 'react-router-dom'
import { Calculator as CalcIcon } from 'lucide-react'
import Layout from '../components/Layout'
import CalculatorPanel from '../components/CalculatorPanel'

// Vollseitige Variante (Nav-Eintrag „Rechner"). Aus der Objektliste wird der
// Rechner als Overlay (CalculatorModal) geöffnet.
export default function Calculator() {
  const [params] = useSearchParams()
  return (
    <Layout>
      <div className="flex items-center gap-2">
        <CalcIcon className="h-6 w-6 text-indigo-300" />
        <h1 className="text-2xl font-bold">Framing- & Belichtungsrechner</h1>
      </div>
      <div className="mt-5">
        <CalculatorPanel
          initialObject={params.get('object') || ''}
          initialTelescopeId={params.get('telescope_id') || undefined}
          initialSetupId={params.get('setup_id') || undefined}
        />
      </div>
    </Layout>
  )
}
