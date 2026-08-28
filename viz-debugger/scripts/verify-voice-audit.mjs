// input_modality: 'voice' 인데 voice 감사 필드가 없으면 발행이 막히는지 검사한다 (REQ-1305).
//
// **타입만으로는 못 막는다.** 나중에 다른 사람이 음성 경로를 하나 더 붙일 때 `as any`
// 한 번이면 타입 검사는 통과하고 기록만 조용히 빈다. 그래서 여기서는 규칙을 텍스트로
// 훑지 않고 **실제 가드 함수를 불러 본다** (Node 의 타입 스트리핑으로 .ts 를 그대로 import).
//
// 두 가지를 본다.
//   1. 가드가 실제로 거부하는가 — voice 를 뺀 대조군, 키 하나만 뺀 대조군 포함
//   2. 명령 출구가 그 가드를 실제로 부르는가 — 호출을 지운 대조군 포함
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const sharedDir = new URL('../src/shared/', import.meta.url);
const guardPath = new URL('voiceAudit.ts', sharedDir);
const egressPath = new URL('commandEgress.ts', sharedDir);

const { buildAudit, CommandAuditError, VOICE_AUDIT_KEYS } = await import(guardPath.href);

const full = {
  transcript: '503 구역 로봇 상태 보여줘',
  transcript_edited: '503 구역 로봇 상태 보여줘',
  avg_logprob: -0.2,
  no_speech_prob: 0.0001,
  mean_word_prob: 0.91,
  engine: 'faster-whisper',
  model: 'large-v3-turbo',
  audio_ref: 'recordings/20260828T000000-abcdef.webm',
};

const failures = [];
const rejects = (label, run) => {
  try {
    run();
    failures.push(`${label} — 거부되지 않고 통과했다`);
  } catch (error) {
    if (!(error instanceof CommandAuditError)) failures.push(`${label} — CommandAuditError 가 아닌 ${error?.name} 로 실패했다`);
  }
};

// 정상 경로는 통과해야 한다. 무엇이든 다 막는 가드는 가드가 아니다.
try {
  const audit = buildAudit('voice', full);
  if (audit.produced_by !== 'human' || audit.input_modality !== 'voice' || !audit.voice) {
    failures.push('정상 음성 요청의 감사 필드가 제대로 만들어지지 않았다');
  }
  for (const key of VOICE_AUDIT_KEYS) {
    if (!(key in audit.voice)) failures.push(`감사 필드에 ${key} 가 실리지 않았다`);
  }
  // 세 수치가 하나로 뭉개지지 않았는지.
  if (audit.voice.avg_logprob === audit.voice.mean_word_prob) failures.push('세 수치가 같은 값으로 뭉쳐졌다');
} catch (error) {
  failures.push(`정상 음성 요청이 거부됐다: ${error?.message}`);
}
try {
  buildAudit('pointer');
} catch (error) {
  failures.push(`화면 조작 요청이 거부됐다: ${error?.message}`);
}

// 음성 대조군 — 빠뜨린 요청은 반드시 잡혀야 한다.
rejects("voice 필드 없이 input_modality='voice'", () => buildAudit('voice'));
rejects("voice 필드가 빈 객체", () => buildAudit('voice', {}));
for (const key of VOICE_AUDIT_KEYS) {
  const partial = { ...full };
  delete partial[key];
  rejects(`voice.${key} 를 뺀 요청`, () => buildAudit('voice', partial));
}
rejects('audio_ref 가 빈 문자열인 요청', () => buildAudit('voice', { ...full, audio_ref: '   ' }));
rejects("input_modality='pointer' 인데 voice 가 실린 요청", () => buildAudit('pointer', full));

// 세 수치는 null 일 수 있다(무음이라 세그먼트가 0건인 경우). 키만 있으면 통과해야 한다.
try {
  buildAudit('voice', { ...full, avg_logprob: null, no_speech_prob: null, mean_word_prob: null });
} catch (error) {
  failures.push(`수치가 null 인 정상 요청이 거부됐다: ${error?.message}`);
}

// 출구가 가드를 실제로 부르는가.
const egressSource = readFileSync(egressPath, 'utf8');
if (!/buildAudit\s*\(/.test(egressSource)) {
  failures.push('commandEgress.ts 가 buildAudit() 을 부르지 않는다 — 가드가 우회됐다');
}
// 축약 표기(`audit,`)와 `audit: audit` 둘 다 받는다.
if (!/(^|[\s{,])audit\s*(,|:\s*audit\b)/m.test(egressSource)) {
  failures.push('commandEgress.ts 가 만들어진 감사 필드를 요청에 싣지 않는다');
}
// 그 검사의 대조군 — 호출을 지운 사본은 반드시 잡혀야 한다.
const withoutGuard = egressSource.replace(/buildAudit\s*\(/g, 'noGuard(');
if (/buildAudit\s*\(/.test(withoutGuard)) failures.push('대조군을 만들지 못했다 (buildAudit 호출 제거 실패)');

// 가드 자체를 무력화한 대조군도 잡히는지 — 규칙을 지운 사본을 실제로 불러 본다.
const scratch = mkdtempSync(join(tmpdir(), 'verify-voice-audit-'));
const mutantPath = join(scratch, 'voiceAudit.ts');
const mutant = readFileSync(guardPath, 'utf8').replace(
  /const missing = VOICE_AUDIT_KEYS\.filter\(\(key\) => !\(key in voice\)\);/,
  'const missing = [];',
);
writeFileSync(mutantPath, mutant, 'utf8');
const mutantModule = await import(pathToFileURL(mutantPath).href);
let mutantCaught = false;
try {
  const partial = { ...full };
  delete partial.avg_logprob;
  mutantModule.buildAudit('voice', partial);
} catch {
  mutantCaught = true;
}
if (mutantCaught) {
  failures.push('가드를 지운 대조군이 여전히 거부됐다 — 이 검사가 무엇을 보고 있는지 불분명하다');
}

if (failures.length) {
  console.error(`❌ 음성 감사 필드 검사 실패:\n  - ${failures.join('\n  - ')}`);
  process.exit(1);
}
console.log(`✅ 통과 — voice 감사 필드 ${VOICE_AUDIT_KEYS.length}개 중 하나라도 빠지면 발행 거부, 출구가 가드를 호출, 가드 제거 대조군 검출`);
