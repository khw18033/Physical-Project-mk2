// scripts/lib/scriptPhrases.mjs (260918 신설 — 영문화 3단계 §1)
//
// **대본에서 화면에 뜨는 문구만 골라낸다.**
//
// 대본 JSON 에는 세 갈래가 섞여 있다.
//
//   화면에 뜨는 것   제목 · 평가 증거 · 액션 아이템 이름 …   ← 영어가 필요하다
//   조회 규칙        `match.must` · `match.any` …            ← `match_en` 이 따로 있다
//   개발 메모        `note` · `comment`                      ← 옮기지 않는다
//
// 그 셋을 가르는 자리가 여기 하나여야 한다. 생성기와 검사가 **같은 목록**을 봐야
// 「사이드카에 다 있다」가 참이 된다 — 갈라지면 둘 다 자기 기준으로 초록이 된다.

/**
 * 화면에 뜨는 자리. `[]` 는 배열 첨자를 뭉갠 것이다.
 *
 * 여기 없는 자리는 **옮기지 않는다**가 아니라 **화면에 안 뜬다**는 뜻이다.
 * 새 자리가 생기면 여기 한 줄을 더한다 — 검사가 그때 빠진 문구를 잡아 준다.
 */
export const DISPLAY_PATHS = [
  'title',
  'utterance.text',
  'milestones[].title',
  'tasks[].title',
  'tasks[].evaluation.criteria[]',
  'tasks[].actionItems[].label',
  'hardware[].kind',
  'hardware[].heartbeat',
  'refEdges[].label',
  'events[].payload.criterion',
  'events[].payload.reason',
  'events[].payload.phase',
  'events[].payload.detected',
  'events[].payload.destination',
  'viewpointTimeline[].payload.reason',
  'map.blind_cells[].reason',
  'params.destination',
];

const DISPLAY = new Set(DISPLAY_PATHS);

function walk(node, path, hit) {
  if (typeof node === 'string') {
    if (DISPLAY.has(path) && /[가-힣]/.test(node)) hit(node, path);
    return;
  }
  if (Array.isArray(node)) { for (const v of node) walk(v, `${path}[]`, hit); return; }
  if (node !== null && typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) walk(v, path === '' ? k : `${path}.${k}`, hit);
  }
}

/**
 * 한 편의 표시 문구 — **나온 차례대로, 중복 없이.**
 *
 * 중복을 지우는 것이 이 설계의 핵심이다. `events[].payload.criterion` 은
 * `tasks[].evaluation.criteria[]` 와 **같은 글자**이고, 둘을 따로 적으면 갈릴 수 있다.
 * 한 장의 사전이면 갈릴 자리가 없다.
 */
export function displayPhrases(script) {
  const seen = new Map();
  walk(script, '', (value, path) => {
    if (!seen.has(value)) seen.set(value, path);
  });
  return seen;
}
