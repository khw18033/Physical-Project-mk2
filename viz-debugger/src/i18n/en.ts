/**
 * src/i18n/en.ts — 영어 사전 (260916 — 영문화 1단계 §2)
 *
 * **여기 적힌 영어는 전부 가안이다.** 0단계 용어집이 확정되면 바뀐다 (지시서 §5).
 *
 * `ko.ts` 와 같은 모양의 평평한 객체. **`ko` 에 있는 키가 여기 없어도 된다** —
 * 없으면 한국어로 떨어지고 콘솔에 한 줄 남는다(`dict.ts`). 4단계까지 1,249줄을 다 못
 * 옮긴다는 전제로 설계한 것이다.
 */

export const en: Record<string, string> = {
  // ① 단순 라벨
  'mode.label': 'Mode',

  // ② 치환이 있는 문장 — **어순이 한국어와 반대다.**
  //    ko 는 「{sec}초째 … 않습니다」로 숫자가 앞, en 은 'No signal for {sec}s' 로 뒤다.
  //    조각을 이어붙이는 방식이었다면 이 한 줄이 불가능했다 (지시서 §2 ③).
  'check.robot.stale': 'No signal for {sec}s — the last value is not treated as current',

  // ③ 긴 오류 문장 — 한국어보다 길다. 좁은 판에서 몇 줄이 되는지가 2단계에 알아야 할 것이다
  'conn.storageBlocked': 'Storage is blocked — changes apply to this session only and revert to defaults on refresh.',

  // ④ 열거형 라벨
  'plane.business': 'Business plane',
  'plane.control': 'Business plane (control)',
  'plane.observability': 'Observability plane',
  'plane.media': 'Media plane',

  // ⑤ `mode.mock` 은 **일부러 비워 둔다.** 지우지 마라 — 이 빈자리가 시범 키 다섯째다.
  //    영문 화면에서 이 버튼만 「목·개발」로 남고 콘솔에 한 줄이 찍히면 fallback 이 도는 것이다.
};
