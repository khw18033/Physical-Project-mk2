// verify:panels-imagery (260929 신설 — 머리줄 판 여닫기 · 연결 관리 이미지 첨부 · SAR / 3D 복원 노드)
//
// 보는 것 넷.
//  1. **머리줄 판 셋(연결 관리 · 이력 · 알림)이 여닫기다** — 버튼을 다시 누르면 닫히고, ESC 로도 닫힌다.
//  2. **닫아도 적던 주소가 남는다** — 저장값과 다른 칸만 들고 있다가 다시 열 때 얹는다(결정 4-B).
//  3. **SAR · 3D 복원 노드가 연결 관리에 붙인 것을 띄운다** — 주소가 파일보다 먼저, 둘 다 없으면 안내 한 줄.
//     모든 편 팔레트에 선다(결정 12-A — `showFor` 없음).
//  4. **화면 문구에 「시연 · 보여주기 · 데모」가 없다** (260929 지시). 새로 단 문구 전부를 두 사전에서 본다.
// 덧붙여 5. 거절된 문장이면 앞 제안 카드를 치운다(결정 16-A).

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
// 자리표에 줄바꿈이 들어간다 — **LF 로 정규화한 원본**에서 읽는다 (`verify:crlf-safe`).
import { readSource } from './lib/source.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...parts) => import(pathToFileURL(join(root, ...parts)).href);
const read = (...parts) => readSource(join(root, ...parts));
const failures = [];
const controls = [];

// ── 1. 여닫기 · ESC ─────────────────────────────────────────────────────────────
const shell = read('src', 'shell', 'AppShell.tsx');
for (const which of ['connections', 'history', 'notifications']) {
  if (!new RegExp(`togglePanel\\('${which}'\\)`).test(shell)) failures.push(`머리줄 「${which}」 버튼이 여닫기(togglePanel)가 아니다`);
}
if (/setPanel\('(connections|history|notifications)'\)/.test(shell)) failures.push('여는 것만 하는 버튼(setPanel(\'…\'))이 남아 있다');
if (!/open === which \? null : which/.test(shell)) failures.push('togglePanel 이 열린 판을 닫지 않는다');
if (!/event\.key === 'Escape'/.test(shell) || !/addEventListener\('keydown'/.test(shell)) failures.push('ESC 로 판을 닫지 않는다');
controls.push('여는 것만 하는 버튼 사본');
if (!/setPanel\('(connections|history|notifications)'\)/.test("<button onClick={() => setPanel('connections')}>")) failures.push('대조군 실패: 여는 것만 하는 버튼이 안 잡힌다');

// ── 2. 닫아도 남는 초안 ─────────────────────────────────────────────────────────
const panelSource = read('src', 'shell', 'ConnectionsPanel.tsx');
{
  const { unsavedDraft } = await load('src', 'shell', 'ConnectionsPanel.tsx').catch(() => ({ unsavedDraft: null }));
  // tsx 를 못 부르는 환경이면 소스에서 본다.
  if (typeof unsavedDraft === 'function') {
    const kept = unsavedDraft({ 'physical.ws': 'ws://pi3:9001', 'detect.base': 'http://a' }, { 'physical.ws': 'ws://pi7:9001', 'detect.base': 'http://a' });
    if (JSON.stringify(kept) !== '{"physical.ws":"ws://pi3:9001"}') failures.push(`닫을 때 남기는 칸이 ${JSON.stringify(kept)} — 저장값과 다른 칸만이어야 한다`);
  }
  if (!/heldDraft = unsavedDraft\(/.test(panelSource)) failures.push('판이 닫힐 때 적던 값을 남기지 않는다');
  if (!/\{ \.\.\.current, \.\.\.heldDraft \}/.test(panelSource)) failures.push('다시 열 때 남긴 값을 얹지 않는다');
}

// ── 3. SAR · 3D 복원 ────────────────────────────────────────────────────────────
{
  const { CONNECTION_TARGETS } = await load('src', 'shared', 'connections.ts');
  for (const id of ['sar', 'recon-3d']) {
    const target = CONNECTION_TARGETS.find((item) => item.id === id);
    if (target === undefined || !target.live) { failures.push(`연결 관리에 ${id} 대상이 없다`); continue; }
    if (!target.fields.some((field) => field.image === true)) failures.push(`${id} 에 이미지 칸이 없다`);
    if (!target.fields.some((field) => field.key === 'base' && field.image !== true)) failures.push(`${id} 에 이미지 주소 칸이 없다 — 서비스가 생기면 판을 다시 만들어야 한다`);
  }
  if (!/field\.image === true\) return <ImageField/.test(panelSource)) failures.push('연결 관리가 이미지 칸을 파일 칸으로 안 그린다');
  const renderers = read('src', 'tabs', 'viewNodes.tsx');
  for (const [kind, target] of [['sar', 'sar'], ['recon-3d', 'recon-3d']]) {
    const block = renderers.match(new RegExp(`kind: '${kind}',[\\s\\S]*?zoom:[^\\n]*`))?.[0] ?? '';
    if (block === '') { failures.push(`뷰 노드 ${kind} 가 없다`); continue; }
    if (/showFor/.test(block)) failures.push(`${kind} 가 일부 편에만 선다 — 모든 편 팔레트여야 한다(결정 12-A)`);
    if (!block.includes(`target="${target}"`)) failures.push(`${kind} 가 연결 관리의 ${target} 를 안 읽는다`);
  }
  // 무엇을 띄우는가 — 주소가 먼저다.
  const source = read('src', 'imagery', 'AttachedImage.tsx');
  if (!/if \(url !== ''\) return \{ src: url, from: 'url'/.test(source)) failures.push('이미지 주소가 붙인 파일보다 먼저가 아니다');
  if (!/if \(source === null\) return <p className="vn-line vn-dim">\{t\('img\.empty'\)\}/.test(source)) failures.push('붙인 것이 없을 때 안내 한 줄이 없다');
  // 이미지는 연결 묶음(localStorage 문자열)에 안 담는다 — 한도를 넘으면 주소까지 저장이 깨진다.
  const store = read('src', 'shared', 'imageStore.ts');
  if (!/indexedDB\.open/.test(store) || /localStorage/.test(store.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, ''))) failures.push('이미지를 IndexedDB 가 아닌 곳에 둔다');
}

// ── 4. 「시연 · 보여주기 · 데모」가 화면에 없다 ─────────────────────────────────
const BANNED = /시연|보여주기|보여 주기|데모|예시용|demo|showcase|mock-?up/i;
const NEW_KEYS = /^(conn\.target\.(sar|recon3d)|conn\.field\.image|conn\.image\.|img\.|viewnode\.(sar|recon3d))/;
function dict(file) {
  const out = {};
  for (const m of read('src', 'i18n', file).matchAll(/^\s*'([^']+)':\s*'((?:[^'\\]|\\.)*)',?$/gm)) out[m[1]] = m[2];
  return out;
}
const ko = dict('ko.ts');
const en = dict('en.ts');
let seen = 0;
for (const [lang, table] of [['ko', ko], ['en', en]]) {
  for (const [key, value] of Object.entries(table)) {
    if (!NEW_KEYS.test(key)) continue;
    seen += 1;
    if (BANNED.test(value)) failures.push(`${lang} ${key} 에 「${value.match(BANNED)[0]}」 — 화면에 적지 않는다(260929 지시)`);
  }
}
if (seen < 30) failures.push(`새 문구를 ${seen}개만 봤다 — 사전 키 이름이 바뀌어 검사가 비었다`);
if (!BANNED.test('SAR 시연 영상')) failures.push('대조군 실패: 「시연」이 안 잡힌다');
controls.push('「시연」을 넣은 문구');
// 대본에도 없다 — 새 편 제목 · 태스크가 화면에 뜬다.
for (const id of ['MSN-260927-01', 'MSN-260929-01']) {
  const script = JSON.parse(read('scenarios', `${id}.json`));
  for (const text of [script.title, ...script.milestones.map((m) => m.title), ...script.tasks.map((t) => t.title)]) {
    if (BANNED.test(text)) failures.push(`${id} 의 「${text}」 에 화면에 적지 않을 낱말이 있다`);
  }
}

// ── 5. 거절된 문장 → 앞 제안 카드를 치운다 ──────────────────────────────────────
const utter = read('src', 'views', 'UtterancePanel.tsx');
if (!/\} else \{[\s\S]{0,400}?rejectProposal\(\);/.test(utter.slice(utter.indexOf('function matchScript')))) failures.push('안 맞은 문장인데 앞 제안을 안 치운다');
{
  const scenario = await load('src', 'data', 'scenario.ts');
  scenario.proposeMission({ origin: 'script', missionId: 'MSN-260909-01', title: 't', keywords: [], planId: null, world: 'registry' });
  scenario.rejectProposal();
  if (scenario.getMissionState().proposal !== null) failures.push('rejectProposal 이 제안을 안 치운다');
}

if (failures.length) {
  console.error(`❌ verify:panels-imagery\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 머리줄 판 셋이 여닫기 · ESC 로 닫힘 · 닫아도 저장 안 한 칸은 다시 열 때 그대로');
console.log('✅ SAR · 3D 복원 — 연결 관리에 이미지 칸 + 주소 칸 · 노드는 주소 먼저, 없으면 붙인 파일 · 모든 편 팔레트 · 이미지는 IndexedDB');
console.log(`✅ 새 문구 ${seen}개 · 새 편 제목에 「시연 · 보여주기 · 데모」 없음 · 거절된 문장이면 앞 제안을 치운다`);
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
