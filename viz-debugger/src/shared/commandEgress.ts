import { recordHuman } from '../data/scenario.ts';
import { getTransport, type CommandAck, type CommandRequest } from '../transport/index.ts';
import { pushNotification } from './notifications.ts';
import { buildAudit, CommandAuditError, type InputModality, type VoiceAudit } from './voiceAudit.ts';

export type AppCommand = {
  action: string;
  entity?: string;
  params?: Record<string, unknown>;
  /** 무엇으로 낸 명령인가. 생략하면 화면 조작(`pointer`)이다. */
  inputModality?: InputModality;
  /** `inputModality: 'voice'` 일 때 **반드시** 있어야 한다 (REQ-1305). */
  voice?: VoiceAudit;
};

let sequence = 0;

/**
 * 앱 전체의 유일한 명령 출구. 셸과 모든 탭은 이 함수만 호출한다.
 *
 * 음성으로 발행되는 명령도 여기를 거친다. **달라지는 것은 경로가 아니라 감사 필드다.**
 * 감사 필드를 만들 수 없으면 `CommandAuditError` 로 던지고 **아무것도 발행·기록하지 않는다** —
 * 절반만 남은 기록이 아무 기록도 없는 것보다 나쁘다.
 */
export async function issueCommand(command: AppCommand): Promise<CommandAck> {
  const entity = command.entity ?? 'MSN-260826-01';
  let audit: Record<string, unknown>;
  try {
    audit = buildAudit(command.inputModality ?? 'pointer', command.voice);
  } catch (error) {
    if (error instanceof CommandAuditError) {
      pushNotification({ id: `audit-${Date.now()}`, source: 'command', message: `${command.action} 발행 거부 — ${error.message}`, occurredAt: new Date().toISOString() });
    }
    throw error;
  }
  recordHuman(command.action, entity, command.params);
  const request: CommandRequest = {
    client_request_id: `viz-${Date.now()}-${sequence++}`,
    entity,
    action: command.action,
    params: command.params ?? {},
    expires_at: new Date(Date.now() + 10_000).toISOString(),
    audit,
  };
  const ack = await getTransport().publishCommand(request);
  if (!ack.accepted) {
    pushNotification({ id: request.client_request_id, source: 'command', message: `${command.action}: ${ack.message}`, occurredAt: new Date().toISOString() });
  }
  return ack;
}
