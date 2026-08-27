import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dagLayout, treeLayout } from '../src/graph/layout.ts';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const scenario = JSON.parse(await readFile(join(root, 'scenarios', 'MSN-260826-01.json'), 'utf8'));
const source = await readFile(join(root, 'src', 'graph', 'TaskGraph.tsx'), 'utf8');
for (const [name, layout] of [['DAG', dagLayout(scenario.tasks)], ['트리', treeLayout(scenario.tasks)]]) {
  const positions = Object.values(layout);
  const unique = new Set(positions.map(({ x, y }) => `${x},${y}`));
  if (positions.length !== 7 || unique.size !== 7) throw new Error(`${name}: 노드 위치가 겹치거나 누락됨`);
  console.log(`✅ ${name} 노드 7개 좌표가 모두 다름`);
}
if (!source.includes('style={{ left: position.x, top: position.y }}')) throw new Error('계산 좌표가 CSS left/top에 적용되지 않음');
console.log('✅ 계산 좌표를 카드 CSS left/top에 적용');
