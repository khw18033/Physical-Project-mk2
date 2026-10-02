/**
 * src/data/actionTrace.ts (260920 신설 — 명령 기록 합류 §1 · §2)
 *
 * **액션 층의 어휘와 그 층을 접는 규칙.** 기록 열의 셋째 층이다.
 *
 * 전까지 기록은 두 군데 살았다.
 *
 * ```
 *   기록 열  src/data/trace.ts             마일스톤 · 태스크     되감기가 닿는다
 *   작업대   src/physical/robotSession.ts  명령과 로봇 응답      되감기가 안 닿는다
 * ```
 *
 * 작업대는 **지금 값**이라 되감아도 안 따라오고, 세션을 닫으면 사라지고, 대본 재생에는
 * 아예 없다. 명령을 기록 열로 옮기는 이유는 명령이 **사건의 모양을 하고 있기** 때문이다 —
 * 낸 시각이 있고 상태가 전이한다(`issued → running → done/failed`). 로봇 위치·배터리·
 * 연결 램프는 여기로 안 온다. 그것은 지금 값이지 사건이 아니고, 260828 에 「두 상태 모델은
 * 합치지 않았다」고 정한 판단이 그대로 유효하다.
 *
 * ## 이 파일은 순수하다
 *
 * `fold.ts` 와 **같은 이유**로 저장소도 대본 파일도 React 도 모른다. `robotSession` 을
 * import 하는 순간 `verify:fold-actions` 와 `verify:scenario-mode` 가 Node 에서 못 연다.
 * 접기는 기록 열만 읽는다 — 작업대를 보지 않는다.
 *
 * ## 「아직 기다림」과 「영영 안 옴」
 *
 * 일지는 일어난 일만 덧붙인다. 그런데 **안 온 응답은 일어나지 않은 일**이다. 그래서
 * 응답이 아니라 **기다림이 끝났다는 사실**(`expired`)을 적는다. 기다린 것은 일어난 일이다.
 *
 * | 시각 t 에서 | 응답 | 기한 사건 | 뜻 |
 * |---|---|---|---|
 * | 명령 났음 | 0건 | 없음 | **아직 기다리는 중** |
 * | 명령 났음 | 0건 | 있음 | **영영 안 왔다** |
 *
 * 기한 사건이 없으면 이 둘은 영원히 구분되지 않는다. 느린 것과 죽은 것은 원인이 완전히
 * 다르므로, 디버깅에서 이 구분이 제일 값이 크다. 그래서 `expired` 는 `status` 와 **별개
 * 칸**이다 — 섞는 순간 구분이 도로 사라진다 (`verify:no-answer` 가 그것을 지킨다).
 */

import type { ActionItemCommand, ScenarioEvent, Task, TaskStatus } from '../model/types.ts';

/**
 * 액션 층 사건 네 종.
 *
 * `nodeId` 는 넷 다 **`commandId`** 다. 액션 아이템의 정체가 `TaskCommandRecord` 이고
 * 그것을 가리키는 키가 `commandId` 이므로 새 식별자를 만들지 않는다. 어느 태스크의
 * 것인지는 `payload.taskId` 에 싣는다 — 대본이 이미 `events[].payload` 를 그렇게 쓴다.
 */
export const ACTION_KINDS = {
  /** 명령이 실제로 나갔다. `producedBy` 는 **그 명령을 낸 주체**다. */
  commanded: 'commanded',
  /** 로봇 응답이 한 줄 도착했다. `producedBy: 'robot'`. */
  answered: 'answered',
  /** 기다리는 기한이 끝났는데 안 왔다. `producedBy: 'robot'` — 안 온 것도 로봇 몫이다. */
  expired: 'expired',
  /** 사람이 값을 바꿨다. `producedBy: 'human'`. */
  adjusted: 'adjusted',
} as const;

export type ActionKind = (typeof ACTION_KINDS)[keyof typeof ACTION_KINDS];

/** 네 종의 이름만. 검사와 측정이 같은 목록을 본다 — 두 벌이면 갈라진다. */
export const ACTION_KIND_LIST: readonly ActionKind[] = Object.values(ACTION_KINDS);

const ACTION_KIND_SET: ReadonlySet<string> = new Set<string>(ACTION_KIND_LIST);

/** 이 사건이 액션 층의 것인가. */
export function isActionEvent(event: { kind: string }): boolean {
  return ACTION_KIND_SET.has(event.kind);
}

/**
 * **액션 층의 상태 어휘.** 태스크 어휘(`TaskStatus`)와 의도적으로 다르다 — 명령은
 * 평가를 받지도 건너뛰어지지도 않는다. 로봇이 주는 상태 그대로다.
 */
export type ActionStatus = 'issued' | 'running' | 'done' | 'failed';

/** 로봇이 보낸 한 줄의 종류. `robotSession.ts` 의 `CommandLogLine` 과 같은 어휘다. */
export type AnswerKind = 'acceptance' | 'status' | 'result';

/** 접은 명령 하나 — 화면이 표를 그릴 만큼. `FoldedStatuses.actions` 는 이것의 요약이다. */
export type FoldedAction = {
  commandId: string;
  taskId: string;
  /** 무슨 명령이었나. 로봇이 「그런 명령 없다」고 하면 어느 이름인지 알아야 한다. */
  action: string;
  /** **실제로 실려 나간 값.** 화면에 적힌 계획값이 아니다. */
  parameters: Record<string, number>;
  /** 추적기가 발급한 요청 식별자 — 감사·추적이 이 키로 걸린다. 대본에는 없다. */
  requestId: string | null;
  issuedAtSec: number;
  status: ActionStatus;
  /** 그 시점까지 온 응답 줄. 받은 순서 그대로다. */
  lines: readonly { atSec: number; kind: AnswerKind; text: string; index: number | null }[];
  /** 기한이 끝났는가. **`status` 와 별개다** — 끝났다는 것이 곧 실패라는 뜻이 아니다. */
  expired: { atSec: number; waitedMs: number; reason: string } | null;
  /** 사람이 바꾼 값들. 전후를 **짝으로** 든다 — 후만 남기면 무엇이 바뀌었는지 모른다. */
  adjustments: readonly { atSec: number; field: string; before: unknown; after: unknown }[];
};

// ── 사건 만들기 ───────────────────────────────────────────────────────────────
//
// **여기 밖에서 액션 사건을 손으로 만들지 않는다.** `produced_by` 와 `payload` 모양이
// 여기저기서 손으로 적히면 그 규칙이 갈라지고, 갈리면 라이브 기록과 목 기록이 다른
// 모양이 된다 — 그 둘을 대조하는 것이 이번 작업의 검증 방법이다 (`trace.ts` 의
// `appendHuman` 머리말과 같은 이유).

export function commandedEvent(input: {
  seq: number; atSec: number; commandId: string; taskId: string;
  action: string; parameters: Record<string, number>;
  requestId?: string | null;
  /**
   * **누가 눌렀나.** 사람이 누른 것(`human`)과 임무가 낸 것(`mission`) 둘뿐이다.
   *
   * 부르는 쪽이 `produced_by` 값을 **직접 적지 못하게** 이름을 갈라 뒀다. 값을 그대로
   * 받으면 물리 층 여기저기에 `producedBy: 'human'` 이 손으로 적히고, 그 순간
   * 「모든 조작은 `produced_by=human` 으로 기록된다」(`VZ-D-08`)가 한 곳 규칙이 아니게 된다
   * (`verify:human-trace` ①이 그것을 지킨다).
   */
  issuedBy: 'human' | 'mission';
}): ScenarioEvent {
  return {
    seq: input.seq,
    atSec: input.atSec,
    nodeId: input.commandId,
    // 명령이 나간 순간 그 명령은 돌고 있다. 액션 층의 `issued` 는 접기가 정한다.
    status: 'running',
    kind: ACTION_KINDS.commanded,
    producedBy: input.issuedBy === 'human' ? 'human' : 'backend',
    payload: {
      taskId: input.taskId,
      action: input.action,
      parameters: { ...input.parameters },
      requestId: input.requestId ?? null,
    },
  };
}

export function answeredEvent(input: {
  seq: number; atSec: number; commandId: string; taskId: string;
  line: string; answerKind: AnswerKind; index?: number | null;
  /** 종료 줄일 때 그 명령이 어떻게 끝났는가. 종료 줄이 아니면 안 본다. */
  outcome?: 'done' | 'failed';
}): ScenarioEvent {
  return {
    seq: input.seq,
    atSec: input.atSec,
    nodeId: input.commandId,
    status: input.answerKind === 'result' ? (input.outcome ?? 'done') : 'running',
    kind: ACTION_KINDS.answered,
    producedBy: 'robot',
    payload: {
      taskId: input.taskId,
      line: input.line,
      // **회전 걸음 번호.** 회전 보고가 아닌 줄은 null 이고, 그것이 정상이다.
      index: input.index ?? null,
      // 지시서 §1 표에 없는 칸이다. 수락·진행·종료를 못 가르면 화면이 줄 종류를 잃고,
      // 무엇보다 **종료 줄만이 명령의 끝을 말하므로** 접기가 상태를 정할 수 없다.
      answerKind: input.answerKind,
    },
  };
}

export function expiredEvent(input: {
  seq: number; atSec: number; commandId: string; taskId: string;
  waitedMs: number; reason: string;
}): ScenarioEvent {
  return {
    seq: input.seq,
    atSec: input.atSec,
    nodeId: input.commandId,
    // **`failed` 를 적지 않는다.** 기다림이 끝난 것이지 그 명령이 실패했다고 안 것이
    // 아니다 — 로봇이 늦게 답할 수도, 이미 실행했을 수도 있다. 그 판정 불가가 이 값이다.
    status: 'awaiting_evaluation',
    kind: ACTION_KINDS.expired,
    producedBy: 'robot',
    payload: { taskId: input.taskId, waitedMs: input.waitedMs, reason: input.reason },
  };
}

export function adjustedEvent(input: {
  seq: number; atSec: number; commandId: string; taskId: string;
  field: string; before: unknown; after: unknown;
}): ScenarioEvent {
  return {
    seq: input.seq,
    atSec: input.atSec,
    nodeId: input.commandId,
    status: 'rerunning',
    kind: ACTION_KINDS.adjusted,
    producedBy: 'human',
    // **전후를 짝으로 든다.** 후만 남기면 화면이 「무엇이 바뀌었나」에 답할 수 없다.
    payload: { taskId: input.taskId, field: input.field, before: input.before, after: input.after },
  };
}

// ── 대본 → 기록 (§5) ─────────────────────────────────────────────────────────

/**
 * **대본의 액션 아이템을 사건으로 편다.** 목 게이트웨이와 로컬 재생기가 **같은 이 함수**를
 * 부른다 — 두 벌이면 통합 빌드와 단독 빌드의 되감기가 갈리고, 그것이 곧 측정축 D 의
 * 오염이다 (`trace.ts` 머리말).
 *
 * 대본은 **정의**를 들고, 재생기가 그것을 기록으로 흘리고, 화면은 흘러온 것만 접는다.
 * 260904 에 `fold.ts` 가 대본이 아니라 열을 접게 된 것과 같은 구조다.
 *
 * `commandId` 는 **액션 아이템의 id 를 그대로 쓴다.** 목에서 명령의 이름이 곧 그 아이템의
 * 이름이고, 새 식별자를 만들지 말라는 것이 §1 의 지시다.
 *
 * `seq` 는 `seqBase + 나온 차례`다. **정해진 순서**라 게이트웨이가 흘리든 로컬 재생기가
 * 흘리든 같은 값이 나온다 — 같은 사건이 두 길로 와도 열이 중복으로 흡수한다.
 */
export function actionItemEvents(
  tasks: readonly Pick<Task, 'id' | 'actionItems'>[],
  seqBase: number,
): readonly ScenarioEvent[] {
  const out: ScenarioEvent[] = [];
  const push = (make: (seq: number) => ScenarioEvent) => { out.push(make(seqBase + out.length)); };
  for (const task of tasks) {
    for (const item of task.actionItems ?? []) {
      const command = (item as { command?: ActionItemCommand }).command;
      if (command === undefined) continue;          // 옛 편 — 정의가 없으면 안 흐른다
      push((seq) => commandedEvent({
        seq, atSec: command.atSec, commandId: item.id, taskId: task.id,
        action: command.action, parameters: command.parameters,
        // 대본의 명령은 임무가 낸 것이다. 사람이 누른 것처럼 남으면 안 된다
        // (`script-engine.ts` 의 감사 actor 규칙과 같은 자리).
        issuedBy: command.issuedBy ?? 'mission',
      }));
      for (const answer of command.answers ?? []) {
        push((seq) => answeredEvent({
          seq, atSec: answer.atSec, commandId: item.id, taskId: task.id,
          line: answer.text, answerKind: answer.kind,
          index: answer.index ?? null, outcome: answer.outcome,
        }));
      }
      const expired = command.expired;
      if (expired !== undefined) {
        push((seq) => expiredEvent({
          seq, atSec: expired.atSec, commandId: item.id, taskId: task.id,
          waitedMs: expired.waitedMs, reason: expired.reason,
        }));
      }
    }
  }
  // 열은 `(atSec, seq)` 오름차순으로 들어가므로 여기서 정렬할 필요가 없다. 다만 재생기가
  // **시각 순서대로** 흘려보내야 하므로 시각으로 한 번 세운다 — 같은 시각이면 만든 차례다.
  return out.slice().sort((a, b) => (a.atSec === b.atSec ? a.seq - b.seq : a.atSec - b.atSec));
}

// ── 접기 ─────────────────────────────────────────────────────────────────────

const asString = (value: unknown, fallback = ''): string => (typeof value === 'string' ? value : fallback);

type MutableAction = Omit<FoldedAction, 'lines' | 'adjustments'> & {
  lines: { atSec: number; kind: AnswerKind; text: string; index: number | null }[];
  adjustments: { atSec: number; field: string; before: unknown; after: unknown }[];
};

/**
 * 시각 t 까지의 액션 층. **낸 순서대로** 돌려준다 — 회전 먼저, 직진 나중.
 *
 * `trace` 는 `(atSec, seq)` 오름차순이라고 전제한다(`TraceStore` 가 보장한다). 그래서
 * 시각을 넘어서면 **끊는다**: 뒤는 전부 미래다. `fold.ts` 의 태스크 접기와 같은 규칙이다.
 *
 * **행을 만드는 것은 `commanded` 뿐이다.** 응답·기한·조정은 이미 있는 행에만 붙는다 —
 * 명령이 없으면 응답도 없다. 남의 도구가 쏜 명령의 보고가 우리 표에 섞이지 않는 것도
 * 같은 규칙의 결과다 (`noteCommandLog` 가 모르는 `command_id` 를 버리는 것과 같다).
 */
export function foldActions(second: number, trace: readonly ScenarioEvent[]): readonly FoldedAction[] {
  const rows = new Map<string, MutableAction>();
  for (const event of trace) {
    if (event.atSec > second) break;
    if (!ACTION_KIND_SET.has(event.kind)) continue;
    const payload = event.payload ?? {};
    const commandId = event.nodeId;
    if (event.kind === ACTION_KINDS.commanded) {
      rows.set(commandId, {
        commandId,
        taskId: asString(payload.taskId),
        action: asString(payload.action),
        parameters: { ...((payload.parameters as Record<string, number> | undefined) ?? {}) },
        requestId: typeof payload.requestId === 'string' ? payload.requestId : null,
        issuedAtSec: event.atSec,
        status: 'issued',
        lines: [],
        expired: null,
        adjustments: [],
      });
      continue;
    }
    const row = rows.get(commandId);
    if (row === undefined) continue;
    if (event.kind === ACTION_KINDS.answered) {
      const kind = asString(payload.answerKind, 'status') as AnswerKind;
      row.lines.push({
        atSec: event.atSec,
        kind,
        text: asString(payload.line),
        index: typeof payload.index === 'number' ? payload.index : null,
      });
      // 종료 줄만이 명령의 끝을 말한다. 수락·진행은 도는 중이다.
      row.status = kind === 'result' ? (event.status === 'failed' ? 'failed' : 'done') : 'running';
    } else if (event.kind === ACTION_KINDS.expired) {
      // **`status` 를 건드리지 않는다.** 섞는 순간 「아직」과 「영영」이 같아진다.
      row.expired = {
        atSec: event.atSec,
        waitedMs: typeof payload.waitedMs === 'number' ? payload.waitedMs : 0,
        reason: asString(payload.reason),
      };
    } else if (event.kind === ACTION_KINDS.adjusted) {
      row.adjustments.push({
        atSec: event.atSec,
        field: asString(payload.field),
        before: payload.before,
        after: payload.after,
      });
    }
  }
  return [...rows.values()].sort((a, b) => (
    a.issuedAtSec === b.issuedAtSec ? a.commandId.localeCompare(b.commandId) : a.issuedAtSec - b.issuedAtSec
  ));
}

/**
 * **아직 기다리는 중인가** — 응답이 0건이고 기한 사건도 없다.
 *
 * 이 함수와 아래 `neverAnswered` 는 **서로 배타**다. 둘 다 참이 되는 입력이 있으면
 * §2 의 구분이 깨진 것이고 `verify:no-answer` 가 그것을 잡는다.
 */
export function stillWaiting(action: FoldedAction): boolean {
  return action.lines.length === 0 && action.expired === null;
}

/** **영영 안 왔다** — 기한이 끝났는데 그때까지 한 줄도 안 왔다. */
export function neverAnswered(action: FoldedAction): boolean {
  return action.lines.length === 0 && action.expired !== null;
}

/**
 * **아직 명령이 안 붙은 조정** — `nodeId` 가 태스크인 `adjusted` 들.
 *
 * 값을 바꾸는 시점에 그 태스크가 명령을 낸 적이 없을 수 있다. 그때 `nodeId` 는 그 태스크다
 * — 조정 대상이 아직 **계획값**이기 때문이다. 새 식별자를 만드는 것이 아니라 이미 있는
 * 노드를 가리킨다.
 *
 * 명령이 붙은 뒤의 조정은 `FoldedAction.adjustments` 로 간다. 화면은 둘 다 전후 짝으로
 * 보여 준다 — 어느 쪽이든 **후만 남기면 무엇이 바뀌었는지 모른다**.
 */
export function planAdjustments(
  second: number,
  trace: readonly ScenarioEvent[],
  taskId: string,
): readonly { atSec: number; field: string; before: unknown; after: unknown }[] {
  const out: { atSec: number; field: string; before: unknown; after: unknown }[] = [];
  for (const event of trace) {
    if (event.atSec > second) break;
    if (event.kind !== ACTION_KINDS.adjusted || event.nodeId !== taskId) continue;
    const payload = event.payload ?? {};
    out.push({ atSec: event.atSec, field: asString(payload.field), before: payload.before, after: payload.after });
  }
  return out;
}

/** 태스크 하나가 낸 명령들. 화면이 노드를 열었을 때 읽는다. */
export function actionsOfTask(actions: readonly FoldedAction[], taskId: string): readonly FoldedAction[] {
  return actions.filter((action) => action.taskId === taskId);
}

/** 액션 층 상태를 태스크 어휘로. 액션 층 밖으로 나갈 때만 쓴다. */
export function taskStatusOfAction(status: ActionStatus): TaskStatus {
  return status === 'issued' ? 'running' : status;
}
