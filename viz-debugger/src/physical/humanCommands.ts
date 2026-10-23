/**
 * src/physical/humanCommands.ts (261023 신설 — 사람 명령 액션 층)
 *
 * **사람이 직접 몬 명령을 액션 층에 적는 자리.** 수동 제어 · SAR · 비행 제어 셋이 여기 하나를 부른다.
 *
 * ## 층과 주체는 다른 축이다
 *
 * > 층은 「명령이냐」가 정하고, 주체는 「누가 냈느냐」가 정한다.
 *
 * 전에는 둘이 섞여 있었다 — 사람이 냈으니 사람 층, 자동이니 액션 층. 그래서 사람이 키로 몬 `teleop` 500건이
 * 사람 층에 점으로만 남았고, 무엇을 얼마나 보냈는지(실린 값 · 장비의 답)는 명령 표가 못 읽었다.
 *
 *   명령(장비에 나간 바이트) → 액션 층. 주체는 낸 쪽: 임무 `backend` · 사람 `human`
 *   누름(시작 · 재시작 · 접근 시작) → 사람 층. 명령이 아니라 사실이다 (`StopButton.tsx`)
 *
 * 세 명령은 순서도에 자리가 없다 — `NO_NODE` 로 적어 **노드에 안 붙는다**(`attachedToNode`). 그래서 분모
 * (§5-2)에도 안 들어간다. 대신 **받은 장비**를 싣는다. 노드가 없는 행을 가를 것이 그것뿐이다.
 *
 * ## 답도 잇는다
 *
 * 그 명령의 `command_id` 로 온 답을 같은 행에 붙인다(`recordHumanAnswer`). 듣는 귀는 둘 중 하나다.
 *
 *   - **수동 제어는 자기 귀로 듣는다.** 한 판에 500건까지 나가므로 명령마다 귀를 걸면 소켓에 귀가 쌓인다.
 *     `manualDispatch.ts` 가 이미 소켓 하나에 귀 하나를 걸어 거절을 듣고 있다 — 그 귀가 답도 넘긴다
 *     (`verify:manual-control` 이 「소켓에 귀 하나」를 지킨다)
 *   - **SAR · 비행 제어는 여기서 건별로 듣는다.** 한 판에 몇 건뿐이고, 끝(종료 · 거절)이 오거나 기한이 지나면 닫는다
 *
 * **기한 사건(`expired`)은 안 적는다** — 수동 제어는 장비가 답을 생략할 수 있는 명령이라(유지 신호 · 키 한 번),
 * 안 온 것을 「영영 안 왔다」로 적으면 없는 고장을 만든다. 정지·일시정지와 다른 점이 이것이다.
 *
 * **로봇에 나가는 바이트는 한 줄도 안 바뀐다.** 이미 나간 뒤에 적기만 한다.
 */

import { NO_NODE } from '../data/actionTrace.ts';
import { recordAnswered, recordCommanded } from '../data/scenario.ts';
import { uplinkWords, type UplinkMessage } from './uplink.ts';

/** 답을 기다리는 시간(건별로 들을 때). 넉넉히 두되 무한정은 아니다. */
const ANSWER_LISTEN_MS = 10_000;

type Listening = { onMessage?: (cb: (message: UplinkMessage) => void) => () => void };

/**
 * 사람이 낸 명령 한 건. **발행이 성공한 뒤에** 부른다 — 안 나간 명령은 명령이 아니다.
 *
 * @param client  답을 건별로 들을 소켓. **`null` 이면 듣지 않는다** — 부르는 쪽이 제 귀로 듣고 `recordHumanAnswer` 로 넘긴다
 */
export function recordHumanCommand(client: Listening | null, input: {
  commandId: string; deviceId: string; action: string;
  parameters: Record<string, number>; requestId?: string | null;
}): void {
  recordCommanded({
    commandId: input.commandId, taskId: NO_NODE, action: input.action,
    parameters: { ...input.parameters }, requestId: input.requestId ?? null,
    // **사람이 낸 것이다.** 층은 명령이라 액션 층이고, 주체는 사람이다.
    issuedBy: 'human', device: input.deviceId,
  });
  if (client === null || typeof client.onMessage !== 'function') return;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const off = client.onMessage((message) => {
    if (message.commandId !== input.commandId) return;
    if (recordHumanAnswer(message)) {
      if (timer !== null) clearTimeout(timer);
      off();
    }
  });
  timer = setTimeout(off, ANSWER_LISTEN_MS);
}

/**
 * 사람이 낸 명령의 답 한 줄. 돌려주는 것은 **그 명령이 끝났나**(종료 · 거절)다 — 귀를 닫을지 정하는 데 쓴다.
 *
 * 그 `command_id` 의 `commanded` 가 열에 없으면 접기가 이 줄을 안 붙인다(`foldActions`) — 남의 명령의 답이
 * 섞이지 않는 것이 같은 규칙의 결과다.
 */
export function recordHumanAnswer(message: UplinkMessage): boolean {
  const refused = message.kind === 'acceptance' && !message.accepted;
  recordAnswered({
    commandId: message.commandId, taskId: NO_NODE, line: uplinkWords(message), answerKind: message.kind,
    outcome: refused || (message.kind === 'result' && message.status !== 'SUCCEEDED') ? 'failed' : 'done',
  });
  return refused || message.kind === 'result';
}
