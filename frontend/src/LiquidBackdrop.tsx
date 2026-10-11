import LiquidGlass from 'liquid-glass-react';
import { useLayoutEffect, useRef, useState } from 'react';

// Only the backdrop refracts; existing content and controls stay sharp and accessible.
export function LiquidBackdrop({ radius = 28 }: { radius?: number }) {
  const host = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState('');
  useLayoutEffect(() => {
    // The library measures its rim only on mount/window resize; our controls also resize with layout.
    const observer = new ResizeObserver(([entry]) => setSize(`${entry.contentRect.width}:${entry.contentRect.height}`));
    if (host.current) observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  return <div ref={host} className="liquid-backdrop" aria-hidden="true"><LiquidGlass key={size}
    displacementScale={30} blurAmount={0.015} saturation={115}
    aberrationIntensity={0.3} elasticity={0} cornerRadius={radius} padding="0"
    className="liquid-lens" style={{ position: 'absolute', top: '50%', left: '50%', width: '100%', height: '100%' }}
  ><span /></LiquidGlass></div>;
}
