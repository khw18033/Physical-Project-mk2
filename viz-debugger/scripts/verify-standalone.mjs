// 탭① 단독 빌드가 셸·다른 탭과 얽히지 않았는지 검사한다.
// 논문 측정축 D는 이 빌드로 재는 것이므로, 관제·영상 탭 코드가 섞이면 측정이 오염된다.
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, normalize, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const sourceRoot = normalize(fileURLToPath(new URL('../src/', import.meta.url)));
const entry = join(sourceRoot, 'standalone.tsx');

/** @param inject 진입점에 덧붙일 가짜 import. 음성 대조군 확인용. */
function scan(inject = '') {
  const visited = new Set();
  const forbidden = [];
  function visit(path) {
    if (visited.has(path)) return;
    visited.add(path);
    const source = readFileSync(path, 'utf8') + (path === entry ? inject : '');
    for (const match of source.matchAll(/from\s+['"](\.[^'"]+)['"]/g)) {
      const next = normalize(join(dirname(path), match[1]));
      if (!/\.(ts|tsx)$/.test(next)) continue;
      const rel = relative(sourceRoot, next).replaceAll('\\', '/');
      // **260916 — `shell/` 이 빠졌다** (단독 빌드 정합 §5).
      //
      // 08-28 에 이 줄을 그을 때 `shell/` 은 「탭 전환 기계」였고, 그래서 「shell/ 금지」가
      // 「탭②~⑤ 부하 금지」와 같은 말이었다. 그 뒤 `shell/` 은 상단 바에 붙는 것들의 서랍이
      // 됐고, 이 줄은 대리 지표를 계속 지키느라 **모드 스위치·연결 관리·긴급정지를 19일간
      // 전달본 밖에 세워 뒀다.** 아무도 그렇게 하기로 결정한 적이 없다.
      //
      // 진짜 기준은 `tabs/` 다 — 대시보드 데이터 계층이 단독 번들에 섞이면 측정축 D 가
      // 오염된다. 셸은 이제 `tabs/` 를 모른다(주입으로 끊었다).
      if (rel.startsWith('tabs/')) forbidden.push(rel);
      if (existsSync(next)) visit(next);
    }
  }
  visit(entry);
  return { visited, forbidden };
}

const actual = scan();
if (actual.forbidden.length) {
  console.error(`❌ 탭① 단독 진입점이 셸/다른 탭을 import함: ${actual.forbidden.join(', ')}`);
  process.exit(1);
}

// 음성 대조군 — 일부러 대시보드 데이터 계층을 끌어오면 반드시 잡혀야 한다.
//
// **260916 — 주입 대상이 셸에서 `tabs/` 로 바뀌었다.** 전에는 `shell/AppShell.tsx` 를 넣어
// 봤는데 그건 이제 정상이라 대조군 구실을 못 한다. 막고 싶은 것을 그대로 넣어야 대조가 된다.
if (scan("\nimport { store } from './tabs/data/index.ts';").forbidden.length === 0) {
  console.error('❌ tabs/ import를 주입한 음성 대조군을 검출하지 못했다 — 이 검사는 무의미하다');
  process.exit(1);
}

if (!existsSync(new URL('../dist-standalone/standalone.html', import.meta.url))) {
  console.error('❌ dist-standalone이 없다. 먼저 npm run build:standalone을 실행해야 한다');
  process.exit(1);
}
console.log(`✅ 통과 — 단독 빌드 존재, 의존 그래프 ${actual.visited.size}개 파일에 셸/다른 탭 import 0건, 주입 시 실패 검출`);
