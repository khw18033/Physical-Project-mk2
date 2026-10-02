// verify:frame-ref (260921 신설 — 탐지 프레임 참조·출처·정합 규칙)
//
// **가리키는 프레임을 모르는 채로 「정합했다」고 그리지 않는다.**
//
// 백엔드 규격에서 `frame_ref` 는 **객체**(`{source_id, capture_timestamp, sequence_id}`)이고
// 목 게이트웨이는 **정수** 하나를 보낸다. 둘을 입구에서 모으지 않으면 타입 검사는 통과하고
// 런타임에 `frame_ref.sequenceId` 가 `undefined` 가 된다 — 조용히 어긋나는 종류다.
//
// 보는 것 여섯.
//  1. 두 모양 — 정수(옛 계약)와 객체(규격)를 둘 다 받고, 쓰레기는 버리는가
//  2. 입구가 하나 — 단언(`as DetectionResult`) 대신 정규화를 지나는가
//  3. 버퍼 키 — `(source_id, sequence_id)` 쌍이되 옛 계약 프레임은 순번만으로 짚히는가
//  4. 세션 — 순번이 줄면 버퍼를 비우는가
//  5. 출처 — `server` 가 안 버려지고, 모르는 tier 는 버려지는가
//  6. 정합 규칙 — 발신자 선언이 사용자 토글을 이기는가, 그 사실이 보고서에 남는가
//
// 대조군 포함 — 검사를 무력화한 사본이 반드시 실패로 잡히는지까지 본다.

import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readSource } from './lib/source.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const code = (source) => source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');

const failures = [];
const controls = [];

const vision = await load('src', 'tabs', 'data', 'vision.ts');
const { FrameBuffer, normalizeDetection, toFrameRef, isNewFrameSession, resolveAlignment, DETECTION_TIERS } = vision;

const frame = (seq, src) => ({
  ...(src === undefined ? {} : { source_id: src }),
  frame_seq: seq, captured_at: 'x', fps: 15,
  display: { width: 640, height: 360 }, reference: { width: 640, height: 360 },
  objects: [{ track_id: 't1', label: 'person', confidence: 0.9, shape: 'person', cx: 100, cy: 100, w: 40, h: 80 }],
});
const det = (ref, extra = {}) => ({
  frame_ref: ref, emitted_at: 'x', inference_delay_ms: 10,
  origin: { tier: 'edge', kind: 'precise', label: 'E', optional: false },
  association: 'enabled', corridor: null,
  bbox_space: { format: 'normalized', origin: 'top-left', reference: { width: 640, height: 360 } },
  detections: [{
    track_id: 't1', label: 'person', confidence: 0.9, class_confidence: 0.9,
    bbox: [0.1, 0.2, 0.1, 0.2], approach: null, trail: [], source_id: 'cam', link: null,
  }],
  ...extra,
});

// ── 1. 두 모양 ───────────────────────────────────────────────────────────────
{
  const fromInt = toFrameRef(12);
  if (fromInt === null || fromInt.sequenceId !== 12) failures.push('정수 frame_ref(옛 계약)를 못 읽는다 — 목 게이트웨이의 정합 시연이 죽는다');
  // **지어 채우지 않는다.** 정수에는 소스도 시각도 없다.
  if (fromInt?.sourceId !== null || fromInt?.captureTimestamp !== null) {
    failures.push('정수에서 모르는 칸을 지어 채웠다 — 없는 사실이 생긴다');
  }
  const fromObj = toFrameRef({ source_id: 'cam-front', capture_timestamp: 't', sequence_id: 12 });
  if (fromObj?.sourceId !== 'cam-front' || fromObj?.sequenceId !== 12) failures.push('객체 frame_ref(규격)를 못 읽는다');
  for (const junk of [null, 'x', {}, { sequence_id: 'a' }, [], undefined, NaN]) {
    if (toFrameRef(junk) !== null) failures.push(`쓰레기 frame_ref 를 받았다 — ${JSON.stringify(junk)}`);
  }
  // 가리키는 프레임을 모르면 그 탐지는 버린다.
  if (normalizeDetection(det(undefined)) !== null) failures.push('frame_ref 가 없는 탐지를 통과시켰다');
  if (normalizeDetection('nope') !== null) failures.push('탐지가 아닌 값을 통과시켰다');
  // `alignment` 부재와 값을 가른다 — 뜻이 다르다.
  if (normalizeDetection(det(1)).alignment !== null) failures.push('alignment 부재를 null 로 안 둔다');
  if (normalizeDetection(det(1, { alignment: 'frame' })).alignment !== 'frame') failures.push('alignment 를 못 읽는다');
}

// ── 2. 입구가 하나 ───────────────────────────────────────────────────────────
{
  const src = code(readSource('src/tabs/data/vision.ts'));
  if (/payload as DetectionResult/.test(src)) {
    failures.push('탐지 payload 를 단언으로 받는다 — 타입 검사는 통과하고 런타임에 조용히 어긋난다');
  }
  if (!/normalizeDetection\(envelope\.payload\)/.test(src)) {
    failures.push('수신부가 정규화를 안 지난다 — 정수와 객체가 섞여 들어온다');
  }
}

// ── 3. 버퍼 키 ───────────────────────────────────────────────────────────────
{
  const buffer = new FrameBuffer();
  for (let i = 1; i <= 5; i += 1) buffer.pushFrame(frame(i));
  if (buffer.frameAt(toFrameRef(3))?.frame_seq !== 3) failures.push('순번으로 프레임을 못 짚는다');
  // 옛 계약 프레임에는 소스가 없다 — 한쪽만 알 때 억지로 안 맞다고 하면 시연이 죽는다.
  if (buffer.frameAt(toFrameRef({ source_id: 'cam-front', capture_timestamp: 't', sequence_id: 3 }))?.frame_seq !== 3) {
    failures.push('소스를 아는 참조로 소스 없는 프레임을 못 짚는다 — 목 게이트웨이의 프레임이 통째로 안 잡힌다');
  }
  // 양쪽 다 알 때는 대조한다.
  const sourced = new FrameBuffer();
  sourced.pushFrame(frame(3, 'cam-a'));
  if (sourced.frameAt(toFrameRef({ source_id: 'cam-b', capture_timestamp: 't', sequence_id: 3 })) !== null) {
    failures.push('다른 카메라의 같은 순번을 같은 프레임이라고 한다');
  }
}

// ── 4. 세션 ──────────────────────────────────────────────────────────────────
{
  if (isNewFrameSession(frame(5), frame(6))) failures.push('순번이 늘었는데 새 세션이라고 한다 — 매 프레임 버퍼를 비운다');
  if (!isNewFrameSession(frame(5), frame(0))) failures.push('순번이 줄었는데 새 세션이 아니다');
  if (!isNewFrameSession(frame(5, 'a'), frame(6, 'b'))) failures.push('카메라가 바뀌었는데 새 세션이 아니다');

  const buffer = new FrameBuffer();
  for (let i = 1; i <= 5; i += 1) buffer.pushFrame(frame(i));
  buffer.pushFrame(frame(0));
  if (buffer.bufferedCount !== 1) {
    failures.push(`순번 역전 뒤 버퍼가 ${buffer.bufferedCount} 장이다 — 1 이어야 한다. 옛 세션의 같은 번호를 짚으면 지연이 음수가 된다`);
  }
}

// ── 5. 출처 ──────────────────────────────────────────────────────────────────
{
  for (const tier of ['device', 'edge', 'server']) {
    if (!DETECTION_TIERS.includes(tier)) failures.push(`출처 목록에 ${tier} 가 없다 — 그 결과가 통째로 드롭된다`);
  }
  const buffer = new FrameBuffer();
  buffer.pushFrame(frame(1));
  for (const tier of ['device', 'edge', 'server']) {
    buffer.pushDetection(normalizeDetection(det(1, { origin: { tier, kind: 'precise', label: tier, optional: false } })));
    if (buffer.detectionOf(tier) === null) failures.push(`${tier} 결과가 버려졌다`);
  }
  buffer.pushDetection(normalizeDetection(det(1, { origin: { tier: 'bogus', kind: 'precise', label: 'x', optional: false } })));
  if (buffer.detectionOf('bogus') !== null) {
    failures.push('모르는 tier 를 보관한다 — 거친 결과가 정밀 결과처럼 보일 수 있다');
  }
}

// ── 6. 정합 규칙 — 발신자 선언이 토글을 이긴다 ───────────────────────────────
{
  const run = (extra) => {
    const buffer = new FrameBuffer();
    for (let i = 1; i <= 5; i += 1) buffer.pushFrame(frame(i));
    buffer.pushDetection(normalizeDetection(det(2, extra)));
    // 사용자 토글은 **켜 둔다** — 선언이 그것을 이기는지 보는 것이 목적이다.
    return resolveAlignment(buffer, true, frame(5))?.origins[0] ?? null;
  };

  const legacy = run({});
  if (legacy === null || !legacy.aligned) failures.push('옛 계약(선언 없음)에서 토글을 켰는데 정합을 안 한다 — 목 게이트웨이의 시연이 죽는다');
  if (legacy?.declaredAlignment !== null) failures.push('선언이 없는데 declaredAlignment 가 채워졌다');

  const declaredFrame = run({ alignment: 'frame' });
  if (declaredFrame === null || !declaredFrame.aligned) failures.push("alignment='frame' 인데 정합을 안 한다");

  // **핵심** — 모르는 값·정합 아님은 토글이 켜져 있어도 정합하지 않는다(Phase 4 결정 3).
  for (const value of ['none', 'latest', 'bogus']) {
    const out = run({ alignment: value });
    if (out === null || out.aligned) {
      failures.push(`alignment='${value}' 인데 정합했다 — 발신자가 아니라고 말한 것을 정합된 것처럼 그린다`);
    }
    if (out?.declaredAlignment !== value) failures.push(`declaredAlignment 가 '${value}' 로 안 남는다 — 화면이 그 사실을 적을 근거가 없다`);
  }

  // 화면이 그 사실을 실제로 적는가.
  const view = code(readSource('src/tabs/views/VideoOverlayView.tsx'));
  if (!/declaredAlignment !== null && !o\.aligned/.test(view)) {
    failures.push('화면이 「정합 대상이 아님」을 안 적는다 — 정합 안 된 박스가 정합된 것처럼 보인다');
  }
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
{
  const src = readSource('src/tabs/data/vision.ts');

  const asserted = src.replace(
    '        const detection = normalizeDetection(envelope.payload);',
    '        const detection = envelope.payload as DetectionResult;',
  );
  if (asserted === src) failures.push('대조군(가)을 만들지 못했다 — 수신부 정규화의 모양이 바뀌었다');
  else controls.push('탐지를 단언으로 받는 사본');

  const noReset = src.replace(
    '    if (last !== undefined && isNewFrameSession(last, frame)) this.clear();\n',
    '',
  );
  if (noReset === src) failures.push('대조군(나)을 만들지 못했다 — 세션 리셋의 모양이 바뀌었다');
  else controls.push('순번이 줄어도 버퍼를 안 비우는 사본');

  const ignoresDeclared = src.replace(
    "  const wantAligned = declared === null ? aligned : declared === 'frame';",
    '  const wantAligned = aligned;',
  );
  if (ignoresDeclared === src) failures.push('대조군(다)을 만들지 못했다 — 정합 규칙의 모양이 바뀌었다');
  else controls.push('발신자 선언을 무시하고 토글만 보는 사본');
}

if (failures.length) {
  console.error(`❌ verify:frame-ref\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 두 모양 — 정수(옛 계약)와 객체(규격)를 둘 다 받고, 모르는 칸은 null 이고 쓰레기는 버린다');
console.log('✅ 입구 — 단언이 아니라 정규화를 지난다 (타입 검사가 못 잡는 어긋남을 막는다)');
console.log('✅ 버퍼 — 소스를 둘 다 알 때만 대조하고, 옛 계약 프레임은 순번만으로 짚힌다');
console.log('✅ 세션 — 순번이 줄거나 카메라가 바뀌면 버퍼를 비운다');
console.log('✅ 출처 — device·edge·server 셋을 보관하고 모르는 tier 는 버린다');
console.log('✅ 정합 — 발신자 선언이 사용자 토글을 이기고, 그 사실이 보고서와 화면에 남는다');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
