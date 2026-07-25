import { useState, useRef, useMemo, useCallback, useEffect } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Stars } from '@react-three/drei'
import * as THREE from 'three'

interface Planet {
  name: string
  nameDE: string
  color: string
  radius: number
  semiMajorAxis: number
  eccentricity: number
  inclination: number
  period: number
  rotationPeriod: number
  axialTilt: number
  moons: number
  atmosphere: string
  temperature: string
  mass: string
  discovery: string
  description: string
}

const PLANETS: Planet[] = [
  {
    name: 'Mercury', nameDE: 'Merkur', color: '#A0A0A0',
    radius: 0.383, semiMajorAxis: 0.387, eccentricity: 0.206,
    inclination: 7.0, period: 87.97, rotationPeriod: 1407.6,
    axialTilt: 0.034, moons: 0, atmosphere: 'Extrem dünn (O, Na, K)',
    temperature: '-173 bis 427 °C', mass: '0.055 Erdmassen',
    discovery: 'Bekannt seit der Antike',
    description: 'Der kleinste und sonnennächste Planet — eine karge, von Kratern bedeckte Wüste.',
  },
  {
    name: 'Venus', nameDE: 'Venus', color: '#E8CDA0',
    radius: 0.949, semiMajorAxis: 0.723, eccentricity: 0.007,
    inclination: 3.4, period: 224.7, rotationPeriod: -5832.5,
    axialTilt: 177.4, moons: 0, atmosphere: 'CO₂ (96,5%), N₂ (3,5%)',
    temperature: '462 °C (Oberfläche)', mass: '0.815 Erdmassen',
    discovery: 'Bekannt seit der Antike',
    description: 'Die glühende Zwillingin der Erde — ein Treibhausplanet mit dichter Wolendecke.',
  },
  {
    name: 'Earth', nameDE: 'Erde', color: '#4F86F7',
    radius: 1.0, semiMajorAxis: 1.0, eccentricity: 0.017,
    inclination: 0.0, period: 365.25, rotationPeriod: 1436.1,
    axialTilt: 23.44, moons: 1, atmosphere: 'N₂ (78%), O₂ (21%)',
    temperature: '-89 bis 57 °C', mass: '1 Erdmasse',
    discovery: 'Bekannt seit der Antike',
    description: 'Unser blauer Planet — der einzige bekannte Welt mit flüssigem Wasser und Leben.',
  },
  {
    name: 'Mars', nameDE: 'Mars', color: '#E06B30',
    radius: 0.532, semiMajorAxis: 1.524, eccentricity: 0.093,
    inclination: 1.85, period: 687.0, rotationPeriod: 1477.0,
    axialTilt: 25.19, moons: 2, atmosphere: 'CO₂ (95,3%), N₂ (2,7%)',
    temperature: '-140 bis 20 °C', mass: '0.107 Erdmassen',
    discovery: 'Bekannt seit der Antike',
    description: 'Der rote Planet — mit dem höchsten Vulkan und tiefsten Canyon des Sonnensystems.',
  },
  {
    name: 'Jupiter', nameDE: 'Jupiter', color: '#D4A574',
    radius: 11.21, semiMajorAxis: 5.203, eccentricity: 0.048,
    inclination: 1.3, period: 4332.6, rotationPeriod: 997.3,
    axialTilt: 3.13, moons: 95, atmosphere: 'H₂ (89,8%), He (10,2%)',
    temperature: '-108 °C (Wolkenobergrenze)', mass: '317.8 Erdmassen',
    discovery: 'Bekannt seit der Antike',
    description: 'Der Gasriese mit dem Großen Roten Fleck — ein ständiger Sturm größer als die Erde.',
  },
  {
    name: 'Saturn', nameDE: 'Saturn', color: '#E8D191',
    radius: 9.45, semiMajorAxis: 9.537, eccentricity: 0.054,
    inclination: 2.49, period: 10759.2, rotationPeriod: 1070.6,
    axialTilt: 26.73, moons: 146, atmosphere: 'H₂ (96,3%), He (3,3%)',
    temperature: '-139 °C (Wolkenobergrenze)', mass: '95.2 Erdmassen',
    discovery: 'Bekannt seit der Antike',
    description: 'Der Ringplanet — ein golden schimmernder Gasriese mit einem atemberaubenden Ringsystem.',
  },
  {
    name: 'Uranus', nameDE: 'Uranus', color: '#A8D8E8',
    radius: 4.01, semiMajorAxis: 19.19, eccentricity: 0.047,
    inclination: 0.77, period: 30688.5, rotationPeriod: -1724.3,
    axialTilt: 97.77, moons: 28, atmosphere: 'H₂ (82,5%), He (15,2%), CH₄ (2,3%)',
    temperature: '-197 °C (Wolkenobergrenze)', mass: '14.5 Erdmassen',
    discovery: '1781 von William Herschel',
    description: 'Der eisige Riese — rotiert auf der Seite wie ein rollender Ball.',
  },
  {
    name: 'Neptune', nameDE: 'Neptun', color: '#5B5DDF',
    radius: 3.88, semiMajorAxis: 30.07, eccentricity: 0.009,
    inclination: 1.77, period: 60189.9, rotationPeriod: 1611.0,
    axialTilt: 28.32, moons: 16, atmosphere: 'H₂ (80%), He (19%), CH₄ (1%)',
    temperature: '-201 °C (Wolkenobergrenze)', mass: '17.1 Erdmassen',
    discovery: '1846 durch mathematische Vorhersage',
    description: 'Der fernste Planet — mit den stärksten Winden des Sonnensystems (bis 2.100 km/h).',
  },
]

function InfoPanelItem({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid rgba(123,167,217,0.2)' }}>
      <span style={{ color: '#7BA7D9', fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</span>
      <span style={{ color: '#E8EEF7', fontSize: '12px', fontFamily: "'JetBrains Mono', monospace" }}>{value}</span>
    </div>
  )
}

function Sun({ onClick }: { onClick: () => void }) {
  return (
    <mesh onClick={onClick} position={[0, 0, 0]}>
      <sphereGeometry args={[2, 64, 64]} />
      <meshStandardMaterial
        color="#FDB813"
        emissive="#FDB813"
        emissiveIntensity={2}
        toneMapped={false}
      />
    </mesh>
  )
}

function PlanetMesh({
  planet,
  time,
  scale,
  isSelected,
  onClick,
}: {
  planet: Planet
  time: number
  scale: number
  isSelected: boolean
  onClick: () => void
}) {
  const orbitRadius = planet.semiMajorAxis * scale
  const angle = (time / planet.period) * Math.PI * 2
  const x = Math.cos(angle) * orbitRadius
  const z = Math.sin(angle) * orbitRadius
  const radius = Math.max(0.15, planet.radius * 0.3)

  return (
    <group>
      <mesh onClick={onClick} position={[x, 0, z]}>
        <sphereGeometry args={[radius, 32, 32]} />
        <meshStandardMaterial
          color={planet.color}
          emissive={isSelected ? '#F5B942' : planet.color}
          emissiveIntensity={isSelected ? 1.5 : 0.3}
          toneMapped={false}
        />
      </mesh>
      {isSelected && (
        <mesh position={[x, 0, z]}>
          <sphereGeometry args={[radius * 1.3, 32, 32]} />
          <meshBasicMaterial
            color="#F5B942"
            transparent
            opacity={0.2}
          />
        </mesh>
      )}
    </group>
  )
}

function OrbitLine({ radius, scale, color = '#7BA7D9' }: { radius: number; scale: number; color?: string }) {
  const points = useMemo(() => {
    const pts = []
    for (let i = 0; i <= 128; i++) {
      const angle = (i / 128) * Math.PI * 2
      pts.push(new THREE.Vector3(Math.cos(angle) * radius * scale, 0, Math.sin(angle) * radius * scale))
    }
    return pts
  }, [radius, scale])

  return (
    <line>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={points.length}
          array={new Float32Array(points.flatMap((p) => [p.x, p.y, p.z]))}
          itemSize={3}
        />
      </bufferGeometry>
      <lineBasicMaterial color={color} transparent opacity={0.4} />
    </line>
  )
}

function SolarSystemCanvas({
  selectedPlanet,
  setSelectedPlanet,
}: {
  selectedPlanet: Planet | null
  setSelectedPlanet: (p: Planet | null) => void
}) {
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

      <Sun
        onClick={() =>
          setSelectedPlanet({
            name: 'Sun',
            nameDE: 'Sonne',
            color: '#FDB813',
            radius: 109,
            semiMajorAxis: 0,
            eccentricity: 0,
            inclination: 0,
            period: 0,
            rotationPeriod: 609.12,
            axialTilt: 7.25,
            moons: 0,
            atmosphere: 'Plasma (H, He)',
            temperature: '5.500 °C (Oberfläche)',
            mass: '333.000 Erdmassen',
            discovery: 'Bekannt seit der Antike',
            description:
              'Unser Stern — eine gelbe Zwergstern vom Typ G2V. Sie enthält 99,86% der Masse des gesamten Sonnensystems.',
          })
        }
      />

      {PLANETS.map((planet) => (
        <group key={planet.name}>
          <OrbitLine radius={planet.semiMajorAxis} scale={scale} />
          <PlanetMesh
            planet={planet}
            time={time}
            scale={scale}
            isSelected={selectedPlanet?.name === planet.name}
            onClick={() => setSelectedPlanet(planet)}
          />
        </group>
      ))}

      <OrbitControls
        enablePan={true}
        enableZoom={true}
        enableRotate={true}
        minDistance={5}
        maxDistance={100}
      />
    </>
  )
}

export default function SolarSystem() {
  const [selectedPlanet, setSelectedPlanet] = useState<Planet | null>(null)

  return (
    <div
      className="relative w-full"
      style={{
        background: '#050810',
        height: '100vh',
        minHeight: '600px',
        position: 'relative',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 10,
          pointerEvents: 'none',
          padding: '16px 24px',
        }}
      >
        <h1
          style={{
            margin: 0,
            fontSize: '24px',
            fontWeight: 700,
            color: '#E8EEF7',
          }}
        >
          Sonnensystem
        </h1>
      </div>

      <Canvas
        camera={{ position: [0, 12, 20], fov: 50 }}
        gl={{ antialias: true, alpha: false }}
        style={{
          background: '#050810',
          width: '100%',
          height: '100%',
        }}
      >
        <SolarSystemCanvas
          selectedPlanet={selectedPlanet}
          setSelectedPlanet={setSelectedPlanet}
        />
      </Canvas>

      {selectedPlanet && (
        <div
          style={{
            position: 'absolute',
            top: 0,
            right: 0,
            width: '360px',
            height: '100%',
            background: '#0D1526',
            borderLeft: '1px solid rgba(123,167,217,0.3)',
            padding: '24px',
            overflowY: 'auto',
            boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
            zIndex: 20,
          }}
        >
          <h2
            style={{
              margin: '0 0 16px 0',
              fontSize: '24px',
              fontWeight: 700,
              color: '#E8EEF7',
            }}
          >
            {selectedPlanet.nameDE}
          </h2>
          <p
            style={{
              margin: '0 0 24px 0',
              fontSize: '14px',
              lineHeight: 1.5,
              color: '#7BA7D9',
            }}
          >
            {selectedPlanet.description}
          </p>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: '8px',
              marginBottom: '24px',
            }}
          >
            <div
              style={{
                background: 'rgba(123,167,217,0.1)',
                borderRadius: '6px',
                padding: '12px',
                textAlign: 'center',
              }}
            >
              <div
                style={{
                  fontSize: '12px',
                  color: '#7BA7D9',
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                  marginBottom: '4px',
                }}
              >
                Durchmesser
              </div>
              <div
                style={{
                  fontSize: '18px',
                  fontWeight: 700,
                  color: '#E8EEF7',
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                {(selectedPlanet.radius * 12742).toFixed(0)} km
              </div>
            </div>
            <div
              style={{
                background: 'rgba(123,167,217,0.1)',
                borderRadius: '6px',
                padding: '12px',
                textAlign: 'center',
              }}
            >
              <div
                style={{
                  fontSize: '12px',
                  color: '#7BA7D9',
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                  marginBottom: '4px',
                }}
              >
                Entfernung
              </div>
              <div
                style={{
                  fontSize: '18px',
                  fontWeight: 700,
                  color: '#E8EEF7',
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                {selectedPlanet.semiMajorAxis.toFixed(2)} AE
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <InfoPanelItem label="Umlaufzeit" value={`${selectedPlanet.period.toFixed(1)} Tage`} />
            <InfoPanelItem label="Rotation" value={`${selectedPlanet.rotationPeriod.toFixed(0)} h`} />
            <InfoPanelItem label="Achsenneigung" value={`${selectedPlanet.axialTilt.toFixed(1)}°`} />
            <InfoPanelItem label="Exzentrizität" value={selectedPlanet.eccentricity.toFixed(3)} />
            <InfoPanelItem label="Bahnneigung" value={`${selectedPlanet.inclination.toFixed(1)}°`} />
            <InfoPanelItem label="Mond(e)" value={selectedPlanet.moons.toString()} />
            <InfoPanelItem label="Atmosphäre" value={selectedPlanet.atmosphere} />
            <InfoPanelItem label="Temperatur" value={selectedPlanet.temperature} />
            <InfoPanelItem label="Masse" value={selectedPlanet.mass} />
            <InfoPanelItem label="Entdeckung" value={selectedPlanet.discovery} />
          </div>
        </div>
      )}
    </div>
  )
}