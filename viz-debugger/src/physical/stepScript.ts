/**
 * src/physical/stepScript.ts (260922 신설 — 정량 명령 직접 입력)
 *
 * **사람이 숫자로 적은 문장을 걸음 목록으로 바꾼다.** 「1m 전진 후 오른쪽 90도 회전」.
 *
 * 임무를 거치지 않고 로봇을 그대로 움직이는 길이다. 탐지·대본이 없어도 명령 경로를 시험할
 * 수 있어야 하고, 그것이 이 파일이 있는 이유다.
 *
 * ## 모델을 부르지 않는다
 *
 * **규칙으로 읽는다.** 숫자를 지어내면 로봇이 그만큼 움직인다 — 문장이 틀리게 읽히는 것과
 * 로봇이 틀리게 걷는 것은 같은 일이 아니다. 대본 매칭이 LLM 이 아닌 것과 같은 이유다
 * (`scenarios/matcher.ts`).
 *
 * ## 절반만 읽고 나머지를 지어내지 않는다
 *
 * 못 읽은 것이 있으면 **걸음을 하나도 안 낸다.** 「1m 전진 후 어쩌고」에서 앞부분만 내면
 * 사람이 적은 것과 다른 것이 나간다. 거부할 때는 **무엇을 못 읽었는지** 말한다.
 *
 * 방향 없는 회전(`90도 회전`)도 거부다. 기본값을 정해 두면 반대로 도는 날이 오고, 그것은
 * 화면이 틀리는 것이 아니라 **로봇이 실제로 반대로 도는** 일이다.
 *
 * ## 규약이 주는 한계는 여기서 처리한다
 *
 *   turn          deg 5~360           (오른쪽 +)
 *   move_forward  distance_m 0.05~10 · vx 0.05~0.30
 *
 * 10m 는 **명령 한 건의 상한**이지 이동 거리의 상한이 아니다. 15m 는 `move_forward` 둘이고,
 * 차례로 내는 장치는 이미 있다(`issueSteps`). 자르는 규칙만 여기 둔다.
 *
 * **자른 것을 숨기지 않는다** — 「15m → 7.5m 두 번」을 보내기 전에 적는다.
 *
 * ## 뒤로·옆으로는 안 만든다
 *
 * Go1 은 뒤로도 옆으로도 걷는다. 막는 것은 **어휘**다 — pi7 이 열어 둔 목록에 `move_forward`
 * 뿐이고, 음수를 넣으면 어떻게 되는지는 문서에 없고 쏴 본 적도 없다. 거절될 수도, 절댓값으로
 * 읽혀 **앞으로 갈 수도** 있다. 실험으로 알아보지 않는다 — 물어보고 답을 받은 뒤에 만든다.
 *
 * 옆으로 가기는 지금도 된다: `오른쪽 90도 회전 후 1m 전진 후 왼쪽 90도 회전`. 게걸음이
 * 아니라 결과가 같은 것이다.
 */

import { APPROACH_VX } from './presets.ts';
import type { TaskCommand } from './missionLink.ts';

/** 규약 범위 (`web-integration.md` §4-2). **여기 밖에 적지 않는다.** */
export const TURN_MIN_DEG = 5;
export const TURN_MAX_DEG = 360;
export const FORWARD_MIN_M = 0.05;
export const FORWARD_MAX_M = 10;

/**
 * **한 걸음이 시한 안에 끝나야 한다.**
 *
 * `STEP_TIMEOUT_MS` 가 60초다(`robotCommands.ts`). 속도를 안 실으면 로봇 기본값 0.15 m/s 이고
 * 10m 에 67초 — 규약 상한만 보고 자르면 **시한에 걸려 다음 구간이 안 나간다.**
 *
 * 45초로 잡는 것은 기립·가감속에 15초를 남기는 것이다. 구간마다 서고 다시 출발하므로
 * 그 시간이 매번 든다.
 */
export const STEP_BUDGET_S = 45;

/**
 * **속도는 문장에서 안 읽는다** (260922 결정).
 *
 * 시연 경로가 이미 이 값을 쓰고(`APPROACH_VX`), 고정하면 구간 상한이 규약의 10m 로 떨어져
 * 자르는 규칙이 단순해진다. 문장에 속도 어휘를 더하면 「0.2미터」와 「0.2m/s」를 가르는
 * 일이 생기고, 그 혼동의 값은 로봇이 실제로 내는 속도다.
 */
export const STEP_VX = APPROACH_VX;

/** 한 구간의 상한. 규약과 시한 중 **먼저 걸리는 쪽**이다. */
export function forwardChunkM(vx: number): number {
  return Math.min(FORWARD_MAX_M, vx * STEP_BUDGET_S);
}

export type StepScript = {
  /** 발행기가 그대로 받는 모양. 못 읽었으면 **빈 배열**이다. */
  steps: readonly TaskCommand[];
  /**
   * 사람이 보기 전에 읽어 주는 줄. 「직진 1.00m (vx 0.30)」·「오른쪽 90도」.
   * **걸음과 하나씩 짝이 맞는다** — 화면이 나란히 적을 수 있게.
   */
  reads: readonly string[];
  /**
   * 알려야 할 것 — 자른 사실, 너무 작아 안 내는 것. **사전 키와 값**이다.
   * 글자로 담으면 담은 순간의 언어로 굳는다(`connections.ts` 와 같은 규칙).
   */
  notes: readonly { key: string; vars?: Record<string, string | number> }[];
  /** 못 읽었으면 왜. 읽었으면 `null`. 이것도 **사전 키**다. */
  reject: { key: string; vars?: Record<string, string | number> } | null;
};

const EMPTY: StepScript = { steps: [], reads: [], notes: [], reject: null };

/**
 * 거리 표기. `1m` `1 m` `1미터` `50cm` `0.5m`.
 *
 * **`\b` 를 안 쓴다.** 자바스크립트의 단어 경계는 한글을 단어 글자로 안 보므로
 * `1미터` 처럼 한글 단위로 끝나면 경계가 안 생겨 **통째로 안 잡힌다.** 대신 뒤에 숫자나
 * 알파벳이 오지 않는 것만 본다 — `1m` 과 `1minute` 를 가르는 데 그것으로 충분하다.
 */
const DISTANCE = /(-?\d+(?:\.\d+)?)\s*(m|미터|cm|센티(?:미터)?)(?![0-9A-Za-z])/i;
/** 각도 표기. `90도` `90°` `90deg`. 경계를 안 쓰는 이유는 위와 같다. */
const ANGLE = /(-?\d+(?:\.\d+)?)\s*(?:도|°|deg)(?![0-9A-Za-z])/i;
/** 방향. 왼쪽이 음수다 — 규약이 「오른쪽 +」이므로. */
const LEFT = /왼쪽|좌회전|좌측|좌\b|반시계|left|ccw/i;
const RIGHT = /오른쪽|우회전|우측|우\b|시계|right|cw/i;
/** 동작. */
const FORWARD = /전진|직진|앞으로|forward/i;
const TURN = /회전|돌아|돌려|turn/i;

/** 이어붙임. 이 글자들로 자른다. */
const JOIN = /\s*(?:그리고|다음에|다음|후에|후|,|·|→|->|then)\s*/;

function distanceM(text: string): number | null {
  const matched = DISTANCE.exec(text);
  if (matched === null) return null;
  const value = Number(matched[1]);
  if (!Number.isFinite(value)) return null;
  return /cm|센티/i.test(matched[2]) ? value / 100 : value;
}

function angleDeg(text: string): number | null {
  const matched = ANGLE.exec(text);
  if (matched === null) return null;
  const value = Number(matched[1]);
  return Number.isFinite(value) ? value : null;
}

/**
 * 문장 한 줄 → 걸음 목록.
 *
 * @param sentence 사람이 적은 것 그대로.
 * @param vx 구간 상한을 정하는 속도. 기본은 `STEP_VX` 이고, 걸음에도 이 값이 실린다.
 */
export function parseStepScript(sentence: string, vx: number = STEP_VX): StepScript {
  const trimmed = sentence.trim();
  if (trimmed === '') return { ...EMPTY, reject: { key: 'step.reject.empty' } };

  const parts = trimmed.split(JOIN).map((part) => part.trim()).filter((part) => part !== '');
  if (parts.length === 0) return { ...EMPTY, reject: { key: 'step.reject.empty' } };

  const steps: TaskCommand[] = [];
  const reads: string[] = [];
  const notes: { key: string; vars?: Record<string, string | number> }[] = [];
  const chunk = forwardChunkM(vx);

  for (const part of parts) {
    const turning = TURN.test(part);
    const moving = FORWARD.test(part);

    // **동작을 모르면 거부한다.** 「조금만 앞으로」는 동작은 알지만 수치가 없고,
    // 「어쩌고」는 동작조차 없다 — 둘 다 여기서 걸린다.
    if (!turning && !moving) {
      return { ...EMPTY, reject: { key: 'step.reject.unknown', vars: { part } } };
    }

    if (turning) {
      const deg = angleDeg(part);
      if (deg === null) return { ...EMPTY, reject: { key: 'step.reject.noAngle', vars: { part } } };
      /**
       * **방향이 없으면 되묻는다.** 부호가 이미 붙어 있으면(`-90도`) 그것이 방향이다.
       * 기본값을 정해 두면 반대로 도는 날이 오고, 그건 로봇이 실제로 하는 일이다.
       */
      const left = LEFT.test(part);
      const right = RIGHT.test(part);
      if (!left && !right && deg >= 0) {
        return { ...EMPTY, reject: { key: 'step.reject.noSide', vars: { part } } };
      }
      if (left && right) {
        return { ...EMPTY, reject: { key: 'step.reject.bothSides', vars: { part } } };
      }
      const signed = left ? -Math.abs(deg) : Math.abs(deg) * (deg < 0 ? -1 : 1);
      pushTurn(signed, steps, reads, notes);
      continue;
    }

    const metres = distanceM(part);
    if (metres === null) return { ...EMPTY, reject: { key: 'step.reject.noDistance', vars: { part } } };
    // **뒤로 가기는 어휘에 없다.** 음수를 쏘지 않는다 — 어떻게 읽히는지 모른다.
    if (metres < 0) return { ...EMPTY, reject: { key: 'step.reject.backward', vars: { part } } };
    pushForward(metres, vx, chunk, steps, reads, notes);
  }

  // 전부 너무 작아 한 걸음도 안 남는 경우 — 읽기는 했으므로 거부가 아니라 「낼 것이 없다」다.
  if (steps.length === 0) return { steps: [], reads: [], notes, reject: { key: 'step.reject.tooSmall' } };
  return { steps, reads, notes, reject: null };
}

/** 회전 하나. 360을 넘으면 나눈다 — 규약 상한이 한 건에 360이다. */
function pushTurn(
  deg: number,
  steps: TaskCommand[],
  reads: string[],
  notes: { key: string; vars?: Record<string, string | number> }[],
): void {
  const total = Math.abs(deg);
  if (total < TURN_MIN_DEG) {
    // **안 낸다.** 규약이 안 받는다. 조용히 버리지 않고 그 사실을 적는다.
    notes.push({ key: 'step.note.turnTooSmall', vars: { deg: total.toFixed(1), min: TURN_MIN_DEG } });
    return;
  }
  const sign = deg < 0 ? -1 : 1;
  if (total > TURN_MAX_DEG) {
    notes.push({ key: 'step.note.turnSplit', vars: { deg: total.toFixed(0), max: TURN_MAX_DEG } });
  }
  let left = total;
  while (left >= TURN_MIN_DEG) {
    const piece = Math.min(left, TURN_MAX_DEG);
    // 남는 꼬리가 5도 미만이 되지 않게 — 그 꼬리는 낼 수 없어 사라진다.
    const take = left - piece < TURN_MIN_DEG && left - piece > 0 ? left : piece;
    const value = Number((take * sign).toFixed(1));
    steps.push({ taskId: 'T-STEP', action: 'turn', parameters: { deg: value } });
    reads.push(readTurn(value));
    left -= take;
  }
}

/** 직진 하나. 구간 상한으로 나눈다. */
function pushForward(
  metres: number,
  vx: number,
  chunk: number,
  steps: TaskCommand[],
  reads: string[],
  notes: { key: string; vars?: Record<string, string | number> }[],
): void {
  if (metres < FORWARD_MIN_M) {
    notes.push({ key: 'step.note.forwardTooSmall', vars: { m: metres.toFixed(2), min: FORWARD_MIN_M } });
    return;
  }
  const pieces = Math.ceil(metres / chunk);
  if (pieces > 1) {
    notes.push({
      key: 'step.note.forwardSplit',
      vars: { total: metres.toFixed(2), pieces, each: (metres / pieces).toFixed(2) },
    });
  }
  // **고르게 나눈다.** 마지막 조각만 짧으면 그 조각이 0.05m 미만이 되어 사라질 수 있다.
  const each = Number((metres / pieces).toFixed(2));
  for (let index = 0; index < pieces; index += 1) {
    steps.push({ taskId: 'T-STEP', action: 'move_forward', parameters: { distance_m: each, vx } });
    reads.push(readForward(each, vx));
  }
}

/**
 * 읽은 것을 사람 말로. **여기도 사전을 안 쓴다** — 숫자와 단위뿐이고 `←`·`→` 는 어느
 * 언어에서도 같다. 「오른쪽」·「왼쪽」이라는 낱말 대신 부호와 화살표를 쓰는 이유가 그것이다.
 */
function readTurn(deg: number): string {
  return `${deg < 0 ? '←' : '→'} ${Math.abs(deg).toFixed(1)}°`;
}

function readForward(metres: number, vx: number): string {
  return `↑ ${metres.toFixed(2)} m (vx ${vx.toFixed(2)})`;
}

/**
 * **읽은 걸음으로 임무 하나를 만든다** (260922 — 발화로 들어온 정량 명령).
 *
 * 머리줄의 입력칸이 아니라 **발화·문장 입력**으로 들어온 정량 명령이 지나는 길이다.
 * 「Go1이 1m 앞으로 전진해」는 대본에도 없고 모델이 만들 것도 아니다 — 사람이 이미
 * 숫자로 다 적었으므로, 그것을 그대로 임무로 세운다.
 *
 * **모델이 낸 임무와 구별해야 한다.** 이 임무의 출처는 규칙이고, 근거는 사람이 적은
 * 문장 그 자체다. 모델 이름을 지어 붙이면 「누가 만든 값인가」가 틀어진다.
 *
 * 마일스톤 하나에 걸음마다 태스크 하나다. **차례대로 매달린다**(`deps`) — 돌기 전에
 * 가면 엉뚱한 데로 가므로 순서가 그림에도 남아야 한다.
 */
export function stepMissionView(sentence: string, script: StepScript, missionId: string): {
  missionId: string;
  label: string;
  world: 'registry';
  utteranceText: string;
  durationSec: number;
  milestones: { id: string; title: string; assignedTargets: string[]; staticStatus: null }[];
  tasks: { id: string; title: string; deps: string[]; target: string | null; actionItems: never[]; milestone: string }[];
  events: never[];
  cast: string[];
  hardware: null;
  params: Record<string, unknown>;
  map: null;
  refEdges: never[];
  viewpoints: null;
  viewpointTimeline: never[];
} {
  const tasks = script.steps.map((step, index) => ({
    id: `T-Q${index + 1}`,
    // **읽은 줄을 그대로 제목으로 쓴다.** 「↑ 1.00 m (vx 0.30)」 — 사람이 보낸 것과
    // 화면에 적힌 것이 같은 글자여야 나중에 대조할 수 있다.
    title: script.reads[index] ?? step.action,
    deps: index === 0 ? [] : [`T-Q${index}`],
    target: null,
    actionItems: [] as never[],
    milestone: 'MS-Q',
  }));
  return {
    missionId,
    label: sentence,
    world: 'registry',
    utteranceText: sentence,
    durationSec: 0,
    milestones: [{ id: 'MS-Q', title: sentence, assignedTargets: [], staticStatus: null }],
    tasks,
    events: [],
    cast: [],
    hardware: null,
    // **걸음을 임무에 실어 둔다.** 승인 뒤 발행하는 쪽이 이것을 읽는다 — 화면이 그린
    // 태스크와 로봇에 나갈 걸음이 **같은 출처**여야 둘이 갈리지 않는다.
    params: { step_commands: script.steps },
    map: null,
    refEdges: [],
    viewpoints: null,
    viewpointTimeline: [],
  };
}

/** 이 임무가 정량 명령으로 세워진 것인가. `params` 가 그 사실을 든다. */
export function stepCommandsOf(params: Record<string, unknown> | null | undefined): readonly TaskCommand[] {
  const raw = params?.step_commands;
  return Array.isArray(raw) ? (raw as TaskCommand[]) : [];
}
