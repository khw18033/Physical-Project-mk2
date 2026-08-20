/**
 * mock-gateway/server.ts
 *
 * 목 게이트웨이 진입점. **별도 프로세스**로 도는 WebSocket 서버다.
 *
 * 목 데이터를 브라우저 안에 두지 않는 이유: 진짜 백엔드 게이트웨이가 나왔을 때
 * **접속 주소만 바꿔** 붙일 수 있어야 하기 때문이다. 브라우저 안의 가짜 데이터는
 * 옮길 때 전부 버려지고, 그 사이 화면 코드가 "값이 항상 즉시 있다"는 가정에 물든다.
 *
 * 한 포트에서 둘을 서빙한다.
 *   - HTTP : GET /registry, GET /scenarios, POST /scenario/:name, GET /health
 *   - WS   : 구독 · 데이터 푸시 · 역할 조회 · 시나리오 트리거
 */

import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { WebSocketServer } from 'ws';

import { INTERVALS, PLACEHOLDERS, SCALE_ASSUMPTIONS, SERVER, THRESHOLDS } from './config.ts';
import { Hub, loadRegistry, type ClientConn } from './hub.ts';
import { createFleet } from './devices.ts';
import { CommandEngine } from './commands.ts';
import { PlanEngine } from './plans.ts';
import { VisionEmitter } from './vision.ts';
import { SCENARIOS, runScenario } from './scenarios.ts';
import type { ClientMessage, CommandRequest, ScopeSpec, Selector } from './protocol.ts';

const HERE = dirname(fileURLToPath(import.meta.url));
const PROTOCOL_VERSION = 'mock-gateway/0.2';

/** 감사 조회가 몇 번 들어왔는지. 주기 폴링이 없다는 것을 숫자로 확인하기 위한 계측값. */
let auditQueryCount = 0;

const hub = new Hub(loadRegistry());
const fleet = createFleet(hub);
const commands = new CommandEngine(hub);
const plans = new PlanEngine(hub);
const vision = new VisionEmitter(hub, 'camera-02');

// 명령 시작·종료 시 액추에이터 발행 주기를 대기 1초 <-> 동작 중 100ms 로 전환한다.
commands.onActivityChange = (entity) => fleet.actuators.get(entity)?.rearm();
for (const actuator of fleet.actuators.values()) actuator.attach(commands);

hub.startLoops();

// 기동 시 계획 하나를 승인 대기로 올려 둔다 — 화면을 열자마자 승인 절차를 볼 수 있게.
plans.propose();

// ── HTTP ─────────────────────────────────────────────────────────────────────

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
  'Access-Control-Allow-Headers': 'content-type',
};

const http = createServer((req, res) => {
  const url = new URL(req.url ?? '/', 'http://' + (req.headers.host ?? 'localhost'));
  const json = (code: number, body: unknown) => {
    res.writeHead(code, { 'content-type': 'application/json; charset=utf-8', ...CORS });
    res.end(JSON.stringify(body, null, 2));
  };

  if (req.method === 'OPTIONS') {
    res.writeHead(204, CORS);
    res.end();
    return;
  }

  // VZ-I-03 / REQ-304·305 — 레지스트리는 정적 파일을 그대로 서빙한다.
  // 값을 발행하지 않는 미배포 대상(robot-03)도 여기에 반드시 있어야 화면이 그릴 수 있다.
  if (url.pathname === '/registry') {
    res.writeHead(200, { 'content-type': 'application/json; charset=utf-8', ...CORS });
    res.end(readFileSync(join(HERE, 'registry.json'), 'utf-8'));
    return;
  }

  if (url.pathname === '/scenarios') {
    json(200, SCENARIOS.map((s) => ({ name: s.name, title: s.title, expect: s.expect })));
    return;
  }

  if (url.pathname.startsWith('/scenario/') && (req.method === 'POST' || req.method === 'GET')) {
    const name = decodeURIComponent(url.pathname.slice('/scenario/'.length));
    const result = runScenario(name, { hub, fleet, commands, plans, vision });
    log((result.ok ? '시나리오 재생' : '시나리오 실패') + ' — ' + name + ': ' + result.message);
    json(result.ok ? 200 : 404, result);
    return;
  }

  /**
   * VZ-I-05 — 감사 이력 조회.
   * **패널을 열 때만** 부르는 경로다. 감사는 확정된 과거 기록이라 폴링해도 새 값이 없고,
   * 진행 중인 명령의 변화는 command_result 푸시로 이미 도달한다.
   */
  if (url.pathname === '/audit') {
    const entity = url.searchParams.get('entity');
    const limit = Number(url.searchParams.get('limit') ?? 20);
    auditQueryCount += 1;
    json(200, {
      records: commands.queryAudit(entity, Math.min(100, Math.max(1, limit))),
      // 주기 폴링이 없는지 검증할 때 쓰는 계측값. 실제 계약에는 없다.
      _query_count: auditQueryCount,
    });
    return;
  }

  /**
   * 액션 카탈로그. 화면이 액션 어휘를 하드코딩하지 않게 서버가 내려준다 —
   * 장비가 바뀌어도 화면을 고치지 않는다는 VZ-O-01의 전제가 여기서 성립한다.
   */
  if (url.pathname === '/actions') {
    const entity = url.searchParams.get('entity') ?? '';
    json(200, { entity, actions: commands.actionsFor(entity) });
    return;
  }

  if (url.pathname === '/health') {
    json(200, {
      ok: true,
      server_time: new Date().toISOString(),
      protocol: PROTOCOL_VERSION,
      clients: hub.clientCount,
      entities: hub.runtime.size,
      audit_query_count: auditQueryCount,
      vision: { open: vision.isOpen, config: vision.describe() },
      stale_threshold_ms: THRESHOLDS.STALE_MS,
      scale_assumptions: SCALE_ASSUMPTIONS,
    });
    return;
  }

  json(404, {
    error: 'not found',
    paths: ['/registry', '/scenarios', '/scenario/:name', '/audit', '/actions', '/health'],
  });
});

// ── WebSocket ────────────────────────────────────────────────────────────────

const wss = new WebSocketServer({ server: http });
let clientSeq = 0;

function isSelector(v: unknown): v is Selector {
  if (typeof v !== 'object' || v === null) return false;
  const s = v as Record<string, unknown>;
  return typeof s.entity === 'string' && typeof s.node === 'string' && typeof s.channel === 'string';
}

/** VZ-I-11 — 현 단계는 'all' 고정이지만, 값을 **버리지 않고** 그대로 되돌려 준다. */
function normalizeScope(v: unknown): ScopeSpec {
  if (v === 'all') return 'all';
  if (typeof v === 'object' && v !== null) return v as ScopeSpec;
  return PLACEHOLDERS.DEFAULT_SCOPE;
}

wss.on('connection', (ws) => {
  clientSeq += 1;
  const conn: ClientConn = {
    id: 'c' + clientSeq,
    subs: new Map(),
    send(msg) {
      if (ws.readyState === ws.OPEN) ws.send(JSON.stringify(msg));
    },
  };
  hub.addClient(conn);
  log('접속 ' + conn.id + ' (총 ' + hub.clientCount + ')');

  conn.send({
    type: 'hello',
    server_time: new Date().toISOString(),
    // 클라이언트는 이 값을 **표시에만** 쓴다. stale 판정 자체는 서버가 이미 끝냈다.
    stale_threshold_ms: THRESHOLDS.STALE_MS,
    protocol: PROTOCOL_VERSION,
  });

  ws.on('message', (raw) => {
    let msg: ClientMessage;
    try {
      msg = JSON.parse(String(raw)) as ClientMessage;
    } catch {
      conn.send({ type: 'error', message: 'JSON 파싱 실패' });
      return;
    }

    switch (msg.type) {
      case 'subscribe': {
        if (!isSelector(msg.selector)) {
          conn.send({ type: 'error', message: '구독은 계약 축 {entity, node, channel}로 표현해야 한다' });
          return;
        }
        const scope = normalizeScope(msg.scope);
        // 구독 즉시 최신값 1회 푸시 (VZ-I-02) — 없으면 평시 센서는 최대 1분간 빈 화면이 된다.
        const snapshot = hub.subscribe(conn, msg.id, msg.selector, scope);
        conn.send({
          type: 'subscribed',
          id: msg.id,
          selector: msg.selector,
          scope,
          snapshot_count: snapshot,
        });
        log(
          '구독 ' + conn.id + '/' + msg.id + ' ' + JSON.stringify(msg.selector) +
          ' scope=' + JSON.stringify(scope) + ' → 스냅샷 ' + snapshot + '건',
        );
        return;
      }
      case 'unsubscribe':
        hub.unsubscribe(conn, msg.id);
        conn.send({ type: 'unsubscribed', id: msg.id });
        return;
      case 'command': {
        const cmd = msg.command as CommandRequest | undefined;
        if (!cmd || typeof cmd.command_id !== 'string' || typeof cmd.entity !== 'string') {
          conn.send({ type: 'error', message: '명령에는 command_id와 entity가 필요하다 (REQ-909)' });
          return;
        }
        // **명령은 여기서 끝난다.** 실제 디바이스로 나가는 경로는 만들지 않는다.
        const outcome = commands.submit(cmd);
        conn.send({
          type: 'command_ack',
          command_id: cmd.command_id,
          accepted: outcome.accepted,
          reason_code: outcome.reasonCode,
          message: outcome.message,
        });
        log('명령 ' + cmd.entity + '/' + cmd.action + ' (' + cmd.command_id + ') → ' + outcome.message);
        return;
      }
      case 'plan_decision': {
        // VZ-U-07 — **승인 전에는 계획이 실행되지 않는다.** 판정은 서버가 소유한다.
        const outcome = plans.decide(msg.plan_id, msg.decision, msg.reason);
        conn.send({ type: 'plan_decision', plan_id: msg.plan_id, accepted: outcome.ok, message: outcome.message });
        log('계획 ' + msg.plan_id + ' ' + msg.decision + ' → ' + outcome.message);
        return;
      }
      case 'video': {
        // VZ-I-06 — **열린 패널만** 프레임을 받는다.
        // 전 카메라 상시 재생은 무선 대역폭과 브라우저 디코딩을 동시에 낭비한다.
        vision.setOpen(msg.open);
        log('영상 패널 ' + msg.entity + ' ' + (msg.open ? '열림' : '닫힘') + ' · ' + vision.describe());
        return;
      }
      case 'role':
        // VZ-C-04 — 권한 범위(scope)는 이번 범위 밖이지만 **응답 형태에 자리만** 둔다.
        conn.send({ type: 'role', role: PLACEHOLDERS.ROLE, scope: [...PLACEHOLDERS.ROLE_SCOPE] });
        return;
      case 'scenario': {
        const result = runScenario(msg.name, { hub, fleet, commands, plans, vision });
        conn.send({ type: 'scenario', name: msg.name, accepted: result.ok, message: result.message });
        log('시나리오 ' + msg.name + ': ' + result.message);
        return;
      }
      case 'ping':
        conn.send({ type: 'pong', t: msg.t, server_time: new Date().toISOString() });
        return;
      default:
        conn.send({ type: 'error', message: '알 수 없는 메시지 타입' });
    }
  });

  ws.on('close', () => {
    hub.removeClient(conn);
    log('종료 ' + conn.id + ' (총 ' + hub.clientCount + ')');
  });
});

function log(line: string): void {
  process.stdout.write('[mock-gateway] ' + new Date().toISOString() + ' ' + line + '\n');
}

http.listen(SERVER.PORT, SERVER.HOST, () => {
  const base = 'http://' + SERVER.HOST + ':' + SERVER.PORT;
  log('기동 — WS ws://' + SERVER.HOST + ':' + SERVER.PORT + ' / 레지스트리 ' + base + '/registry');
  log(
    '규모 가정(VZ-C-05) 구역 ' + SCALE_ASSUMPTIONS.ZONE_COUNT +
    ' · 장치 상한 ' + SCALE_ASSUMPTIONS.MAX_ENTITIES +
    ' · 동시 사용자 ' + SCALE_ASSUMPTIONS.CONCURRENT_OPERATORS +
    ' / 등록 대상 ' + hub.runtime.size + '개',
  );
  log(
    'stale 임계 ' + THRESHOLDS.STALE_MS + 'ms · 재판정 ' + INTERVALS.AVAILABILITY_SWEEP_MS +
    'ms · 상태 정기 발행 ' + INTERVALS.ZONE_STATE_REFRESH_MS + 'ms',
  );
  log('시나리오: ' + SCENARIOS.map((s) => s.name).join(', '));
});

for (const sig of ['SIGINT', 'SIGTERM'] as const) {
  process.on(sig, () => {
    log('종료 신호 수신 — 정리 중');
    fleet.stopAll();
    wss.close();
    http.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 500);
  });
}
