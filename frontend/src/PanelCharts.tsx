import { motion, useReducedMotion } from 'motion/react';
import { EASE_OUT } from './components/beui/ease';

export type ChartSegment = { label: string; value: number };
const tones = ['var(--chart-peach)', 'var(--chart-lavender)', 'var(--chart-taupe)'];

// Data-driven SVG charts, using beUI motion tokens and Bklit's quiet ring/legend treatment.
export function ShareRing({ segments, value, label }: { segments: ChartSegment[]; value: string; label: string }) {
  const reduced = useReducedMotion();
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  let offset = 0;
  return <div className="visual-ring-summary"><div className="visual-ring"><svg viewBox="0 0 160 160" role="img" aria-label={segments.map(segment => `${segment.label}: ${segment.value}`).join(', ')}>
    <circle cx="80" cy="80" r="65" fill="none" stroke="var(--border)" strokeWidth="12" />
    {segments.map((segment, index) => {
      const length = total ? segment.value / total * 100 : 0;
      const start = offset; offset += length;
      return length > 0 && <motion.circle key={segment.label} cx="80" cy="80" r="65" fill="none" stroke={tones[index % tones.length]} strokeWidth="12" pathLength="100" strokeDashoffset={-start} strokeDasharray={`${Math.max(0, length - (length < 100 ? 2 : 0))} 100`} transform="rotate(-90 80 80)" initial={reduced ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: .5, ease: EASE_OUT }} />;
    })}</svg><div className="visual-ring-center"><strong>{value}</strong><span>{label}</span></div></div><div className="visual-legend">{segments.map((segment, index) => <div key={segment.label}><i style={{ background: tones[index % tones.length] }} /><span>{segment.label}</span><strong>{segment.value}</strong></div>)}</div></div>;
}

export function ComparisonBars({ items, label }: { items: { label: string; value: number; display: string }[]; label: string }) {
  const reduced = useReducedMotion();
  const max = Math.max(...items.map(item => item.value), 0);
  return <figure className="comparison-bars" aria-label={label}>{items.slice(0, 6).map((item, index) => <div className="comparison-bar" key={index}><div><span>{item.label}</span><strong>{item.display}</strong></div><div className="comparison-track"><motion.div style={{ background: tones[index % tones.length] }} initial={reduced ? false : { width: 0 }} animate={{ width: `${max > 0 ? item.value / max * 100 : 0}%` }} transition={{ duration: .65, ease: EASE_OUT }} /></div></div>)}</figure>;
}

export function numericComparison(columns: string[], rows: string[][]) {
  if (columns.length !== 2 || rows.length < 2) return null;
  const parsed = rows.map(row => row.length === 2 ? row[1].trim().match(/^([$€£₹]?)(\d+(?:,\d{3})*(?:\.\d+)?)(\s*(?:%|\/\s*(?:mo|month|year)|per month|per year))?$/i) : null);
  if (parsed.some(value => !value || !Number.isFinite(Number(value[2].replaceAll(',', ''))))) return null;
  const unit = (match: RegExpMatchArray) => `${match[1]}|${(match[3] || '').toLowerCase().replaceAll(/\s/g, '')}`;
  if (parsed.some(match => unit(match!) !== unit(parsed[0]!))) return null;
  return rows.map((row, index) => ({ label: row[0], display: row[1], value: Number(parsed[index]![2].replaceAll(',', '')) }));
}

export function ScenarioLines({ trajectories, horizon }: { trajectories: { label: string; points: { day: number; value: number | string }[] }[]; horizon: number }) {
  const values = trajectories.flatMap(trajectory => trajectory.points.map(point => Number(point.value)));
  const scale = Math.max(...values.map(Math.abs), 1);
  const low = Math.min(0, ...values.map(value => value / scale));
  const high = Math.max(0, ...values.map(value => value / scale));
  const y = (value: number | string) => 148 - ((Number(value) / scale - low) / (high - low || 1)) * 124;
  return <figure className="scenario-lines" aria-label="Scenario endpoints only"><svg viewBox="0 0 340 185" role="img" aria-label={trajectories.map(trajectory => `${trajectory.label}: ${trajectory.points.map(point => `day ${point.day}, ${point.value}`).join(' to ')}`).join('; ')}>
    {[24, 86, 148].map(row => <line key={row} x1="12" x2="328" y1={row} y2={row} stroke="var(--border)" strokeDasharray="3 6" />)}
    {trajectories.map((trajectory, index) => <g key={trajectory.label}><polyline fill="none" stroke={tones[index % tones.length]} strokeWidth="3" strokeLinecap="round" points={trajectory.points.map(point => `${12 + point.day / horizon * 304},${y(point.value)}`).join(' ')} />{trajectory.points.map((point, p) => <circle key={p} cx={12 + point.day / horizon * 304} cy={y(point.value)} r="4" fill={tones[index % tones.length]} />)}</g>)}
    <text x="12" y="178">Today</text><text x="316" y="178" textAnchor="end">Day {horizon}</text>
  </svg><figcaption>Possible outcomes · based on your assumptions</figcaption></figure>;
}
