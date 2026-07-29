import { create } from 'zustand';
import { MoonData } from '../../data/planets';

type Vec3 = [number, number, number];

interface FlyTarget {
  position: Vec3;
  name: string;
}

interface SolarSystemState {
  selectedPlanet: string | null;
  selectedMoon: MoonData | null;
  flyTarget: FlyTarget | null;
  isFlying: boolean;
  timeWarp: number;
  simulatedDate: Date;
  // Aktuelle Welt-Positionen der Planeten (wird jeden Frame von Planet.tsx aktualisiert)
  planetPositions: Record<string, Vec3>;
  selectPlanet: (name: string, position: Vec3) => void;
  clearSelection: () => void;
  selectMoon: (moonData: MoonData, position: Vec3) => void;
  clearMoonSelection: () => void;
  setFlying: (v: boolean) => void;
  setTimeWarp: (v: number) => void;
  tickSimulation: (deltaSeconds: number) => void;
  resetView: () => void;
  resetTrigger: number;
}

export const useSolarSystemStore = create<SolarSystemState>((set) => ({
  selectedPlanet: null,
  selectedMoon: null,
  flyTarget: null,
  isFlying: false,
  timeWarp: 0.5,
  resetTrigger: 0,
  simulatedDate: new Date(),
  planetPositions: {},
  selectPlanet: (name, position) =>
    set({ selectedPlanet: name, flyTarget: { position, name }, isFlying: true }),
  clearSelection: () =>
    set({ selectedPlanet: null, selectedMoon: null, flyTarget: null, isFlying: false }),
  selectMoon: (moonData, position) =>
    set({ selectedMoon: moonData, selectedPlanet: null, flyTarget: { position, name: moonData.name }, isFlying: true }),
  clearMoonSelection: () =>
    set({ selectedMoon: null }),
  setFlying: (v) => set({ isFlying: v }),
  setTimeWarp: (v) => set({ timeWarp: v }),
  tickSimulation: (deltaSeconds) =>
    set((state) => ({
      simulatedDate: new Date(
        state.simulatedDate.getTime() + deltaSeconds * state.timeWarp * 86400 * 1000
      ),
    })),
  resetView: () =>
    set((state) => ({
      selectedPlanet: null,
      selectedMoon: null,
      flyTarget: null,
      isFlying: false,
      timeWarp: 1,
      resetTrigger: state.resetTrigger + 1,
    })),
}));