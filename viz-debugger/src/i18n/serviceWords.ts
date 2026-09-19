/**
 * src/i18n/serviceWords.ts (260919 신설 — 영문화 5단계 §4)
 *
 * **탐지 서비스가 한국어로 말한다.** 그 말을 영문 화면에서 읽을 수 있게 옮긴다.
 *
 * ## 왜 사전이 아니라 여기인가
 *
 * 탐지 서비스는 **우리 저장소에 없다.** 탐지 파트의 PC에서 도는 별도 프로그램이고,
 * 우리가 고쳐 `_en` 을 달아 달라고 할 수 없다. 게이트웨이(우리 것)는 요청한 언어로
 * 답하게 고쳤지만 여기는 그 길이 막혀 있다.
 *
 * 화면 사전(`i18n/ko.ts`)에 넣는 것도 아니다 — 그 글자는 **우리가 쓴 것이 아니다.**
 * 서비스가 문장을 한 줄 바꾸면 사전은 조용히 낡고, 아무도 모르는 채 옛 번역이 뜬다.
 *
 * 그래서 **옮기는 표를 따로 두고, 모르는 문장은 한국어 그대로 통과시킨다.**
 * 지어내지 않는다 — 못 옮긴 것은 못 옮긴 채로 보이는 편이 낫다.
 *
 * ## 원문을 버리지 않는다
 *
 * 화면은 옮긴 말을 보여 주고, **원문 한국어는 로그의 상세 줄에 그대로 남긴다**
 * (260919 사용자 결정). 탐지 파트와 이야기할 때 화면에 뜬 영어가 아니라 **서비스가
 * 실제로 뱉은 글자**를 보고 말해야 한다.
 *
 * ## 모양은 조각으로 이어져 있다
 *
 * 기록 45판에서 받은 문장을 다 모아 보니 이렇다.
 *
 *     경로 산출 실패 -- 문이 어느 프레임에서도 검출되지 않음 -- 갈 방향이 없다
 *       (위치 추정: pedestal이 … / 문만으로도 위치를 못 잡음: 문이 …)
 *
 * ` -- ` 와 ` · ` 로 이어진 **조각마다 그 자체로 완결된 말**이라, 조각을 옮기고 이음매는
 * 그대로 두면 된다. 낱개 모양은 여덟 가지뿐이고 숫자만 바뀐다.
 *
 * ## 왜 `detect/` 가 아니라 여기인가
 *
 * 이건 **옮기는 표**다. 문장이 탐지에서 왔다는 것은 출처일 뿐이고 하는 일은 사전과 같다.
 * `detect/` 에 두면 자율주행처럼 탐지를 못 보는 면이 이 표를 못 쓴다 — `verify:autodrive-ai`
 * 가 그 경계를 지키고, 260919 에 실제로 한 번 걸렸다.
 */

import type { Lang } from '../shared/language.ts';

/** 한 조각을 옮기는 규칙. 안 맞으면 다음으로 넘어간다. */
type Rule = readonly [RegExp, (m: RegExpMatchArray) => string];

/**
 * 기록 45판에서 실제로 받은 모양 전부. `verify:detect-words` 가 그 45판을 다시 훑어
 * **빠진 모양이 없는지** 본다 — 서비스가 새 문장을 뱉으면 그 검사가 알려 준다.
 */
const RULES: readonly Rule[] = [
  // 회전 지시 — 화면이 가장 크게 그리는 한 줄이다.
  [/^왼쪽\(반시계\)으로 ([\d.]+)도 회전$/, (m) => `Turn ${m[1]}° left (counter-clockwise)`],
  [/^오른쪽\(시계\)으로 ([\d.]+)도 회전$/, (m) => `Turn ${m[1]}° right (clockwise)`],

  // 경로를 어떤 근거로 냈나 (A·B·C 세 갈래).
  [/^도면 위 로봇 자리에서 목표까지 산출 \(A -- 단상 기반 위치\)$/,
    () => 'Computed on the plan from the robot to the target (A — position from the podium)'],
  [/^도면 위 로봇 자리에서 목표까지 산출 \(B -- 문만으로 추정한 위치\)$/,
    () => 'Computed on the plan from the robot to the target (B — position estimated from the door alone)'],
  [/^C -- 로봇 위치를 못 잡아 문 관측\(방위·겉보기 크기\)만으로 산출\. 도면 위 경로 그림 없음$/,
    () => 'C — the robot position could not be fixed, so this comes from door observations alone (bearing · apparent size). No path drawing on the plan'],

  // 실패·대체 경로의 각 걸음.
  [/^경로 산출 실패$/, () => 'Path computation failed'],
  [/^pedestal이 어느 프레임에서도 검출되지 않아 로봇 위치를 추정할 수 없음$/,
    () => 'The pedestal was not detected in any frame, so the robot position cannot be estimated'],
  [/^문이 어느 프레임에서도 검출되지 않음$/, () => 'The door was not detected in any frame'],
  [/^갈 방향이 없다$/, () => 'there is no direction to go'],
  [/^문이 검출된 프레임이 없거나, 모든 치수가 프레임 가장자리에 잘려 거리를 못 구함$/,
    () => 'No frame detected the door, or every dimension was clipped at the frame edge, so the distance cannot be computed'],
  [/^방향은 알지만 얼마나 갈지 모른다$/, () => 'the direction is known but not how far to go'],
  [/^도면 기반 경로 산출$/, () => 'Path computed from the plan'],
  [/^단상 관측 (\d+)프레임$/, (m) => `Pedestal seen in ${m[1]} frame(s)`],
  [/^추정 위치 \(([\d.-]+), ([\d.-]+)\)cm가 단상 안$/,
    (m) => `The estimated position (${m[1]}, ${m[2]}) cm falls inside the pedestal`],
  [/^문 거리 ([\d.]+)cm\(겉보기 크기\) · 문 방위 ([\d.]+)도\(bearing_refinement\)$/,
    (m) => `Door distance ${m[1]} cm (apparent size) · door bearing ${m[2]}° (bearing_refinement)`],
  [/^문 방위 ([\d.]+)도 · 문 거리 ([\d.]+)cm -- 도면 위치 없이 산출$/,
    (m) => `Door bearing ${m[1]}° · door distance ${m[2]} cm — computed without a position on the plan`],

  // 괄호 안의 라벨 둘.
  [/^위치 추정: (.*)$/s, (m) => `position estimate: ${translateParts(m[1])}`],
  [/^문만으로도 위치를 못 잡음: (.*)$/s, (m) => `could not fix the position from the door alone: ${translateParts(m[1])}`],
];

/** 한 조각. 못 옮기면 **한국어 그대로** 돌려준다 — 지어내지 않는다. */
function piece(korean: string): string {
  const one = korean.trim();
  for (const [re, make] of RULES) {
    const m = re.exec(one);
    if (m !== null) return make(m);
  }
  return one;
}

/**
 * 이음매(` -- ` · ` · ` · ` / `)는 그대로 두고 **조각만** 옮긴다.
 *
 * 괄호는 통째로 한 조각으로 보고 안쪽을 다시 나눈다 — 「(위치 추정: A / B)」 처럼
 * 설명이 괄호 안에 또 이어져 있다.
 */
function translateParts(korean: string): string {
  const one = korean.trim();

  // **통째로 아는 문장을 먼저 본다.** 안 그러면 「문 거리 …cm(겉보기 크기) · 문 방위 …」가
  // 가운데 ` · ` 에서 쪼개져 규칙에 영영 안 걸린다 (처음에 그렇게 만들어 25건을 놓쳤다).
  const direct = piece(one);
  if (direct !== one) return direct;

  const wrapped = /^\((.*)\)$/s.exec(one);
  if (wrapped !== null) return `(${translateParts(wrapped[1])})`;

  // 「… (…)」 — 뒤에 괄호가 붙은 모양은 앞뒤를 갈라 따로 옮긴다.
  const tail = /^(.*?)\s+\((.*)\)$/s.exec(one);
  if (tail !== null) return `${translateParts(tail[1])} (${translateParts(tail[2])})`;

  for (const sep of [' -- ', ' · ', ' / ']) {
    if (korean.includes(sep)) {
      return korean.split(sep).map(translateParts).join(sep === ' -- ' ? ' — ' : sep);
    }
  }
  return one;
}

/**
 * 탐지 서비스가 준 한 줄을 **화면 언어로**. `ko` 면 입력을 그대로 돌려준다 —
 * 한국어 화면은 한 글자도 안 달라진다.
 */
export function serviceWords(korean: string | null | undefined, lang: Lang): string {
  if (korean === null || korean === undefined || korean === '') return '';
  if (lang !== 'en') return korean;
  return translateParts(korean);
}

/**
 * 그 줄을 **옮겼는가.** 원문을 나란히 보여 줄지 정할 때 쓴다 — 안 옮겨졌으면
 * 화면에 이미 한국어가 떠 있으므로 원문을 또 적을 이유가 없다.
 */
export function isTranslated(korean: string | null | undefined, lang: Lang): boolean {
  if (korean === null || korean === undefined || korean === '') return false;
  return lang === 'en' && translateParts(korean) !== korean;
}
