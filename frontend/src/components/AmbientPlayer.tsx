import { useEffect, useRef } from 'react';

export default function AmbientPlayer() {
  const ref = useRef<HTMLAudioElement>(null);
  useEffect(() => {
    const a = ref.current;
    if (!a) return;
    a.volume = 0.3;
    const tryPlay = () => { a.play().catch(() => {}); };
    tryPlay();
    document.addEventListener('click', tryPlay, { once: true });
    return () => document.removeEventListener('click', tryPlay);
  }, []);
  return <audio ref={ref} src="/audio/ambient.mp3" loop autoPlay preload="auto" hidden />;
}