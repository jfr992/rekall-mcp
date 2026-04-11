import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('ui scaffold', () => {
  it('has a Next.js app shell', () => {
    expect(existsSync(resolve(process.cwd(), 'app', 'page.tsx'))).toBe(true);
    expect(existsSync(resolve(process.cwd(), 'components', 'dashboard.tsx'))).toBe(true);

    const page = readFileSync(resolve(process.cwd(), 'app', 'page.tsx'), 'utf8');
    const dashboard = readFileSync(resolve(process.cwd(), 'components', 'dashboard.tsx'), 'utf8');

    expect(page).toContain('Dashboard');
    expect(dashboard).toContain('Brain + KB cockpit');
  });
});
