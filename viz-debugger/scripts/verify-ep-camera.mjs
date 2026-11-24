// verify:ep-camera (261124 신설 — RoboMaster EP 카메라 분기)
//
// **EP 가 붙으면 관제 웹이 그 카메라 중계(H.264 WebSocket)를 찾아 그리는가.**
//
// HW `pi/robot/ep_camera.py`(bfec5dd)가 EP 카메라를 풀지 않고 WebSocket 으로 낸다. 와이어 포맷:
//   텍스트   {"t":"hello","codec":"avc1.…","cam":"ep-001"}
//   바이너리 [키프레임 1바이트][float64 BE 시각 ms][Annex-B]
// 주소는 노드가 `status.media` 로 알린다(port · path · 있으면 url).
//
// 보는 것 다섯.
//  1. 와이어 한 건을 뜯는다 — hello · 프레임 · 틀린 것은 사유(던지지 않는다)
//  2. 뜯은 것이 `/media` 와 같은 디코더 입력(MediaFrame, h264)이 된다
//  3. `status.media` 를 저장한다 — 자기소개 id 로, 주소 칸이 안 바뀌면 판 번호가 안 오른다
//  4. `robomaster_ep` 장비 → ws 주소(h264ws). 블록의 url > 브로커 호스트+port+path > 기본 8091 /ws. 위치는 front 하나
//  5. 받는 부품이 주소 꼴로 갈린다 — ws:// 는 `<img>` 가 아니라 소켓 캔버스
//
// 대조군 — available:false · 다른 transport 이면 주소를 안 짓는다, Go1 은 그대로 MJPEG 다, front 아닌 위치는 null.

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readSource } from './lib/source.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const read = (...p) => readSource(join(root, ...p));

const failures = [];
const controls = [];

const sock = await load('src', 'media', 'h264Socket.ts');
const state = await load('src', 'physical', 'deviceState.ts');
const identity = await load('src', 'physical', 'deviceIdentity.ts');
const connections = await load('src', 'shared', 'connections.ts');
const view = await load('src', 'physical', 'cameraView.ts');

function frameBytes(flag, ts, payload) {
  const buf = new ArrayBuffer(9 + payload.length);
  const dv = new DataView(buf);
  dv.setUint8(0, flag);
  dv.setFloat64(1, ts, false);
  new Uint8Array(buf, 9).set(payload);
  return buf;
}

// ── 1. 와이어 ──────────────────────────────────────────────────────────────────
{
  const hello = sock.parseH264Hello('{"t":"hello","codec":"avc1.4d6029","cam":"ep-001"}');
  if (!hello.ok || hello.hello.codec !== 'avc1.4d6029' || hello.hello.cam !== 'ep-001') failures.push(`hello 를 못 뜯는다 — ${JSON.stringify(hello)}`);
  for (const [text, why] of [['{"t":"bye"}', 't 가 hello 아님'], ['{"t":"hello"}', 'codec 없음'], ['not json', 'JSON 아님']]) {
    const r = sock.parseH264Hello(text);
    if (r.ok) failures.push(`${why} 를 hello 로 받았다`); else controls.push(`hello 거름(${why})`);
  }
  const idr = new Uint8Array([0, 0, 0, 1, 0x67, 0x4d, 0x60, 0x29, 0, 0, 0, 1, 0x65, 0x88]);
  const f = sock.parseH264Frame(frameBytes(1, 1795000000123.5, idr));
  if (!f.ok) failures.push(`프레임을 못 뜯는다 — ${f.reason}`);
  else {
    if (!f.frame.keyframe) failures.push('키프레임 표시를 놓쳤다');
    if (f.frame.timestampMs !== 1795000000123.5) failures.push(`시각이 틀렸다 — ${f.frame.timestampMs}(big-endian float64 여야 한다)`);
    if (f.frame.data.length !== idr.length || f.frame.data[4] !== 0x67) failures.push('페이로드가 헤더 9바이트 뒤에서 시작하지 않는다');
  }
  const delta = sock.parseH264Frame(frameBytes(0, 1, new Uint8Array([0, 0, 1, 0x41])));
  if (!delta.ok || delta.frame.keyframe) failures.push('델타 프레임을 키프레임으로 읽었다');
  for (const [buf, why] of [[new ArrayBuffer(4), 'too_short'], [frameBytes(7, 0, new Uint8Array([1])), 'bad_flag'], [frameBytes(1, 0, new Uint8Array([])), 'empty_payload']]) {
    let r;
    try { r = sock.parseH264Frame(buf); } catch (e) { failures.push(`${why} 에서 던졌다 — 사유를 값으로 돌려줘야 한다`); continue; }
    if (r.ok || r.reason !== why) failures.push(`${why} 가 사유로 안 나온다 — ${JSON.stringify(r)}`); else controls.push(`프레임 거름(${why})`);
  }

  // ── 2. 디코더 입력 ──────────────────────────────────────────────────────────
  if (f.ok && hello.ok) {
    const m = sock.toMediaFrame(f.frame, hello.hello, 7);
    if (m.header.encoding !== 'h264') failures.push('디코더 입력의 encoding 이 h264 가 아니다 — decode.ts 가 안 푼다');
    if (m.header.codec !== 'avc1.4d6029') failures.push('hello 의 코덱이 디코더로 안 넘어간다 — 상수로 박으면 실물에서 설정이 실패한다');
    if (!m.header.keyframe || m.header.frameRef.sequenceId !== 7) failures.push('키프레임 · 순번이 안 넘어간다');
    if (m.payload !== f.frame.data) failures.push('페이로드를 복사·변형했다');
  }
}

// ── 3. status.media 저장 ──────────────────────────────────────────────────────
const EP_BROKER = 'ws://pi1.example:9001/mqtt';
const GO1_BROKER = 'ws://pi7.example:9001/mqtt';
const epStatus = (media) => ({
  status: 'online',
  registration: { entity_id: 'ep-001', entity_type: 'robot', device_type: 'robomaster_ep' },
  media,
});
{
  state.resetDevices();
  identity.resetDeviceIdentity();
  const v0 = state.deviceMediaVersion();
  state.receiveDeviceMessage('zoneA/robot/ep-001/status', epStatus({
    streaming: false, available: true, source: 'ep_camera', codec: 'h264/websocket', transport: 'websocket', port: 8091, path: '/ws/ep-001', cam_key: 'ep-001', viewers: 0,
  }), EP_BROKER);
  const m = state.deviceMedia('ep-001');
  if (m === null) failures.push('status.media 가 저장되지 않았다');
  else if (m.port !== 8091 || m.path !== '/ws/ep-001' || m.transport !== 'websocket' || m.available !== true) failures.push(`media 를 잘못 뜯었다 — ${JSON.stringify(m)}`);
  const v1 = state.deviceMediaVersion();
  if (v1 === v0) failures.push('media 가 처음 왔는데 판 번호가 안 올랐다 — 카메라 칸이 주소를 다시 안 짓는다');
  // 보는 사람이 붙어 streaming · avc 만 바뀌었다 — 주소는 그대로이므로 소켓을 다시 붙이면 안 된다.
  state.receiveDeviceMessage('zoneA/robot/ep-001/status', epStatus({
    streaming: true, available: true, source: 'ep_camera', transport: 'websocket', port: 8091, path: '/ws/ep-001', avc: 'avc1.4d6029', viewers: 1,
  }), EP_BROKER);
  if (state.deviceMediaVersion() !== v1) failures.push('streaming 만 바뀌었는데 판 번호가 올랐다 — 볼 때마다 소켓이 다시 붙는다');
  else controls.push('streaming · avc 변화는 주소를 다시 안 짓는다');
  if (state.deviceMedia('ep-001')?.avc !== 'avc1.4d6029') failures.push('avc 는 판 번호와 별개로 갱신돼야 한다');
  // media 가 없는 status(Go1 옛 노드 · LWT)는 아는 블록을 지우지 않는다.
  state.receiveDeviceMessage('zoneA/robot/ep-001/status', { status: 'online' }, EP_BROKER);
  if (state.deviceMedia('ep-001') === null) failures.push('media 없는 status 가 블록을 지웠다');
}

// ── 4. 주소 짓기 ──────────────────────────────────────────────────────────────
{
  connections.saveConnections({ [connections.connectionKey('physical', 'ws')]: `${EP_BROKER}\n${GO1_BROKER}` });
  identity.noteDeviceReport('go1-001', 'robot', { status: 'online', registration: { entity_id: 'go1-001', entity_type: 'robot', device_type: 'go1_robot' } }, GO1_BROKER);

  const ep = view.directCameraUrl('ep-001', 'front');
  if (ep === null) failures.push('EP 의 카메라 주소를 못 짓는다');
  else {
    if (ep.kind !== 'h264ws') failures.push(`EP 카메라 종류가 ${ep.kind} — h264ws 여야 한다`);
    if (ep.url !== 'ws://pi1.example:8091/ws/ep-001') failures.push(`EP 주소가 ${ep.url} — 브로커 호스트 + 알린 port · path 여야 한다`);
  }
  const positions = view.directCameraPositions('ep-001');
  if (positions?.join('|') !== 'front') failures.push(`EP 위치 목록이 ${positions} — front 하나여야 한다(고르기 칸이 안 생긴다)`);
  if (view.directCameraUrl('ep-001', 'left') !== null) failures.push('EP 에 없는 위치(left)에서 주소가 나온다');
  else controls.push('EP 의 없는 위치는 null');

  // 노드가 공개 주소를 알면 그 url 이 이긴다.
  state.receiveDeviceMessage('zoneA/robot/ep-001/status', epStatus({ available: true, transport: 'websocket', port: 18091, path: '/ws/ep-001', url: 'ws://ep-proxy.example:18091/ws/ep-001' }), EP_BROKER);
  if (view.directCameraUrl('ep-001', 'front')?.url !== 'ws://ep-proxy.example:18091/ws/ep-001') failures.push('노드가 알린 url 을 안 쓴다');

  // 대조군 — 붙을 수 없다고 했으면 짓지 않는다.
  state.receiveDeviceMessage('zoneA/robot/ep-001/status', epStatus({ available: false, transport: 'websocket', port: 8091, path: '/ws/ep-001' }), EP_BROKER);
  if (view.directCameraUrl('ep-001', 'front') !== null) failures.push('available:false 인데 주소를 지었다');
  else controls.push('available:false → 주소 없음');
  // 대조군 — 옛 경로(ffmpeg RTP)를 알리면 이 길이 아니다.
  state.receiveDeviceMessage('zoneA/robot/ep-001/status', epStatus({ available: true, transport: 'rtp', codec: 'mjpeg/rtp', source: 'test' }), EP_BROKER);
  if (view.directCameraUrl('ep-001', 'front') !== null) failures.push('transport:rtp 인데 소켓 주소를 지었다');
  else controls.push('transport:rtp → 주소 없음');

  // 블록이 아직 안 왔다 — 중계 기본값(8091 · /ws)으로 붙는다.
  state.resetDevices();
  identity.noteDeviceReport('ep-001', 'robot', epStatus(undefined), EP_BROKER);
  identity.noteDeviceReport('go1-001', 'robot', { status: 'online', registration: { entity_id: 'go1-001', entity_type: 'robot', device_type: 'go1_robot' } }, GO1_BROKER);
  if (view.directCameraUrl('ep-001', 'front')?.url !== 'ws://pi1.example:8091/ws') failures.push(`블록 전 기본 주소가 ${view.directCameraUrl('ep-001', 'front')?.url}`);

  // 대조군 — Go1 은 그대로 MJPEG 다.
  const go1 = view.directCameraUrl('go1-001', 'front');
  if (go1?.kind !== 'stream' || go1.url !== 'http://pi7.example:8090/stream/1') failures.push(`Go1 길이 바뀌었다 — ${JSON.stringify(go1)}`);
  else controls.push('Go1 은 MJPEG 그대로');
  connections.saveConnections({});
}

// ── 5. 받는 부품 ──────────────────────────────────────────────────────────────
{
  if (!sock.isH264SocketUrl('ws://a:8091/ws') || !sock.isH264SocketUrl('WSS://a/ws')) failures.push('ws 주소를 소켓으로 안 가른다');
  if (sock.isH264SocketUrl('http://a:8090/stream/1') || sock.isH264SocketUrl('/drone-cam/frame?base=ws://x')) failures.push('http · 상대 주소를 소켓으로 가른다');
  else controls.push('MJPEG · 중계 주소는 <img> 그대로');
  const cam = read('src', 'media', 'views', 'DeviceCamera.tsx');
  if (!/export function DirectCamera\(props[^)]*\)\s*\{\s*return isH264SocketUrl\(props\.url\)/.test(cam)) failures.push('DirectCamera 가 주소 꼴로 갈리지 않는다');
  if (!/createDecoder\(\)/.test(cam.slice(cam.indexOf('function H264SocketCamera')))) failures.push('소켓 카메라가 /media 와 같은 디코더를 안 쓴다');
  if (!/typeof VideoDecoder === 'undefined'/.test(cam)) failures.push('WebCodecs 없는 브라우저를 안 가린다');
  const runner = read('src', 'physical', 'taskRunner.ts');
  if (!/source\.kind === 'h264ws'\) return socketCameraProbe/.test(runner)) failures.push('판 열기 카메라 확인이 소켓 길을 모른다 — fetch 로 ws 주소를 두드린다');
}

if (failures.length) {
  console.error('❌ verify:ep-camera');
  for (const f of failures) console.error('  - ' + f);
  process.exit(1);
}
console.log(`✅ verify:ep-camera — 와이어 · media 블록 · EP 주소 · 받는 부품 · 대조군 ${controls.length}건 (${controls.join(' · ')})`);
