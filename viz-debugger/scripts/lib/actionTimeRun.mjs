// scripts/lib/actionTimeRun.mjs (261025 신설) — `actionTimeProbe.mjs` 를 **자식 프로세스 하나에 판 하나**로 띄운다.
//
// 판 상태가 모듈 전역이라 한 프로세스에서 두 판을 몰면 앞 판이 남는다. 대조군 트리도 같은 길로 몬다.
//
//   node scripts/lib/actionTimeRun.mjs <root> <door|local|gen>     → stdout 에 JSON 한 줄
import { execFileSync } from 'node:child_process';
import { cpSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { makeScratch } from './scratch.mjs';
import { mutate, readSource } from './source.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const vizRoot = join(here, '..', '..');

/** 판 하나를 자식 프로세스로 몬다. */
export function runProbe(root, which) {
  const out = execFileSync(process.execPath, [fileURLToPath(import.meta.url), root, which], {
    encoding: 'utf8', cwd: vizRoot, maxBuffer: 16 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'],
  });
  const line = out.trim().split('\n').filter((l) => l.startsWith('{')).at(-1);
  return JSON.parse(line);
}

/**
 * **대조군 트리.** `src/` · `scenarios/` 를 통째로 복사하고 파일 하나를 바꾼다. LF 로 정규화한 원본에서
 * 바꾼다(`readSource`). 치환이 아무것도 안 바꿨으면 `null` — 대조군을 못 만든 것이다.
 *
 * 트리는 `viz-debugger/.verify-<이름>-xxxx/viz/` 다. 한 칸 더 들어가는 이유 — `pi7Run` 이 `root/../door_example`
 * 의 경로 증거를 읽는다. 패키지(`react` · `mqtt` …)는 위로 올라가며 `viz-debugger/node_modules` 에서 풀린다.
 */
export function mutantTree(prefix, file, from, to) {
  const scratch = makeScratch(vizRoot, prefix);
  const root = join(scratch.dir, 'viz');
  cpSync(join(vizRoot, 'src'), join(root, 'src'), { recursive: true });
  cpSync(join(vizRoot, 'scenarios'), join(root, 'scenarios'), { recursive: true });
  const evidence = join('door_example', 'test', 'door', 'evidence.json');
  mkdirSync(dirname(join(scratch.dir, evidence)), { recursive: true });
  cpSync(join(vizRoot, '..', evidence), join(scratch.dir, evidence));
  const changed = mutate(readSource(vizRoot, file), from, to);
  if (changed === null) { scratch.cleanup(); return null; }
  // 쓰기는 원본 줄바꿈과 상관없이 LF 다 — 읽는 쪽(`node`)은 상관하지 않는다.
  writeFileSync(join(root, file), changed, 'utf8');
  return { root, cleanup: scratch.cleanup };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const [root, which] = process.argv.slice(2);
  const { probe } = await import(pathToFileURL(join(here, 'actionTimeProbe.mjs')).href);
  const result = await probe(root, which);
  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exit(0);
}
