/**
 * scripts/vision-redis-latest.mjs (261124 신설 — 객체 탐지 상태판 · 지정 탐지 대상)
 *
 * **data_stream Redis 의 `vision_stream:<소스>:<모델>` 마지막 한 건만 읽는다.** 쓰지 않는다.
 *
 * ## 왜 Redis 인가
 *
 * 지정 클래스 탐지(`targeted`)가 **무엇을 찾고 있는지**(`targets`)와 런처 프로필 판(`profile{label, version, scan}`)은
 * 비전 결과 한 건(`result` JSON)에 실려 있다(data_stream `vision_infer.py` · `a1e43f8`). 그런데 스트림 서버의 HTTP 창구
 * (`/vision/frame`)는 화면용 칸만 남기고 이것을 걸러 낸다(`view_result`). data_stream 은 고치지 않기로 했으므로
 * (261124 지시) 같은 값을 Redis 에서 직접 읽는다 — Redis 6380 은 테일넷 IP 에도 묶여 있다(배포 가이드 9장, 261124 사용자 확인).
 *
 * ## 무엇을 보내나
 *
 * 명령은 `XREVRANGE <키> + - COUNT 1` 하나뿐이다. 다른 명령을 보낼 길을 열지 않는다. 한 건에는 오버레이 JPEG(수십~수백 KB)가
 * 같이 들어 있어 필드를 골라 받을 수 없다 — 그래서 화면은 2초마다, `targeted` 가 살아 있는 포트에만 묻는다.
 * 돌려주는 것은 아래 `summarizeVisionEntry` 가 고른 작은 JSON 이다(그림 · 검출 상자는 빼고 라벨 수만).
 *
 * 순수 함수(`encodeCommand` · `parseResp` · `summarizeVisionEntry`)는 검사(`verify:detect-status`)가 그대로 부른다.
 */

import net from 'node:net';

/** 키 조각 — 소스 · 모델 이름. data_stream 이름표와 같은 모양만 받는다. */
export const KEY_PART = /^[A-Za-z0-9_-]{1,64}$/;
const MAX_REPLY = 16 * 1024 * 1024;

/** RESP 배열 명령. */
export function encodeCommand(args) {
  const parts = args.map((arg) => {
    const bytes = Buffer.from(String(arg), 'utf8');
    return Buffer.concat([Buffer.from(`$${bytes.length}\r\n`), bytes, Buffer.from('\r\n')]);
  });
  return Buffer.concat([Buffer.from(`*${args.length}\r\n`), ...parts]);
}

/**
 * RESP 하나를 뜯는다 → `[값, 다음 위치]`, 덜 왔으면 null. 벌크 문자열은 Buffer 로 둔다(JPEG 가 섞여 있다).
 * 오류 응답(`-ERR …`)은 `{ error }` 로 돌려준다.
 */
export function parseResp(buf, at = 0) {
  if (at >= buf.length) return null;
  const end = buf.indexOf('\r\n', at);
  if (end < 0) return null;
  const type = String.fromCharCode(buf[at]);
  const line = buf.toString('utf8', at + 1, end);
  if (type === '+') return [line, end + 2];
  if (type === '-') return [{ error: line }, end + 2];
  if (type === ':') return [Number(line), end + 2];
  if (type === '$') {
    const n = Number(line);
    if (n < 0) return [null, end + 2];
    if (buf.length < end + 2 + n + 2) return null;
    return [buf.subarray(end + 2, end + 2 + n), end + 4 + n];
  }
  if (type === '*') {
    const n = Number(line);
    if (n < 0) return [null, end + 2];
    const out = [];
    let next = end + 2;
    for (let i = 0; i < n; i += 1) {
      const got = parseResp(buf, next);
      if (got === null) return null;
      out.push(got[0]);
      next = got[1];
    }
    return [out, next];
  }
  throw new Error(`RESP 형식이 아닙니다 (${JSON.stringify(type)})`);
}

const strList = (value) => (Array.isArray(value) ? value.filter((v) => typeof v === 'string' && v !== '') : null);

/**
 * `XREVRANGE` 한 항목 `[id, [필드, 값, …]]` → 화면이 쓰는 작은 요약. 모양이 아니면 null.
 * `result` 가 JSON 이 아니면 `resultError` 를 적고 나머지는 비운다 — 지어내지 않는다.
 */
export function summarizeVisionEntry(entry) {
  if (!Array.isArray(entry) || entry.length !== 2 || !Array.isArray(entry[1])) return null;
  const id = Buffer.isBuffer(entry[0]) ? entry[0].toString('utf8') : String(entry[0]);
  const fields = {};
  for (let i = 0; i + 1 < entry[1].length; i += 2) {
    const name = Buffer.isBuffer(entry[1][i]) ? entry[1][i].toString('utf8') : String(entry[1][i]);
    fields[name] = entry[1][i + 1];
  }
  const ms = Number(id.split('-')[0]);
  const out = {
    id,
    atMs: Number.isFinite(ms) ? ms : null,
    model: null, stream: null, run: null, n: null, emittedAt: null,
    targets: null, targetsAll: null, targetScope: null, provisional: null, distance: null, profile: null, labels: null, resultError: null,
  };
  if (!Buffer.isBuffer(fields.result)) { out.resultError = 'result 칸이 없습니다'; return out; }
  let result;
  try { result = JSON.parse(fields.result.toString('utf8')); } catch { out.resultError = 'result 가 JSON 이 아닙니다'; return out; }
  if (result === null || typeof result !== 'object' || Array.isArray(result)) { out.resultError = 'result 가 사전이 아닙니다'; return out; }
  out.model = typeof result.model === 'string' ? result.model : null;
  out.stream = typeof result.stream === 'string' ? result.stream : null;
  out.run = typeof result.run === 'string' ? result.run : null;
  out.n = typeof result.n === 'number' ? result.n : null;
  out.emittedAt = typeof result.emitted_at === 'string' ? result.emitted_at : null;
  // **이 장비의 대상이 먼저다** (261126). 한 비전 프로세스가 여러 장비를 맡으면 `targets` · `provisional` 은 그 장비들의
  // 대상을 합친 목록이고, 장비마다 따로 준 대상은 `targets_device` 에 실린다 — 실측: go1(robot1) 에 person, pi12 에 chair 를
  // 주었더니 두 결과 모두 `targets: [person, chair]`, `targets_device` 만 각각 [person] · [chair] 였다.
  // 칸이 없으면(그 칸이 생기기 전 판 · 장비별 지정이 없는 장비) 예전처럼 `targets` 를 쓴다.
  // **빈 목록은 「찾는 대상 없음」이다** (261126) — data_stream 은 빈 목록이면 그 장비의 검출을 전부 거른다
  // (`vision_infer.py` `_detect_one`: `allow is not None` 이면 `name in allow` 만 남김, `fc2340b`). 전체 목록으로 내려가면 화면이 거짓이다.
  const all = strList(result.targets);
  const own = strList(result.targets_device);
  const byDevice = own !== null;
  out.targets = byDevice ? own : all;
  out.targetsAll = all;
  out.targetScope = byDevice ? 'device' : all !== null ? 'all' : null;
  const provisional = strList(result.provisional);
  out.provisional = byDevice && provisional !== null ? provisional.filter((name) => own.includes(name)) : provisional;
  out.distance = typeof result.distance === 'boolean' ? result.distance : null;
  if (result.profile !== null && typeof result.profile === 'object' && !Array.isArray(result.profile)) {
    const p = result.profile;
    out.profile = {
      label: typeof p.label === 'string' ? p.label : null,
      version: typeof p.version === 'number' ? p.version : null,
      // 스캔 판 동안만 붙는다 — 판 번호(scan_id 문자열, vision_infer.py `cfg["_scan"] = meta["scan_id"]`).
      scanId: typeof p.scan === 'string' && p.scan !== '' ? p.scan : null,
    };
  }
  if (Array.isArray(result.detections)) {
    const labels = {};
    for (const det of result.detections) {
      const label = det !== null && typeof det === 'object' && typeof det.label === 'string' ? det.label : null;
      if (label !== null) labels[label] = (labels[label] ?? 0) + 1;
    }
    out.labels = labels;
  }
  return out;
}

/**
 * Redis 에 붙어 한 키의 마지막 한 건을 읽는다 → 요약(없으면 `{ empty: true }`). 실패는 던진다.
 * `connect` 는 검사가 갈아 끼운다.
 */
export function readLatest({ host, port, key, timeoutMs = 3000, connect = net.connect }) {
  return new Promise((resolve, reject) => {
    const socket = connect({ host, port });
    let buf = Buffer.alloc(0);
    let settled = false;
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      if (error) reject(error); else resolve(value);
    };
    const timer = setTimeout(() => finish(new Error(`${timeoutMs / 1000}초 안에 Redis 가 답하지 않았습니다`)), timeoutMs);
    socket.on('connect', () => socket.write(encodeCommand(['XREVRANGE', key, '+', '-', 'COUNT', '1'])));
    socket.on('error', (error) => finish(error));
    socket.on('close', () => finish(new Error('Redis 가 답 없이 닫았습니다')));
    socket.on('data', (chunk) => {
      buf = Buffer.concat([buf, chunk]);
      if (buf.length > MAX_REPLY) { finish(new Error('Redis 답이 너무 큽니다')); return; }
      let got;
      try { got = parseResp(buf); } catch (error) { finish(error); return; }
      if (got === null) return;
      const [value] = got;
      if (value !== null && typeof value === 'object' && !Array.isArray(value) && 'error' in value) { finish(new Error(`Redis: ${value.error}`)); return; }
      if (!Array.isArray(value) || value.length === 0) { finish(null, { empty: true }); return; }
      const summary = summarizeVisionEntry(value[0]);
      if (summary === null) finish(new Error('XREVRANGE 답의 모양이 아닙니다'));
      else finish(null, summary);
    });
  });
}
