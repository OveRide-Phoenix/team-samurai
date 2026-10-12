import { MeshGradient } from '@paper-design/shaders-react';
import { useEffect, useState } from 'react';

const palettes = {
  light: ['#fff4e7', '#efbda5', '#c9c2ec', '#f6d6bd'],
  dark: ['#201d1c', '#46382f', '#333038', '#655143'],
};

// The mesh shader engine used by beui.dev/components/motion/shader-background.
export function Atmosphere({ mode }: { mode: 'light' | 'dark' }) {
  const [reduce, setReduce] = useState(true);
  const [supported, setSupported] = useState(false);
  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const syncMotion = () => setReduce(preference.matches);
    syncMotion();
    preference.addEventListener('change', syncMotion);
    const probe = document.createElement('canvas');
    const gl = probe.getContext('webgl2');
    setSupported(Boolean(gl));
    gl?.getExtension('WEBGL_lose_context')?.loseContext();
    return () => preference.removeEventListener('change', syncMotion);
  }, []);
  return <div className="atmosphere" aria-hidden="true" data-motion={reduce ? 'static' : 'animated'}>{supported && <MeshGradient
    className="atmosphere-shader" colors={palettes[mode]} speed={reduce === false ? 0.12 : 0}
    distortion={0.65} swirl={0.2} grainOverlay={0.02} minPixelRatio={1} maxPixelCount={1_000_000}
    style={{ width: '100%', height: '100%' }}
  />}</div>;
}
