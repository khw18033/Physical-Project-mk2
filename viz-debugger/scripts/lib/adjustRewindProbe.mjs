// scripts/lib/adjustRewindProbe.mjs (261026 신설 — 조정 되감기)
//
// **실패 칸을 실제로 그려 본다.** `ActionModal.tsx` 는 TSX 라 노드가 바로 못 읽는다 — esbuild 로 그 화면과 저장소를
// **한 묶음**으로 묶어(같은 저장소 인스턴스를 봐야 한다) `renderToString` 으로 그린 글자를 센다. 판정은
// `verify:adjust-rewind` 가 한다.
//
// 판은 실물 `261026/024124_MSN-260909-01` 의 두 사건을 그대로 다시 적는다 — T-B1 의 `speed 0.35 → 0.25`(112.395초) ·
// `clearance 0.18 → 0.30`(140.858초). 기록 길(`recordAdjusted`)을 그대로 탄다.
//
//   node scripts/lib/adjustRewindProbe.mjs <root>   → stdout 에 JSON 한 줄
import { createRequire } from 'node:module';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const vizRoot = join(fileURLToPath(new URL('.', import.meta.url)), '..', '..');
const { build } = createRequire(join(vizRoot, 'package.json'))('esbuild');

export async function probe(root) {
  const src = (...p) => JSON.stringify(join(resolve(root), 'src', ...p).replaceAll('\\', '/'));
  const out = mkdtempSync(join(tmpdir(), 'adjust-rewind-'));
  try {
    const file = join(out, 'bundle.mjs');
    await build({
      stdin: {
        contents: [
          `export * as scenario from ${src('data', 'scenario.ts')};`,
          `export { ActionModal } from ${src('views', 'ActionModal.tsx')};`,
          "export { createElement } from 'react';",
          "export { renderToString } from 'react-dom/server';",
        ].join('\n'),
        resolveDir: resolve(root),
        loader: 'js',
      },
      bundle: true, format: 'esm', platform: 'node', outfile: file, logLevel: 'silent',
      jsx: 'automatic',
      loader: { '.css': 'empty', '.png': 'empty', '.svg': 'empty', '.jpg': 'empty' },
      define: { 'import.meta.env': JSON.stringify({ DEV: false, PROD: true, MODE: 'test' }) },
      // 묶음 안의 CJS(react)가 `require` 를 찾는다.
      banner: { js: "import { createRequire as __cr } from 'node:module'; const require = __cr(import.meta.url);" },
    });
    const { scenario, ActionModal, createElement, renderToString } = await import(pathToFileURL(file).href);

    scenario.previewMission('MSN-260909-01');
    const view = scenario.currentMission();
    const task = view.tasks.find((t) => t.id === 'T-B1');
    scenario.recordAdjusted({ commandId: 'T-B1', taskId: 'T-B1', field: 'speed', before: '0.35', after: '0.25', atSec: 112.395 });
    scenario.recordAdjusted({ commandId: 'T-B1', taskId: 'T-B1', field: 'clearance', before: '0.18', after: '0.30', atSec: 140.858 });
    const recorded = scenario.traceFor(view).filter((e) => e.kind === 'adjusted').length;

    const look = (props) => {
      const html = renderToString(createElement(ActionModal, { task, view, onClose: () => undefined, ...props }));
      const list = html.match(/<div class="robot-log__adjust[^"]*">([\s\S]*?)<\/div>/);
      return {
        inputs: (html.match(/<input /g) ?? []).length,
        list: list !== null,
        lines: list === null ? 0 : (list[1].match(/<li>|<li /g) ?? []).length,
        speed: html.includes('speed · 0.35 → 0.25'),
        clearance: html.includes('clearance · 0.18 → 0.30'),
      };
    };
    return {
      recorded,
      // 되감기 — 슬라이더 세 지점 · 따라가는 중(override 없음) · 실패 칸이 어떻게든 열린 경우
      rewind100: look({ rewind: true, second: 100 }),
      rewind120: look({ rewind: true, second: 120 }),
      rewind141: look({ rewind: true, second: 141 }),
      rewindFollow: look({ rewind: true }),
      rewindFailure: look({ rewind: true, failure: true, second: 120 }),
      // 라이브 실패 칸 — 입력칸 둘 · 목록
      live: look({ failure: true }),
    };
  } finally {
    rmSync(out, { recursive: true, force: true });
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const [root] = process.argv.slice(2);
  process.stdout.write(`${JSON.stringify(await probe(root))}\n`);
  process.exit(0);
}
