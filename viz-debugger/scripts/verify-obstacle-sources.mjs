// verify:obstacle-sources (260929 신설 — 3D 가상환경 · 탐지 영상 모든 임무 · 장애물 탐지 주소 둘 이상)
//
// 보는 것 넷.
//  1. **3D 가상환경** — 연결 관리 대상이 있고 기본 주소가 사용자가 준 것이다. 노드는 모든 임무에 선다.
//  2. **탐지 영상 · 객체 탐지 로그가 모든 임무에 선다** — 연결 관리 이름은 「장애물 탐지 영상」. 문 찾기의
//     탐지 영상과 팔레트에서 이름이 겹치지 않는다(같은 이름 둘이면 어느 것인지 모른다).
//  3. **주소 둘 이상** — 목록 칸이고, 주소마다 폴링 · 값 · 줄이 따로다. 첫 줄 열은 전과 같다(자율주행 편 판정).
//  4. **노드마다 고른다** — 같은 노드 여러 장이 각자 다른 주소를 본다. 연결 확인도 주소마다 줄을 낸다.

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readSource } from './lib/source.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...parts) => import(pathToFileURL(join(root, ...parts)).href);
const read = (...parts) => readSource(join(root, ...parts));
const failures = [];
const controls = [];

const connections = await load('src', 'shared', 'connections.ts');
const client = await load('src', 'autodrive', 'aiClient.ts');
const obstacle = await load('src', 'autodrive', 'obstacle.ts');
const choice = await load('src', 'autodrive', 'sourceChoice.ts');

// ── 1. 3D 가상환경 ──────────────────────────────────────────────────────────────
{
  const target = connections.CONNECTION_TARGETS.find((item) => item.id === 'virtual-3d');
  if (target === undefined || !target.live) failures.push('연결 관리에 3D 가상환경 대상이 없다');
  if (connections.connectionAddress('virtual-3d', 'base') !== 'http://100.68.72.33:8080/') failures.push(`3D 가상환경 기본 주소가 ${connections.connectionAddress('virtual-3d', 'base')} — 사용자가 준 주소여야 한다`);
  const view = read('src', 'virtualmap', 'Virtual3D.tsx');
  if (!/connectionAddress\('virtual-3d', 'base'\)/.test(view)) failures.push('3D 가상환경 노드가 연결 관리의 주소를 안 읽는다');
}

// ── 2. 모든 임무 · 이름 ─────────────────────────────────────────────────────────
const renderers = read('src', 'tabs', 'viewNodes.tsx');
const entryOf = (kind) => renderers.slice(renderers.indexOf(`kind: '${kind}'`), renderers.indexOf('zoom:', renderers.indexOf(`kind: '${kind}'`)));
for (const kind of ['virtual-3d', 'autodrive-cam', 'obstacle-log']) {
  if (!renderers.includes(`kind: '${kind}'`)) failures.push(`뷰 노드 ${kind} 가 없다`);
  else if (/showFor:/.test(entryOf(kind))) failures.push(`${kind} 가 일부 임무에만 선다 — 모든 임무여야 한다`);
}
function dict(file) {
  const out = {};
  for (const m of read('src', 'i18n', file).matchAll(/^\s*'([^']+)':\s*'((?:[^'\\]|\\.)*)',?$/gm)) out[m[1]] = m[2];
  return out;
}
const ko = dict('ko.ts');
if (ko['conn.target.autodriveAi'] !== '장애물 탐지 영상') failures.push(`연결 관리 이름이 「${ko['conn.target.autodriveAi']}」 — 「장애물 탐지 영상」이어야 한다`);
if (!/labelKey: 'viewnode\.obstacleVideo'/.test(entryOf('autodrive-cam')) || ko['viewnode.obstacleVideo'] !== '탐지 영상') failures.push('자율주행 영상 노드의 이름이 「탐지 영상」이 아니다');
if (ko['viewnode.virtual3d'] !== '3D 가상환경') failures.push('3D 가상환경 노드 이름이 다르다');
{
  // 팔레트에서 같은 이름이 둘이면 안 된다.
  const labels = [...renderers.matchAll(/labelKey: '([^']+)'/g)].map((m) => ko[m[1]]);
  const dup = labels.filter((label, index) => labels.indexOf(label) !== index);
  if (dup.length > 0) failures.push(`팔레트에 같은 이름이 둘 — ${[...new Set(dup)].join(', ')}`);
  if (['탐지 영상', '탐지 영상'].filter((label, index, all) => all.indexOf(label) !== index).length === 0) failures.push('대조군 실패: 같은 이름 둘이 안 잡힌다');
  controls.push('같은 이름 둘인 팔레트');
}

// ── 3. 주소 둘 이상 · 주소마다 따로 ─────────────────────────────────────────────
{
  const field = connections.CONNECTION_TARGETS.find((item) => item.id === 'autodrive-ai')?.fields.find((f) => f.key === 'base');
  if (field?.list !== true) failures.push('장애물 탐지 주소 칸이 목록(여러 줄)이 아니다');
  // 260929 — 기본값 두 줄(Go1 · 드론). 첫 줄이 Go1 이어야 자율주행 편 판정이 전과 같은 주소를 본다.
  if (JSON.stringify(client.aiBases()) !== '["http://210.110.250.33:7864","http://100.114.96.78:8891"]') failures.push(`기본 주소가 ${JSON.stringify(client.aiBases())} — Go1 · 드론 두 줄이어야 한다`);
  const panel = read('src', 'shell', 'ConnectionsPanel.tsx');
  if (!/'autodrive-ai': \{ presets: AI_PRESETS/.test(panel)) failures.push('장애물 탐지 영상 줄에 로봇처럼 고르는 칸이 없다');
  connections.registerConnectionDefault('autodrive-ai', 'base', 'http://a.test:7864/\nhttp://b.test:7864');
  if (JSON.stringify(client.aiBases()) !== '["http://a.test:7864","http://b.test:7864"]') failures.push(`주소 목록이 ${JSON.stringify(client.aiBases())}`);
  if (client.aiBase() !== 'http://a.test:7864') failures.push('첫 줄이 기본 주소가 아니다 — 자율주행 편 판정이 엉뚱한 주소를 본다');
  if (client.aiStreamUrl('http://b.test:7864') !== 'http://b.test:7864/stream/ai/go1_front') failures.push('고른 주소의 영상 주소가 틀렸다');

  obstacle.resetObstacle();
  const asked = [];
  const sample = (tag) => ({ timestamp: '1', camera_id: 'go1_front', detections: [{ id: 1, name: tag, distance_cm: 40, risk_level: 'near' }], has_near_obstacle: true, state_change: false });
  const fetcher = async (url) => {
    asked.push(url);
    const tag = url.includes('b.test') ? 'b' : 'a';
    return { ok: true, status: 200, headers: { get: (k) => (k === 'X-Autodrive-Relay' && url.startsWith('/autodrive-ai/') ? '1' : null) }, json: async () => sample(tag) };
  };
  const releaseB = obstacle.holdObstaclePollingAt('http://b.test:7864', fetcher);
  await new Promise((resolve) => setTimeout(resolve, 60));
  const channelB = obstacle.obstacleChannelFor('http://b.test:7864');
  if (channelB.state.latest?.detections[0]?.name !== 'b') failures.push('둘째 주소의 열이 둘째 주소 값을 안 받았다');
  if (obstacle.obstacleState().latest !== null) failures.push('둘째 주소를 물었는데 첫 줄 열에 값이 들어갔다 — 두 로봇의 장애물이 섞인다');
  if (!asked.every((url) => url.includes(encodeURIComponent('http://b.test:7864')))) failures.push(`둘째 주소 폴링이 다른 주소를 물었다 — ${asked.join(' | ')}`);
  if (obstacle.obstacleHolders() !== 0) failures.push('둘째 주소를 붙잡았는데 첫 줄 열의 폴링 수가 늘었다');
  releaseB();
  if (obstacle.obstacleChannelFor(null) !== obstacle.obstacleChannelFor('http://a.test:7864/')) failures.push('첫 줄 주소를 고르면 첫 줄 열이 아니다 — 같은 서버를 두 번 묻는다');
  controls.push('같은 주소 → 같은 열');
  obstacle.resetObstacle();
}

// ── 4. 노드마다 고른다 · 확인도 주소마다 ────────────────────────────────────────
{
  choice.setObstacleSource('node-1', 'http://b.test:7864');
  choice.setObstacleSource('node-2', null);
  if (choice.obstacleSource('node-1') !== 'http://b.test:7864' || choice.obstacleSource('node-2') !== null) failures.push('노드마다 고른 주소가 따로 남지 않는다');
  const views = read('src', 'autodrive', 'views', 'AutodriveViews.tsx');
  if (!/export function AiSourcePicker/.test(views) || !/\{zoom && <AiSourcePicker nodeId=\{nodeId\} \/>\}/.test(views)) failures.push('탐지 영상 확대에 주소 고르기가 없다');
  for (const kind of ['autodrive-cam', 'obstacle-log']) {
    const block = renderers.slice(renderers.indexOf(`kind: '${kind}'`), renderers.indexOf('},', renderers.indexOf(`kind: '${kind}'`)));
    if (!/nodeId=\{node\?\.id/.test(block)) failures.push(`${kind} 노드가 자기 id 로 주소를 고르지 않는다 — 여러 장이 같은 주소를 본다`);
  }
  const { checkAutodriveAi } = await load('src', 'shared', 'connectionCheck.ts');
  const lines = await checkAutodriveAi(async (url) => ({ ok: true, status: 200, headers: { get: (k) => (k === 'X-Autodrive-Relay' && url.startsWith('/autodrive-ai/') ? '1' : null) }, json: async () => ({ detections: [], has_near_obstacle: false }) }));
  const scopes = [...new Set(lines.map((line) => line.scope))];
  if (lines.length !== 4 || JSON.stringify(scopes) !== '["http://a.test:7864","http://b.test:7864"]') failures.push(`연결 확인이 주소마다 줄을 안 낸다 — ${lines.length}줄 · ${JSON.stringify(scopes)}`);
  if (new Set(lines.map((line) => line.id)).size !== lines.length) failures.push('연결 확인 줄 id 가 겹친다');
}

if (failures.length) {
  console.error(`❌ verify:obstacle-sources\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 3D 가상환경 — 연결 관리 대상 · 기본 http://100.68.72.33:8080/ · 모든 임무 노드');
console.log('✅ 탐지 영상 · 객체 탐지 로그 — 모든 임무 · 연결 관리 이름 「장애물 탐지 영상」 · 문 탐지 영상과 이름 안 겹침');
console.log('✅ 주소 둘 이상 — 목록 칸 · 첫 줄이 기본 · 주소마다 폴링 · 값 따로 · 노드마다 고름 · 연결 확인도 주소마다');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
