import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const children = [
  spawn(process.execPath, ['gateway/server.mjs'], { cwd: root, stdio: 'inherit' }),
  spawn(process.execPath, [join(root, 'node_modules', 'vite', 'bin', 'vite.js')], { cwd: root, stdio: 'inherit' }),
];
const stop = () => children.forEach((child) => child.kill());
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { stop(); process.exit(0); });
for (const child of children) child.on('exit', (code) => { stop(); process.exit(code ?? 0); });
