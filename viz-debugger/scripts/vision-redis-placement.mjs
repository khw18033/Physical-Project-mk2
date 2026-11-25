/**
 * scripts/vision-redis-placement.mjs (261125 신설 — 객체 탐지 상태판 · 모델 실행 장치)
 *
 * **data_stream 오케스트레이터의 배치표와 노드 정보를 Redis 스트림 두 개에서 읽는다.** 쓰지 않는다.
 *
 *   orchestration_stream  (orch/1)  `planned` 기록의 `plan` = 배치표. `gpu_units[] = {unit, node, models, sources, fps_cap, need_mb, need_basis}`
 *   node_resource_stream  (node/1)  노드마다 role · source(k3s | local) · 사용량 · gpu, `added`/`baseline` 일 때만 `baseline`(하드웨어)
 *
 * 둘 다 data_stream `ds_resources/streams.py`(a9ce9df) 의 계약이다. 가시화는 이 스트림을 **읽기만** 한다(그쪽 계획 §1-4).
 *
 * ## 261125 사용자 결정
 *
 * 1. 배치표는 받으면 화면이 저장해 그대로 쓴다. 바뀌면 data_stream 이 `planned` 를 처음부터 다시 보내므로 **가장 최근
 *    `planned` 하나**만 돌려주면 된다 — 이 창구는 그 한 건을 고르기만 하고, 저장 · 갈아 끼우기는 화면(`placement.ts`)이 한다.
 * 2. 배치표에 없는 모델은 data_stream 기기에서 도는 것으로 **확정**한다(추정으로 적지 않는다) — 그 판단도 화면이 한다.
 *    자원 배분을 끄면 런처가 비전을 data_stream 기기 WSL 에서 바로 띄운다(data_stream `launcher.ps1` · 서버 고정, host 키는 안 더함).
 * 3. (261125 data_stream 답 뒤 검토) 배치가 바뀔 때마다 스트림이 갱신되므로 화면도 따라간다 — 새 `planned` 는 교체, 실행 끝(`stopped`)은
 *    요청별 마지막 기록(`requests`)으로 저장본에 이어 붙인다. 신구는 기록 시각 `ts` 로 가린다.
 *
 * 명령은 `XREVRANGE <키> + - COUNT <n>` 하나뿐이고, 키는 위 두 스트림만 받는다. 순수 함수(`entryFields` ·
 * `summarizePlacement`)는 검사(`verify:detect-placement`)가 그대로 부른다.
 */

import net from 'node:net';
import { encodeCommand, parseResp } from './vision-redis-latest.mjs';

export const ORCH_STREAM = 'orchestration_stream';
export const NODE_STREAM = 'node_resource_stream';
/** 이 창구가 읽어도 되는 키 — 이것 말고는 보내지 않는다. */
export const PLACEMENT_KEYS = Object.freeze([ORCH_STREAM, NODE_STREAM]);
/** 오케스트레이션 기록은 실행 한 번에 열 건 안팎이고, 노드 기록은 잦지 않다(30초 · 10% 구간). */
export const ORCH_COUNT = 200;
export const NODE_COUNT = 300;
const MAX_REPLY = 4 * 1024 * 1024;

const text = (value) => (Buffer.isBuffer(value) ? value.toString('utf8') : value === null || value === undefined ? '' : String(value));

/** `XREVRANGE` 한 항목 `[id, [필드, 값, …]]` → `{ id, atMs, fields }`(값은 글자). 모양이 아니면 null. */
export function entryFields(entry) {
  if (!Array.isArray(entry) || entry.length !== 2 || !Array.isArray(entry[1])) return null;
  const id = text(entry[0]);
  const fields = {};
  for (let i = 0; i + 1 < entry[1].length; i += 2) fields[text(entry[1][i])] = text(entry[1][i + 1]);
  const ms = Number(id.split('-')[0]);
  return { id, atMs: Number.isFinite(ms) ? ms : null, fields };
}

const json = (raw) => { if (raw === '' || raw === undefined) return null; try { return JSON.parse(raw); } catch { return null; } };
const num = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const numText = (raw) => { if (raw === '' || raw === undefined) return null; const n = Number(raw); return Number.isFinite(n) ? n : null; };
const strs = (value) => (Array.isArray(value) ? value.filter((v) => typeof v === 'string' && v !== '').map(String) : []);
const obj = (value) => (value !== null && typeof value === 'object' && !Array.isArray(value) ? value : null);

function gpuUnit(raw) {
  const u = obj(raw);
  if (u === null || typeof u.node !== 'string') return null;
  const fps = {};
  for (const [source, value] of Object.entries(obj(u.fps_cap) ?? {})) if (num(value) !== null) fps[source] = value;
  return {
    unit: typeof u.unit === 'string' ? u.unit : null,
    node: u.node,
    models: strs(u.models),
    sources: strs(u.sources),
    fpsCap: fps,
    needMb: num(u.need_mb),
    needBasis: typeof u.need_basis === 'string' ? u.need_basis : null,
  };
}

function cpuUnit(raw) {
  const u = obj(raw);
  if (u === null || typeof u.node !== 'string' || typeof u.task !== 'string') return null;
  return { task: u.task, node: u.node, reason: typeof u.reason === 'string' ? u.reason : null };
}

/** 기록의 `ts`(ISO, +09:00) → ms. 없거나 깨졌으면 null. */
export function tsMs(raw) {
  if (typeof raw !== 'string' || raw === '') return null;
  const ms = Date.parse(raw);
  return Number.isFinite(ms) ? ms : null;
}

/**
 * 기록의 순서 — **기록이 난 시각(`ts`)이 먼저**, 없으면 스트림 ID 시각. Redis 가 꺼져 있던 동안의 기록은 data_stream 이 나중에
 * 몰아 쓰므로(outbox) 스트림 ID 는 늦게 붙는다 — ID 로 가리면 옛 `planned` 가 새것처럼 보인다(261125 검토 B).
 */
export function orderOf(item) {
  return item?.tsMs ?? item?.atMs ?? 0;
}

/** `planned` 한 건 → 배치표 요약. `plan` 이 JSON 이 아니면 null — 지어내지 않는다. */
function planOf(entry) {
  const f = entry.fields;
  const plan = obj(json(f.plan));
  if (plan === null) return null;
  return {
    eventId: f.event_id || entry.id,
    streamId: entry.id,
    atMs: entry.atMs,
    tsMs: tsMs(f.ts),
    ts: f.ts || null,
    requestId: f.request_id || null,
    mode: f.mode || null,
    basis: f.basis || null,
    algorithm: typeof plan.algorithm === 'string' ? plan.algorithm : null,
    gpuUnits: (Array.isArray(plan.gpu_units) ? plan.gpu_units : []).map(gpuUnit).filter((u) => u !== null),
    cpuUnits: (Array.isArray(plan.cpu_units) ? plan.cpu_units : []).map(cpuUnit).filter((u) => u !== null),
    refused: (Array.isArray(plan.refused) ? plan.refused : []).map(obj).filter((r) => r !== null)
      .map((r) => ({ item: typeof r.item === 'string' ? r.item : '', reason: typeof r.reason === 'string' ? r.reason : '' })),
  };
}

function gpuUsage(raw) {
  return (Array.isArray(raw) ? raw : []).map(obj).filter((g) => g !== null).map((g) => ({
    name: typeof g.name === 'string' ? g.name : null,
    memTotalMb: num(g.mem_total_mb),
    memUsedMb: num(g.mem_used_mb),
    utilPct: num(g.util_pct),
    tempC: num(g.temp_c),
  }));
}

function baselineOf(raw) {
  const b = obj(json(raw));
  if (b === null) return null;
  return {
    arch: typeof b.arch === 'string' ? b.arch : null,
    cpuCount: num(b.cpu_count),
    cpuModel: typeof b.cpu_model === 'string' ? b.cpu_model : null,
    memTotalMb: num(b.mem_total_mb),
    gpus: gpuUsage(b.gpus).map((g) => ({ name: g.name, memTotalMb: g.memTotalMb })),
  };
}

/**
 * 두 스트림의 최근 기록(**새것이 앞** — XREVRANGE 순서) → 화면이 쓰는 요약.
 *   plan      가장 새(`ts` 순) `planned` 하나(없으면 null) + 그 요청의 마지막 기록(`last`)
 *   requests  읽은 범위 안 요청마다 마지막 기록 — 화면이 **저장해 둔 배치표**의 끝남(`stopped`)을 따라가는 데 쓴다.
 *             배치표가 스트림에서 밀려난 뒤에 온 `stopped` 도 이것으로 이어 붙는다(261125 검토 A)
 *   nodes     노드마다 마지막 기록의 상태 · 사용량, 그리고 가장 최근 baseline(없으면 null)
 */
export function summarizePlacement(orchEntries, nodeEntries) {
  const orch = (orchEntries ?? []).map(entryFields).filter((e) => e !== null && e.fields.schema === 'orch/1');
  const requests = {};
  for (const entry of orch) {
    const rid = entry.fields.request_id;
    if (!rid) continue;
    const item = { event: entry.fields.event || null, reason: entry.fields.reason || null, ts: entry.fields.ts || null, tsMs: tsMs(entry.fields.ts), atMs: entry.atMs };
    if (requests[rid] === undefined || orderOf(item) > orderOf(requests[rid])) requests[rid] = item;
  }
  let plan = null;
  for (const entry of orch) {
    if (entry.fields.event !== 'planned') continue;
    const candidate = planOf(entry);
    if (candidate !== null && (plan === null || orderOf(candidate) > orderOf(plan))) plan = candidate;
  }
  // 같은 요청의 기록 가운데 가장 새것(planned 뒤의 applied · running · stopped · failed …).
  if (plan !== null) plan.last = (plan.requestId !== null ? requests[plan.requestId] : undefined) ?? null;

  const nodes = {};
  for (const entry of (nodeEntries ?? []).map(entryFields)) {
    if (entry === null || entry.fields.schema !== 'node/1' || !entry.fields.node) continue;
    const f = entry.fields;
    let node = nodes[f.node];
    if (node === undefined) {
      node = nodes[f.node] = {
        node: f.node,
        role: f.role || null,
        source: f.source || null,
        ready: f.ready === '1',
        change: f.change || null,
        cpuPct: numText(f.cpu_pct),
        memPct: numText(f.mem_pct),
        memMb: numText(f.mem_mb),
        tempC: numText(f.temp_c),
        gpu: gpuUsage(json(f.gpu)),
        serviceMode: f.service_mode || null,
        ts: f.ts || null,
        atMs: entry.atMs,
        baseline: null,
        baselineAtMs: null,
      };
    }
    if (node.baseline === null && f.baseline) {
      const baseline = baselineOf(f.baseline);
      if (baseline !== null) { node.baseline = baseline; node.baselineAtMs = entry.atMs; }
    }
  }
  return { plan, requests, nodes };
}

/**
 * Redis 에 붙어 한 스트림의 최근 `count` 건을 읽는다(새것이 앞). 키는 `PLACEMENT_KEYS` 만. 실패는 던진다.
 * `connect` 는 검사가 갈아 끼운다.
 */
export function readRecent({ host, port, key, count, timeoutMs = 3000, connect = net.connect }) {
  if (!PLACEMENT_KEYS.includes(key)) return Promise.reject(new Error(`읽을 수 없는 키입니다: ${key}`));
  const n = Math.max(1, Math.min(1000, Math.floor(Number(count) || 1)));
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
    socket.on('connect', () => socket.write(encodeCommand(['XREVRANGE', key, '+', '-', 'COUNT', String(n)])));
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
      // 키가 없으면(오케스트레이터를 한 번도 안 띄움) 빈 배열이다.
      finish(null, Array.isArray(value) ? value : []);
    });
  });
}

/** 두 스트림을 읽어 요약 하나. `reader` 는 검사가 갈아 끼운다. */
export async function readPlacement({ host, port, reader = readRecent }) {
  const orch = await reader({ host, port, key: ORCH_STREAM, count: ORCH_COUNT });
  const nodes = await reader({ host, port, key: NODE_STREAM, count: NODE_COUNT });
  return summarizePlacement(orch, nodes);
}
