import { motion } from 'framer-motion';
import { PlanetData, SUN_DATA } from '../../data/planets';

interface InfoPanelProps {
  data: PlanetData | typeof SUN_DATA | null;
  onClose: () => void;
}

export default function InfoPanel({ data, onClose }: InfoPanelProps) {
  if (!data) return null;

  const photoUrl = (data as PlanetData).realPhotoUrl;

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 30 }}
      transition={{ duration: 0.3 }}
      className="fixed bottom-6 right-6 w-80 max-h-[80vh] overflow-y-auto bg-black/70 backdrop-blur-md text-white p-5 rounded-xl border border-white/10"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">{data.nameDE ?? data.name}</h2>
        <button
          onClick={onClose}
          className="text-white/60 hover:text-white/80 text-xl leading-none"
        >
          ×
        </button>
      </div>

      {/* Real photo */}
      {photoUrl && (
        <img
          src={photoUrl}
          alt={data.nameDE ?? data.name}
          className="w-full h-[180px] object-cover rounded-lg mb-4"
        />
      )}

      {/* Description */}
      {data.description && (
        <p className="text-sm text-gray-300 mb-4">{data.description}</p>
      )}

      {/* Physics section */}
      <div className="border-t border-white/10 pt-3 mb-3">
        <h3 className="text-sm font-semibold mb-2">Physik</h3>
        <div className="space-y-1">
          <div className="flex justify-between text-xs">
            <span className="text-gray-400">Masse:</span>
            <span>{data.mass}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-gray-400">Durchmesser:</span>
            <span>{data.diameter} km</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-gray-400">Temperatur:</span>
            <span>{data.temperature}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-gray-400">Atmosphäre:</span>
            <span>{data.atmosphere}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-gray-400">Monde:</span>
            <span>{data.moons}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-gray-400">Umlaufdauer:</span>
            <span>{data.period > 0 ? `${data.period} Jahre` : '—'}</span>
          </div>
        </div>
      </div>

      {/* Photo tips section */}
      {data.photoTip && (
        <div className="border-t border-white/10 pt-3">
          <h3 className="text-sm font-semibold mb-2">Fotografie-Tipps</h3>
          <div className="space-y-1">
            <div className="flex justify-between text-xs">
              <span className="text-gray-400">Belichtung:</span>
              <span>{data.photoTip.exposure}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-gray-400">Filter:</span>
              <span>{data.photoTip.filter}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-gray-400">Beste Zeit:</span>
              <span>{data.photoTip.bestTimes}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-gray-400">Besonderheiten:</span>
              <span>{data.photoTip.notes}</span>
            </div>
          </div>
        </div>
      )}
    </motion.div>
  );
}