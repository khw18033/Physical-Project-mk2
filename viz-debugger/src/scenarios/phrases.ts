/**
 * src/scenarios/phrases.ts (260918 신설 — 영문화 3단계 §1)
 *
 * **대본의 글자를 영어로 바꾼다. 사전(`i18n/`)이 아니라 데이터 쪽이다.**
 *
 * `i18n/ko.ts`·`en.ts` 는 **화면이 쓴 문구**를 담는다. 대본 제목·평가 증거·액션 아이템
 * 이름은 화면이 쓴 것이 아니라 **대본이 들고 온 값**이다. 둘을 한 사전에 담으면
 * 대본 한 편이 늘 때마다 사전이 부풀고, 번역 검수에서 무엇이 화면 문구이고 무엇이
 * 데이터인지가 흐려진다. 그래서 편마다 사이드카 한 장(`MSN-*.en.json`)을 둔다.
 *
 * ## 키가 한국어인 것은 일부러다
 *
 * ```
 *   tasks[].evaluation.criteria[]   「문 열림이 탐지 결과로 확인된다」
 *   events[].payload.criterion      「문 열림이 탐지 결과로 확인된다」   ← 같은 글자
 * ```
 *
 * 둘은 대본 안에서 **같은 문장**이고, 경로 기반 사전이면 같은 것을 두 번 적어야 한다.
 * 두 번 적으면 갈릴 수 있고, 갈리면 화면이 한 임무에 두 말을 한다. 문구 사전은 갈릴
 * 자리가 없다 — **한국어가 키이므로 같은 글자는 저절로 같은 영어**가 된다.
 *
 * ## 한국어 화면은 원본 객체를 그대로 돌려준다
 *
 * `translateView()` 는 `ko` 에서 **입력을 그대로 반환한다.** 복사도 안 한다 —
 * 한국어 화면이 한 글자도 달라지면 안 된다는 요구가 있고, 손대지 않는 것이 그 요구를
 * 지키는 가장 싼 방법이다. 참조가 그대로라 `useSyncExternalStore` 의 같음 비교도 안 깨진다.
 */

import { getLang, type Lang } from '../shared/language.ts';
import en260826 from '../../scenarios/MSN-260826-01.en.json' with { type: 'json' };
import en260831a from '../../scenarios/MSN-260831-01.en.json' with { type: 'json' };
import en260831b from '../../scenarios/MSN-260831-02.en.json' with { type: 'json' };
import en260831c from '../../scenarios/MSN-260831-03.en.json' with { type: 'json' };
import en260909 from '../../scenarios/MSN-260909-01.en.json' with { type: 'json' };
import en260915 from '../../scenarios/MSN-260915-01.en.json' with { type: 'json' };
import type { ScriptMatch } from './types.ts';

type Sidecar = {
  missionId: string;
  phrases: Record<string, string>;
  match_en?: ScriptMatch;
};

const SIDECARS = [en260826, en260831a, en260831b, en260831c, en260909, en260915] as unknown as Sidecar[];

const BY_ID = new Map<string, Sidecar>(SIDECARS.map((s) => [s.missionId, s]));

/**
 * 대본 문구 하나. 영어가 없으면 **한국어를 그대로 돌려준다** — 사전(`t()`)과 같은 규칙이다.
 *
 * 값이 한국어가 아니면(숫자·식별자) 찾지도 않는다. 번역 대상이 아닌 것을 사이드카에
 * 넣으라고 검사가 조르는 일이 없게 한다.
 */
export function scriptPhrase(
  missionId: string | null | undefined,
  korean: string,
  lang: Lang = getLang(),
): string {
  // 260919 — **언어를 값으로 받는다.** 목 게이트웨이가 이 함수를 그대로 끌어 쓰는데,
  // 서버에는 브라우저 전역이 없어 `getLang()` 이 늘 `ko` 다. 그래서 승인 팝업의 구간
  // 이름(대본 마일스톤)이 영문 화면에서도 한국어로 남아 있었다 — `verify:gateway-wire` 가 찾았다.
  if (lang !== 'en' || missionId === null || missionId === undefined) return korean;
  return BY_ID.get(missionId)?.phrases[korean] ?? korean;
}

/**
 * 그 편의 **영어 조회 규칙**. 없으면 null — 그때는 한국어 규칙만 돈다.
 *
 * 영어 화면에서 영어로 말했는데 한국어 규칙으로 고르려 하면 아무것도 안 맞는다.
 * 「억지로 고르지 않는다」가 원칙이므로 안 맞으면 생성 경로로 간다(`matcher.ts`).
 */
export function matchEnOf(missionId: string): ScriptMatch | null {
  return BY_ID.get(missionId)?.match_en ?? null;
}

/** 이 편에 영어 사이드카가 있는가. 검사와 화면 안내가 쓴다. */
export function hasSidecar(missionId: string): boolean {
  return BY_ID.has(missionId);
}

/** payload 안에서 화면에 뜨는 칸. 나머지(숫자·식별자)는 건드리지 않는다. */
// 260920 — `line` 이 늘었다. 액션 층의 `answered` 가 로봇이 준 한 줄을 여기 싣는다.
// 대본이 쓴 줄은 사이드카에 있으므로 바뀌고, **실시간으로 받은 줄은 그대로 남는다** —
// 그것은 로봇이 준 값이지 우리가 쓴 문장이 아니다(위 주석과 같은 규칙).
const PAYLOAD_FIELDS = ['criterion', 'reason', 'phase', 'detected', 'destination', 'line'] as const;

function payload(missionId: string, value: unknown): unknown {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return value;
  const source = value as Record<string, unknown>;
  let changed = false;
  const out: Record<string, unknown> = { ...source };
  for (const field of PAYLOAD_FIELDS) {
    const v = source[field];
    if (typeof v !== 'string') continue;
    const en = scriptPhrase(missionId, v);
    if (en !== v) { out[field] = en; changed = true; }
  }
  return changed ? out : value;
}

/** 사건 열 — 대본이 쓴 문장만 바뀐다. 실시간으로 받은 것은 사이드카에 없으므로 그대로 남는다. */
export function translateEvents<T extends { payload?: unknown }>(missionId: string, events: readonly T[]): readonly T[] {
  if (getLang() !== 'en' || !BY_ID.has(missionId)) return events;
  let changed = false;
  const out = events.map((e) => {
    const next = payload(missionId, e.payload);
    if (next === e.payload) return e;
    changed = true;
    return { ...e, payload: next };
  });
  return changed ? out : events;
}

/** `MissionView` 를 닮은 것. 여기서 `MissionView` 를 import 하면 `data/` → `scenarios/` 고리가 생긴다. */
type ViewLike = {
  missionId: string;
  label: string;
  utteranceText: string;
  milestones: readonly { title: string }[];
  tasks: readonly {
    title: string;
    evaluation?: { criteria?: readonly string[] } | null;
    actionItems?: readonly { label: string }[];
  }[];
  events: readonly { payload?: unknown }[];
  hardware?: readonly { kind?: string; heartbeat?: string }[] | null;
  refEdges?: readonly { label?: string }[];
  viewpointTimeline?: readonly { payload?: unknown }[];
  map?: { blind_cells?: readonly { reason?: string }[] } | null;
  params?: Record<string, unknown>;
};

/**
 * 화면이 그릴 임무 하나를 영어로. **`ko` 면 입력을 그대로 돌려준다.**
 *
 * 캐시는 편 하나치만 둔다 — 화면이 한 번에 그리는 임무는 하나이고, 그리기마다 통째로
 * 새로 만들면 `useSyncExternalStore` 가 매번 바뀐 것으로 본다.
 */
let cache: { key: string; view: ViewLike } | null = null;

export function translateView<T extends ViewLike>(view: T): T {
  if (getLang() !== 'en' || !BY_ID.has(view.missionId)) return view;
  const key = `${view.missionId}`;
  if (cache !== null && cache.key === key && (cache.view as unknown as { __src?: unknown }).__src === view) {
    return cache.view as T;
  }
  const p = (v: string) => scriptPhrase(view.missionId, v);
  const out: ViewLike & { __src?: unknown } = {
    ...view,
    label: p(view.label),
    utteranceText: p(view.utteranceText),
    milestones: view.milestones.map((m) => ({ ...m, title: p(m.title) })),
    tasks: view.tasks.map((task) => ({
      ...task,
      title: p(task.title),
      evaluation: task.evaluation
        ? { ...task.evaluation, criteria: task.evaluation.criteria?.map(p) }
        : task.evaluation,
      actionItems: task.actionItems?.map((a) => ({ ...a, label: p(a.label) })),
    })),
    events: translateEvents(view.missionId, view.events),
    hardware: view.hardware?.map((h) => ({
      ...h,
      kind: h.kind === undefined ? h.kind : p(h.kind),
      heartbeat: h.heartbeat === undefined ? h.heartbeat : p(h.heartbeat),
    })) ?? view.hardware,
    refEdges: view.refEdges?.map((e) => ({ ...e, label: e.label === undefined ? e.label : p(e.label) })),
    viewpointTimeline: view.viewpointTimeline === undefined
      ? view.viewpointTimeline
      : translateEvents(view.missionId, view.viewpointTimeline),
    map: view.map
      ? { ...view.map, blind_cells: view.map.blind_cells?.map((c) => ({ ...c, reason: c.reason === undefined ? c.reason : p(c.reason) })) }
      : view.map,
    params: view.params === undefined
      ? view.params
      : typeof view.params.destination === 'string'
        ? { ...view.params, destination: p(view.params.destination) }
        : view.params,
  };
  out.__src = view;
  cache = { key, view: out };
  return out as T;
}
