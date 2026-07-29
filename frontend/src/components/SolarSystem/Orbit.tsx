import { useMemo } from 'react';
import * as THREE from 'three';

export interface OrbitProps {
  semiMajorAxis: number;
  eccentricity: number;
  inclination: number;
  color?: string;
}

export default function Orbit({
  semiMajorAxis,
  eccentricity,
  inclination,
  color = '#64a0ff',
}: OrbitProps) {
  const positions = useMemo(() => {
    const a = semiMajorAxis;
    const e = eccentricity;
    const b = a * Math.sqrt(1 - e * e);
    const segments = 256;
    const arr = new Float32Array(segments * 3);

    for (let i = 0; i < segments; i++) {
      const theta = (i / segments) * Math.PI * 2;
      const x = a * (Math.cos(theta) - e);
      const z0 = b * Math.sin(theta);
      const y = z0 * Math.sin(inclination);
      const z = z0 * Math.cos(inclination);
      arr[i * 3] = x;
      arr[i * 3 + 1] = y;
      arr[i * 3 + 2] = z;
    }
    return arr;
  }, [semiMajorAxis, eccentricity, inclination]);

  return (
    <line>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
        />
      </bufferGeometry>
      <lineBasicMaterial
        color={color}
        transparent
        opacity={0.25}
        depthWrite={false}
        depthTest={true}
        toneMapped={false}
        polygonOffset
        polygonOffsetFactor={1}
      />
    </line>
  );
}