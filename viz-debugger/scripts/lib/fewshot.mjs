// scripts/lib/fewshot.mjs (260906 신설 — 마일스톤 분리 지시서 §4-3)
//
// **채점 대상인 편을 예시에서 빼는 규칙이 사는 유일한 파일이다.**
//
// 이 규칙을 부르는 쪽마다 적으면 언젠가 한 곳이 빠지고, 그러면 정답을 보여주고 정답을
// 맞히라고 한 표가 나온다 — **논문에서 가장 먼저 찔리는 자리**다. 그래서 규칙을 한 곳에
// 두고 `verify:no-leak` 이 이 함수를 실제로 불러 검사한다.
//
// 실행 스크립트(`run-baseline.mjs`)에서 떼어 낸 이유는 하나 더 있다. 검사가 실행
// 스크립트를 import 하면 검사를 돌릴 때마다 모델이 20건을 생성한다.

/**
 * few-shot 예시로 쓸 모양 — **마일스톤까지만.**
 *
 * 태스크는 `VZ-G-02` 의 몫이고(§5), `deps` 는 모델이 아니라 `solveDeps()` 가 만든다.
 * 예시에 태스크를 넣으면 모델이 이번 단계에서 하지 말아야 할 일을 배운다.
 *
 * 항목 순서는 **계약의 차례대로** 둔다. 문법이 그 순서를 고정하므로(`gbnf.ts`),
 * 예시가 다른 순서면 모델이 예시와 문법 사이에서 싸운다.
 */
export function asExample(mission) {
  return {
    mission_id: mission.mission_id,
    utterance: mission.utterance,
    milestones: mission.milestones.map((milestone) => ({
      milestone_id: milestone.milestone_id,
      title: milestone.title,
      order: milestone.order,
      status: 'pending',
      tasks: [],
      assigned_targets: milestone.assigned_targets,
    })),
  };
}

/**
 * 예시를 몇 편 싣는가. **이 목록이 규칙의 전부다** — `verify:no-leak` 이 기록의 예시 수를
 * 이 둘 중 하나로만 받아들이고, 한 실행 안에서 섞여 있으면 실패로 끝낸다.
 *
 * `none` 이 7단계에 생겼다. 6단계가 남긴 질문이 「개수 일치 45% 가 실력인가 예시를
 * 베낀 것인가」였고, 그것은 **예시를 빼고 같은 것을 재야** 답이 된다. 그래서 「언제나
 * 정답셋에서 하나 뺀 수」였던 규칙을 **0 또는 그 수**로 넓혔다 — 넓힌 것은 개수뿐이고,
 * 채점 대상 편이 예시에 드는 것은 여전히 어느 판에서도 금지다.
 */
export const SHOT_MODES = /** @type {const} */ (['leave-one-out', 'none']);

/**
 * **누출을 막는 유일한 자리.** 채점 대상 편을 예시에서 뺀다 (leave-one-out).
 *
 * @param missionId 지금 채점할 편. 이 편은 예시에 **절대** 들어가지 않는다.
 * @param missions  정답셋 전부.
 * @param shots     `'leave-one-out'`(기본) 또는 `'none'`(예시 0편 · 7단계 C 판).
 */
export function examplesFor(missionId, missions, shots = 'leave-one-out') {
  if (!SHOT_MODES.includes(shots)) throw new Error(`모르는 예시 방식: ${shots} — ${SHOT_MODES.join(' 또는 ')}`);
  // 0편은 **예시를 안 주는 것**이지 「없는 예시를 골랐다」가 아니다. 그래서 필터가 아니라
  // 이른 반환으로 가른다 — 정답셋이 1편이 되어도 0편은 0편이다.
  if (shots === 'none') return [];
  return missions.filter((mission) => mission.mission_id !== missionId).map(asExample);
}

/**
 * 그 실행이 돈 편 수에서 **허용되는 예시 수.** 검사와 실행이 같은 함수를 본다.
 *
 * @param missionCount 그 실행이 돈 편 수.
 */
export function allowedExampleCounts(missionCount) {
  return [0, missionCount - 1];
}
