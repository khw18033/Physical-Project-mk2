// input_modality: 'voice' 인데 voice 감사 필드가 없으면 발행이 막히는지 검사한다 (REQ-1305).
//
// **타입만으로는 못 막는다.** 나중에 다른 사람이 음성 경로를 하나 더 붙일 때 `as any`
// 한 번이면 타입 검사는 통과하고 기록만 조용히 빈다. 그래서 여기서는 규칙을 텍스트로
// 훑지 않고 **실제 가드 함수를 불러 본다** (Node 의 타입 스트리핑으로 .ts 를 그대로 import).
//
// 통합 이후 감사 필드는 두 파일이 나눠 맡는다.
//   voiceAudit.ts     — 검사만 한다 (발행 전에 막는 자리)
//   auditFieldMap.ts  — 이름을 붙인다 (감사 필드 이름을 한 파일에 가두는 곳)
// 그래서 이 검사도 둘 다 본다. 이름이 두 벌로 갈라지는 것이 막고 싶은 일이다.
//
// 네 가지를 본다.
//   1. 가드가 실제로 거부하는가 — voice 를 뺀 대조군, 키 하나만 뺀 대조군 포함
//   2. 통과한 값이 auditFieldMap 을 거쳐 **세 수치가 각각 살아서** 실리는가
//   3. 명령 출구가 그 두 단계를 실제로 거치는가 — 호출을 지운 대조군 포함
//   4. 가드를 무력화한 사본이 잡히는가
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const sharedDir = new URL('../src/shared/', import.meta.url);
const guardPath = new URL('voiceAudit.ts', sharedDir);
const fieldMapPath = new URL('auditFieldMap.ts', sharedDir);
const egressPath = new URL('commandEgress.ts', sharedDir);
const centerPath = new URL('commandCenter.ts', sharedDir);

const { buildAudit, CommandAuditError, VOICE_AUDIT_KEYS } = await import(guardPath.href);
const { buildAuditPayload, toAuditEntry } = await import(fieldMapPath.href);

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

// --- 1. 정상 경로는 통과해야 한다. 무엇이든 다 막는 가드는 가드가 아니다. -----------
let checked;
try {
  checked = buildAudit('voice', full);
  if (checked.inputMode !== 'voice') failures.push(`정상 음성 요청의 inputMode 가 '${checked.inputMode}' 다`);
  if (!checked.voice) failures.push('정상 음성 요청에서 voice 가 사라졌다');
} catch (error) {
  failures.push(`정상 음성 요청이 거부됐다: ${error?.message}`);
}
try {
  const pointer = buildAudit('pointer');
  if (pointer.inputMode !== 'click') failures.push(`화면 조작의 inputMode 가 '${pointer.inputMode}' 다`);
  if (pointer.voice) failures.push('화면 조작인데 voice 가 실렸다');
} catch (error) {
  failures.push(`화면 조작 요청이 거부됐다: ${error?.message}`);
}

// --- 2. 이름 붙이기 — 세 수치가 각각 살아 있는가 -----------------------------------
if (checked) {
  const payload = buildAuditPayload({ inputMode: checked.inputMode, decisionSource: 'human', voice: checked.voice });
  if (payload.input_mode !== 'voice') failures.push('감사 필드에 input_mode 가 실리지 않았다');
  if (payload.decision_source !== 'human') failures.push('감사 필드에 decision_source 가 실리지 않았다');
  if (!payload.voice) failures.push('감사 필드에 voice 가 실리지 않았다 (REQ-1305)');
  else {
    for (const key of VOICE_AUDIT_KEYS) {
      if (!(key in payload.voice)) failures.push(`감사 필드 voice 에 ${key} 가 실리지 않았다`);
    }
    // 세 수치가 하나로 뭉개지지 않았는지. 뭉치면 VZ-L-03 임계를 실측할 근거가 사라진다.
    const numbers = [payload.voice.avg_logprob, payload.voice.no_speech_prob, payload.voice.mean_word_prob];
    if (new Set(numbers).size !== 3) failures.push('세 수치가 같은 값으로 뭉쳐졌다');
    if (payload.voice.transcript === undefined || payload.voice.transcript_edited === undefined) {
      failures.push('원문과 수정본 중 한쪽만 실렸다');
    }
  }
  // 화면 표시 경로도 이 이름을 실제로 읽는가 (auditFieldMap 안에서 이름이 갈라지는 것 방지).
  const entry = toAuditEntry({ ...payload, command_id: 'cmd-1' });
  const labels = entry.rows.map((row) => row.label);
  for (const label of ['입력 수단', '전사(원문)', 'STT 엔진', '녹음']) {
    if (!labels.includes(label)) failures.push(`감사 표시행에 '${label}' 이 없다 — 이름이 갈라졌다`);
  }
}

// --- 3. 음성 대조군 — 빠뜨린 요청은 반드시 잡혀야 한다 ------------------------------
rejects("voice 필드 없이 input_modality='voice'", () => buildAudit('voice'));
rejects('voice 필드가 빈 객체', () => buildAudit('voice', {}));
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

// --- 4. 출구가 두 단계를 실제로 거치는가 -------------------------------------------
const egressSource = readFileSync(egressPath, 'utf8');
const centerSource = readFileSync(centerPath, 'utf8');
if (!/buildAudit\s*\(/.test(egressSource)) {
  failures.push('commandEgress.ts 가 buildAudit() 을 부르지 않는다 — 가드가 우회됐다');
}
if (!/commandTracker\.issue\s*\(/.test(egressSource)) {
  failures.push('commandEgress.ts 가 commandTracker.issue() 를 부르지 않는다 — 출구가 갈라졌다');
}
if (!/buildAuditPayload\s*\(/.test(centerSource)) {
  failures.push('commandCenter.ts 가 buildAuditPayload() 를 부르지 않는다 — 이름이 두 벌이 됐다');
}
if (!/voice:\s*options\.voice/.test(centerSource)) {
  failures.push('commandCenter.ts 가 voice 를 감사 필드로 넘기지 않는다');
}
// 그 검사의 대조군 — 호출을 지운 사본은 반드시 잡혀야 한다.
if (/buildAudit\s*\(/.test(egressSource.replace(/buildAudit\s*\(/g, 'noGuard('))) {
  failures.push('대조군을 만들지 못했다 (buildAudit 호출 제거 실패)');
}

// --- 5. 가드 자체를 무력화한 대조군 -------------------------------------------------
const scratch = mkdtempSync(join(tmpdir(), 'verify-voice-audit-'));
const mutantPath = join(scratch, 'voiceAudit.ts');
const mutant = readFileSync(guardPath, 'utf8').replace(
  /const missing = VOICE_AUDIT_KEYS\.filter\(\(key\) => !\(key in voice\)\);/,
  'const missing = [];',
);
writeFileSync(mutantPath, mutant, 'utf8');
// 옆 모듈(auditFieldMap.ts)을 타입으로만 참조하므로 사본만 옮겨도 import 가 성립한다.
writeFileSync(join(scratch, 'auditFieldMap.ts'), readFileSync(fieldMapPath, 'utf8'), 'utf8');
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
console.log(`✅ 통과 — voice 감사 필드 ${VOICE_AUDIT_KEYS.length}개 중 하나라도 빠지면 발행 거부, 세 수치가 각각 실림, 출구가 가드→이름붙이기 두 단계를 거침, 가드 제거 대조군 검출`);
