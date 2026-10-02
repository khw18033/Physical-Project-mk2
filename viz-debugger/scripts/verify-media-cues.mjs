// verify:media-cues (260929 신설 — 연결 관리에 붙인 동영상을 정해진 노드에서 재생)
//
// 보는 것 넷 (260929 결정 1-A · 2-A · 3-B).
//  1. **붙이는 칸** — 3D 가상환경에 동영상 칸 하나, 장애물 탐지 영상에는 **저장된 주소마다** 한 칸.
//  2. **이상 탐지 편에서만** 시점이 있다 — 탐지 영상은 「첫 번째 장치 이동」, 3D 가상환경은 「두 번째 장치 이동」.
//     다른 편에는 시점이 없어 지금처럼 실시간 화면이다.
//  3. **위치 규칙** — 시작 전엔 0 에서 멈춤 · 시작 뒤엔 머리 − 시작 시각 · 판이 멈추면 영상도 멈춤.
//  4. **노드가 그 칸을 읽는다** — 탐지 영상은 고른 주소의 칸(`autodrive-ai.video@<주소>`), 3D 가상환경은 한 칸.

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readSource } from './lib/source.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...parts) => import(pathToFileURL(join(root, ...parts)).href);
const read = (...parts) => readSource(join(root, ...parts));
const failures = [];
const controls = [];

// ── 1. 칸 ───────────────────────────────────────────────────────────────────────
{
  const { CONNECTION_TARGETS } = await load('src', 'shared', 'connections.ts');
  const v3d = CONNECTION_TARGETS.find((item) => item.id === 'virtual-3d');
  if (!v3d?.fields.some((field) => field.key === 'video' && field.video === true)) failures.push('3D 가상환경에 동영상 칸이 없다');
  const ai = CONNECTION_TARGETS.find((item) => item.id === 'autodrive-ai');
  if (ai?.fields.find((field) => field.key === 'base')?.videoPerRow !== true) failures.push('장애물 탐지 영상 주소마다 동영상 칸이 없다');
  const panel = read('src', 'shell', 'ConnectionsPanel.tsx');
  if (!/field\.videoPerRow === true && splitAddressList\(current\[key\]/.test(panel)) failures.push('동영상 칸이 저장된 주소마다 그려지지 않는다');
  if (!/storageKey=\{`\$\{target\.id\}\.video@\$\{row/.test(panel)) failures.push('주소마다 다른 키로 저장하지 않는다 — 한 영상이 모든 주소에 쓰인다');
  if (!/field\.video === true\) return <ImageField[^\n]*video \/>/.test(panel)) failures.push('동영상 칸이 동영상을 받지 않는다');
}

// ── 2. 시점은 이상 탐지 편에만 ──────────────────────────────────────────────────
{
  const { SCRIPT_IDS } = await load('src', 'scenarios', 'manifest.ts');
  for (const id of SCRIPT_IDS) {
    const script = JSON.parse(read('scenarios', `${id}.json`));
    const cues = script.params?.media_cues;
    if (id === 'MSN-260929-02') {
      const want = { 'autodrive-ai': 'T-E1', 'virtual-3d': [{ task: 'T-C1', key: 'virtual-3d.video' }, { task: 'T-E3', key: 'virtual-3d.video2' }] };
      if (JSON.stringify(cues) !== JSON.stringify(want)) failures.push(`이상 탐지 편의 재생 시점이 ${JSON.stringify(cues)}`);
      const title = (tid) => script.tasks.find((t) => t.id === tid)?.title;
      if (title('T-E1') !== '첫 번째 장치 이동' || title('T-C1') !== '모니터링 진행' || title('T-E3') !== '두 번째 장치 이동') failures.push('재생 시점 태스크 이름이 지시와 다르다');
    } else if (cues !== undefined) failures.push(`${id} 에 재생 시점이 있다 — 이상 탐지 편에서만 튼다(결정 2-A)`);
  }
  const { CONNECTION_TARGETS } = await load('src', 'shared', 'connections.ts');
  const v3d = CONNECTION_TARGETS.find((item) => item.id === 'virtual-3d');
  if (JSON.stringify(v3d?.fields.filter((f) => f.video === true).map((f) => f.key)) !== '["video","video2"]') failures.push('3D 가상환경에 동영상 칸이 둘(모니터링 · 두 번째 장치 이동)이 아니다');
}

// ── 3. 위치 규칙 ────────────────────────────────────────────────────────────────
{
  const { cuePosition, cuesOf } = await load('src', 'imagery', 'cue.ts');
  const cues = cuesOf([{ task: 'T-C1', key: 'a' }, { task: 'T-E3', key: 'b' }], 'x');
  const trace = [
    { seq: 1, atSec: 0, nodeId: 'T-C1', status: 'pending', kind: 'created', producedBy: 'backend' },
    { seq: 2, atSec: 20, nodeId: 'T-C1', status: 'running', kind: 'started', producedBy: 'backend' },
    { seq: 3, atSec: 60, nodeId: 'T-E3', status: 'running', kind: 'started', producedBy: 'backend' },
  ];
  const before = cuePosition(trace, cues, 10, true);
  if (before.cue?.key !== 'a' || before.started || before.at !== 0 || before.playing) failures.push(`시작 전인데 ${JSON.stringify(before)} — 첫 영상 첫 장면에서 멈춰야 한다`);
  const first = cuePosition(trace, cues, 23, true);
  if (first.cue?.key !== 'a' || first.at !== 3 || !first.playing) failures.push(`모니터링 3초째인데 ${JSON.stringify(first)}`);
  const second = cuePosition(trace, cues, 72.5, true);
  if (second.cue?.key !== 'b' || second.at !== 12.5) failures.push(`두 번째 장치 이동 12.5초째인데 ${JSON.stringify(second)} — 둘째 영상이어야 한다`);
  const paused = cuePosition(trace, cues, 72.5, false);
  if (paused.playing) failures.push('판이 멈췄는데 영상이 돈다');
  const onlySecond = cuePosition(trace, cues, 23, true, (key) => key === 'b');
  if (onlySecond.cue?.key !== 'b' || onlySecond.started) failures.push('첫 영상을 안 붙였는데 둘째 영상을 첫 장면에서 멈춰 두지 않는다');
  if (JSON.stringify(cuesOf('T-E1', 'k')) !== '[{"task":"T-E1","key":"k"}]') failures.push('시점 하나(문자열)를 못 읽는다');
  const rewound = cuePosition(trace, cues, 19, true);
  if (rewound.started) failures.push('대조군 실패: 되감았는데 재생 중으로 읽힌다');
  controls.push('시작 전으로 되감은 판');
}

// ── 4. 노드가 그 칸을 읽는다 ───────────────────────────────────────────────────
{
  const nodes = read('src', 'tabs', 'viewNodes.tsx');
  if (!/<CuedVideo target="virtual-3d" storageKey="virtual-3d\.video"><Virtual3D \/>/.test(nodes)) failures.push('3D 가상환경 노드가 붙인 동영상을 안 본다');
  if (!/<AiCuedCam nodeId=/.test(nodes)) failures.push('탐지 영상 노드가 붙인 동영상을 안 본다');
  const views = read('src', 'autodrive', 'views', 'AutodriveViews.tsx');
  if (!/<CuedVideo target="autodrive-ai" storageKey=\{`autodrive-ai\.video@\$\{base\}`\}/.test(views)) failures.push('탐지 영상이 고른 주소의 동영상 칸을 안 읽는다');
  const cued = read('src', 'imagery', 'CuedVideo.tsx');
  if (!/if \(position\.cue === null\) return <>\{children\}<\/>;/.test(cued)) failures.push('시점이 없거나 영상을 안 붙였을 때 실시간 화면으로 돌아가지 않는다');
  // 노드에는 영상만 — 언제 · 몇 초째 · 어느 파일인지 적지 않는다(260929 지시).
  if (/cue\.(waiting|playing|from)/.test(cued)) failures.push('노드에 재생 시점 · 경과 · 파일 이름 문구가 남아 있다');
}

if (failures.length) {
  console.error(`❌ verify:media-cues\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 칸 — 3D 가상환경 한 칸 · 장애물 탐지 영상은 저장된 주소마다 한 칸(키가 주소별)');
console.log('✅ 시점 — 이상 탐지 편에만: 탐지 영상은 첫 번째 장치 이동 · 3D 가상환경은 두 번째 장치 이동');
console.log('✅ 위치 — 시작 전 0 에서 멈춤 · 시작 뒤 머리 − 시작 · 판이 멈추면 멈춤 · 안 붙였으면 실시간 그대로');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
