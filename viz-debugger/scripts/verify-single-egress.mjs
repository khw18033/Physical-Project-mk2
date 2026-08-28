import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../src/', import.meta.url));
const files = [];
function walk(directory) {
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) walk(path);
    else if (/\.(ts|tsx)$/.test(name)) files.push(path);
  }
}
walk(root);

function exits(extra = '') {
  return files.flatMap((path) => {
    if (path.endsWith(join('transport', 'WsTransport.ts'))) return [];
    const source = readFileSync(path, 'utf8') + (path.endsWith('commandEgress.ts') ? extra : '');
    return [...source.matchAll(/\.publishCommand\s*\(/g)].map(() => relative(root, path));
  });
}

const actual = exits();
if (actual.length !== 1 || !actual[0].replaceAll('\\', '/').endsWith('shared/commandEgress.ts')) {
  console.error(`❌ 명령 출구 ${actual.length}개: ${actual.join(', ')}`);
  process.exit(1);
}
if (exits('\ngetTransport().publishCommand({});').length !== 2) {
  console.error('❌ 두 번째 출구를 주입한 음성 대조군을 검출하지 못했다');
  process.exit(1);
}
console.log('✅ 통과 — 앱 명령 출구 1개(shared/commandEgress.ts), 두 번째 출구 주입 시 실패 검출');
