import { readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

/** Windows and macOS file systems ignore case: `Foo.tsx` next to `foo.ts` resolves to the wrong
 *  module there (the build only works on Linux). Module names must differ in more than case. */
function modules(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (name === 'node_modules' || name.startsWith('.')) return [];
    return statSync(path).isDirectory() ? modules(path) : /\.(tsx?|jsx?|css)$/.test(name) ? [path] : [];
  });
}

describe('source file names', () => {
  it('have no case-insensitive collisions (Windows build)', () => {
    const seen = new Map<string, string>();
    const clashes: string[] = [];
    for (const file of [...modules('src'), ...modules('tests'), ...modules('e2e')]) {
      const key = relative('.', file).toLowerCase().replace(/\.(tsx?|jsx?)$/, '');
      const other = seen.get(key);
      if (other && other !== file) clashes.push(`${other} ↔ ${file}`);
      seen.set(key, file);
    }
    expect(clashes).toEqual([]);
  });
});
