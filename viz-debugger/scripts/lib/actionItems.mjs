// scripts/lib/actionItems.mjs (261023 신설 — 생성기 3단계 H)
//
// **생성된 액션 아이템이 원칙을 지켰는가**를 보는 유일한 자리다. 채점기(`score-generation.mjs`)
// 와 검사(`verify:action-item-shape`)가 같이 쓴다 — 둘이 따로 세면 표와 검사가 조용히 갈라진다.
//
// 문법은 계약에서 뽑으므로(`gbnf.ts`) **모양은 문법이 이미 막는다.** 여기서 보는 것은 문법이
// 못 보는 둘이다.
//
//   어디에 붙었나 — 액션 아이템은 장비에 주는 행동강령이라 `act` 에만 있어야 한다.
//                   탐지 같은 서비스는 켜 두면 입력이 오는 대로 돌아 지정할 행동이 없다.
//   무엇을 냈나   — `params.action` 이 그 태스크 target 의 생성 어휘(`equipment.json` 의
//                   `actions`)에 있는가. `params` 가 `{"type":"object"}` 라 문법은 이름을 모른다.

/** `equipment.json` → 장비 id 별 동작 이름 집합. 표가 없으면 빈 Map — 0 이 아니라 「모른다」다. */
export function actionVocabulary(equipment) {
  return new Map(Object.entries(equipment?.actions ?? {}).map(([id, names]) => [id, new Set(names)]));
}

/**
 * 임무 하나의 태스크·액션 아이템을 훑어 원칙 위반을 센다.
 *
 * | 칸 | 뜻 |
 * |---|---|
 * | `misplaced` | `act` 가 아닌데 액션 아이템을 든 태스크 — **잘못 든 자리** |
 * | `empty_act` | `act` 인데 액션 아이템이 없는 태스크 — **빈 자리**. 정답에도 있다(장비 없는 act) |
 * | `off_list` | 그 target 의 동작 목록에 없는 이름 — **목록 밖으로 지어낸 것** |
 * | `no_action` | `params.action` 이 없거나 문자열이 아니다 — 명령이 아니다 |
 * | `target_mismatch` | 아이템의 target 이 태스크의 target 과 다르다 |
 * | `adapter_set` | adapter 가 빈 문자열이 아니다 — 결정 ①을 어겼다 |
 * | `extra_params` | action 밖에 값을 단 아이템. **위반이 아니다** — 발화가 요구한 값일 수 있다. 사람이 읽을 목록이다 |
 */
export function inspectActionItems(mission, vocabulary) {
  const out = { items: 0, misplaced: [], empty_act: [], off_list: [], no_action: [], target_mismatch: [], adapter_set: [], extra_params: [] };
  for (const milestone of mission?.milestones ?? []) {
    for (const task of milestone.tasks ?? []) {
      const items = Array.isArray(task.action_items) ? task.action_items : [];
      out.items += items.length;
      if (task.node_kind !== 'act') {
        if (items.length > 0) out.misplaced.push({ task_id: task.task_id, node_kind: task.node_kind ?? null, actions: items.map((item) => item?.params?.action ?? null) });
        continue;
      }
      if (items.length === 0) out.empty_act.push({ task_id: task.task_id, target: task.target ?? null });
      const allowed = vocabulary.get(task.target) ?? new Set();
      for (const item of items) {
        const action = item?.params?.action;
        if (typeof action !== 'string' || action === '') {
          out.no_action.push({ task_id: task.task_id, item_id: item?.item_id ?? null });
          continue;
        }
        if (!allowed.has(action)) out.off_list.push({ task_id: task.task_id, target: task.target ?? null, action });
        if ((item.target ?? null) !== (task.target ?? null)) out.target_mismatch.push({ task_id: task.task_id, item_target: item.target ?? null, task_target: task.target ?? null });
        if (item.adapter !== '') out.adapter_set.push({ task_id: task.task_id, adapter: item.adapter ?? null });
        const extra = Object.keys(item.params ?? {}).filter((key) => key !== 'action');
        if (extra.length > 0) out.extra_params.push({ task_id: task.task_id, action, params: item.params });
      }
    }
  }
  return out;
}

/**
 * 동작을 (target, action) 쌍으로 편다. **짝짓기는 제목이 아니라 붙은 대상으로 한다** — 같은
 * 장비에 같은 명령을 냈으면 맞은 것이다. 액션 아이템에는 제목이 없고, 태스크 제목으로 짝지으면
 * 제목 유사도의 흔들림이 이 축에 섞인다.
 *
 * `act` 가 아닌 태스크의 아이템도 편다 — 그것도 **생성이 낸 동작**이고, 정답에 없으니
 * 정밀도를 깎는 것이 맞다(잘못 든 자리가 정밀도에서도 보이게).
 */
export function actionPairs(tasks) {
  const pairs = [];
  for (const task of tasks ?? []) {
    for (const item of Array.isArray(task.action_items) ? task.action_items : []) {
      pairs.push(`${task.target ?? '(null)'}|${item?.params?.action ?? '(없음)'}`);
    }
  }
  return pairs;
}

/** 다중집합 교집합의 크기. 같은 명령을 두 번 내야 하는 정답에 한 번만 내면 하나만 맞는다. */
export function multisetHits(gold, got) {
  const left = new Map();
  for (const key of gold) left.set(key, (left.get(key) ?? 0) + 1);
  let hits = 0;
  for (const key of got) {
    const n = left.get(key) ?? 0;
    if (n > 0) { hits += 1; left.set(key, n - 1); }
  }
  return hits;
}
