import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { startStt } from './dev-stt.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const children = [
  spawn(process.execPath, ['gateway/server.mjs'], { cwd: root, stdio: 'inherit' }),
  spawn(process.execPath, [join(root, 'node_modules', 'vite', 'bin', 'vite.js')], { cwd: root, stdio: 'inherit' }),
];
// STT 서비스는 **없어도 되는 프로세스**다. 죽어도 나머지를 끌어내리지 않는다 (제약 5).
// 그래서 아래 children 배열에 넣지 않고 따로 들고 있다가 종료할 때만 같이 정리한다.
const stt = startStt();

const stop = () => { children.forEach((child) => child.kill()); stt?.kill(); };
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { stop(); process.exit(0); });
for (const child of children) child.on('exit', (code) => { stop(); process.exit(code ?? 0); });
