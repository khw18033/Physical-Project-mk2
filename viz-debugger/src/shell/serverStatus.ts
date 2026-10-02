/**
 * src/shell/serverStatus.ts (261002 신설 — 서버 칸에 서버 이름 · 자원 상태)
 *
 * **서버 칸이 「백엔드 서버」 대신 그 서버의 이름을 적고, 읽을 수 있으면 CPU · 메모리를 적는다.**
 *
 * ## 이름 — 기계가 스스로 밝힌 것만
 *
 * 게이트웨이 소켓(`/state`)은 서버 자신에 대해 아무것도 안 준다(장비 봉투만 온다). 그래서 이름은 **같은 기계의 다른 창구**가
 * 밝힌 것을 쓴다. 지어내지 않는다 — 어느 창구에서 왔는지도 같이 든다(`nameFrom`).
 *
 *   1. 지표(`node_uname_info` 의 `nodename`) — 아래 지표 주소가 node_exporter 면
 *   2. 추론 스트림 서버 `/health` 의 `host` — 게이트웨이와 **호스트가 같은** 포트가 연결 관리에 있으면
 *      (261002 실측 — 백엔드 `100.102.8.102:8765` 와 추론 서버 `100.102.8.102:10001` 은 한 기계이고 `host: sysai-server2`)
 *   3. 둘 다 없으면 null — 칸은 주소(호스트:포트)를 적는다
 *
 * ## 자원 — 지표 주소가 있을 때만
 *
 * 연결 관리 게이트웨이의 「서버 지표 주소」 칸(`gateway.metrics`)이 원천이다. 비어 있으면 **게이트웨이 호스트의 9100**
 * (node_exporter 기본 포트)을 한 번 두드려 본다. Prometheus 글자 형식만 읽고 `node_*` 지표에서 CPU · 메모리 · 부하 · 디스크
 * · 가동 시간을 뽑는다. CPU 사용률은 **두 번 받은 누계의 차이**다 — 첫 번은 「재는 중」이다.
 *
 * 261002 실측 — 그 서버의 9100 은 node_exporter 가 아니라 Pushgateway 이고(`node_*` 없음), Prometheus(9090)는 테일넷에서
 * 안 닿는다. 그래서 지금은 자원이 **안 나오는 것이 맞다** — 칸은 그 사유를 그대로 적는다. 서버 쪽에 node_exporter 가
 * 뜨면(또는 그 주소를 칸에 넣으면) 코드를 안 고치고 나온다.
 *
 * 지표 서버도 CORS 를 안 열므로 개발 서버 창구(`scripts/server-metrics-relay.mjs`)를 지난다.
 */

import { useSyncExternalStore } from 'react';
import { t } from '../i18n/dict.ts';
import { connectionAddress, subscribeConnections } from '../shared/connections.ts';
import { fetchStreamHealth, visionBases, type FetchLike as VisionFetchLike } from '../vision/visionClient.ts';

/** 창구 — `scripts/server-metrics-relay.mjs` 의 `METRICS_RELAY_URL` 과 같아야 한다. */
const RELAY = '/server-metrics';
/** node_exporter 기본 포트. 지표 주소 칸이 비었을 때만 쓴다. */
export const NODE_EXPORTER_PORT = 9100;
export const SERVER_STATUS_POLL_MS = 10_000;
/** 이름을 추론 서버에 다시 묻는 주기 — 이름은 잘 안 바뀐다. */
const NAME_REFRESH_MS = 60_000;

export type MetricSample = { name: string; labels: Readonly<Record<string, string>>; value: number };

/** Prometheus 글자 형식 한 덩어리 → 표본들. 모르는 줄은 버린다(던지지 않는다). **순수 함수.** */
export function parsePrometheusText(text: string): MetricSample[] {
  const out: MetricSample[] = [];
  for (const raw of text.split('\n')) {
    const lineText = raw.trim();
    if (lineText === '' || lineText.startsWith('#')) continue;
    const match = /^([A-Za-z_:][A-Za-z0-9_:]*)(\{(.*)\})?\s+(\S+)/.exec(lineText);
    if (match === null) continue;
    const value = Number(match[4]);
    if (!Number.isFinite(value)) continue;
    const labels: Record<string, string> = {};
    if (match[3] !== undefined) {
      for (const pair of match[3].matchAll(/([A-Za-z_][A-Za-z0-9_]*)="((?:[^"\\]|\\.)*)"/g)) labels[pair[1]] = pair[2].replace(/\\(.)/g, '$1');
    }
    out.push({ name: match[1], labels, value });
  }
  return out;
}

export type CpuTotals = { idle: number; total: number };

export type ServerResources = {
  /** CPU 사용률(%). 두 번 받아야 생긴다. */
  cpuPct: number | null;
  cores: number | null;
  memUsedPct: number | null;
  memTotalBytes: number | null;
  load1: number | null;
  load5: number | null;
  load15: number | null;
  uptimeS: number | null;
  /** `/` 의 사용률(%). */
  diskUsedPct: number | null;
};

/**
 * node_exporter 표본 → 자원 요약과 CPU 누계. `node_*` 가 하나도 없으면 null(기계 지표가 아니다). **순수 함수.**
 * `previous` 는 앞 번 누계 — 있으면 그 차이로 CPU 사용률을 낸다.
 */
export function summarizeNode(samples: readonly MetricSample[], previous: CpuTotals | null): { resources: ServerResources; cpu: CpuTotals | null; nodename: string | null } | null {
  if (!samples.some((s) => s.name.startsWith('node_'))) return null;
  const one = (name: string, match: (labels: Readonly<Record<string, string>>) => boolean = () => true) =>
    samples.find((s) => s.name === name && match(s.labels))?.value ?? null;
  const cpuRows = samples.filter((s) => s.name === 'node_cpu_seconds_total');
  let cpu: CpuTotals | null = null;
  let cores: number | null = null;
  if (cpuRows.length > 0) {
    cpu = {
      idle: cpuRows.filter((s) => s.labels.mode === 'idle' || s.labels.mode === 'iowait').reduce((sum, s) => sum + s.value, 0),
      total: cpuRows.reduce((sum, s) => sum + s.value, 0),
    };
    cores = new Set(cpuRows.map((s) => s.labels.cpu)).size;
  }
  let cpuPct: number | null = null;
  if (cpu !== null && previous !== null && cpu.total > previous.total) {
    const busy = (cpu.total - previous.total) - (cpu.idle - previous.idle);
    cpuPct = Math.min(100, Math.max(0, (busy / (cpu.total - previous.total)) * 100));
  }
  const memTotal = one('node_memory_MemTotal_bytes');
  const memAvail = one('node_memory_MemAvailable_bytes');
  const root = (labels: Readonly<Record<string, string>>) => labels.mountpoint === '/';
  const fsSize = one('node_filesystem_size_bytes', root);
  const fsAvail = one('node_filesystem_avail_bytes', root);
  const now = one('node_time_seconds');
  const boot = one('node_boot_time_seconds');
  return {
    cpu,
    nodename: samples.find((s) => s.name === 'node_uname_info')?.labels.nodename || null,
    resources: {
      cpuPct,
      cores,
      memUsedPct: memTotal !== null && memAvail !== null && memTotal > 0 ? ((memTotal - memAvail) / memTotal) * 100 : null,
      memTotalBytes: memTotal,
      load1: one('node_load1'),
      load5: one('node_load5'),
      load15: one('node_load15'),
      uptimeS: now !== null && boot !== null ? Math.max(0, now - boot) : null,
      diskUsedPct: fsSize !== null && fsAvail !== null && fsSize > 0 ? ((fsSize - fsAvail) / fsSize) * 100 : null,
    },
  };
}

/** 게이트웨이 주소의 호스트. 주소가 아니면 null. */
export function gatewayHost(): string | null {
  try {
    const host = new URL(connectionAddress('gateway', 'ws').trim()).hostname;
    return host === '' ? null : host;
  } catch {
    return null;
  }
}

/** 읽을 지표 주소와 그것이 칸에 적힌 것인지(아니면 9100 짐작인지). 게이트웨이 주소도 없으면 null. */
export function serverMetricsTarget(): { url: string; auto: boolean } | null {
  const written = connectionAddress('gateway', 'metrics').trim();
  if (written !== '') return { url: written, auto: false };
  const host = gatewayHost();
  if (host === null) return null;
  return { url: `http://${host.includes(':') ? `[${host}]` : host}:${NODE_EXPORTER_PORT}/metrics`, auto: true };
}

/** 같은 기계의 추론 서버 포트 — 게이트웨이와 호스트가 같은 것. */
export function sameHostVisionBase(host: string | null, bases: readonly string[]): string | null {
  if (host === null) return null;
  return bases.find((base) => { try { return new URL(base).hostname === host; } catch { return false; } }) ?? null;
}

export type ServerStatus = {
  name: string | null;
  nameFrom: 'metrics' | 'vision' | null;
  metricsUrl: string | null;
  metricsAuto: boolean;
  resources: ServerResources | null;
  /** 자원을 못 읽은 사유. 읽었으면 null. */
  metricsError: string | null;
  checkedAtMs: number | null;
};

const EMPTY: ServerStatus = { name: null, nameFrom: null, metricsUrl: null, metricsAuto: false, resources: null, metricsError: null, checkedAtMs: null };
let status: ServerStatus = EMPTY;
const listeners = new Set<() => void>();
let previousCpu: { url: string; cpu: CpuTotals } | null = null;
let visionName: { host: string; name: string | null; atMs: number } | null = null;

function commit(next: ServerStatus): void {
  status = next;
  for (const listener of listeners) listener();
}

export function serverStatus(): ServerStatus {
  return status;
}

export function useServerStatus(): ServerStatus {
  return useSyncExternalStore((listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; }, serverStatus, serverStatus);
}

export type TextFetch = (url: string, init?: { signal?: AbortSignal }) => Promise<{
  ok: boolean; status: number; headers: { get(name: string): string | null }; text(): Promise<string>;
}>;

/** 지표 한 번. 창구 먼저 — 창구가 없는 서버면(헤더 없음) 직접 두드린다(대개 CORS 로 막힌다). */
export async function fetchMetricsText(url: string, fetcher: TextFetch = globalThis.fetch as unknown as TextFetch, timeoutMs = 5000): Promise<{ ok: true; text: string } | { ok: false; reason: string }> {
  const once = async (target: string): Promise<{ status: number; relayed: boolean; text: string } | { error: string }> => {
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), timeoutMs);
    try {
      const response = await fetcher(target, { signal: abort.signal });
      return { status: response.status, relayed: response.headers.get('X-Metrics-Relay') === '1', text: await response.text() };
    } catch (error) {
      return { error: error instanceof Error ? (error.name === 'AbortError' ? t('srvm.noAnswer', { sec: timeoutMs / 1000 }) : error.message) : String(error) };
    } finally {
      clearTimeout(timer);
    }
  };
  const settle = (got: { status: number; text: string }) => {
    if (got.status === 200) return { ok: true as const, text: got.text };
    let why = got.text.slice(0, 200);
    try { const said = JSON.parse(got.text) as { error?: unknown }; if (typeof said.error === 'string') why = said.error; } catch { /* 글자 그대로 */ }
    return { ok: false as const, reason: t('srvm.status', { status: got.status, why }) };
  };
  const viaRelay = await once(`${RELAY}?url=${encodeURIComponent(url)}`);
  if ('status' in viaRelay && viaRelay.relayed) return settle(viaRelay);
  const direct = await once(url);
  if ('error' in direct) return { ok: false, reason: t('srvm.directFailed', { why: direct.error }) };
  return settle(direct);
}

/** 한 번 읽어 저장소를 고친다. 검사가 직접 부른다. */
export async function refreshServerStatus(fetcher?: TextFetch, nowMs: () => number = Date.now, visionFetcher?: VisionFetchLike): Promise<void> {
  const target = serverMetricsTarget();
  let resources: ServerResources | null = null;
  let metricsError: string | null = null;
  let nodename: string | null = null;
  if (target === null) {
    metricsError = t('srvm.noGateway');
  } else {
    const got = await fetchMetricsText(target.url, fetcher);
    if (!got.ok) {
      metricsError = got.reason;
    } else {
      const summary = summarizeNode(parsePrometheusText(got.text), previousCpu?.url === target.url ? previousCpu.cpu : null);
      if (summary === null) {
        metricsError = t('srvm.notNode');
      } else {
        resources = summary.resources;
        nodename = summary.nodename;
        if (summary.cpu !== null) previousCpu = { url: target.url, cpu: summary.cpu };
      }
    }
  }

  // 이름 — 지표가 밝혔으면 그것, 아니면 같은 기계의 추론 서버.
  const host = gatewayHost();
  if (nodename === null && host !== null && (visionName === null || visionName.host !== host || nowMs() - visionName.atMs > NAME_REFRESH_MS)) {
    const base = sameHostVisionBase(host, visionBases());
    let name: string | null = null;
    if (base !== null) {
      const health = await fetchStreamHealth(base, visionFetcher);
      name = health.ok ? health.health.host : null;
    }
    visionName = { host, name, atMs: nowMs() };
  }
  const fromVision = visionName !== null && visionName.host === host ? visionName.name : null;
  commit({
    name: nodename ?? fromVision,
    nameFrom: nodename !== null ? 'metrics' : fromVision !== null ? 'vision' : null,
    metricsUrl: target?.url ?? null,
    metricsAuto: target?.auto ?? false,
    resources,
    metricsError,
    checkedAtMs: nowMs(),
  });
}

let holders = 0;
let timer: ReturnType<typeof setInterval> | null = null;
let offConnections: (() => void) | null = null;
let inFlight = false;

function tick(): void {
  if (inFlight) return;
  inFlight = true;
  void refreshServerStatus().finally(() => { inFlight = false; });
}

/** 서버 칸이 떠 있는 동안 붙잡는다. 돌려준 함수로 놓는다 — `useEffect` 의 정리 함수로 쓴다. */
export function holdServerStatus(): () => void {
  holders += 1;
  if (timer === null) {
    tick();
    timer = setInterval(tick, SERVER_STATUS_POLL_MS);
    // 게이트웨이 주소 · 지표 주소가 바뀌면 곧바로 다시 읽는다. 앞 누계는 버린다 — 다른 기계의 차이를 재면 안 된다.
    let last = `${connectionAddress('gateway', 'ws')}|${connectionAddress('gateway', 'metrics')}`;
    offConnections = subscribeConnections(() => {
      const now = `${connectionAddress('gateway', 'ws')}|${connectionAddress('gateway', 'metrics')}`;
      if (now === last) return;
      last = now;
      previousCpu = null;
      visionName = null;
      tick();
    });
  }
  return () => {
    holders = Math.max(0, holders - 1);
    if (holders === 0 && timer !== null) {
      clearInterval(timer);
      timer = null;
      offConnections?.();
      offConnections = null;
    }
  };
}

/** 검사가 부른다. */
export function resetServerStatus(): void {
  status = EMPTY;
  previousCpu = null;
  visionName = null;
  for (const listener of listeners) listener();
}
