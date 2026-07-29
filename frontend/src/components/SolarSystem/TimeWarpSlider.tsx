import { useSolarSystemStore } from "./store";

function formatTimeWarp(value: number): string {
  if (value === 0) return "⏸ Pause";
  if (Number.isInteger(value)) {
    return `${value}×`;
  }
  return `${value.toFixed(1)}×`;
}

function formatSimulatedDate(date: Date): string {
  return date.toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function TimeWarpSlider() {
  const timeWarp = useSolarSystemStore((s) => s.timeWarp);
  const setTimeWarp = useSolarSystemStore((s) => s.setTimeWarp);
  const simulatedDate = useSolarSystemStore((s) => s.simulatedDate);
  const resetView = useSolarSystemStore((s) => s.resetView);

  const isPaused = timeWarp === 0;

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-20 pointer-events-none">
      <div className="pointer-events-auto bg-black/40 backdrop-blur-md rounded-xl px-6 py-3 border border-white/10 text-white shadow-lg transition-all duration-300">
        <div className="flex items-center gap-4">
          <span className="text-sm font-medium tracking-wide select-none">
            Time Warp
          </span>
          <input
            type="range"
            min={0}
            max={10}
            step={0.1}
            value={timeWarp}
            onChange={(e) => setTimeWarp(parseFloat(e.target.value))}
            onKeyDown={(e) => e.preventDefault()}
            onKeyUp={(e) => e.preventDefault()}
            className="accent-cyan-400 w-64 cursor-pointer"
            tabIndex={-1}
          />
          <span className="text-sm font-mono tabular-nums min-w-[4.5rem] text-right">
            {formatTimeWarp(timeWarp)}
          </span>
          {/* Pause / Resume Button */}
          <button
            onClick={() => setTimeWarp(isPaused ? 1 : 0)}
            className="ml-2 px-3 py-1 rounded-lg bg-white/10 hover:bg-white/20 border border-white/15 text-sm transition-colors"
            title={isPaused ? "Abspielen" : "Pause"}
          >
            {isPaused ? "▶" : "⏸"}
          </button>
          {/* Reset View Button */}
          <button
            onClick={() => resetView()}
            className="px-3 py-1 rounded-lg bg-white/10 hover:bg-white/20 border border-white/15 text-sm transition-colors"
            title="Ansicht zurücksetzen"
          >
            ↺
          </button>
        </div>
        <div className="mt-1 text-center text-xs font-mono tabular-nums text-white/70">
          {formatSimulatedDate(simulatedDate)}
        </div>
      </div>
    </div>
  );
}