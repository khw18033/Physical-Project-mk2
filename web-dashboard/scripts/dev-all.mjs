/**
 * scripts/dev-all.mjs
 *
 * 목 게이트웨이와 Vite 개발 서버를 한 번에 띄운다.
 * 라이브러리를 늘리지 않으려고 concurrently 같은 도구 대신 child_process만 쓴다.
 */

import { spawn } from 'node:child_process';

const procs = [];

function start(name, command, args) {
  const p = spawn(command, args, { stdio: 'inherit', shell: process.platform === 'win32' });
  p.on('exit', (code) => {
    process.stdout.write('[dev-all] ' + name + ' 종료 (code=' + code + ')\n');
    stopAll();
    process.exit(code ?? 0);
  });
  procs.push(p);
  return p;
}

function stopAll() {
  for (const p of procs) {
    if (!p.killed) p.kill();
  }
}

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    stopAll();
    process.exit(0);
  });
}

start('mock-gateway', process.execPath, ['mock-gateway/server.ts']);
start('vite', 'npx', ['vite']);
