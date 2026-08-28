import { recordHuman } from '../data/scenario.ts';
import { getTransport, type CommandAck, type CommandRequest } from '../transport/index.ts';
import { pushNotification } from './notifications.ts';

export type AppCommand = {
  action: string;
  entity?: string;
  params?: Record<string, unknown>;
};

let sequence = 0;

/** 앱 전체의 유일한 명령 출구. 셸과 모든 탭은 이 함수만 호출한다. */
export async function issueCommand(command: AppCommand): Promise<CommandAck> {
  const entity = command.entity ?? 'MSN-260826-01';
  recordHuman(command.action, entity, command.params);
  const request: CommandRequest = {
    client_request_id: `viz-${Date.now()}-${sequence++}`,
    entity,
    action: command.action,
    params: command.params ?? {},
    expires_at: new Date(Date.now() + 10_000).toISOString(),
    audit: { produced_by: 'human', input_modality: 'pointer' },
  };
  const ack = await getTransport().publishCommand(request);
  if (!ack.accepted) {
    pushNotification({ id: request.client_request_id, source: 'command', message: `${command.action}: ${ack.message}`, occurredAt: new Date().toISOString() });
  }
  return ack;
}
