/**
 * src/physical/encode.ts (260910 신설 — 하드웨어 연동 §1)
 *
 * **명령을 바이트로 바꾸는 자리.** 토픽·주소는 여기 없다 — 그것은 `PhysicalClient.ts` 다.
 *
 * 하드웨어가 실제로 쏴 보고 잰 수치가 둘 있고, 우리 인코딩이 그 길이와 같아야 한다.
 * 하나라도 필드 번호나 와이어 타입이 어긋나면 길이가 달라지므로 **길이가 서명 노릇을 한다.**
 * `verify:command-encode` 가 매번 다시 잰다.
 *
 * ## 장비 id 가 두 개인 이유
 *
 * 화면과 대본은 `robot-01`(registry.json 의 id)을 쓰고 하드웨어는 `go1-001` 을 쓴다.
 * **둘 다 맞는 이름이고, 갈아 끼우는 자리가 여기 하나다.** registry 를 고치면 대본 네 편과
 * `verify:script-library` 의 cast 대조가 전부 따라 움직이는데, 그것은 이번 범위 밖이고
 * 화면에 찍히는 이름을 바꿀 이유도 없다. 바깥 세상의 이름은 경계 파일 안에 둔다 —
 * `SttClient` 가 STT 주소를 혼자 아는 것과 같은 규칙이다(`verify:physical-port`).
 */

import { physical } from './protocol.js';
import { STOP_ACTION } from './presets.ts';

/** 하드웨어가 부르는 장비 이름. **이 디렉터리 밖에 적지 않는다.** */
export const HARDWARE_TARGET = 'go1-001';

/** 화면·대본의 장비 id → 하드웨어의 장비 id. 지금은 하나뿐이라 표가 짧다. */
const TARGET_OF: Record<string, string> = { 'robot-01': HARDWARE_TARGET };

/** 화면 id 를 하드웨어 id 로. 모르는 id 는 그대로 보낸다 — 지어내지 않는다. */
export function hardwareTarget(vizEntityId: string): string {
  return TARGET_OF[vizEntityId] ?? vizEntityId;
}

/**
 * 하드웨어가 받는 셋과, **우리가 정의해 넘긴 정지 하나** (`STOP_ACTION`).
 * 그 밖의 action 은 장치가 거부한다(Capability §5-4).
 *
 * 정지의 이름은 상수에서 끌어온다 — 하드웨어가 다른 이름을 쓰겠다고 하면 `presets.ts` 의
 * 그 한 줄만 고치면 이 타입까지 같이 따라온다.
 */
export type PhysicalAction = 'ping' | 'scan_mission' | 'move_forward' | typeof STOP_ACTION;

export type CommandInput = {
  commandId: string;
  action: PhysicalAction;
  /** `map<string, double>` 이다 — **문자열 파라미터를 넣을 자리가 없다**(§1). */
  parameters?: Record<string, number>;
  /** 기본은 하드웨어 장비. 화면 id 를 넘기면 위 표로 바꾼다. */
  target?: string;
};

/** 하드웨어가 잰 수치. 검사와 화면이 같은 값을 본다. */
export const PING_BYTES = 31;
export const SCAN_REFERENCE_BYTES = 79;

/**
 * 명령 하나를 봉투에 담아 바이트로. **봉투는 `PhysicalCommandEnvelope` 다** — 지시서
 * 예시의 `Envelope` 는 줄임말이고 스키마의 실제 이름은 이쪽이다.
 *
 * `deadline_unix_ms` 는 넣지 않는다. 0 이면 없음이고(스키마 §5-2), 시연에서 마감을 걸
 * 이유가 없다 — 넣으면 그 시각이 지났을 때 로봇이 시작을 거부한다.
 */
export function encodeCommand(input: CommandInput): Uint8Array {
  const command: Record<string, unknown> = {
    commandId: input.commandId,
    target: hardwareTarget(input.target ?? 'robot-01'),
    action: input.action,
  };
  // 파라미터가 없으면 **필드를 아예 안 넣는다.** 빈 맵을 넣어도 바이트는 같지만,
  // 「없음」과 「비어 있음」을 구별해 두는 편이 나중에 읽기 쉽다.
  if (input.parameters !== undefined && Object.keys(input.parameters).length > 0) {
    command.parameters = input.parameters;
  }
  return physical.PhysicalCommandEnvelope.encode(
    physical.PhysicalCommandEnvelope.create({ command }),
  ).finish();
}

/** 명령 id — 재전송 식별용이다(스키마 field 1). 12자로 맞춰 기준 수치와 길이가 같게 둔다. */
let commandSeq = 0;
export function nextCommandId(): string {
  commandSeq += 1;
  return 'cmd-' + String(commandSeq).padStart(8, '0');
}
