/**
 * scripts/dev-all.mjs
 *
 * 목 게이트웨이 · Vite 개발 서버 · STT 서비스를 한 번에 띄운다.
 * 라이브러리를 늘리지 않으려고 concurrently 같은 도구 대신 child_process만 쓴다.
 *
 * **목 게이트웨이는 하나다.** 통합 전에는 10줄짜리 시나리오 재생기(server.mjs)와
 * web-dashboard 의 4,757줄짜리 게이트웨이가 따로 있었지만, 지금은 후자가 본체가 되고
 * 시나리오 재생이 그 안의 `trace_event` 채널로 접혔다. 게이트웨이가 둘이면
 * transport 가 싱글턴이라 탭 중 절반이 빈 화면이 된다.
 */

import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { startStt } from './dev-stt.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const children = [
  // shell 없이 스크립트 파일을 직접 실행한다 — shell:true + args 조합은 인자가
  // 이스케이프되지 않고 이어붙기만 해서 Node가 경고한다(DEP0190).
  spawn(process.execPath, ['gateway/server.ts'], { cwd: root, stdio: 'inherit' }),
  spawn(process.execPath, [join(root, 'node_modules', 'vite', 'bin', 'vite.js')], { cwd: root, stdio: 'inherit' }),
];
// STT 서비스는 **없어도 되는 프로세스**다. 죽어도 나머지를 끌어내리지 않는다 (제약 5).
// 그래서 위 children 배열에 넣지 않고 따로 들고 있다가 종료할 때만 같이 정리한다.
const stt = startStt();

const stop = () => { children.forEach((child) => child.kill()); stt?.kill(); };
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { stop(); process.exit(0); });
for (const child of children) child.on('exit', (code) => { stop(); process.exit(code ?? 0); });
