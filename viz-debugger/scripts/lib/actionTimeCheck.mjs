// scripts/lib/actionTimeCheck.mjs (261025 신설) — 액션 층 시각 검사 셋의 공통 틀.
//
// 원본 트리를 몰아 판정이 **통과**해야 하고, 대조군 트리마다 같은 판정이 **실패**해야 한다. 대조군은 LF 로
// 정규화한 원본에서 한 줄을 바꾼 `src/` 사본이다(`actionTimeRun.mjs` 의 `mutantTree`).
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mutantTree, runProbe } from './actionTimeRun.mjs';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

/**
 * @param name     검사 이름(출력용)
 * @param judge    `(probes) => string[]` — 위반 문장 목록. 빈 배열이면 통과
 * @param boards   몰 판 이름들(`door` · `local` · `gen`)
 * @param controls `[{ name, prefix, file, from, to }]`
 */
export function checkWithControls(name, { judge, boards, controls }) {
  const failures = [];
  const drive = (root) => Object.fromEntries(boards.map((b) => [b, runProbe(root, b)]));

  const real = drive(vizRoot);
  const found = judge(real);
  for (const line of found) failures.push(line);
  if (found.length === 0) console.log(`✅ 원본 — ${boards.join(' · ')} 판 판정 통과`);

  const caught = [];
  for (const c of controls) {
    const tree = mutantTree(c.prefix, c.file, c.from, c.to);
    if (tree === null) { failures.push(`대조군을 만들지 못했다: ${c.name} — 치환이 아무것도 안 바꿨다 (${c.file})`); continue; }
    try {
      const hit = judge(drive(tree.root));
      if (hit.length > 0) caught.push(`${c.name} (${hit[0].slice(0, 70)})`);
      else failures.push(`대조군 실패: ${c.name} — 변조 사본이 잡히지 않았다`);
    } finally {
      tree.cleanup();
    }
  }
  if (failures.length > 0) {
    console.error(`❌ ${name} — ${failures.length}건\n- ${failures.join('\n- ')}`);
    process.exit(1);
  }
  console.log(`✅ 대조군 ${caught.length}건 전부 검출 — ${caught.join(' · ')}`);
  return real;
}

/** 판 하나의 층별 사건. */
export const of = (probe, layer, kind) => probe.events.filter((e) => e.layer === layer && (kind === undefined || e.kind === kind));
export const fmt = (n) => Number(n).toFixed(3);
