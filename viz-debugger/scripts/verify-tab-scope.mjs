// 시나리오 → 탭 범위 (260901) — **같은 대응이 두 곳에 손으로 적히는 것을 막는다.**
//
// 이 검사가 막으려는 실패는 셋이다.
//  1. **표가 갈라지는 것** — 축→탭 표(AXIS_TABS)와 패널→축 표(SCENARIO_PANELS)가 서로 다른
//     탭을 가리키면, 탭 바는 흐린데 패널은 살아 있거나 그 반대가 된다. 사용자가 「이 대본엔
//     없음」이라고 적힌 탭을 눌렀는데 내용이 그대로 있으면 안내가 거짓말이 된다.
//  2. **화면과 표가 갈라지는 것** — 화면이 표에 없는 패널 id 로 접거나, 표에 있는 패널을
//     아무도 접지 않으면 표는 장식이 된다. 소스에서 실제 PanelGate/TabGate 사용을 읽어 맞춘다.
//  3. **세 편의 「쓰는 탭」이 지시서와 달라지는 것** — 대본을 고치다 축이 늘거나 줄면 조용히
//     달라진다. 1편 ①②④⑤ · 2편 ①②④⑤ · 3편 ①②③④ 를 못으로 박아 둔다.
//
// 규칙과 표는 `src/scenarios/axes.ts` 하나에서 읽는다 — 여기에 베껴 적으면 이 검사가
// 막으려던 실패를 이 검사가 저지르게 된다. 대본은 verify:script-library 와 같은 방식으로
// scenarios/*.json 을 직접 읽는다(브라우저 번들의 JSON import 는 Node ESM 에서 안 열린다).
//
// 음성 대조군 포함 — 표·화면·대본을 각각 무력화한 사본이 반드시 실패로 잡히는지 본다.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const axes = await import(pathToFileURL(join(root, 'src', 'scenarios', 'axes.ts')).href);
const { AXIS_TABS, SCENARIO_PANELS, TAB_LABEL, axesOfScript, panelAlive, panelsOfTab, tabsOfScript } = axes;
const { SCRIPT_IDS } = await import(pathToFileURL(join(root, 'src', 'scenarios', 'manifest.ts')).href);

const scripts = SCRIPT_IDS.map((id) =>
  JSON.parse(readFileSync(join(root, 'scenarios', `${id}.json`), 'utf8')),
);

const failures = [];
const controls = [];
const read = (...parts) => readFileSync(join(root, ...parts), 'utf8');

// ── ① 두 표의 아귀 ───────────────────────────────────────────────────────────
function checkTables(axisTabs, panels) {
  const f = [];
  const tabIds = new Set(Object.keys(TAB_LABEL));
  for (const [axis, tabs] of Object.entries(axisTabs)) {
    if (!Array.isArray(tabs) || tabs.length === 0) {
      f.push(`AXIS_TABS의 ${axis}에 탭이 없다 — 축이 어디에도 안 나타나면 그릴 자리가 없다`);
    }
    for (const tab of tabs) if (!tabIds.has(tab)) f.push(`AXIS_TABS의 ${axis}가 없는 탭 ${tab}을 가리킨다`);
    if (tabs.includes('debugger')) {
      f.push(`AXIS_TABS의 ${axis}가 탭①을 가리킨다 — 탭①은 임무 축이라 늘 살아 있고 표에 없어야 한다`);
    }
  }
  // 패널의 탭이 그 패널 축의 탭 목록 안에 있어야 한다.
  for (const panel of panels) {
    if (panel.axes.length === 0) f.push(`패널 ${panel.id}에 축이 없다 — 접힘 판정을 할 수 없다`);
    for (const axis of panel.axes) {
      const tabs = axisTabs[axis];
      if (tabs === undefined) {
        f.push(`패널 ${panel.id}이 표에 없는 축 ${axis}를 쓴다`);
        continue;
      }
      if (!tabs.includes(panel.tab)) {
        f.push(`어긋남: 패널 ${panel.id}은 탭 ${panel.tab}에 있는데 축 ${axis}의 표는 [${tabs.join(', ')}]다`);
      }
    }
  }
  // 역방향 — 표의 (축→탭) 칸을 아무 패널도 맡지 않으면 그 축은 그 탭에서 접힘 판정을 못 받는다.
  for (const [axis, tabs] of Object.entries(axisTabs)) {
    for (const tab of tabs) {
      if (!panels.some((p) => p.tab === tab && p.axes.includes(axis))) {
        f.push(`빈 칸: 축 ${axis}가 탭 ${tab}에 나타난다고 적혀 있는데 그 탭에 이 축을 맡은 패널이 없다`);
      }
    }
  }
  return f;
}
failures.push(...checkTables(AXIS_TABS, SCENARIO_PANELS));

// ── ② 화면과 표 ──────────────────────────────────────────────────────────────
// 화면이 실제로 어떤 id/탭으로 접는지 소스에서 읽는다. 표에 적어 두고 화면이 안 쓰면
// 표는 장식이고, 화면이 표에 없는 id 를 쓰면 런타임에 터진다.
const gateSources = [
  ['src/tabs/index.tsx', read('src', 'tabs', 'index.tsx')],
  ['src/tabs/views/MetricsView.tsx', read('src', 'tabs', 'views', 'MetricsView.tsx')],
];
function collectGates(sources) {
  const panelIds = new Set();
  const tabIds = new Set();
  for (const [, source] of sources) {
    for (const m of source.matchAll(/<PanelGate\s+id="([^"]+)"/g)) panelIds.add(m[1]);
    for (const m of source.matchAll(/<TabGate\s+tab="([^"]+)"/g)) tabIds.add(m[1]);
  }
  return { panelIds, tabIds };
}
function checkScreens(sources, panels) {
  const f = [];
  const { panelIds, tabIds } = collectGates(sources);
  for (const id of panelIds) {
    if (!panels.some((p) => p.id === id)) f.push(`화면이 표에 없는 패널 id 로 접는다 — ${id}`);
  }
  for (const panel of panels) {
    if (!panelIds.has(panel.id)) {
      f.push(`표의 패널 ${panel.id}(${panel.title})을 아무 화면도 접지 않는다 — 표가 장식이 된다`);
    }
  }
  // 탭 넷(②~⑤)은 전부 TabGate 를 지나야 한다. 탭①은 셸이 프롭으로 받는 화면이라 없다.
  for (const tab of ['overview', 'control', 'metrics', 'video']) {
    if (!tabIds.has(tab)) f.push(`탭 ${tab}에 TabGate 가 없다 — 패널이 전부 접혀도 본문이 그대로 뜬다`);
  }
  return f;
}
failures.push(...checkScreens(gateSources, SCENARIO_PANELS));

// 접힘은 **시나리오 모드에서만**이다 — 일반·목 모드에서 접히면 「남이 줄 데이터가 어디에
// 얼마나 있는지」를 보여 주는 화면이 사라진다.
const gateSource = read('src', 'tabs', 'ScenarioGate.tsx');
function checkModeGuard(source) {
  const f = [];
  // 두 게이트 모두 「시나리오 모드가 아니면 axes 가 null → 전부 그린다」로 시작해야 한다.
  const guards = [...source.matchAll(/axes === null\) return <>\{children\}<\/>;/g)].length;
  if (guards < 2) f.push(`ScenarioGate 에 시나리오 모드 가드가 ${guards}곳뿐이다 — PanelGate·TabGate 둘 다 있어야 한다`);
  if (!source.includes('enterScriptPreview')) {
    f.push('접힘 카드에 「그 대본으로 바꾸기」 경로가 없다 — 막지 않는다는 규칙이 화면에서 사라졌다');
  }
  return f;
}
failures.push(...checkModeGuard(gateSource));

// 층 1 — 안 쓰는 탭은 흐리게 하되 **막지 않는다.** 막으면 「왜 안 눌리지」가 새 질문이 된다.
const shellSource = read('src', 'shell', 'AppShell.tsx');
if (!shellSource.includes('app-tabs__unused')) failures.push('탭 바에 안 쓰는 탭 표시(app-tabs__unused)가 없다 — 층 1이 없다');
if (/app-tabs__unused[\s\S]{0,400}?disabled/.test(shellSource)) failures.push('안 쓰는 탭을 disabled 로 막았다 — 눌러서 확인할 수 있어야 한다');
if (!shellSource.includes('nowPlaying(')) failures.push('셸이 「지금」 안내줄을 그리지 않는다 — 탭을 옮겨도 남으려면 셸이 그려야 한다');

// ── ③ 세 편의 「쓰는 탭」 — 지시서 표를 못으로 박는다 ─────────────────────────
const EXPECTED = {
  'MSN-260831-01': ['debugger', 'overview', 'metrics', 'video'],
  'MSN-260831-02': ['debugger', 'overview', 'metrics', 'video'],
  'MSN-260831-03': ['debugger', 'overview', 'control', 'metrics'],
};
function checkScripts(list) {
  const f = [];
  for (const script of list) {
    const want = EXPECTED[script.missionId];
    if (want === undefined) {
      f.push(`쓰는 탭 기대표에 ${script.missionId}가 없다 — 대본을 더했으면 표도 더해야 한다`);
      continue;
    }
    const got = [...tabsOfScript(script)].sort();
    if (got.join(',') !== [...want].sort().join(',')) {
      f.push(`${script.missionId}의 쓰는 탭이 [${got.join(', ')}] — 기대는 [${want.join(', ')}]`);
    }
  }
  return f;
}
failures.push(...checkScripts(scripts));

// 패널 단위까지 — 「1편에서 탭③이 통째로 접히는가」를 패널 표로 다시 확인한다.
function collapsedPanels(script) {
  const set = axesOfScript(script);
  return SCENARIO_PANELS.filter((p) => !panelAlive(p, set)).map((p) => p.id);
}
const PANEL_EXPECTED = {
  'MSN-260831-01': ['risk', 'control', 'metrics-push'],
  'MSN-260831-02': ['risk', 'control', 'metrics-push'],
  'MSN-260831-03': ['risk', 'zone-map', 'metrics-push', 'video'],
};
for (const script of scripts) {
  const got = collapsedPanels(script).sort();
  const want = [...(PANEL_EXPECTED[script.missionId] ?? [])].sort();
  if (got.join(',') !== want.join(',')) {
    failures.push(`${script.missionId}에서 접히는 패널이 [${got.join(', ')}] — 기대는 [${want.join(', ')}]`);
  }
}
// 탭 전체가 접히는 경우 — 그 탭의 패널이 하나도 안 살아야 「한 장으로 대체」가 성립한다.
for (const script of scripts) {
  const set = axesOfScript(script);
  const used = tabsOfScript(script);
  for (const tab of Object.keys(TAB_LABEL)) {
    if (tab === 'debugger') continue;
    const alive = panelsOfTab(tab).some((p) => panelAlive(p, set));
    if (alive !== used.has(tab)) {
      failures.push(
        `${script.missionId}: 탭 ${tab} — 탭 바는 ${used.has(tab) ? '쓴다' : '안 쓴다'}는데 패널은 ${alive ? '살아 있다' : '전부 접힌다'}`,
      );
    }
  }
}

// ── 음성 대조군 — 무력화한 사본이 반드시 잡히는가 ────────────────────────────
function control(name, found, marker) {
  if (!found.some((msg) => msg.includes(marker))) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  else controls.push(name);
}
control('축→탭 표를 옮김 (actuator를 탭④로)', checkTables({ ...AXIS_TABS, actuator: ['metrics'] }, SCENARIO_PANELS), '어긋남');
control(
  '패널을 다른 탭으로 (제어 패널을 탭②로)',
  checkTables(AXIS_TABS, SCENARIO_PANELS.map((p) => (p.id === 'control' ? { ...p, tab: 'overview' } : p))),
  '어긋남',
);
control(
  '표에만 있고 화면이 안 쓰는 패널',
  checkScreens(gateSources, [...SCENARIO_PANELS, { id: 'ghost', tab: 'overview', title: '유령', axes: ['position'], why: '' }]),
  'ghost',
);
control(
  'TabGate 삭제 사본',
  checkScreens(gateSources.map(([name, src]) => [name, src.replaceAll('<TabGate tab="control"', '<div data-x="control"')]), SCENARIO_PANELS),
  'TabGate 가 없다',
);
control('모드 가드 삭제 사본', checkModeGuard(gateSource.replaceAll('axes === null', 'false')), '가드');
control(
  '대본에 액추에이터 명령 주입 (1편이 탭③을 쓰게 됨)',
  checkScripts([
    { ...scripts[0], commands: [{ atSec: 1, entity: 'actuator-01', action: 'close_gate', producedBy: 'backend', taskId: 'x' }] },
  ]),
  '쓰는 탭',
);

if (failures.length) {
  console.error(`❌ verify:tab-scope\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 축→탭 표(${Object.keys(AXIS_TABS).length}축)와 패널→축 표(${SCENARIO_PANELS.length}패널)의 아귀 — 양방향 대조, 빈 칸 없음`);
console.log('✅ 화면과 표 — 게이트가 표의 id 만 쓰고 표의 패널을 전부 누군가 접는다 · 접힘은 시나리오 모드에서만 · 탭 바는 흐리게만 하고 막지 않는다');
console.log('✅ 쓰는 탭 — 1편 ①②④⑤ · 2편 ①②④⑤ · 3편 ①②③④ (탭 바와 패널 접힘이 서로 어긋나지 않음)');
console.log(`✅ 음성 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
