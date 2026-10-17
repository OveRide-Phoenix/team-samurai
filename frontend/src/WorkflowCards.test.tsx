import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { CompanyWorkspace } from './App';
import { emptyWorkspace } from './model';

it('retains management cards below the map with forms collapsed', () => {
  const workspace = emptyWorkspace();
  const company = { id: 'company-test', name: 'Card layout', workspace, workspaceId: '00000000-0000-4000-8000-000000000001', companyId: '00000000-0000-4000-8000-000000000002', currentRevision: 0, stateSha256: 'a'.repeat(64) };
  const html = renderToStaticMarkup(<CompanyWorkspace company={company} workspace={workspace} setWorkspace={() => undefined} mode="light" toggleMode={() => undefined} onOpen={() => undefined} initialView="company" storageError={false} />);
  const files = html.indexOf('aria-label="Workspace files"');
  const operations = html.indexOf('aria-label="Founder operations"');
  expect(files).toBeGreaterThan(html.indexOf('class="home-panels"'));
  expect(operations).toBeGreaterThan(files);
  expect(html).toContain('data-panel-id="utility-files"');
  expect(html).toContain('data-panel-id="utility-operations"');
  expect(html).not.toContain('<details open');
});

it('keeps pinned panels in Mentor and the graph beside the same OpenUI conversation', () => {
  const panel = { id: 'saved', kind: 'evidence' as const, title: 'Research evidence', note: '', claims: [] };
  const workspace = { ...emptyWorkspace(), pinned: [panel], messages: [{ id: 'm', role: 'assistant' as const, text: '', panel }] };
  const props = { company: { id: 'shared-chat', name: 'Idea', workspace }, workspace, setWorkspace: () => undefined, mode: 'light' as const, toggleMode: () => undefined, onOpen: () => undefined, storageError: false };
  const mentor = renderToStaticMarkup(<CompanyWorkspace {...props} />);
  expect(mentor.slice(mentor.indexOf('<aside'), mentor.indexOf('</aside>'))).toContain('Research evidence');
  expect(mentor).toContain('Pinned panels');
  const map = renderToStaticMarkup(<CompanyWorkspace {...props} initialView="company" />);
  expect(map).toContain('aria-label="Idea aspect map"');
  expect(map).not.toContain('idea-question-branch');
  expect(map.slice(map.indexOf('<main'))).toContain('Research evidence');
  expect(map).toContain('aria-label="Guided aspect question"');
});

it('opens in Mentor with an OpenUI chat question and no checkpoint form cards', () => {
  const workspace = emptyWorkspace();
  const html = renderToStaticMarkup(<CompanyWorkspace company={{ id: 'chat-first', name: 'Software idea', workspace }} workspace={workspace} setWorkspace={() => undefined} mode="light" toggleMode={() => undefined} onOpen={() => undefined} storageError={false} />);
  expect(html).toContain('aria-label="Guided aspect question"');
  expect(html).toContain('Who experiences this problem');
  expect(html).toContain('class="aspect-guide"');
  expect(html).not.toContain('class="aspect-checkpoints"');
  expect(html).not.toContain('class="aspect-field"');
});

it('keeps the first pass with its original reply so later mentor feedback follows it', () => {
  const panel = { id: 'intake', kind: 'evidence' as const, title: 'Idea brief', note: '', claims: [], idea_analysis: { summary: 'Demand remains untested.', starting_points: [] } };
  const workspace = { ...emptyWorkspace(), messages: [{ id: 'first', role: 'assistant' as const, text: '', panel }, { id: 'feedback', role: 'assistant' as const, text: 'New evidence changes the recommendation.' }] };
  const html = renderToStaticMarkup(<CompanyWorkspace company={{ id: 'ordered-chat', name: 'Idea', workspace }} workspace={workspace} setWorkspace={() => undefined} mode="light" toggleMode={() => undefined} onOpen={() => undefined} storageError={false} />);
  const firstPass = html.indexOf('aria-label="Mentor first pass"');
  const feedback = html.indexOf('New evidence changes the recommendation.');
  expect(firstPass).toBeGreaterThan(-1);
  expect(feedback).toBeGreaterThan(firstPass);
  expect(html.indexOf('aria-label="Guided aspect question"')).toBeGreaterThan(feedback);
});
