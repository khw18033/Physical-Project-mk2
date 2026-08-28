/**
 * src/shared/voiceAudit.ts
 *
 * 책임소재 필드(REQ-1305 / VZ-O-03)를 만드는 곳. **의존이 없다 —** 그래야
 * `verify:voice-audit` 이 브라우저 없이 이 함수를 실제로 불러 보고,
 * `voice` 가 빠진 요청이 정말 거부되는지 **런타임에서** 확인할 수 있다.
 *
 * 타입만으로 막지 않는 이유: 나중에 다른 사람이 음성 경로를 하나 더 붙일 때
 * `as any` 한 번이면 타입 검사는 통과한다. 조용히 빠지는 곳이라 런타임에서도 막는다.
 *
 * **기록은 여기서 하지 않는다.** 브라우저는 감사 필드를 만들어 전달만 하고,
 * 적재는 백엔드 audit-writer 의 일이다.
 */

export type InputModality = 'pointer' | 'voice';

/**
 * 음성으로 들어온 명령의 출처.
 *
 * `transcript` 와 `transcript_edited` 를 **둘 다** 남긴다. 원문만 남기면 사람이 고친
 * 오인식을 놓치고, 수정본만 남기면 STT 성능을 나중에 평가할 수 없다.
 *
 * 세 수치는 각각 그대로 싣는다. 하나로 뭉치지 않는다 — 뭉치면 `VZ-L-03` 임계를
 * 실측할 근거가 사라진다. 값이 `null` 인 것은 정상이다(무음이라 세그먼트가 0건인 경우 등).
 * 다만 **키가 없는 것은 정상이 아니다** — 그건 경로 어딘가에서 빠뜨린 것이다.
 */
export type VoiceAudit = {
  transcript: string;
  transcript_edited: string;
  avg_logprob: number | null;
  no_speech_prob: number | null;
  mean_word_prob: number | null;
  engine: string;
  model: string;
  audio_ref: string;
};

/** 키가 반드시 있어야 하는 항목. 값의 null 여부는 따지지 않는다. */
export const VOICE_AUDIT_KEYS = [
  'transcript',
  'transcript_edited',
  'avg_logprob',
  'no_speech_prob',
  'mean_word_prob',
  'engine',
  'model',
  'audio_ref',
] as const;

/** 문자열이어야 하는 항목. 비어 있으면 채우지 않은 것으로 본다. */
const REQUIRED_TEXT_KEYS = ['transcript', 'transcript_edited', 'engine', 'model', 'audio_ref'] as const;

export class CommandAuditError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CommandAuditError';
  }
}

/**
 * 감사 필드를 만든다. 만들 수 없으면 **던진다** — 발행하지 않는다.
 *
 * `input_modality: 'voice'` 인데 `voice` 가 비어 있으면 거부한다. 빈 채로 내보내면
 * 그 명령은 "사람이 냈다"는 것 말고는 아무것도 되짚을 수 없는 기록이 된다.
 */
export function buildAudit(modality: InputModality, voice?: VoiceAudit): Record<string, unknown> {
  if (modality !== 'voice') {
    if (voice) throw new CommandAuditError(`input_modality='${modality}' 인데 voice 필드가 실려 있습니다`);
    return { produced_by: 'human', input_modality: modality };
  }
  if (!voice || typeof voice !== 'object') {
    throw new CommandAuditError("input_modality='voice' 인데 voice 감사 필드가 없습니다 (REQ-1305)");
  }
  const missing = VOICE_AUDIT_KEYS.filter((key) => !(key in voice));
  if (missing.length) {
    throw new CommandAuditError(`voice 감사 필드 누락: ${missing.join(', ')} (REQ-1305)`);
  }
  const blank = REQUIRED_TEXT_KEYS.filter((key) => typeof voice[key] !== 'string' || !voice[key].trim());
  if (blank.length) {
    throw new CommandAuditError(`voice 감사 필드가 비어 있습니다: ${blank.join(', ')} (REQ-1305)`);
  }
  return { produced_by: 'human', input_modality: 'voice', voice: { ...voice } };
}
