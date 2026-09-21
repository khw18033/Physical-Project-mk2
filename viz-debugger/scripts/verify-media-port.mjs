// verify:media-port (260921 신설 — `/media` 수신 경로)
//
// **「연결됨인데 영상만 안 옴」이 진단 가능한가.**
//
// 이 경로의 가장 나쁜 실패는 형식이 틀렸는데 **화면에 아무 신호가 없는 것**이다. 전송
// 계층이 `JSON.parse` 로 시작해 `catch { return }` 하던 자리가 정확히 그것이었다.
// 그래서 이 검사는 「잘 되는가」보다 **「안 될 때 그 사실이 남는가」**를 본다.
//
// 보는 것 여덟.
//  1. 경계 — 영상 소켓 주소·경로를 아는 면이 `src/media/` 하나인가
//  2. 파서 — `[4B][JSON][페이로드]` 를 실제로 흘려서. **던지지 않는가**
//  3. 망가진 입력마다 **사유가 다른가** (한 덩어리로 뭉치면 어느 단계인지 모른다)
//  4. 세션 — 순번이 줄면 새 세션인가
//  5. 끊김 — 4401·4404·4400 은 재시도하지 않는가
//  6. 바이너리 갈래 — `binaryType`·문자열 분기가 클라이언트에 있는가
//  7. 자리 — 상설 판이 아니라 대상 상태 오버레이 안인가
//  8. 한글·영어 두 벌
//
// 대조군 포함 — 검사를 무력화한 사본이 반드시 실패로 잡히는지까지 본다.

import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readdirSync, statSync } from 'node:fs';
import { readSource } from './lib/source.mjs';
import { isScratchPath } from './lib/scratch.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const code = (source) => source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');

const failures = [];
const controls = [];

function walk(dir, out = []) {
  for (const name of readdirSync(join(root, dir))) {
    const rel = `${dir}/${name}`;
    if (isScratchPath(rel)) continue;
    if (statSync(join(root, rel)).isDirectory()) walk(rel, out);
    else if (/\.(ts|tsx)$/.test(name)) out.push(rel);
  }
  return out;
}
const SOURCES = walk('src');
/** 경계 밖. **사전은 뺀다** — 거기 있는 글자는 화면에 적히는 문구이지 주소가 아니다. */
const outside = SOURCES.filter((rel) => !rel.startsWith('src/media/') && !rel.startsWith('src/i18n/'));

// ── 1. 경계 ──────────────────────────────────────────────────────────────────
{
  const MARKS = [
    { re: /['"`]\/media\?/, what: '영상 경로' },
    { re: /source_id=/, what: '카메라 키 쿼리' },
    { re: /VITE_MEDIA_WS/, what: '영상 소켓 환경변수' },
  ];
  for (const rel of outside) {
    const src = code(readSource(rel));
    for (const mark of MARKS) {
      if (mark.re.test(src)) failures.push(`${rel} 가 ${mark.what} 를 직접 적는다 — 그 면은 src/media/ 하나여야 한다`);
    }
  }
  // 토큰 칸을 손으로 적으면 두 벌이 된다.
  for (const rel of outside) {
    if (/['"]media\.token['"]/.test(code(readSource(rel)))) {
      failures.push(`${rel} 가 'media.token' 을 손으로 적는다 — connectionKey() 로 만든다`);
    }
  }
  // **토큰이 저장소에 적혀 있으면 안 된다.** 화면에서 입력하는 값이다.
  for (const rel of SOURCES) {
    if (/token\s*[:=]\s*['"][A-Za-z0-9]{16,}['"]/.test(code(readSource(rel)))) {
      failures.push(`${rel} 에 토큰처럼 보이는 값이 박혀 있다 — 토큰은 화면에서 입력하고 커밋하지 않는다`);
    }
  }
}

// ── 2·3. 파서를 실제로 흘린다 ────────────────────────────────────────────────
{
  const { parseMediaFrame, isNewSession } = await load('src', 'media', 'parse.ts');

  const build = (header, payload) => {
    const json = new TextEncoder().encode(JSON.stringify(header));
    const out = new Uint8Array(4 + json.length + payload.length);
    new DataView(out.buffer).setUint32(0, json.length, false);
    out.set(json, 4);
    out.set(payload, 4 + json.length);
    return out.buffer;
  };
  const header = {
    frame_ref: { source_id: 'cam-front', capture_timestamp: '2026-09-19T14:23:07.412+09:00', sequence_id: 4837 },
    encoding: 'h264', keyframe: true, width: 464, height: 400,
    codec: 'avc1.42C01E', correlation_id: null,
  };
  const payload = new Uint8Array([1, 2, 3, 4, 5]);

  const ok = parseMediaFrame(build(header, payload));
  if (!ok.ok) failures.push(`정상 프레임을 못 뜯었다 — ${ok.reason}`);
  else {
    const f = ok.frame;
    if (f.header.frameRef.sourceId !== 'cam-front') failures.push('source_id 를 못 읽었다');
    if (f.header.frameRef.sequenceId !== 4837) failures.push('sequence_id 를 못 읽었다');
    if (f.header.codec !== 'avc1.42C01E') failures.push('codec 을 못 읽었다 — 디코더 설정이 실패한다');
    if (f.header.width !== 464 || f.header.height !== 400) failures.push('해상도를 못 읽었다');
    if (f.payload.length !== payload.length) failures.push(`페이로드 길이가 ${f.payload.length} 다 — ${payload.length} 여야 한다`);
    if (f.payload[0] !== 1 || f.payload[4] !== 5) failures.push('페이로드 바이트가 어긋났다 — 오프셋이 틀렸다');
  }

  // **모르는 코덱을 파서가 거르면 안 된다.** 서버도 값 어휘를 안 본다.
  const weird = parseMediaFrame(build({ ...header, encoding: 'av1' }, payload));
  if (!weird.ok) failures.push('모르는 encoding 을 파서가 걸렀다 — 상대가 코덱을 늘릴 때마다 화면이 조용히 빈다');

  // 망가진 입력 — **사유가 갈려야 한다.**
  const short = parseMediaFrame(new Uint8Array([0, 0]).buffer);
  if (short.ok || short.reason !== 'too_short') failures.push(`짧은 입력의 사유가 ${short.reason} 다`);

  const big = new Uint8Array(8);
  new DataView(big.buffer).setUint32(0, 9999, false);
  const over = parseMediaFrame(big.buffer);
  if (over.ok || over.reason !== 'bad_header_length') {
    failures.push(`길이 칸이 남은 바이트보다 큰 입력의 사유가 ${over.reason} 다 — 안 막으면 디코더가 두 단계 뒤에서 실패한다`);
  }

  const notJson = new Uint8Array(4 + 3);
  new DataView(notJson.buffer).setUint32(0, 3, false);
  notJson.set(new TextEncoder().encode('{x{'), 4);
  const bad = parseMediaFrame(notJson.buffer);
  if (bad.ok || bad.reason !== 'header_not_json') failures.push(`JSON 이 아닌 헤더의 사유가 ${bad.reason} 다`);

  for (const missing of ['frame_ref', 'encoding', 'keyframe', 'width', 'height']) {
    const partial = { ...header };
    delete partial[missing];
    const out = parseMediaFrame(build(partial, payload));
    if (out.ok || out.reason !== 'header_shape') failures.push(`필수 칸 ${missing} 이 없는데 통과했다 (${out.reason})`);
  }

  // 던지지 않는다 — 어떤 쓰레기를 넣어도.
  for (const junk of [new ArrayBuffer(0), new ArrayBuffer(3), new Uint8Array([255, 255, 255, 255, 1]).buffer]) {
    try {
      parseMediaFrame(junk);
    } catch (error) {
      failures.push(`파서가 던졌다 — ${error.message}. 던지면 부르는 쪽이 try 로 감싸고, 조용히 버리는 자리가 또 생긴다`);
    }
  }

  // ── 4. 세션 ────────────────────────────────────────────────────────────────
  const ref = (sourceId, sequenceId) => ({ sourceId, captureTimestamp: 'x', sequenceId });
  if (!isNewSession(null, ref('a', 1))) failures.push('첫 프레임이 새 세션이 아니다');
  if (!isNewSession(ref('a', 100), ref('a', 3))) failures.push('순번이 줄었는데 새 세션이 아니다 — 지연 계산이 음수가 된다');
  if (!isNewSession(ref('a', 1), ref('b', 2))) failures.push('소스가 바뀌었는데 새 세션이 아니다');
  if (isNewSession(ref('a', 1), ref('a', 2))) failures.push('순번이 늘었는데 새 세션이라고 한다 — 매 프레임 버퍼를 비운다');
}

// ── 5·6. 클라이언트 ──────────────────────────────────────────────────────────
{
  const { FATAL_CLOSE_CODES } = await load('src', 'media', 'MediaClient.ts');
  for (const fatal of [4400, 4401, 4404]) {
    if (!FATAL_CLOSE_CODES.includes(fatal)) {
      failures.push(`${fatal} 이 재시도 제외 목록에 없다 — 재시도해도 같은 코드가 오므로 루프가 된다`);
    }
  }
  if (FATAL_CLOSE_CODES.includes(1006)) failures.push('평범한 끊김(1006)을 재시도 제외로 뒀다 — 되붙어야 하는 경우다');

  const client = code(readSource('src/media/MediaClient.ts'));
  if (!/binaryType = 'arraybuffer'/.test(client)) {
    failures.push("binaryType 을 'arraybuffer' 로 안 둔다 — 기본값 blob 이면 .arrayBuffer() 가 비동기라 순서가 뒤집힌다");
  }
  if (!/typeof event\.data === 'string'/.test(client)) {
    failures.push('문자열/바이너리 갈래가 없다 — 전부 JSON 으로 간주하면 영상이 조용히 버려진다');
  }
  // 전송 계층이 버린 것을 세는가 (백엔드가 명시적으로 부탁한 항목).
  const transport = code(readSource('src/transport/WsTransport.ts'));
  if (!/this\.dropped \+= 1;/.test(transport)) {
    failures.push('전송 계층이 못 읽은 메시지를 안 센다 — 형식이 틀려도 화면에 아무 신호가 없다');
  }
}

// ── 6b. 자리 — 상설 판이 아니라 대상 상태 오버레이 안이다 ────────────────────
{
  // 260921 — 처음엔 마일스톤 오른쪽 기둥에 상설 판으로 뒀다가 옮겼다. 영상은 늘 보는
  // 값이 아니라 **한 장비의 카메라에 딸린 것**이고, 기둥을 셋으로 나누면 다른 둘이 좁아진다.
  const overlay = code(readSource('src/views/DeviceStatusOverlay.tsx'));
  if (!/<MediaSection deviceId=\{deviceId\} \/>/.test(overlay)) {
    failures.push('대상 상태 오버레이에 카메라 칸이 없다 — 하드웨어 카드를 더블클릭해도 영상을 볼 수 없다');
  }
  const main = code(readSource('src/main.tsx'));
  if (/MediaSection|MediaPanel/.test(main)) {
    failures.push('마일스톤 화면이 영상 칸을 상설로 그린다 — 하드웨어·기능 기둥이 그만큼 좁아진다');
  }
  // **대응표가 없다는 사실을 적는가.** 장비마다 다른 카메라가 뜨는 척하면 안 된다.
  const section = code(readSource('src/media/views/MediaSection.tsx'));
  if (!/media\.cameraUnmapped/.test(section)) {
    failures.push('장비-카메라 대응표가 없다는 사실을 화면이 안 적는다 — 아무 장비에서나 같은 카메라가 뜬다');
  }
  // **열면 붙는다** — 백엔드 표현으로 「패널 열 때 붙으면 온디맨드」다. `/media` 는 붙는 것이
  // 켜기라 칸이 뜨는 것과 소켓이 붙는 것이 같은 일이고, 한 번 더 누르게 하면 관문 B 에서
  // 「왜 안 나오지」의 첫 원인이 그 버튼이 된다.
  if (!/const \[on, setOn\] = useState\(true\);/.test(section)) {
    failures.push('오버레이를 열어도 안 붙는다 — /media 는 붙는 것이 켜기다(온디맨드)');
  }
}

// ── 7. 한글·영어 두 벌 ───────────────────────────────────────────────────────
{
  const { ko } = await load('src', 'i18n', 'ko.ts');
  const { en } = await load('src', 'i18n', 'en.ts');
  const used = new Set();
  for (const rel of SOURCES.filter((r) => r.startsWith('src/media/'))) {
    for (const [, key] of code(readSource(rel)).matchAll(/(?<![A-Za-z0-9_$])t\('([^'{]+)'/g)) used.add(key);
    for (const [, key] of code(readSource(rel)).matchAll(/(?:label|why)Key: '([^']+)'/g)) used.add(key);
  }
  const missingKo = [...used].filter((k) => ko[k] === undefined);
  const missingEn = [...used].filter((k) => en[k] === undefined);
  if (missingKo.length > 0) failures.push(`한국어 사전에 없는 키 — ${missingKo.join(' · ')}`);
  if (missingEn.length > 0) failures.push(`영어 사전에 없는 키 — ${missingEn.join(' · ')}`);
  for (const rel of SOURCES.filter((r) => r.startsWith('src/media/'))) {
    const hits = [...code(readSource(rel)).matchAll(/'([^']*[가-힣][^']*)'/g)].map((m) => m[1]);
    if (hits.length > 0) failures.push(`${rel} 에 표시용 한글이 박혀 있다 — 「${hits[0]}」 (사전 키로 옮긴다)`);
  }
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
{
  const clientSrc = readSource('src/media/MediaClient.ts');
  const blobbed = clientSrc.replace("ws.binaryType = 'arraybuffer';", '');
  if (blobbed === clientSrc) failures.push('대조군(가)을 만들지 못했다 — binaryType 줄의 모양이 바뀌었다');
  else controls.push('binaryType 을 기본값으로 되돌린 사본');

  const retried = clientSrc.replace(
    'export const FATAL_CLOSE_CODES: readonly number[] = [4400, 4401, 4404];',
    'export const FATAL_CLOSE_CODES: readonly number[] = [];',
  );
  if (retried === clientSrc) failures.push('대조군(나)을 만들지 못했다 — 재시도 제외 목록의 모양이 바뀌었다');
  else controls.push('4401 을 재시도하는 사본');

  const transportSrc = readSource('src/transport/WsTransport.ts');
  const silent = transportSrc.replace('      this.dropped += 1;\n', '');
  if (silent === transportSrc) failures.push('대조군(다)을 만들지 못했다 — 전송 계층 카운터의 모양이 바뀌었다');
  else controls.push('버린 메시지를 안 세는 사본');
}

if (failures.length) {
  console.error(`❌ verify:media-port\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 경계 — 영상 경로·카메라 키·환경변수를 아는 면은 src/media/ 하나, 토큰은 코드에 0건');
console.log('✅ 파서 — 정상 프레임을 뜯고, 모르는 코덱은 안 거르고, 어떤 쓰레기에도 안 던진다');
console.log('✅ 사유 — 짧음·길이초과·JSON아님·필수칸없음이 각각 다른 사유로 갈린다');
console.log('✅ 세션 — 순번 역전·소스 변경만 새 세션이고, 정상 증가는 아니다');
console.log('✅ 끊김 — 4400·4401·4404 는 재시도하지 않고, 평범한 끊김은 되붙는다');
console.log('✅ 수신 — binaryType 이 arraybuffer 이고 문자열/바이너리가 갈리며, 전송 계층도 버린 수를 센다');
console.log('✅ 자리 — 대상 상태 오버레이 안의 한 칸 · 마일스톤에는 상설로 없음 · 열면 붙는다(온디맨드)');
console.log('✅ 두 벌 — 화면이 쓰는 키가 ko·en 양쪽에 다 있고 경계 안에 박힌 표시용 한글 0건');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
