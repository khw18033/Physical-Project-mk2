// scripts/lib/detectViewsProbe.mjs (261102 신설 — 박스 근거)
//
// **탐지 근거 카드를 실제로 그려 본다.** `DetectViews.tsx` 는 TSX 라 노드가 바로 못 읽는다 — esbuild 로 그 화면과
// 저장소를 **한 묶음**으로 묶어(같은 저장소 인스턴스를 봐야 한다) `renderToString` 으로 그린다(`adjustRewindProbe.mjs` 와 같은 방법).
//
// 묶음은 두 벌을 만들 수 있다 — 지금 작업본과 **고치기 전 커밋**(`baselineTree`). 문 편 화면이 고치기 전과 한 글자도
// 안 바뀌었는지는 같은 입력을 두 묶음에 넣고 그린 글자를 견주어 본다.
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const vizRoot = join(fileURLToPath(new URL('.', import.meta.url)), '..', '..');
const repoRoot = join(vizRoot, '..');
const { build } = createRequire(join(vizRoot, 'package.json'))('esbuild');

/** `vizDir` 의 탐지 화면 · 저장소 · 사전을 한 묶음으로. `outFile` 에 쓰고 불러온다. */
export async function bundleDetectViews(vizDir, outFile) {
  const src = (...p) => JSON.stringify(join(resolve(vizDir), 'src', ...p).replaceAll('\\', '/'));
  await build({
    stdin: {
      contents: [
        `export * as scenario from ${src('data', 'scenario.ts')};`,
        `export * as store from ${src('detect', 'store.ts')};`,
        `export * as parse from ${src('detect', 'parse.ts')};`,
        `export { DetectReason, DetectCam } from ${src('detect', 'views', 'DetectViews.tsx')};`,
        "export { createElement } from 'react';",
        "export { renderToString } from 'react-dom/server';",
      ].join('\n'),
      resolveDir: resolve(vizDir),
      loader: 'js',
    },
    bundle: true, format: 'esm', platform: 'node', outfile: outFile, logLevel: 'silent',
    jsx: 'automatic',
    // 고치기 전 트리는 node_modules 가 없다 — 작업본의 것을 쓴다.
    nodePaths: [join(vizRoot, 'node_modules')],
    loader: { '.css': 'empty', '.png': 'empty', '.svg': 'empty', '.jpg': 'empty' },
    define: { 'import.meta.env': JSON.stringify({ DEV: false, PROD: true, MODE: 'test' }) },
    banner: { js: "import { createRequire as __cr } from 'node:module'; const require = __cr(import.meta.url);" },
  });
  return import(pathToFileURL(outFile).href);
}

/**
 * **고치기 전 커밋의 트리를 `dir` 에 꺼낸다.** 작업본의 색인(index)은 건드리지 않는다 — 임시 색인 파일에 읽어
 * 그 색인에서 꺼낸다. 화면이 읽는 자리만 꺼낸다(`src` 가 저장소 뿌리의 `contracts` · `equipment` · `places` 를 import 한다).
 * 돌려주는 값은 그 트리의 `viz-debugger` 자리다.
 */
export function baselineTree(commit, dir) {
  const env = { ...process.env, GIT_INDEX_FILE: join(dir, '.baseline-index') };
  const git = (args, input) => execFileSync('git', args, { cwd: repoRoot, env, input, encoding: 'utf8', maxBuffer: 1 << 26 });
  git(['read-tree', commit]);
  const paths = git(['ls-files', '--', 'viz-debugger/src', 'viz-debugger/scenarios', 'viz-debugger/capability-sample',
    'viz-debugger/stt', 'contracts', 'equipment', 'places', 'door_example/test']);
  const prefix = `${resolve(dir).replaceAll('\\', '/')}/tree/`;
  git(['checkout-index', `--prefix=${prefix}`, '--stdin'], paths);
  return join(dir, 'tree', 'viz-debugger');
}
