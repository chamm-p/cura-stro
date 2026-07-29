import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { useFrame } from '@react-three/fiber'
import { useSolarSystemStore } from './store'

/**
 * Asteroidengürtel zwischen Mars (Achse 22) und Jupiter (Achse 40).
 * ~2500 kleine Felsen auf leicht verteilten elliptischen Bahnen.
 * Rotieren langsam um die Sonne, Geschwindigkeit folgt timeWarp.
 */
const COUNT = 2500
const INNER = 25
const OUTER = 32

export default function AsteroidBelt() {
  const meshRef = useRef<THREE.InstancedMesh>(null)
  const dummy = useMemo(() => new THREE.Object3D(), [])

  // Stabile, deterministische Zufallswerte pro Asteroid
  const asteroids = useMemo(() => {
    const arr: { a: number; e: number; phase: number; incl: number; scale: number; rotSpeed: number }[] = []
    for (let i = 0; i < COUNT; i++) {
      const a = INNER + Math.random() * (OUTER - INNER)
      const e = Math.random() * 0.08
      const phase = Math.random() * Math.PI * 2
      const incl = (Math.random() - 0.5) * 0.06 // leichte Neigung
      const scale = 0.05 + Math.random() * 0.12
      const rotSpeed = 0.5 + Math.random() * 1.5
      arr.push({ a, e, phase, incl, scale, rotSpeed })
    }
    return arr
  }, [])

  const bValues = useMemo(
    () => asteroids.map((ast) => ast.a * Math.sqrt(1 - ast.e * ast.e)),
    [asteroids],
  )

  useFrame((state, delta) => {
    const timeWarp = useSolarSystemStore.getState().timeWarp
    if (!meshRef.current) return

    for (let i = 0; i < asteroids.length; i++) {
      const ast = asteroids[i]
      ast.phase += (delta * 0.5 * timeWarp) / (ast.a / 16) // langsamere äußere Bahnen
      const theta = ast.phase
      const x0 = ast.a * (Math.cos(theta) - ast.e)
      const z0 = bValues[i] * Math.sin(theta)
      const y = z0 * Math.sin(ast.incl)
      const z = z0 * Math.cos(ast.incl)

      dummy.position.set(x0, y, z)
      dummy.rotation.set(theta * ast.rotSpeed, theta * ast.rotSpeed * 0.7, 0)
      dummy.scale.setScalar(ast.scale)
      dummy.updateMatrix()
      meshRef.current.setMatrixAt(i, dummy.matrix)
    }
    meshRef.current.instanceMatrix.needsUpdate = true
  })

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, COUNT]} castShadow={false} receiveShadow={false}>
      <dodecahedronGeometry args={[1, 0]} />
      <meshStandardMaterial color="#8a7a6a" roughness={0.95} metalness={0.0} />
    </instancedMesh>
  )
}