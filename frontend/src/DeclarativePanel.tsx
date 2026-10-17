import { z } from 'zod';
import { createLibrary, defineComponent } from '@openuidev/react-lang';
import { panelSchema, type Panel } from './model';
import { ComparisonBars, numericComparison } from './PanelCharts';
import { OpenUIRender } from './OpenUIRender';

type ComposedPanel = Extract<Panel, { kind: 'declarative' }>;
const Text = defineComponent({
  name: 'Text', description: 'Plain business text', props: z.object({ text: z.string() }),
  component: ({ props }) => <p className="declarative-text">{props.text}</p>,
});
const Metric = defineComponent({
  name: 'Metric', description: 'Metric with its basis', props: z.object({ label: z.string(), value: z.string(), detail: z.string() }),
  component: ({ props }) => <div className="declarative-metric"><span>{props.label}</span><strong>{props.value}</strong><small>{props.detail}</small></div>,
});
const List = defineComponent({
  name: 'List', description: 'Titled business list', props: z.object({ title: z.string(), items: z.array(z.string()) }),
  component: ({ props }) => <div className="declarative-list"><strong>{props.title}</strong><ul>{props.items.map((item, index) => <li key={index}><span className="declarative-list-dot" aria-hidden="true" /><span>{item}</span></li>)}</ul></div>,
});
const Table = defineComponent({
  name: 'Table', description: 'Business comparison table', props: z.object({ columns: z.array(z.string()), rows: z.array(z.array(z.string())) }),
  component: ({ props }) => <ComparisonTable {...props} />,
});
function ComparisonTable(props: { columns: string[]; rows: string[][] }) {
  const items = numericComparison(props.columns, props.rows);
  const table = <div className="declarative-table"><div className="panel-table-scroll"><table><caption className="sr-only">Comparison · {props.rows.length} rows</caption><thead><tr>{props.columns.map((column, index) => <th scope="col" key={index}>{column}</th>)}</tr></thead><tbody>{props.rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div></div>;
  return items ? <><ComparisonBars items={items} label={props.columns.join(' · ')} /><details className="panel-details"><summary>View comparison table</summary>{table}</details></> : table;
}
const Column = defineComponent({
  name: 'Column', description: 'Vertical business layout', props: z.object({ children: z.array(z.union([Text.ref, Metric.ref, List.ref, Table.ref])) }),
  component: ({ props, renderNode }) => <div className="declarative-blocks">{props.children.map((child, index) => <div key={index} data-block={child.typeName}>{renderNode(child)}</div>)}</div>,
});
export const businessLibrary = createLibrary({ root: 'Column', components: [Column, Text, Metric, List, Table] });

export function declarativeResponse(panel: ComposedPanel): string {
  const parsed = panelSchema.parse(panel);
  if (parsed.kind !== 'declarative') throw new Error('Expected composed panel');
  // Keep saved panels and the backend contract stable; only the rendering language changes.
  const blocks = parsed.blocks.map(block => {
    switch (block.kind) {
      case 'text': return `Text(${JSON.stringify(block.text)})`;
      case 'metric': return `Metric(${[block.label, block.value, block.detail].map(value => JSON.stringify(value)).join(', ')})`;
      case 'list': return `List(${JSON.stringify(block.title)}, ${JSON.stringify(block.items)})`;
      case 'table': return `Table(${JSON.stringify(block.columns)}, ${JSON.stringify(block.rows)})`;
    }
  });
  return `root = Column([${blocks.join(', ')}])`;
}
export function DeclarativePanel({ panel }: { panel: ComposedPanel }) {
  const response = declarativeResponse(panel);
  return <OpenUIRender response={response} library={businessLibrary} />;
}
