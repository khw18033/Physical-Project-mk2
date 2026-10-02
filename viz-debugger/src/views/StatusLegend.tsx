/**
 * 상태 범례. **범위 밖이었지만 같이 옮겼다** (260917 — 영문화 2단계).
 *
 * 2단계의 범위 목록은 「한글을 품은 파일」로 만들었는데, 이 파일은 자기 한글이 없고
 * `STATE_STYLE.label` 을 **그려 주기만** 했다. 그 label 이 사전으로 가면서 여기도 같이
 * 움직여야 했다 — 안 고치면 영문 화면에서 범례만 한국어로 남는다.
 */
import { STATE_STYLE, stateLabel } from '../graph/stateStyle.ts';
import { useLang } from '../shared/language.ts';
import type { TaskStatus } from '../model/types.ts';

export function StatusLegend() {
  // `stateLabel()` 은 값을 줄 뿐 리렌더를 안 일으킨다 (지시서 §2 ①).
  useLang();
  return <div className="legend">{(Object.keys(STATE_STYLE) as TaskStatus[]).map((status) => <span className={STATE_STYLE[status].className} key={status}>{STATE_STYLE[status].icon} {stateLabel(status)}</span>)}</div>;
}
