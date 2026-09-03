// 확대는 탭이 아니다 (260903 — 노드 캔버스 2단계).
//
// 이 검사가 막으려는 실패는 하나다: **확대가 이름만 바꾼 탭이 되는 것.**
// 노드로 통합하는 이유가 「화면을 바꾸지 않고 공시 ↔ 통시를 넘어간다」(HCI 차별점 2)인데,
// 확대가 캔버스를 갈아 치우면 탭을 옮기는 것과 똑같아지고 그 문장이 다시 거짓이 된다.
//
// 지시서 §6이 그것을 **검사 가능한 네 조건**으로 적어 뒀다. 여기서 그 넷을 소스로 확인한다.
//
//  1. 캔버스가 **뒤에 남아 보인다** — 오버레이이고, 배경이 반투명이며, 캔버스를 조건부로
//     그리지 않는다(확대 중에도 TaskGraph 가 그대로 마운트돼 있다).
//  2. 닫으면 **정확히 같은 자리** — 닫기가 zoom 상태 하나만 되돌린다. 다른 상태를 함께
//     초기화하면 「어디였지」가 생긴다.
//  3. 전역에 **`activeTab` 류 상태가 없다** — 캔버스 쪽에 그런 상태가 하나도 없어야 한다.
//  4. 확대는 **한 번에 하나** — 상태가 문자열 하나다. 배열이면 둘이 열리고, 둘이 열리면
//     분할 화면이고, 분할 화면은 곧 탭이 된다.
//
// **3단계(탭 제거) 몫은 아직 여기 없다.** `AppShell` 의 `activeTab` 은 탭 바가 살아 있는
// 2단계에서는 정상이다. 대신 **그것이 셸 한 곳뿐인지**를 지금 못 박아 둔다 — 둘째가
// 생기면 3단계에서 지울 것이 둘이 된다.
//
// 음성 대조군 포함 — 판정들이 무력화된 사본을 실제로 잡는지 확인한다.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const read = (...parts) => readFileSync(join(root, ...parts), 'utf8');
const failures = [];
const check = (ok, message) => { if (!ok) failures.push(message); };

/**
 * 주석을 걷어낸 소스. 이 저장소의 주석은 「왜 activeTab 이 아닌가」를 길게 적으므로,
 * 걷어내지 않으면 **설명이 위반으로 잡힌다.** 검사 대상은 코드다.
 */
const stripComments = (source) => source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');

const main = read('src', 'main.tsx');
const overlay = read('src', 'canvas', 'ZoomOverlay.tsx');
const graph = read('src', 'graph', 'TaskGraph.tsx');
const css = read('src', 'style.css');

// ── ① 캔버스가 뒤에 남아 보인다 ───────────────────────────────────────────────
{
  // 캔버스를 확대와 **바꿔치기**하지 않는다. TaskGraph 를 그리는 자리에 zoom 삼항이 없어야 한다.
  const swapsCanvas = (source) => /zoom[A-Za-z]*\s*(!==\s*null|===\s*null|\?)[^\n]{0,80}<TaskGraph/.test(source);
  check(!swapsCanvas(main), '확대할 때 캔버스를 갈아 치운다 — 오버레이가 아니라 화면 전환이다');
  check(main.includes('<TaskGraph'), 'TaskGraph 를 그리는 곳이 없다');
  check(/\{zoomedNode !== null && zoomedEntry !== null && <ZoomOverlay/.test(main), '확대 오버레이가 캔버스의 형제로 얹히지 않는다');
  // 배경이 불투명하면 뒤가 안 보인다. 8자리 hex(알파 포함)여야 한다.
  const backdrop = /\.modal-backdrop\{[^}]*background:#([0-9a-f]{6,8})/.exec(css);
  check(backdrop !== null && backdrop[1].length === 8, `확대 배경이 불투명하다(#${backdrop === null ? '없음' : backdrop[1]}) — 캔버스가 뒤에 보여야 한다`);
  check(overlay.includes('modal-backdrop'), '확대가 ActionModal 계통(.modal-backdrop)이 아니다');
  // 음성 대조군.
  if (!swapsCanvas('return zoomedId !== null ? <Zoom /> : <TaskGraph tasks={tasks} />;')) {
    failures.push('대조군 실패: 캔버스를 갈아 치우는 사본을 판정이 놓쳤다 — 이 검사는 무의미하다');
  }
  console.log('✅ 캔버스가 뒤에 남는다 — 오버레이는 형제이고 배경은 반투명, TaskGraph 는 조건 없이 그린다');
}

// ── ② 닫으면 정확히 같은 자리 ────────────────────────────────────────────────
{
  const close = /onClose=\{\(\) => ([^}]+)\}/.exec(main);
  check(close !== null, '확대 닫기 경로가 없다');
  if (close !== null) {
    const body = close[1];
    check(/setZoomedId\(null\)/.test(body), `닫기가 확대 상태를 되돌리지 않는다: ${body}`);
    // 닫으면서 다른 상태까지 만지면 「어디였지」가 생긴다 — 자리·스크롤·되감기 시각은 그대로여야 한다.
    const otherSets = body.match(/set[A-Z][A-Za-z]*\(/g)?.filter((name) => name !== 'setZoomedId(') ?? [];
    check(otherSets.length === 0, `닫기가 다른 상태도 되돌린다(${otherSets.join(' ')}) — 닫으면 같은 자리여야 한다`);
  }
  // Esc 로도 닫힌다 — 여는 길이 둘(더블클릭·버튼)이면 닫는 길도 둘 이상이어야 한다.
  check(overlay.includes("'Escape'"), '확대가 Esc 로 닫히지 않는다');
  console.log('✅ 닫으면 같은 자리 — 닫기가 확대 상태 하나만 되돌린다 (Esc·배경·버튼)');
}

// ── ③ 전역에 activeTab 류 상태가 없다 ────────────────────────────────────────
{
  const CANVAS_FILES = ['types.ts', 'registry.ts', 'scope.ts', 'persist.ts', 'defaults.ts', 'useCanvas.ts', 'Palette.tsx', 'ViewNodeCard.tsx', 'ZoomOverlay.tsx'];
  const looksLikeTabState = (source) => /activeTab|activePanel|currentTab|selectedTab|tabIndex/.test(source);
  for (const file of CANVAS_FILES) {
    check(!looksLikeTabState(stripComments(read('src', 'canvas', file))), `src/canvas/${file} 에 탭 류 상태가 있다 — 확대가 이름만 바꾼 탭이 된다`);
  }
  check(!looksLikeTabState(stripComments(graph)), 'TaskGraph 에 탭 류 상태가 있다');
  // 셸의 activeTab 은 **2단계에서는 정상**이다(탭 바가 살아 있다). 둘이 되지만 않으면 된다.
  const shell = stripComments(read('src', 'shell', 'AppShell.tsx'));
  const shellCount = (shell.match(/activeTab/g) ?? []).length;
  check(shellCount > 0, 'AppShell 에 activeTab 이 없다 — 2단계에서는 탭 바가 그대로여야 한다');
  const mainCount = (stripComments(main).match(/activeTab/g) ?? []).length;
  check(mainCount === 0, `탭① 화면(main.tsx)에 activeTab 이 ${mainCount}곳 생겼다 — 탭 상태는 셸 한 곳뿐이어야 한다`);
  if (!looksLikeTabState("const [activeTab, setActiveTab] = useState('a');")) {
    failures.push('대조군 실패: 탭 류 상태를 판정이 놓쳤다 — 이 검사는 무의미하다');
  }
  console.log(`✅ 탭 류 상태 — 캔버스·그래프에 0곳, 셸에만 ${shellCount}곳(3단계에 사라진다)`);
}

// ── ④ 확대는 한 번에 하나 ────────────────────────────────────────────────────
{
  // 상태가 문자열 하나다. 배열·집합이면 둘이 열린다.
  check(/const \[zoomedId, setZoomedId\] = useState<string \| null>\(null\)/.test(main), '확대 상태가 「문자열 하나」가 아니다 — 둘이 열릴 수 있다');
  check(/zoomedId: string \| null;/.test(graph), '캔버스 계약의 확대 상태가 「문자열 하나」가 아니다');
  check(!/zoomedIds|zoomed.*Set<|zoomed.*\[\]/.test(main + graph), '확대 상태가 여러 개를 담는 모양이다 — 분할 화면은 곧 탭이 된다');
  // 오버레이를 목록으로 그리지 않는다.
  check(!/<ZoomOverlay[\s\S]{0,200}\.map\(/.test(main) && !/\.map\([^)]*<ZoomOverlay/.test(main), '확대 오버레이를 목록으로 그린다 — 한 번에 하나여야 한다');
  console.log('✅ 확대는 한 번에 하나 — 상태가 문자열 하나이고 오버레이를 목록으로 그리지 않는다');
}

if (failures.length) {
  console.error('❌ 「확대는 탭이 아니다」 검사 실패:');
  for (const line of failures) console.error(`  - ${line}`);
  process.exit(1);
}
console.log('✅ 통과 — 오버레이 · 같은 자리 · 탭 상태 없음 · 동시 하나 (지시서 §6 네 조건)');
