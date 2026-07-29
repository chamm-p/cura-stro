import { useRef, useState } from 'react'
import * as THREE from 'three'
import { useFrame } from '@react-three/fiber'
import { useTexture } from '@react-three/drei'
import { PlanetData } from '../../data/planets'
import PlanetLabel from './PlanetLabel'
import { useSolarSystemStore } from './store'

interface PlanetProps {
  data: PlanetData
  onClick: () => void
  isSelected: boolean
}

export default function Planet({ data, onClick, isSelected }: PlanetProps) {
  const groupRef = useRef<THREE.Group>(null)
  const spinRef = useRef<THREE.Mesh>(null)
  const angleRef = useRef(0)
  const spinRef2 = useRef(0)
  const [hovered, setHovered] = useState(false)
  const texture = useTexture(data.textureMap)
  texture.colorSpace = THREE.SRGBColorSpace

  // Sichtbarer Planet — Wurzel-Skalierung dämpft Größenunterschiede.
  const size = Math.max(0.8, Math.sqrt(data.radius) * 0.8)

  // Unsichtbarer, größerer Treffer-Mesh für zuverlässiges Hover/Klick
  const hitSize = Math.max(size * 2.5, 2.5)

  // Saturn-Ring: nur für Saturn rendern
  const hasRing = data.name === 'Saturn'
  const ringInner = size * 1.4
  const ringOuter = size * 2.3

  // Bahn-Parameter (gleiche Formel wie Orbit.tsx)
  const a = data.semiMajorAxis
  const e = data.eccentricity
  const b = a * Math.sqrt(1 - e * e)
  const incl = (data.inclination * Math.PI) / 180

  useFrame((state, delta) => {
    const timeWarp = useSolarSystemStore.getState().timeWarp

    // --- Elliptische Bahn-Position (group) — Kepler-Formel wie Orbit.tsx ---
    // Sonne sitzt im Brennpunkt (Ursprung); Ellipse ist um -e verschoben.
    angleRef.current += (delta * 0.5 * timeWarp) / data.period
    const theta = angleRef.current
    const x0 = a * (Math.cos(theta) - e)
    const z0 = b * Math.sin(theta)
    // Neigung: rotiere die Ellipse um die X-Achse
    const y = z0 * Math.sin(incl)
    const z = z0 * Math.cos(incl)

    if (groupRef.current) {
      groupRef.current.position.set(x0, y, z)
    }

    // --- Position in den Store schreiben (für Kamera-Tracking) ---
    useSolarSystemStore.setState((s) => ({
      planetPositions: { ...s.planetPositions, [data.name]: [x0, y, z] },
    }))

    // --- Eigenrotation um die Achse (innerer Mesh) ---
    // rotationPeriod in Stunden; Erde = 23.93h → 1 U/min bei timeWarp=1
    // Negative Rotationsperiode = retrograde Rotation (Venus, Uranus)
    const rotSpeed = data.rotationPeriod !== 0 ? (24 / data.rotationPeriod) : 0
    spinRef2.current += delta * rotSpeed * timeWarp * 0.5
    if (spinRef.current) {
      spinRef.current.rotation.y = spinRef2.current
    }
  })

  return (
    <group ref={groupRef}>
      {/* Sichtbarer Planet — rotiert um eigene Achse */}
      <mesh
        ref={spinRef}
        onClick={onClick}
        onPointerOver={(e) => {
          e.stopPropagation()
          setHovered(true)
          document.body.style.cursor = 'pointer'
        }}
        onPointerOut={(e) => {
          e.stopPropagation()
          setHovered(false)
          document.body.style.cursor = 'default'
        }}
        castShadow
        receiveShadow
      >
        <sphereGeometry args={[size, 64, 64]} />
        <meshStandardMaterial
          map={texture}
          roughness={0.9}
          metalness={0.0}
          emissive={isSelected ? data.color : '#000000'}
          emissiveIntensity={isSelected ? 0.3 : 0}
        />
      </mesh>

      {/* Saturn-Ring — geneigte Scheibe um den Planeten */}
      {hasRing && (
        <mesh rotation={[Math.PI / 2.2, 0, 0]} receiveShadow>
          <ringGeometry args={[ringInner, ringOuter, 128]} />
          <meshStandardMaterial
            color="#d4c5a0"
            side={THREE.DoubleSide}
            transparent
            opacity={0.85}
            roughness={0.8}
            metalness={0.0}
          />
        </mesh>
      )}

      {/* Unsichtbarer Treffer-Mesh — erleichtert Hover & Klick */}
      <mesh
        onClick={onClick}
        onPointerOver={(e) => {
          e.stopPropagation()
          setHovered(true)
          document.body.style.cursor = 'pointer'
        }}
        onPointerOut={(e) => {
          e.stopPropagation()
          setHovered(false)
          document.body.style.cursor = 'default'
        }}
      >
        <sphereGeometry args={[hitSize, 16, 16]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {/* Hover-Label — immer (auch bei Auswahl), außer Sonne */}
      <PlanetLabel name={data.nameDE} visible={hovered || isSelected} />
    </group>
  )
}