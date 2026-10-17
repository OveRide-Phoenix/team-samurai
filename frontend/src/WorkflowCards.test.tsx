import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { CompanyWorkspace } from './App';
import { emptyWorkspace } from './model';

it('places management cards inside the measured card grid with forms collapsed', () => {
  const workspace = emptyWorkspace();
  const company = { id: 'company-test', name: 'Card layout', workspace, workspaceId: '00000000-0000-4000-8000-000000000001', companyId: '00000000-0000-4000-8000-000000000002', currentRevision: 0, stateSha256: 'a'.repeat(64) };
  const html = renderToStaticMarkup(<CompanyWorkspace company={company} workspace={workspace} setWorkspace={() => undefined} mode="light" toggleMode={() => undefined} onOpen={() => undefined} storageError={false} />);
  const files = html.indexOf('aria-label="Workspace files"');
  const operations = html.indexOf('aria-label="Founder operations"');
  expect(files).toBeGreaterThan(html.indexOf('class="home-panels"'));
  expect(operations).toBeGreaterThan(files);
  expect(html).toContain('data-panel-id="utility-files"');
  expect(html).toContain('data-panel-id="utility-operations"');
  expect(html).not.toContain('<details open');
});
