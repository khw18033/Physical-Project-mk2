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
if (source.includes('viewBox={`0 0 1380')) throw new Error('SVG와 HTML 노드가 서로 다른 좌표계를 사용함');
if (!source.includes('width={width} height={height}')) throw new Error('SVG가 그래프 캔버스 픽셀 크기를 공유하지 않음');
console.log('✅ SVG 연결선과 HTML 노드가 같은 픽셀 좌표계 사용');
if (!source.includes('onPointerDown=') || !source.includes('onPointerMove=')) throw new Error('노드 드래그 경로 누락');
console.log('✅ 포인터 드래그로 노드 위치와 연결선 좌표를 함께 갱신');
