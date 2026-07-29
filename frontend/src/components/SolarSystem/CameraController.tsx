import { useRef, useEffect } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { useSolarSystemStore } from './store';

const UP = new THREE.Vector3(0, 1, 0);
const MOVE_SPEED = 2;
const FLY_SPEED = 0.5;
const FLY_OFFSET = new THREE.Vector3(0, 8, 20);
const DEFAULT_CAM_POS = new THREE.Vector3(0, 40, 80);
const DEFAULT_CAM_TARGET = new THREE.Vector3(0, 0, 0);

const easeOutCubic = (t: number): number => 1 - Math.pow(1 - t, 3);

export default function CameraController() {
  const { camera } = useThree();
  const keys = useRef<Record<string, boolean>>({});
  const flyStartRef = useRef<THREE.Vector3 | null>(null);
  const flyProgressRef = useRef<number>(0);
  const controlsRef = useRef<any>(null);
  const trackPos = useRef(new THREE.Vector3());

  const flyTarget = useSolarSystemStore((s) => s.flyTarget);
  const isFlying = useSolarSystemStore((s) => s.isFlying);
  const setFlying = useSolarSystemStore((s) => s.setFlying);
  const resetTrigger = useSolarSystemStore((s) => s.resetTrigger);
  const selectedPlanet = useSolarSystemStore((s) => s.selectedPlanet);

  // Reset Kamera + OrbitControls-Target, wenn resetTrigger sich ändert
  useEffect(() => {
    camera.position.copy(DEFAULT_CAM_POS);
    camera.lookAt(DEFAULT_CAM_TARGET);
    if (controlsRef.current) {
      controlsRef.current.target.copy(DEFAULT_CAM_TARGET);
      controlsRef.current.update();
    }
    flyStartRef.current = null;
    flyProgressRef.current = 0;
  }, [resetTrigger]);

  // Tastatur-Events — robust gegen Focus-Probleme
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      // Nur WASDQE abfangen, andere Keys (z.B. Slider) nicht stören
      if (['w', 'a', 's', 'd', 'e', 'q'].includes(k)) {
        keys.current[k] = true;
        e.preventDefault(); // verhindert Scrollen/Browser-Default bei diesen Tasten
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (['w', 'a', 's', 'd', 'e', 'q'].includes(k)) {
        keys.current[k] = false;
        e.preventDefault();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, []);

  useFrame((_, delta) => {
    // --- Fly-to animation ---
    if (flyTarget && isFlying) {
      if (flyStartRef.current === null) {
        flyStartRef.current = camera.position.clone();
        flyProgressRef.current = 0;
      }

      flyProgressRef.current = Math.min(1, flyProgressRef.current + delta * FLY_SPEED);
      const t = easeOutCubic(flyProgressRef.current);

      const targetPos = new THREE.Vector3(
        flyTarget.position[0] + FLY_OFFSET.x,
        flyTarget.position[1] + FLY_OFFSET.y,
        flyTarget.position[2] + FLY_OFFSET.z,
      );

      camera.position.lerpVectors(flyStartRef.current, targetPos, t);
      camera.lookAt(
        flyTarget.position[0],
        flyTarget.position[1],
        flyTarget.position[2],
      );

      // OrbitControls-Target auf Planeten-Position setzen, damit Fokus dort bleibt
      if (controlsRef.current) {
        controlsRef.current.target.set(
          flyTarget.position[0],
          flyTarget.position[1],
          flyTarget.position[2],
        );
        controlsRef.current.update();
      }

      if (flyProgressRef.current >= 1) {
        setFlying(false);
        flyProgressRef.current = 0;
        flyStartRef.current = null;
      }
      return;
    }

    // --- WASDQE movement (vor Tracking, damit freies Fliegen Vorrang hat) ---
    const forward = camera.getWorldDirection(new THREE.Vector3());
    const right = new THREE.Vector3().crossVectors(forward, UP).normalize();

    const move = new THREE.Vector3();
    if (keys.current['w']) move.add(forward);
    if (keys.current['s']) move.sub(forward);
    if (keys.current['d']) move.add(right);
    if (keys.current['a']) move.sub(right);
    if (keys.current['e']) move.add(UP);
    if (keys.current['q']) move.sub(UP);

    if (move.lengthSq() > 0) {
      move.normalize().multiplyScalar(MOVE_SPEED * delta * 60);
      camera.position.add(move);
      // OrbitControls-Target wird NICHT mitbewegt — Kamera fliegt frei,
      // unabhängig von der Planetenrotation.
      return; // Während freiem Flug kein Tracking-Override
    }

    // --- Tracking: fokussierten Planeten in der Bildmitte halten ---
    // Wenn ein Planet ausgewählt ist (und kein Fly-to läuft und keine WASDQE-Bewegung),
    // folgt das OrbitControls-Target kontinuierlich der Planeten-Position aus dem Store.
    if (selectedPlanet && controlsRef.current) {
      const pos = useSolarSystemStore.getState().planetPositions[selectedPlanet];
      if (pos) {
        trackPos.current.set(pos[0], pos[1], pos[2]);
        controlsRef.current.target.copy(trackPos.current);
        controlsRef.current.update();
      }
    }
  });

  return (
    <OrbitControls
      ref={controlsRef}
      makeDefault
      enableZoom
      enableKeys={false}
      mouseButtons={{
        LEFT: undefined as unknown as THREE.MOUSE,
        MIDDLE: THREE.MOUSE.DOLLY,
        RIGHT: THREE.MOUSE.ROTATE,
      }}
    />
  );
}