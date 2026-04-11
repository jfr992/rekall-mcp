import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('dashboard app', () => {
  it('renders the dashboard component from the app entrypoint', () => {
    const page = readFileSync(resolve(process.cwd(), 'app', 'page.tsx'), 'utf8');
    const dashboard = readFileSync(resolve(process.cwd(), 'components', 'dashboard.tsx'), 'utf8');

    expect(page).toContain('Dashboard');
    expect(dashboard).toContain('Brain + KB cockpit');
    expect(dashboard).toContain('setInterval(load, 5000)');
    expect(dashboard).toContain('Neural Graph');
    expect(dashboard).toContain('PressurePanel');
    expect(dashboard).toContain('HandoffPanel');
    expect(dashboard).toContain('KbPanel');
  });
});
