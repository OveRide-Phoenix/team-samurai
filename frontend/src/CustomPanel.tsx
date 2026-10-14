import { useEffect, useMemo, useRef, useState } from 'react';
import interFont from '@fontsource-variable/inter/files/inter-latin-wght-normal.woff2?inline';
import sharedControls from './panel-controls.css?inline';
import type { Panel } from './model';

type CustomView = Extract<Panel, { kind: 'custom' }>;
export function sandboxDocument(panel: CustomView, mode: 'light' | 'dark' = 'light'): string {
  const css = panel.css.replace(/<\/style/gi, '<\\/style');
  const javascript = panel.javascript.replace(/<\/script/gi, '<\\/script');
  const theme = mode === 'dark' ? ['#f4eee6','#c0afa1','#e6c8a4','#2c231b','rgba(83,69,57,.90)','#ead4b62e'] : ['#352e2b','#73635b','#695043','#ffffff','#f5eee6cc','#725b4629'];
  const tokens = ['foreground','muted-foreground','primary','primary-foreground','surface','border'].map((name, index) => `--${name}:${theme[index]}!important`).join(';');
  // The first important layer owns the house controls, even when generated CSS uses !important.
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; style-src-attr 'none'; img-src data:; font-src data:; connect-src 'none'; frame-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"><style>@layer samurai;@font-face{font-family:'Inter Variable';font-style:normal;font-weight:100 900;src:url('${interFont}') format('woff2')}@layer samurai{:root{color-scheme:${mode};${tokens}}html{background:transparent!important}${sharedControls}}</style><style>${css}</style></head><body class="samurai-custom">${panel.html}<script>${javascript}</script><script>(()=>{const report=()=>parent.postMessage({type:'samurai:custom:size',height:Math.ceil(document.body.getBoundingClientRect().height)},'*');new ResizeObserver(report).observe(document.body);document.fonts.ready.then(report);report()})()</script></body></html>`;
}
export function customFrameHeight(event: { source: unknown; origin: string; data: unknown }, source: unknown): number | undefined {
  if (!source || event.source !== source || event.origin !== 'null' || !event.data || typeof event.data !== 'object') return undefined;
  const value = event.data as Record<string, unknown>;
  if (Object.keys(value).length !== 2 || value.type !== 'samurai:custom:size' || typeof value.height !== 'number' || !Number.isSafeInteger(value.height) || value.height < 0) return undefined;
  return Math.max(120, Math.min(720, value.height + 2));
}
export function CustomPanel({ panel, compact, mode }: { panel: CustomView; compact: boolean; mode: 'light' | 'dark' }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(220);
  const document = useMemo(() => sandboxDocument(panel, mode), [panel.html, panel.css, panel.javascript, mode]);
  useEffect(() => {
    const resize = (event: MessageEvent<unknown>) => {
      const next = customFrameHeight(event, frame.current?.contentWindow);
      if (next !== undefined) setHeight(next);
    };
    window.addEventListener('message', resize);
    return () => window.removeEventListener('message', resize);
  }, []);
  return compact ? <p>Expand to use this custom view.</p> : <iframe ref={frame} className="custom-panel-frame" style={{height}} title={panel.title} srcDoc={document} sandbox="allow-scripts" referrerPolicy="no-referrer" loading="eager" />;
}
