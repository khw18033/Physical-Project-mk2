// scripts/lib/scratch.mjs (260917 신설 — 검사 위생 지시서 §3)
//
// **대조군 사본이 사는 임시 폴더.** 만드는 자리와 치우는 자리를 하나로 모은다.
//
// ## 왜 `src/` 안에 만드나
//
// 대조군은 원본을 한 군데 무력화한 사본이고, 그 사본이 `import` 로 이웃 모듈을 끌어온다.
// 상대 경로가 풀리려면 **원본 옆**에 있어야 한다. `os.tmpdir()` 에 두면 import 가 깨진다.
// 그 자체는 맞는 설계다.
//
// ## 무엇이 문제였나 — 조용한 정리 실패
//
// ```js
// try { rmSync(scratch, { recursive: true, force: true }); }
// catch { console.warn('임시 디렉터리 정리 실패 — ' + scratch); }   // ← 삼킨다
// ```
//
// 윈도우에서 열린 모듈 핸들 때문에 `EPERM` 이 나면 폴더가 남는다. 그리고 **남은 것이 다른
// 검사의 판정을 바꿨다.** 260917 에 실제로 일어난 일:
//
// ```
// ❌ verify:trace-append
// - 기록 열을 따로 만드는 곳이 있다: src/data/.verify-human-acukey/trace-3.ts, … 6건
// ```
//
// `verify:human-trace` 가 흘린 파일을 `verify:trace-append` 가 위반으로 셌다. `.gitignore` 에
// 접두사가 8줄까지 늘어난 것이 그 증상이었다 — 「끝나면 스스로 지운다」고 적어 두고
// 안 지워지니까 한 줄씩 더한 것이다.
//
// ## 그래서 셋을 한다
//
// 1. **만들 때 같은 접두사의 오래된 형제를 먼저 지운다** — 앞 실행이 흘렸어도 다음 실행이 치운다
// 2. **정리 실패를 안 삼킨다** — 모아 뒀다가 끝날 때 눈에 띄게 적는다
// 3. 그래도 판정은 잔여물에 안 흔들려야 한다 — 그건 이 파일이 아니라 **훑는 쪽**의 몫이다
//    (`isScratchPath()` 를 쓴다)

import { mkdtempSync, readdirSync, rmSync, statSync } from 'node:fs';
import { join } from 'node:path';

/** 임시 폴더 이름의 약속. 이 접두사 하나로 `.gitignore`·제외 판정·청소가 다 걸린다. */
export const SCRATCH_PREFIX = '.verify-';

/**
 * 이 경로가 대조군 임시 폴더 안인가.
 *
 * **`src/` 를 훑는 검사는 전부 이것으로 걸러야 한다.** 남의 쓰레기가 내 판정을 바꾸면 안 된다.
 * 잔여물이 0이어도 넣는다 — 정리는 실패할 수 있고, 판정은 아니다.
 */
export function isScratchPath(path) {
  return String(path).replaceAll('\\', '/').split('/').some((part) => part.startsWith(SCRATCH_PREFIX));
}

/** 못 지운 것들. 끝날 때 한 번에 적는다. */
const unswept = [];

/** 같은 접두사의 오래된 형제를 지운다. 앞 실행이 흘린 것을 다음 실행이 치우는 자리다. */
function sweepSiblings(parent, prefix) {
  let entries;
  try {
    entries = readdirSync(parent);
  } catch {
    return; // 부모가 아직 없으면 지울 형제도 없다.
  }
  for (const name of entries) {
    if (!name.startsWith(prefix)) continue;
    const path = join(parent, name);
    try {
      if (!statSync(path).isDirectory()) continue;
      rmSync(path, { recursive: true, force: true });
    } catch {
      // 지금 도는 다른 검사가 쓰고 있을 수도 있다. 여기서 막지 않는다 —
      // 못 지운 것은 아래 `cleanup()` 과 `verify:clean` 이 다시 본다.
    }
  }
}

/**
 * 대조군 임시 폴더를 만든다.
 *
 * @param parent  원본 옆 — 상대 import 가 풀리는 자리여야 한다
 * @param prefix  `.verify-` 로 시작해야 한다 (제외 판정과 `.gitignore` 가 그 약속에 걸린다)
 */
export function makeScratch(parent, prefix) {
  if (!prefix.startsWith(SCRATCH_PREFIX)) {
    throw new Error(`임시 폴더 접두사는 '${SCRATCH_PREFIX}' 로 시작해야 한다 — 받은 값: ${prefix}`);
  }
  sweepSiblings(parent, prefix);
  const dir = mkdtempSync(join(parent, prefix));
  return {
    dir,
    /** 파일 하나의 경로. */
    file: (name) => join(dir, name),
    /**
     * 치운다. **실패해도 검사를 떨어뜨리지 않는다** — 정리 실패는 위반이 아니다.
     * 다만 조용히 넘어가지도 않는다. 끝날 때 목록으로 뜬다.
     */
    cleanup: () => {
      try {
        rmSync(dir, { recursive: true, force: true });
      } catch (error) {
        unswept.push({ dir, reason: error?.code ?? String(error) });
      }
    },
  };
}

/**
 * 못 지운 것을 **눈에 띄게** 적는다. 프로세스가 끝날 때 저절로 돈다 —
 * 스크립트마다 손으로 부르게 하면 빼먹는 곳이 생기고, 빼먹은 그 조용함이 원래 문제였다.
 */
process.on('exit', () => {
  if (unswept.length === 0) return;
  console.warn(`\n⚠️  임시 디렉터리 ${unswept.length}개를 못 지웠다 — 다음 검사의 판정을 바꿀 수 있다.`);
  for (const item of unswept) console.warn(`    ${item.dir}  (${item.reason})`);
  console.warn('    `npm run verify:clean` 으로 비운다.');
});
