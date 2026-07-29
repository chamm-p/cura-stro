import { useTexture } from '@react-three/drei'
import * as THREE from 'three'
import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'

export type SunProps = {
  onClick?: () => void
}

const glowVertexShader = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const glowFragmentShader = /* glsl */ `
  varying vec2 vUv;
  void main() {
    float dist = length(vUv - 0.5) * 2.0;
    if (dist < 0.44) discard;
    float t = (dist - 0.44) / (1.0 - 0.44);
    float glow = exp(-t * 2.0) * 0.35;
    float edgeFade = 1.0 - smoothstep(0.5, 0.85, dist);
    glow *= edgeFade;
    vec3 color = mix(vec3(1.0, 0.85, 0.45), vec3(1.0, 0.45, 0.1), t);
    gl_FragColor = vec4(color, glow);
  }
`

export function Sun({ onClick }: SunProps) {
  const texture = useTexture('/textures/sun.jpg')
  const glowRef = useRef<THREE.Mesh>(null)

  const glowMaterial = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: glowVertexShader,
        fragmentShader: glowFragmentShader,
        transparent: true,
        blending: THREE.AdditiveBlending,
        side: THREE.DoubleSide,
        depthWrite: false,
        toneMapped: false,
      }),
    []
  )

  useFrame(({ camera }) => {
    if (glowRef.current) {
      glowRef.current.lookAt(camera.position)
    }
  })

  return (
    <group>
      {/* Sonnenkugel mit Textur */}
      <mesh onClick={onClick}>
        <sphereGeometry args={[4, 64, 64]} />
        <meshBasicMaterial map={texture} toneMapped={false} />
      </mesh>

      {/* Billboard-Corona-Glow: hellster Punkt direkt am Sonnenrand, nach außen abblendend */}
      <mesh ref={glowRef} material={glowMaterial}>
        <planeGeometry args={[18, 18]} />
      </mesh>

      {/* Lichtquelle */}
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