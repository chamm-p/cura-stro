import { Html } from '@react-three/drei';
import { AnimatePresence, motion } from 'framer-motion';

interface PlanetLabelProps {
  name: string;
  visible: boolean;
}

export default function PlanetLabel({ name, visible }: PlanetLabelProps) {
  return (
    <Html
      center
      style={{ pointerEvents: 'none' }}
      zIndexRange={[100, 0]}
      wrapperClass="planet-label-wrapper"
    >
      <div style={{ transform: 'translateY(-48px) scale(1)' }}>
        <AnimatePresence>
          {visible && (
            <motion.div
              key="planet-label"
              className="pointer-events-none whitespace-nowrap font-semibold text-white bg-black/70 px-4 py-2 rounded-lg backdrop-blur-md border border-white/20 shadow-lg"
              style={{
                fontSize: '28px',
                lineHeight: '1.2',
                fontWeight: 700,
                textShadow: '0 2px 8px rgba(0,0,0,0.8)',
                letterSpacing: '0.5px',
              }}
              initial={{ opacity: 0, y: -10, scale: 0.8 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -10, scale: 0.8 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
            >
              {name}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </Html>
  );
}