/**
 * src/physical/linkWatch.ts (260921 신설 — 드론 연결 §화면 「FC 링크」)
 *
 * **FC 링크 줄을 계속 다시 잰다.**
 *
 * 연결 관리는 원래 **눌러서 확인하는 판**이다. 그 박자가 맞는 줄이 둘 있다 — 브로커는
 * 붙어 있으면 붙어 있고, 단말은 답하면 답한다. 그런데 **FC 링크는 시연 도중에 바뀐다.**
 * TELEM 점퍼가 빠지거나 기체 전원이 내려가면 라즈베리파이는 멀쩡한 채로 FC 만 끊긴다.
 * 그때 화면이 「아까 눌렀을 때는 초록이었다」를 보여 주고 있으면 아무 소용이 없다.
 *
 * 그래서 붙어 있는 동안 `ping` 을 되풀이한다. `ping` 의 답에 `fc_link` 가 실려 오므로
 * (드론 계약 §5) 그것이 곧 지금의 FC 링크다.
 *
 * ## Go1 에는 아무 일도 일어나지 않는다
 *
 * **기종으로 가르지 않는다.** 한 번이라도 `fc_link` 를 실어 보낸 장비에만 돈다 —
 * Go1 은 그 키를 안 싣고, 그래서 `ping` 이 되풀이되지 않는다. 판정 근거가 주소도 기종
 * 목록도 아니라 **장비가 보낸 키 하나**이고, 그것이 없으면 이 파일은 잠든 채로 있다.
 *
 * 거꾸로 말하면 이 감시는 **장비가 스스로 켠다.** 드론 쪽이 나중에 `fc_link` 를 빼면
 * 감시도 저절로 멎는다 — 우리가 고칠 자리가 없다.
 *
 * ## 「확인 중」을 켜지 않는다
 *
 * `checkTarget` 을 그대로 부르면 2초마다 `checking: true` 가 켜져 **「확인」 버튼이 계속
 * 깜빡이며 비활성이 된다.** 사람이 누르려는 순간 회색이 되는 판은 못 쓴다. 그래서 결과만
 * 조용히 갈아 끼운다.
 */

import { checkPhysical, type PhysicalProbe, type RobotFacts } from '../shared/connectionCheck.ts';
import { setHealth } from '../shared/connectionHealth.ts';

/**
 * 다시 재는 간격. 드론 상태가 1Hz 이므로 그보다 촘촘할 이유가 없고, 2초면 점퍼를 뽑고
 * 화면을 볼 때쯤 이미 빨갛다.
 */
export const LINK_WATCH_MS = 2_000;

/** 한 번이라도 FC 링크를 말한 적이 있는가. 그 전에는 감시를 켜지 않는다. */
let armed = false;
let timer: ReturnType<typeof setInterval> | null = null;
/** 겹쳐 돌지 않게. 앞 왕복이 안 끝났으면 이번 차례는 건너뛴다. */
let inFlight = false;

/**
 * 확인 결과를 보고 감시를 켤지 정한다. **연결 확인이 끝날 때마다** 부른다.
 *
 * 켜는 조건은 하나다 — 그 장비가 `fc_link` 를 말했는가. 그 줄의 이름(`check.line.fcLink`)이
 * 곧 그 사실이라 여기서 다시 판정하지 않는다.
 */
export function armLinkWatch(
  lines: readonly { labelKey: string }[],
  probe: () => PhysicalProbe,
  facts: () => RobotFacts | null,
): void {
  if (!lines.some((row) => row.labelKey === 'check.line.fcLink')) return;
  armed = true;
  start(probe, facts);
}

function start(probe: () => PhysicalProbe, facts: () => RobotFacts | null): void {
  if (timer !== null || !armed) return;
  timer = setInterval(() => {
    if (inFlight) return;
    const client = probe();
    // 끊겼으면 재지 않는다. 다시 붙으면 사람이 「확인」을 누르고, 그때 다시 켜진다.
    if (client.getStatus().state !== 'open') { stopLinkWatch(); return; }
    inFlight = true;
    void checkPhysical(client, facts)
      .then((lines) => { setHealth('physical', lines); })
      // 여기서 예외가 새면 타이머가 조용히 죽는다 — 삼키되 다음 차례는 돈다.
      .catch(() => undefined)
      .finally(() => { inFlight = false; });
  }, LINK_WATCH_MS);
}

/** 감시를 멈춘다. 끊겼을 때와 화면을 떠날 때. */
export function stopLinkWatch(): void {
  if (timer !== null) { clearInterval(timer); timer = null; }
  armed = false;
}

/** 지금 돌고 있는가. 검사가 본다. */
export function linkWatchRunning(): boolean {
  return timer !== null;
}
