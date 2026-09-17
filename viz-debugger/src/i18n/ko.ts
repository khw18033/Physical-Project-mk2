/**
 * src/i18n/ko.ts — 한국어 사전 (260916 — 영문화 1단계 §2)
 *
 * **평평한 객체 하나.** 중첩하지 않는다 — 키에 점이 들어 있으니 구조는 이름이 진다.
 * `en.ts` 와 같은 모양이어야 한다.
 *
 * 지금은 **시범 키 다섯**뿐이다. 2단계에서 시연 경로 문구가 여기로 들어온다.
 */

export const ko: Record<string, string> = {
  // ① 단순 라벨 — 우상단 모드 스위치
  'mode.label': '모드',

  // ② 치환이 있는 문장 — 영어는 어순이 반대라 조각을 이어붙이면 옮길 수 없다
  'check.robot.stale': '{sec}초째 소식이 없습니다 — 마지막 값을 현재로 보지 않습니다',

  // ③ 긴 오류 문장 — 좁은 판에서 줄바꿈이 레이아웃을 깨는지 본다
  'conn.storageBlocked': '저장소가 막혀 있습니다 — 바꿔도 이번 세션에만 적용되고 새로고침하면 기본값으로 돌아갑니다.',

  // ④ 열거형 라벨 — PLANE_LABEL (DF-1b)
  'plane.business': '업무 평면',
  'plane.control': '업무 평면 (제어)',
  'plane.observability': '관측 평면',
  'plane.media': '미디어 평면',

  // ⑤ en 을 일부러 비운 키 — fallback 이 실제로 도는지 눈으로 본다
  'mode.mock': '목·개발',
};
