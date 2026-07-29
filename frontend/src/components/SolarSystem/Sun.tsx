import { useTexture } from '@react-three/drei'

export type SunProps = {
  onClick?: () => void
}

export function Sun({ onClick }: SunProps) {
  const texture = useTexture('/textures/sun.jpg')

  return (
    <group>
      <mesh onClick={onClick}>
        <sphereGeometry args={[4, 64, 64]} />
        <meshBasicMaterial map={texture} toneMapped={false} />
      </mesh>
      <pointLight
        position={[0, 0, 0]}
        intensity={4.0}
        distance={0}
        decay={0}
        castShadow
        shadow-mapSize={[4096, 4096]}
        shadow-camera-near={1}
        shadow-camera-far={500}
        shadow-bias={-0.001}
      />
    </group>
  )
}