import { Suspense } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Stars } from '@react-three/drei'
import { EffectComposer, Bloom, Vignette } from '@react-three/postprocessing'
import * as THREE from 'three'
import { Link } from 'react-router-dom'
import { PLANETS, SUN_DATA, EARTH_MOONS, type PlanetData, type MoonData } from '../data/planets'
import { Sun } from '../components/SolarSystem/Sun'
import Orbit from '../components/SolarSystem/Orbit'
import Planet from '../components/SolarSystem/Planet'
import CameraController from '../components/SolarSystem/CameraController'
import { useSolarSystemStore } from '../components/SolarSystem/store'
import InfoPanel from '../components/SolarSystem/InfoPanel'
import TimeWarpSlider from '../components/SolarSystem/TimeWarpSlider'
import AsteroidBelt from '../components/SolarSystem/AsteroidBelt'

function SimulationTicker() {
  const tickSimulation = useSolarSystemStore((s) => s.tickSimulation)
  useFrame((_, delta) => {
    tickSimulation(delta)
  })
  return null
}

function Scene() {
  const { camera } = useThree()
  const selectedPlanet = useSolarSystemStore((s) => s.selectedPlanet)
  const selectPlanet = useSolarSystemStore((s) => s.selectPlanet)
  const selectedMoon = useSolarSystemStore((s) => s.selectedMoon)
  const selectMoon = useSolarSystemStore((s) => s.selectMoon)

  camera.position.set(0, 30, 60)

  return (
    <>
      <ambientLight intensity={0.03} />

      <Stars radius={300} depth={50} count={5000} factor={4} saturation={0} fade speed={1} />

      <Sun onClick={() => selectPlanet(SUN_DATA.name, [0, 0, 0])} />

      {/* Asteroidengürtel zwischen Mars (22) und Jupiter (40) */}
      <AsteroidBelt />

      {PLANETS.map((p) => {
        const a = p.semiMajorAxis
        const e = p.eccentricity
        const startX = a * (1 - e)
        const startZ = 0
        return (
          <group key={p.name}>
            <Orbit
              eccentricity={p.eccentricity}
              semiMajorAxis={a}
              inclination={(p.inclination * Math.PI) / 180}
              color="#64a0ff"
            />
            <Planet
              data={p}
              onClick={() => selectPlanet(p.name, [startX, 0, startZ])}
              isSelected={selectedPlanet === p.name}
              moons={p.name === 'Earth' ? EARTH_MOONS : undefined}
              onMoonClick={p.name === 'Earth' ? (moonData, pos) => selectMoon(moonData, pos) : undefined}
            />
          </group>
        )
      })}

      <SimulationTicker />

      <CameraController />

      <EffectComposer multisampling={4}>
        <Bloom mipmapBlur intensity={0.8} luminanceThreshold={0.2} luminanceSmoothing={0.3} radius={0.8} />
        <Vignette eskil={false} offset={0.1} darkness={0.6} />
      </EffectComposer>
    </>
  )
}

export default function SolarSystem() {
  const selectedPlanet = useSolarSystemStore((s) => s.selectedPlanet)
  const selectedMoon = useSolarSystemStore((s) => s.selectedMoon)
  const selectedData: PlanetData | null =
    selectedPlanet === SUN_DATA.name
      ? SUN_DATA
      : PLANETS.find((p) => p.name === selectedPlanet) ?? null

  return (
    <div className="relative w-full h-screen bg-black">
      <audio autoPlay loop src="/assets/ambient.mp3" />
      <div className="absolute top-4 left-4 z-10">
        <Link
          to="/"
          className="px-4 py-2 bg-white/10 hover:bg-white/20 text-white rounded-lg backdrop-blur-sm transition-colors"
        >
          ← Dashboard
        </Link>
      </div>

      <Canvas
        shadows
        camera={{ fov: 50 }}
        gl={{
          antialias: true,
          toneMapping: THREE.ACESFilmicToneMapping,
        }}
      >
        <Suspense fallback={null}>
          <Scene />
        </Suspense>
      </Canvas>

      <TimeWarpSlider />

      {/* Planet InfoPanel */}
      {selectedData && (
        <InfoPanel
          data={selectedData}
          onClose={() => useSolarSystemStore.getState().clearSelection()}
        />
      )}

      {/* Moon InfoPanel */}
      {selectedMoon && !selectedData && (
        <InfoPanel
          data={selectedMoon}
          onClose={() => useSolarSystemStore.getState().clearMoonSelection()}
        />
      )}
    </div>
  )
}