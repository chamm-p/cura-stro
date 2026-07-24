import { useState, useRef, useMemo, useCallback, useEffect } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Stars } from '@react-three/drei'
import * as THREE from 'three'
import { EffectComposer, Bloom, Vignette } from '@react-three/postprocessing'
import { motion, AnimatePresence } from 'framer-motion'
import { X, ChevronLeft, ChevronRight, Play, Pause, ZoomIn, ZoomOut } from 'lucide-react'

// ─── Kepler-Elemente (J2000.0) ───────────────────────────────────────────────
const PLANETS = [
  {
    name: 'Mercury', nameDE: 'Merkur', color: '#b5a7a7',
    radius: 0.383, semiMajorAxis: 0.387, eccentricity: 0.2056,
    inclination: 7.0, period: 0.241, rotationPeriod: 1407.6,
    axialTilt: 0.034, moons: 0, atmosphere: 'Extrem dünn (Na, K)',
    temperature: '−173 bis 427 °C', mass: '0.055 Erdmassen',
    discovery: 'Bekannt seit der Antike',
    description: 'Der kleinste Planet und sonnennächste. Ohne nennenswerte Atmosphäre unterliegt er extremen Temperaturschwankungen.',
  },
  {
    name: 'Venus', nameDE: 'Venus', color: '#e8cda0',
    radius: 0.949, semiMajorAxis: 0.723, eccentricity: 0.0068,
    inclination: 3.39, period: 0.615, rotationPeriod: -5832.5,
    axialTilt: 177.4, moons: 0, atmosphere: 'CO₂, N₂ (dicht, 92 bar)',
    temperature: 'ca. 462 °C', mass: '0.815 Erdmassen',
    discovery: 'Bekannt seit der Antike',
    description: 'Die "Zwillingswelt" der Erde. Ihre dichte CO₂-Atmosphäre erzeugt den stärksten Treibhauseffekt des Sonnensystems. Sie rotiert retrograd.',
  },
  {
    name: 'Earth', nameDE: 'Erde', color: '#4a90d9',
    radius: 1.0, semiMajorAxis: 1.0, eccentricity: 0.0167,
    inclination: 0.0, period: 1.0, rotationPeriod: 23.93,
    axialTilt: 23.44, moons: 1, atmosphere: 'N₂, O₂ (1 bar)',
    temperature: '−89 bis 57 °C', mass: '1.0 Erdmassen',
    discovery: 'Bekannt seit der Antike',
    description: 'Unser Heimatplanet — der einzige bekannte Ort mit flüssigem Wasser auf der Oberfläche und Leben.',
  },
  {
    name: 'Mars', nameDE: 'Mars', color: '#c1440e',
    radius: 0.532, semiMajorAxis: 1.524, eccentricity: 0.0934,
    inclination: 1.85, period: 1.881, rotationPeriod: 24.62,
    axialTilt: 25.19, moons: 2, atmosphere: 'CO₂, N₂, Ar (0.006 bar)',
    temperature: '−140 bis 20 °C', mass: '0.107 Erdmassen',
    discovery: 'Bekannt seit der Antike',
    description: 'Der "rote Planet" mit dem höchsten Vulkan (Olympus Mons) und dem tiefsten Canyon (Valles Marineris) des Sonnensystems.',
  },
  {
    name: 'Jupiter', nameDE: 'Jupiter', color: '#c88b3a',
    radius: 11.21, semiMajorAxis: 5.203, eccentricity: 0.0489,
    inclination: 1.31, period: 11.86, rotationPeriod: 9.93,
    axialTilt: 3.13, moons: 95, atmosphere: 'H₂, He',
    temperature: 'ca. −110 °C (Wolkenobergrenze)', mass: '317.8 Erdmassen',
    discovery: 'Bekannt seit der Antike',
    description: 'Der Gasriese und massereichste Planet. Der Große Rote Fleck ist ein Sturm, der seit über 350 Jahren tobt.',
    ringColor: '#8a7355', ringInner: 1.4, ringOuter: 1.6,
  },
  {
    name: 'Saturn', nameDE: 'Saturn', color: '#e8d5a3',
    radius: 9.45, semiMajorAxis: 9.537, eccentricity: 0.0565,
    inclination: 2.49, period: 29.46, rotationPeriod: 10.66,
    axialTilt: 26.73, moons: 146, atmosphere: 'H₂, He',
    temperature: 'ca. −140 °C (Wolkenobergrenze)', mass: '95.2 Erdmassen',
    discovery: 'Bekannt seit der Antike',
    description: 'Berühmt für sein spektakuläres Ringsystem aus Eis und Gestein. Saturn ist so leicht, dass er auf Wasser schwimmen würde.',
    ringColor: '#d4c090', ringInner: 1.2, ringOuter: 2.3,
  },
  {
    name: 'Uranus', nameDE: 'Uranus', color: '#72b5c4',
    radius: 4.01, semiMajorAxis: 19.19, eccentricity: 0.0457,
    inclination: 0.77, period: 84.01, rotationPeriod: -17.24,
    axialTilt: 97.77, moons: 28, atmosphere: 'H₂, He, CH₄',
    temperature: 'ca. −195 °C', mass: '14.5 Erdmassen',
    discovery: 'William Herschel, 1781',
    description: 'Der "Kippler" — Uranus rotiert fast auf der Seite. Das Methan in seiner Atmosphäre verleiht ihm die charakteristische cyanefarbe.',
    ringColor: '#6a9a9a', ringInner: 1.3, ringOuter: 1.7,
  },
  {
    name: 'Neptune', nameDE: 'Neptun', color: '#3f54ba',
    radius: 3.88, semiMajorAxis: 30.07, eccentricity: 0.0113,
    inclination: 1.77, period: 164.8, rotationPeriod: 16.11,
    axialTilt: 28.32, moons: 16, atmosphere: 'H₂, He, CH₄',
    temperature: 'ca. −200 °C', mass: '17.1 Erdmassen',
    discovery: 'Johann Galle, 1846',
    description: 'Der windstärkste Planet mit Geschwindigkeiten bis zu 2.100 km/h. Neptuns tiefblaue Farbe kommt vom Methan in der Atmosphäre.',
    ringColor: '#4a5a8a', ringInner: 1.3, ringOuter: 1.6,
  },
]

// ─── Hilfsfunktionen ─────────────────────────────────────────────────────────
function keplerOrbit(a, e, i, t) {
  const M = (2 * Math.PI * t) / (a ** 1.5)
  let E = M
  for (let j = 0; j < 10; j++) {
    E = E - (E - e * Math.sin(E) - M) / (1 - e * Math.cos(E))
  }
  const trueAnomaly = 2 * Math.atan2(
    Math.sqrt(1 + e) * Math.sin(E / 2),
    Math.sqrt(1 - e) * Math.cos(E / 2)
  )
  const r = a * (1 - e * Math.cos(E))
  const x = r * Math.cos(trueAnomaly)
  const z = r * Math.sin(trueAnomaly) * Math.sin((i * Math.PI) / 180)
  const y = r * Math.sin(trueAnomaly) * Math.cos((i * Math.PI) / 180)
  return [x, y, z]
}

// ─── Sonne ───────────────────────────────────────────────────────────────────
function Sun({ onClick }) {
  const sunRef = useRef(null)
  const pulseRef = useRef(null)

  useFrame(({ clock }) => {
    if (sunRef.current) {
      sunRef.current.rotation.y = clock.getElapsedTime() * 0.05
    }
    if (pulseRef.current) {
      const s = 1 + 0.03 * Math.sin(clock.getElapsedTime() * 2)
      pulseRef.current.scale.set(s, s, s)
    }
  })

  return (
    <group onClick={onClick}>
      <mesh ref={sunRef} position={[0, 0, 0]}>
        <sphereGeometry args={[1.8, 64, 64]} />
        <meshStandardMaterial
          color="#FDB813"
          emissive="#FDB813"
          emissiveIntensity={2}
          roughness={0.4}
          metalness={0.1}
        />
      </mesh>
      <mesh ref={pulseRef} position={[0, 0, 0]}>
        <sphereGeometry args={[2.2, 32, 32]} />
        <meshStandardMaterial
          color="#FDB813"
          emissive="#FDB813"
          emissiveIntensity={0.8}
          transparent
          opacity={0.3}
        />
      </mesh>
      <mesh position={[0, 0, 0]}>
        <sphereGeometry args={[3.5, 32, 32]} />
        <meshStandardMaterial
          color="#FDB813"
          emissive="#FDB813"
          emissiveIntensity={0.3}
          transparent
          opacity={0.08}
        />
      </mesh>
    </group>
  )
}

// ─── Planeten-Label ──────────────────────────────────────────────────────────
function PlanetLabel({ position, text }) {
  const canvasRef = useRef(null)
  const spriteRef = useRef(null)

  useEffect(() => {
    if (!canvasRef.current || !spriteRef.current) return
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    canvas.width = 256
    canvas.height = 64
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ctx.font = 'bold 28px Inter, sans-serif'
    ctx.fillStyle = '#e0e0e0'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.shadowColor = 'rgba(0,0,0,0.8)'
    ctx.shadowBlur = 8
    ctx.fillText(text, canvas.width / 2, canvas.height / 2)

    const texture = new THREE.CanvasTexture(canvas)
    texture.needsUpdate = true
    spriteRef.current.material.map = texture
    spriteRef.current.material.needsUpdate = true
  }, [text])

  return (
    <mesh ref={spriteRef} position={position} scale={[1.2, 0.3, 1]} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[1.2, 0.3]} />
      <meshBasicMaterial transparent depthWrite={false} />
    </mesh>
  )
}

// ─── Planet ──────────────────────────────────────────────────────────────────
function Planet({ data, time, scale, onClick }) {
  const meshRef = useRef(null)

  const pos = useMemo(() => {
    const [x, y, z] = keplerOrbit(data.semiMajorAxis * scale, data.eccentricity, data.inclination, time)
    return [x, y, z]
  }, [data, time, scale])

  const orbitPath = useMemo(() => {
    const points = []
    const segments = 128
    for (let i = 0; i <= segments; i++) {
      const t = (i / segments) * time + (time * 0.01)
      const [x, y, z] = keplerOrbit(data.semiMajorAxis * scale, data.eccentricity, data.inclination, t)
      points.push([x, y, z])
    }
    return points
  }, [data, time, scale])

  useFrame(({ clock }) => {
    if (meshRef.current) {
      const rotSpeed = (2 * Math.PI) / (Math.abs(data.rotationPeriod) / 24)
      meshRef.current.rotation.y = clock.getElapsedTime() * rotSpeed * 0.1
    }
  })

  const displayRadius = Math.max(0.12, Math.min(data.radius * 0.15, 0.8))

  return (
    <group position={pos} onClick={onClick}>
      <mesh ref={meshRef}>
        <sphereGeometry args={[displayRadius, 32, 32]} />
        <meshStandardMaterial
          color={data.color}
          roughness={0.7}
          metalness={0.1}
        />
      </mesh>

      {data.ringColor && (
        <mesh rotation={[Math.PI / 2.5, 0, 0]}>
          <ringGeometry args={[displayRadius * data.ringInner, displayRadius * data.ringOuter, 64]} />
          <meshStandardMaterial
            color={data.ringColor}
            transparent
            opacity={0.6}
            side={2}
          />
        </mesh>
      )}

      <line>
        <bufferGeometry>
          <float32BufferAttribute
            attach="attributes-position"
            args={[new Float32Array(orbitPath.flatMap(p => p)), 3]}
          />
        </bufferGeometry>
        <lineBasicMaterial color="#ffffff" transparent opacity={0.15} />
      </line>

      <PlanetLabel position={[0, displayRadius + 0.2, 0]} text={data.nameDE} />
    </group>
  )
}

// ─── Planeten-Info-Panel ─────────────────────────────────────────────────────
function PlanetInfoPanel({ planet, onClose }) {
  if (!planet) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 20 }}
      className="absolute bottom-6 left-6 right-6 max-w-lg rounded-2xl border border-white/10 bg-[#0c1024]/95 p-6 backdrop-blur-xl"
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div
            className="h-10 w-10 rounded-full shadow-lg"
            style={{
              background: `radial-gradient(circle at 35% 35%, ${planet.color}, ${planet.color}88)`,
              boxShadow: `0 0 20px ${planet.color}44`,
            }}
          />
          <div>
            <h3 className="text-lg font-bold">{planet.nameDE}</h3>
            <p className="text-xs text-slate-400">{planet.name}</p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <p className="mt-3 text-sm text-slate-300 leading-relaxed">{planet.description}</p>

      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <InfoPanelItem label="Radius" value={`${(planet.radius * 6371).toFixed(0)} km`} />
        <InfoPanelItem label="Entfernung" value={`${planet.semiMajorAxis.toFixed(2)} AU`} />
        <InfoPanelItem label="Umlaufzeit" value={`${planet.period.toFixed(2)} Jahre`} />
        <InfoPanelItem label="Masse" value={planet.mass} />
        <InfoPanelItem label="Temperatur" value={planet.temperature} />
        <InfoPanelItem label="Atmosphäre" value={planet.atmosphere} />
        <InfoPanelItem label="Rotation" value={`${planet.rotationPeriod.toFixed(1)} h`} />
        <InfoPanelItem label="Achsenneigung" value={`${planet.axialTilt.toFixed(1)}°`} />
        <InfoPanelItem label="Mond-System" value={`${planet.moons} Monde`} />
        <InfoPanelItem label="Entdecker" value={planet.discovery} />
      </div>
    </motion.div>
  )
}

function InfoPanelItem({ label, value }) {
  return (
    <div className="rounded-lg bg-white/5 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-0.5 font-medium text-slate-200">{value}</div>
    </div>
  )
}

// ─── Zeitreise-Slider ────────────────────────────────────────────────────────
function TimeTravelSlider({ time, setTime, playing, setPlaying, speed, setSpeed }) {
  return (
    <div className="absolute top-6 right-6 flex items-center gap-3 rounded-xl border border-white/10 bg-[#0c1024]/90 px-4 py-2 backdrop-blur-xl">
      <button
        onClick={() => setPlaying(!playing)}
        className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-white"
        title={playing ? 'Pause' : 'Abspielen'}
      >
        {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
      </button>

      <input
        type="range"
        min={0}
        max={100}
        step={0.1}
        value={time}
        onChange={(e) => setTime(parseFloat(e.target.value))}
        className="h-2 w-32 cursor-pointer appearance-none rounded-full bg-white/10 accent-indigo-400"
        style={{
          background: `linear-gradient(to right, #6366f1 ${time}%, rgba(255,255,255,0.1) ${time}%)`,
        }}
      />

      <span className="text-xs font-mono text-slate-400">
        {time.toFixed(1)}y
      </span>

      <div className="flex items-center gap-1">
        <button
          onClick={() => setSpeed(Math.max(0.1, speed / 2))}
          className="rounded p-1 text-xs text-slate-400 hover:bg-white/10 hover:text-white"
          title="Langsamer"
        >
          <ZoomOut className="h-3 w-3" />
        </button>
        <span className="text-xs font-mono text-slate-400 w-8 text-center">
          {speed.toFixed(1)}×
        </span>
        <button
          onClick={() => setSpeed(Math.min(16, speed * 2))}
          className="rounded p-1 text-xs text-slate-400 hover:bg-white/10 hover:text-white"
          title="Schneller"
        >
          <ZoomIn className="h-3 w-3" />
        </button>
      </div>
    </div>
  )
}

// ─── Haupt-Canvas ────────────────────────────────────────────────────────────
function SolarSystemCanvas({ selectedPlanet, setSelectedPlanet }) {
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(1)
  const { camera } = useThree()

  useFrame(({ clock }) => {
    if (playing) {
      setTime((prev) => prev + clock.getDelta() * speed * 2)
    }
  })

  const resetCamera = useCallback(() => {
    camera.position.set(0, 12, 20)
    camera.lookAt(0, 0, 0)
  }, [camera])

  const zoomIn = useCallback(() => {
    camera.position.multiplyScalar(0.8)
  }, [camera])

  const zoomOut = useCallback(() => {
    camera.position.multiplyScalar(1.25)
  }, [camera])

  const scale = 2.5

  return (
    <>
      <ambientLight intensity={0.15} />
      <pointLight position={[0, 0, 0]} intensity={3} color="#FDB813" distance={50} />

      <Stars radius={100} depth={50} count={5000} factor={4} saturation={0} fade speed={1} />

      <Sun onClick={() => setSelectedPlanet({
        name: 'Sun', nameDE: 'Sonne', color: '#FDB813',
        radius: 109, semiMajorAxis: 0, eccentricity: 0,
        inclination: 0, period: 0, rotationPeriod: 609.12,
        axialTilt: 7.25, moons: 0, atmosphere: 'Plasma (H, He)',
        temperature: '5.500 °C (Oberfläche)', mass: '333.000 Erdmassen',
        discovery: 'Bekannt seit der Antike',
        description: 'Unser Stern — eine gelbe Zwergstern vom Typ G2V. Sie enthält 99,86% der Masse des gesamten Sonnensystems.',
      })} />

      {PLANETS.map((planet) => (
        <Planet
          key={planet.name}
          data={planet}
          time={time}
          scale={scale}
          onClick={() => setSelectedPlanet(planet)}
        />
      ))}

      <OrbitControls
        enablePan={true}
        enableZoom={true}
        minDistance={3}
        maxDistance={80}
        autoRotate={false}
        autoRotateSpeed={0.5}
      />

      <EffectComposer>
        <Bloom
          intensity={0.6}
          radius={0.4}
          threshold={0.7}
        />
        <Vignette
          eskil={false}
          offset={0.1}
          darkness={0.6}
        />
      </EffectComposer>

      <TimeTravelSlider
        time={time}
        setTime={setTime}
        playing={playing}
        setPlaying={setPlaying}
        speed={speed}
        setSpeed={setSpeed}
      />

      <div className="absolute top-6 left-6 flex items-center gap-2 rounded-xl border border-white/10 bg-[#0c1024]/90 px-4 py-2 backdrop-blur-xl">
        <span className="text-sm font-semibold text-white">Sonnensystem</span>
      </div>

      <div className="absolute top-6 left-1/2 -translate-x-1/2 flex items-center gap-2">
        <button
          onClick={resetCamera}
          className="rounded-lg border border-white/10 bg-[#0c1024]/90 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/10 backdrop-blur-xl"
        >
          Reset
        </button>
        <button
          onClick={zoomIn}
          className="rounded-lg border border-white/10 bg-[#0c1024]/90 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/10 backdrop-blur-xl"
        >
          <ZoomIn className="h-3 w-3" />
        </button>
        <button
          onClick={zoomOut}
          className="rounded-lg border border-white/10 bg-[#0c1024]/90 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/10 backdrop-blur-xl"
        >
          <ZoomOut className="h-3 w-3" />
        </button>
      </div>

      <AnimatePresence>
        {selectedPlanet && (
          <PlanetInfoPanel
            planet={selectedPlanet}
            onClose={() => setSelectedPlanet(null)}
          />
        )}
      </AnimatePresence>
    </>
  )
}

// ─── Hauptkomponente ─────────────────────────────────────────────────────────
export default function SolarSystemPage() {
  const [selectedPlanet, setSelectedPlanet] = useState(null)

  return (
    <div className="relative h-[70vh] w-full overflow-hidden rounded-2xl border border-white/10 bg-[#05060f]">
      <h1 className="absolute top-4 left-6 z-10 text-2xl font-bold text-white">Sonnensystem</h1>
      <Canvas
        camera={{ position: [0, 12, 20], fov: 50 }}
        gl={{ antialias: true, alpha: false }}
        style={{ background: 'var(--bg)' }}
      >
        <SolarSystemCanvas
          selectedPlanet={selectedPlanet}
          setSelectedPlanet={setSelectedPlanet}
        />
      </Canvas>
    </div>
  )
}