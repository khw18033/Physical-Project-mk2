// verify:i18n-demo-path (260917 신설 — 영문화 2단계 지시서 §7)
//
// **시연 경로가 영어로 도는 상태를 못 잃게 한다.**
//
// 2단계가 22개 파일 608개 문구를 사전으로 옮겼다. 그 뒤로 누가 그 파일에 한글을 한 줄
// 직접 박으면, 화면은 한국어에서 멀쩡해 보이고 **영문 화면에서만 그 한 줄이 한국어로 남는다.**
// 눈으로 보기 전에는 모른다 — 그래서 검사로 잡는다.
//
// 보는 것 넷.
//  1. **시연 경로 22개 파일에 표시용 한글이 0건** — 주석·타입은 제외한다
//  2. **`t()` 를 쓰는 컴포넌트는 `useLang()` 을 갖는다** — 1단계 보고서 §3 ①이 지목한 함정
//  3. **ko 키가 en 에도 있다** — 시범 키 `mode.mock` 하나만 예외(그 빈자리가 fallback 의 증거다)
//  4. 대조군 — 위 셋을 어긴 사본이 반드시 잡혀야 한다
//
// 5단계의 `verify:no-raw-korean` 이 1번을 저장소 전체로 넓힌 것이 된다.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const { ko } = await import(pathToFileURL(join(root, 'src', 'i18n', 'ko.ts')).href);
const { en } = await import(pathToFileURL(join(root, 'src', 'i18n', 'en.ts')).href);

const failures = [];
const controls = [];

/** 2단계 범위 (지시서 §1). 늘리는 것은 3·4단계의 몫이다 — 줄이면 시연이 영어로 안 돈다. */
const DEMO_PATH = [
  'shared/pendingSources.ts', 'shared/PendingSource.tsx',
  'views/UtterancePanel.tsx', 'views/ActionModal.tsx', 'views/MissionHistory.tsx', 'views/ResetButton.tsx',
  'shell/HelpOverlay.tsx', 'shell/AppShell.tsx', 'shell/ConnectionsPanel.tsx', 'shell/ModeSwitch.tsx', 'shell/ConnectionLamp.tsx',
  'tabs/views/PlanApproval.tsx', 'physical/StopButton.tsx',
  'graph/TaskGraph.tsx', 'graph/shape.ts', 'graph/stateStyle.ts',
  'canvas/ViewNodeCard.tsx', 'canvas/Palette.tsx', 'canvas/ZoomOverlay.tsx',
  'canvas/persist.ts', 'canvas/useCanvas.ts', 'canvas/registry.ts',
];

/**
 * **개발자에게만 보이는 한글은 대상이 아니다.**
 *
 * `throw new Error('…')` 는 프로그래밍 실수를 알리는 자리이고 화면에 안 뜬다. 옮기면
 * 사전이 화면 문구와 개발 메시지를 섞어 담게 되고, 번역 품질 검수에서 무엇을 봐야 하는지가
 * 흐려진다. 두 곳뿐이라 목록으로 못박는다 — 늘면 여기가 먼저 걸린다.
 */
const DEV_ONLY = [
  'pendingSources 에 없는 id',
  '뷰 노드 kind 가 중복 등록됐다',
];

const read = (rel) => readFileSync(join(root, 'src', rel), 'utf8');
/** 주석을 지운다 — 이 저장소의 주석은 한글로 길고, 그건 옮길 대상이 아니다. */
const code = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

// ── 1. 시연 경로에 표시용 한글이 0건 ─────────────────────────────────────────
{
  let checked = 0;
  for (const rel of DEMO_PATH) {
    const src = code(read(rel));
    const literals = [...src.matchAll(/(['"`])((?:[^\\\n]|\\.)*?)\1/g)].map((m) => m[2]);
    const jsxText = [...src.matchAll(/>([^<>{}]*[가-힣][^<>]*)</g)].map((m) => m[1].trim());
    const left = [...literals.filter((v) => /[가-힣]/.test(v)), ...jsxText]
      .filter((v) => !DEV_ONLY.some((allow) => v.includes(allow)));
    checked += 1;
    for (const v of left) {
      failures.push(`${rel}: 한글이 직접 박혀 있다 — 「${v.slice(0, 50)}」. 사전으로 보내라 (t())`);
    }
  }
  if (checked !== DEMO_PATH.length) failures.push('시연 경로 파일을 다 못 읽었다');
  console.log(`✅ 시연 경로 ${DEMO_PATH.length}개 파일에 표시용 한글 0건 — 개발자 메시지 ${DEV_ONLY.length}건만 예외`);
}

// ── 2. `t()` 를 쓰면 `useLang()` 도 있다 ─────────────────────────────────────
//
// **1단계에서 실제로 밟은 함정이다** (보고서 §3 ①). `t()` 는 부르는 순간의 값을 줄 뿐
// 구독이 아니라, 이 훅이 없으면 그 부품만 옛 언어로 남는다. 증상이 「일부만 안 바뀐다」라
// 원인을 찾기 어렵다 — 2단계에서 세 번 빠뜨렸고 세 번 다 이 규칙으로 잡았다.
{
  let withT = 0;
  for (const rel of DEMO_PATH) {
    const src = code(read(rel));
    if (!/\bt\(/.test(src)) continue;
    withT += 1;
    // **`.tsx` 만 컴포넌트다.** `.ts` 는 순수 함수라 부르는 쪽이 훅을 갖고 있으면 된다
    // (`graph/shape.ts` 의 `shapeLabel()` 을 `main.tsx` 가 그리는 식).
    //
    // 처음에는 `<` 가 있는지로 갈랐는데 `Record<Plane, string>` 같은 **타입 제네릭**이 걸려
    // 순수 모듈 넷이 거짓 실패로 떴다. 확장자가 정확한 잣대다.
    if (!rel.endsWith('.tsx')) continue;
    if (!/useLang\(\)/.test(src)) {
      failures.push(`${rel}: t() 를 쓰는데 useLang() 이 없다 — 언어를 바꿔도 이 부품만 옛 언어로 남는다`);
    }
  }
  console.log(`✅ useLang() — t() 를 쓰는 ${withT}개 파일이 전부 언어 전환에 다시 그린다`);
}

// ── 3. ko 키가 en 에도 있다 ──────────────────────────────────────────────────
//
// **시범 키 `mode.mock` 하나만 비어 있어야 한다.** 그 빈자리가 fallback 이 실제로 도는
// 증거이고(1단계 §4 다섯째), 채우면 2단계 이후로 그 증거가 사라진다.
{
  const EXPECTED_GAP = ['mode.mock'];
  const missing = Object.keys(ko).filter((key) => en[key] === undefined);
  const unexpected = missing.filter((key) => !EXPECTED_GAP.includes(key));
  const filled = EXPECTED_GAP.filter((key) => en[key] !== undefined);
  for (const key of unexpected) failures.push(`en 에 없는 키: ${key} — 시연 경로 키는 전부 있어야 한다`);
  for (const key of filled) failures.push(`${key} 가 en 에 채워졌다 — 이 빈자리가 fallback 이 도는 증거다 (1단계 §4 다섯째)`);
  const orphan = Object.keys(en).filter((key) => ko[key] === undefined);
  for (const key of orphan) failures.push(`ko 에 없는데 en 에만 있는 키: ${key} — 한국어가 없으면 fallback 이 키 이름을 그린다`);
  console.log(`✅ 사전 — ko ${Object.keys(ko).length}키 · en ${Object.keys(en).length}키 · 비어 있는 것은 ${EXPECTED_GAP.join(', ')} 하나뿐`);
}

// ── 4. 대조군 — 위 셋을 어긴 사본이 잡혀야 한다 ──────────────────────────────
//
// 실제 파일을 안 건드린다. 판정식에 손으로 만든 입력을 먹여 **잣대가 무는지**만 본다 —
// 진짜 위반이 하나라도 있으면 대조군이 그것 때문에 통과/실패해서 무엇을 확인한 것인지
// 알 수 없어진다 (검사 위생 260917 에서 세운 규약).
{
  const hangul = (src) => {
    const s = code(src);
    return [...[...s.matchAll(/(['"`])((?:[^\\\n]|\\.)*?)\1/g)].map((m) => m[2]).filter((v) => /[가-힣]/.test(v)),
      ...[...s.matchAll(/>([^<>{}]*[가-힣][^<>]*)</g)].map((m) => m[1])].length;
  };
  const cases = [
    ['JSX 에 한글을 도로 박은 사본', hangul('const a = <p>연결 예정</p>;') > 0, true],
    ['문자열에 한글을 도로 박은 사본', hangul("const a = '연결 예정';") > 0, true],
    ['주석의 한글 (잡으면 안 된다)', hangul('// 연결 예정을 그린다\nconst a = 1;') > 0, false],
    ['키만 든 코드 (잡으면 안 된다)', hangul("const a = <p>{t('conn.pendingBadge')}</p>;") > 0, false],
  ];
  for (const [label, caught, shouldCatch] of cases) {
    if (caught !== shouldCatch) {
      failures.push(`대조군 실패: ${label} — ${shouldCatch ? '잡아야 하는데 놓쳤다' : '잡으면 안 되는데 잡았다'}. 이 검사는 무의미하다`);
    } else controls.push(label);
  }
}

if (failures.length) {
  console.error(`❌ verify:i18n-demo-path\n- ${failures.join('\n- ')}`);
  console.error('\n   시연 경로에 한글이 직접 박히면 한국어 화면은 멀쩡하고 영문 화면에서만 그 줄이 남는다.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — 박힌 한글은 잡고, 주석과 키는 통과시킨다`);
