import { useEffect, useState } from 'react';
import { z } from 'zod-v3';
import { A2UIProvider, A2UIRenderer, createCatalog, useA2UI, useA2UIError } from '@copilotkit/a2ui-renderer';
import type { Panel } from './model';

type ComposedPanel = Extract<Panel, { kind: 'declarative' }>;
const definitions = {
  Column: { props: z.object({ children: z.array(z.string()) }), description: 'Vertical business layout' },
  Text: { props: z.object({ text: z.string() }), description: 'Plain text' },
  Metric: { props: z.object({ label: z.string(), value: z.string(), detail: z.string() }), description: 'Metric with its basis' },
  List: { props: z.object({ title: z.string(), items: z.array(z.string()) }), description: 'Titled list' },
  Table: { props: z.object({ columns: z.array(z.string()), rows: z.array(z.array(z.string())) }), description: 'Searchable business table' },
};
const catalogId = 'samurai://business/v1';
const catalog = createCatalog(definitions, {
  Column: ({ props, children }) => <div className="declarative-blocks">{props.children.map(id => <div key={id}>{children(id)}</div>)}</div>,
  Text: ({ props }) => <p className="declarative-text">{props.text}</p>,
  Metric: ({ props }) => <div className="declarative-metric"><span>{props.label}</span><strong>{props.value}</strong><small>{props.detail}</small></div>,
  List: ({ props }) => <div className="declarative-list"><strong>{props.title}</strong><ul>{props.items.map((item, index) => <li key={index}><span className="declarative-list-dot" aria-hidden="true" /><span>{item}</span></li>)}</ul></div>,
  Table: ({ props }) => <BusinessTable {...props} />,
}, { catalogId });

function BusinessTable({ columns, rows }: { columns: string[]; rows: string[][] }) {
  const [query, setQuery] = useState('');
  return <div className="declarative-table"><div className="declarative-table-toolbar"><span>{rows.filter(row => row.some(cell => cell.toLowerCase().includes(query.toLowerCase()))).length} rows</span><input className="panel-table-search" aria-label="Search table" placeholder="Search rows" value={query} onChange={event => setQuery(event.target.value)} /></div><div className="panel-table-scroll"><table><thead><tr>{columns.map((column, index) => <th scope="col" key={index}>{column}</th>)}</tr></thead><tbody>{rows.filter(row => row.some(cell => cell.toLowerCase().includes(query.toLowerCase()))).map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div></div>;
}

export function declarativeMessages(panel: ComposedPanel): Record<string, unknown>[] {
  const names = { text: 'Text', metric: 'Metric', list: 'List', table: 'Table' } as const;
  return [
    { version: 'v0.9', createSurface: { surfaceId: panel.id, catalogId } },
    { version: 'v0.9', updateComponents: { surfaceId: panel.id, components: [
      { id: 'root', component: 'Column', children: panel.blocks.map((_, index) => `block-${index}`) },
      ...panel.blocks.map(({ kind, ...props }, index) => ({ id: `block-${index}`, component: names[kind], ...props })),
    ] } },
  ];
}
function Surface({ panel }: { panel: ComposedPanel }) {
  const { processMessages, clearSurfaces } = useA2UI();
  const error = useA2UIError();
  const content = JSON.stringify(panel.blocks);
  useEffect(() => { clearSurfaces(); processMessages(declarativeMessages(panel)); }, [panel.id, content, processMessages, clearSurfaces]);
  return error ? <p role="alert" className="error-note">This view could not be displayed. Ask Samurai to revise it.</p> : <A2UIRenderer surfaceId={panel.id} />;
}
export function DeclarativePanel({ panel }: { panel: ComposedPanel }) {
  return <A2UIProvider catalog={catalog}><Surface panel={panel} /></A2UIProvider>;
}
