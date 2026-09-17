// verify:clean (260917 신설 — 검사 위생 지시서 §3③)
//
// 대조군 임시 폴더를 한 번에 비운다.
//
// 평소에는 쓸 일이 없어야 한다 — `lib/scratch.mjs` 가 만들 때 형제를 쓸고 끝날 때 치운다.
// 이 명령이 필요한 때는 **정리가 실패해서 「N개를 못 지웠다」가 떴을 때**다. 윈도우에서
// 열린 모듈 핸들 때문에 `EPERM` 이 나면 그 판에서는 못 지우고, 프로세스가 끝난 뒤에는 지워진다.
import { readdirSync, rmSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { SCRATCH_PREFIX } from './lib/scratch.mjs';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..');

const found = [];
(function walk(dir) {
  let entries;
  try { entries = readdirSync(dir); } catch { return; }
  for (const name of entries) {
    if (name === 'node_modules' || name === '.git') continue;
    const path = join(dir, name);
    let isDir;
    try { isDir = statSync(path).isDirectory(); } catch { continue; }
    if (!isDir) continue;
    if (name.startsWith(SCRATCH_PREFIX)) { found.push(path); continue; } // 안으로 더 안 들어간다
    walk(path);
  }
})(vizRoot);

if (found.length === 0) {
  console.log('✅ 비어 있다 — 대조군 임시 디렉터리 0개');
  process.exit(0);
}

const stuck = [];
for (const path of found) {
  try {
    rmSync(path, { recursive: true, force: true });
    console.log(`   지움  ${relative(vizRoot, path).replaceAll('\\', '/')}`);
  } catch (error) {
    stuck.push({ path, reason: error?.code ?? String(error) });
  }
}

if (stuck.length > 0) {
  console.error(`\n❌ ${stuck.length}개를 못 지웠다 — 검사가 아직 돌고 있거나 파일 핸들이 열려 있다.`);
  for (const item of stuck) console.error(`   ${relative(vizRoot, item.path).replaceAll('\\', '/')}  (${item.reason})`);
  process.exit(1);
}

console.log(`\n✅ ${found.length}개를 지웠다`);
