/**
 * src/i18n/RichText.tsx (260917 신설 — 영문화 2단계)
 *
 * **긴 산문 한 문단을 한 키에 담는다.**
 *
 * ## 왜 필요했나
 *
 * 도움말(`shell/HelpOverlay.tsx`)의 문단은 강조가 문장 안에 잘게 박혀 있다.
 *
 * ```tsx
 * <p>계획을 만드는 것은 AI지만 <b>가시화에 가져다주고 …는 백엔드</b>입니다.
 *    경로는 <b>생성(AI) → 백엔드 중계 → …</b> 순이고, <b>승인된 계획만</b> 엣지로 나갑니다.</p>
 * ```
 *
 * 이 한 문단이 **조각 일곱**이다. 조각마다 키를 주면 번역가가 문장을 통째로 못 보고
 * 어순도 못 바꾼다 — 지시서 §2 ③이 금지하는 바로 그 모양이다. 도움말 전체로는 조각이
 * 74개였고, 문단 단위로 묶으니 **30개**가 됐다.
 *
 * ## 그래서 표기를 문자열 안에 둔다
 *
 * ```
 * ko: '계획을 만드는 것은 AI지만 **가시화에 …는 백엔드**입니다. 중계 단계(`relay_stage`)는 …'
 * ```
 *
 * `**…**` 는 `<b>`, `` `…` `` 는 `<code>` 가 된다. 번역가는 문장 하나를 받고 강조를
 * 어디에 둘지도 같이 정한다 — 영어는 강조할 자리가 한국어와 다르다.
 *
 * ## 마크다운을 넣는 것이 아니다
 *
 * **두 표기뿐이다.** 목록도 링크도 제목도 안 받는다 — 그런 것이 필요해지면 그건 문단이
 * 아니라 구조이고, JSX 로 짜는 편이 맞다. 의존성도 안 늘린다(`react` 넷 그대로).
 *
 * 표기가 안 맞으면(`**` 가 홀수) **그 자리만 글자 그대로 나온다.** 던지지 않는다 —
 * 번역 한 줄의 오타가 도움말 전체를 못 열게 만들면 안 된다.
 */

import { Fragment, type ReactNode } from 'react';
import { t } from './dict.ts';

/** `**굵게**` 와 `` `코드` `` 만 푼다. 나머지는 글자 그대로. */
export function renderRich(text: string): ReactNode {
  const out: ReactNode[] = [];
  const pattern = /\*\*([^*]+)\*\*|`([^`]+)`/g;
  let at = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > at) out.push(<Fragment key={key += 1}>{text.slice(at, match.index)}</Fragment>);
    if (match[1] !== undefined) out.push(<b key={key += 1}>{match[1]}</b>);
    else out.push(<code key={key += 1}>{match[2]}</code>);
    at = match.index + match[0].length;
  }
  if (at < text.length) out.push(<Fragment key={key += 1}>{text.slice(at)}</Fragment>);
  return out;
}

/**
 * 사전에서 한 문단을 꺼내 그린다.
 *
 * **부르는 컴포넌트가 `useLang()` 을 갖고 있어야 한다** (지시서 §2 ①) — 이 부품은 값을
 * 받아 그릴 뿐 구독하지 않는다.
 */
export function Rich({ id, vars }: { id: string; vars?: Record<string, string | number> }) {
  return <>{renderRich(t(id, vars))}</>;
}
