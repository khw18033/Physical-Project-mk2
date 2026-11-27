#!/usr/bin/env node
/**
 * scripts/check-history-server.mjs (261119 신설 — 임무 이력 서버 적합성 검사)
 *
 * **서버가 규약대로 답하는지 본다.** 서버 담당이 자기 서버에 돌리는 검사다.
 * 이 파일 하나만 있으면 된다 — 저장소의 다른 파일을 안 읽는다. Node 18 이상.
 *
 *   node check-history-server.mjs http://<서버주소>:<포트>
 *
 * 규약: documents/협의/임무이력서버_요청_VZ_261119.md
 *
 * 검사용 판은 날짜 `000101` 아래에 쓴다(가시화 화면은 이 날짜를 목록에서 숨긴다). 지우지 않는다 —
 * 서버에는 지우는 창구가 없다(규약 §2). 여러 번 돌리면 검사 판이 그만큼 쌓인다.
 */

const base = (process.argv[2] ?? '').replace(/\/+$/, '');
if (!/^https?:\/\//.test(base)) {
  console.error('사용법: node check-history-server.mjs http://<서버주소>:<포트>');
  process.exit(2);
}
const API = `${base}/api/v1`;
const ORIGIN = 'http://viz-check.local:5173';

const results = [];
const check = (id, title, ok, detail = '') => results.push({ id, title, ok: Boolean(ok), detail });
const two = (n) => String(n).padStart(2, '0');
const now = new Date();
const DATE = '000101';
const tag = Math.random().toString(36).slice(2, 8);
const RUN = `${two(now.getHours())}${two(now.getMinutes())}${two(now.getSeconds())}_CONFORMANCE-${tag}`;
const RUN_CTL = `${two(now.getHours())}${two(now.getMinutes())}${two(now.getSeconds())}_CTL-check-${tag}`;
const RUN_NO_MISSION = `${two(now.getHours())}${two(now.getMinutes())}${two(now.getSeconds())}_ORPHAN-${tag}`;

async function call(method, path, body, headers = {}) {
  try {
    const response = await fetch(`${API}${path}`, { method, body, headers: { Origin: ORIGIN, ...headers } });
    const bytes = Buffer.from(await response.arrayBuffer());
    let json = null;
    try { json = JSON.parse(bytes.toString('utf8')); } catch { /* 그림 · 빈 본문 */ }
    return { status: response.status, headers: response.headers, bytes, json };
  } catch (error) {
    return { status: 0, headers: new Headers(), bytes: Buffer.alloc(0), json: null, error: error instanceof Error ? error.message : String(error) };
  }
}
const putJson = (date, run, file, doc) => call('PUT', `/runs/${date}/${encodeURIComponent(run)}/${file}`,
  typeof doc === 'string' ? doc : JSON.stringify(doc), { 'Content-Type': 'application/json' });

/** 가시화 기록기가 쓰는 것과 같은 모양의 mission.json (줄임). */
const mission = {
  schema: 'mission-record/2', missionId: `CONFORMANCE-${tag}`, label: '적합성 검사 — 한글 이름 보존',
  startedAtIso: now.toISOString(), updatedAtIso: now.toISOString(), endedAtIso: null, outcome: null,
  done: 1, of: 4, failedTaskId: null, reason: '', headSec: 12.5, robotDriven: true, testMode: true,
  imageCount: 1, path: null, pathFailure: null,
  endpoints: { robot: 'ws://example:9001' },
  view: { missionId: `CONFORMANCE-${tag}`, label: '적합성 검사', tasks: [{ id: 'T-A1', title: '첫 노드' }], milestones: [] },
};
const progress = { schema: 'mission-record/2', missionId: mission.missionId, headSec: 12.5, trace: [{ seq: 1, atSec: 0.5, nodeId: 'T-A1', status: 'running' }] };
// 가장 작은 올바른 JPEG 은 아니어도 된다 — 서버는 그림을 해석하지 않고 바이트를 그대로 돌려주면 된다.
const jpeg = Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), Buffer.from(`conformance-${tag}`), Buffer.from([0xff, 0xd9])]);

// ── 1. 서버 확인 ──────────────────────────────────────────────────────────────
{
  const health = await call('GET', '/health');
  check('H1', 'GET /api/v1/health 가 200', health.status === 200, health.error ?? `status ${health.status}`);
  check('H2', 'health 의 service 가 "mission-history"', health.json?.service === 'mission-history', JSON.stringify(health.json));
  check('H3', 'health 의 apiVersion 이 1', health.json?.apiVersion === 1, `apiVersion=${health.json?.apiVersion}`);
  check('H4', 'health 의 serverTime 이 ISO 시각', typeof health.json?.serverTime === 'string' && !Number.isNaN(Date.parse(health.json.serverTime)), String(health.json?.serverTime));
  check('C1', 'health 응답에 Access-Control-Allow-Origin', health.headers.get('access-control-allow-origin') !== null, String(health.headers.get('access-control-allow-origin')));
  if (health.status === 0) {
    print();
    console.error(`\n서버에 닿지 못했습니다: ${health.error}`);
    process.exit(1);
  }
}

// ── 2. CORS 사전 요청 ─────────────────────────────────────────────────────────
{
  const pre = await call('OPTIONS', `/runs/${DATE}/${RUN}/mission.json`, undefined, {
    'Access-Control-Request-Method': 'PUT', 'Access-Control-Request-Headers': 'content-type',
    'Access-Control-Request-Private-Network': 'true',
  });
  const methods = (pre.headers.get('access-control-allow-methods') ?? '').toUpperCase();
  const allowHeaders = (pre.headers.get('access-control-allow-headers') ?? '').toLowerCase();
  check('C2', 'OPTIONS 사전 요청이 2xx', pre.status >= 200 && pre.status < 300, `status ${pre.status}`);
  check('C3', '허용 메서드에 GET · PUT · POST', ['GET', 'PUT', 'POST'].every((m) => methods.includes(m)) || methods.includes('*'), methods);
  check('C4', '허용 머리에 Content-Type', allowHeaders.includes('content-type') || allowHeaders.includes('*'), allowHeaders);
  check('C5', 'Access-Control-Allow-Private-Network: true (권장)', pre.headers.get('access-control-allow-private-network') === 'true', String(pre.headers.get('access-control-allow-private-network')));
}

// ── 3. 쓰기 ───────────────────────────────────────────────────────────────────
{
  const p = await putJson(DATE, RUN, 'progress.json', progress);
  check('W1', 'progress.json PUT 이 200', p.status === 200, `status ${p.status} ${p.bytes.toString('utf8').slice(0, 120)}`);
  const m = await putJson(DATE, RUN, 'mission.json', { ...mission, label: '덮어쓰기 전' });
  check('W2', 'mission.json PUT 이 200', m.status === 200, `status ${m.status}`);
  const again = await putJson(DATE, RUN, 'mission.json', mission);
  check('W3', '같은 파일을 다시 PUT 하면 200 (덮어쓰기)', again.status === 200, `status ${again.status}`);
  check('W4', 'PUT 응답에도 Access-Control-Allow-Origin', again.headers.get('access-control-allow-origin') !== null);
  const img = await call('POST', `/runs/${DATE}/${RUN}/images/detect/frame_000001_original.jpg`, jpeg, { 'Content-Type': 'image/jpeg' });
  check('W5', '그림 POST 가 200', img.status === 200, `status ${img.status}`);
  const robotImg = await call('POST', `/runs/${DATE}/${RUN}/images/robot/rot_045.jpg`, jpeg, { 'Content-Type': 'image/jpeg' });
  check('W6', '로봇 그림 POST 가 200', robotImg.status === 200, `status ${robotImg.status}`);
  const big = { ...progress, filler: 'x'.repeat(6 * 1024 * 1024) };
  const bigPut = await putJson(DATE, RUN, 'progress.json', big);
  check('W7', '6MB progress.json 을 받는다', bigPut.status === 200, `status ${bigPut.status}`);
  const back = await putJson(DATE, RUN, 'progress.json', progress);
  check('W8', 'progress.json 을 다시 작은 것으로 덮는다', back.status === 200, `status ${back.status}`);
  const ctl = await putJson(DATE, RUN_CTL, 'mission.json', {
    schema: 'control-record/1', recordKind: 'control', sessionKind: 'flight', deviceId: 'x500-001', missionId: `CTL-check-${tag}`,
    startedAtIso: now.toISOString(), updatedAtIso: now.toISOString(), endedAtIso: null, closeReason: null,
    counts: { commands: 1, rejected: 0, blocked: 0 }, missions: [], flight: null,
  });
  check('W9', '조작 판(recordKind: "control") mission.json 도 받는다', ctl.status === 200, `status ${ctl.status}`);
  const orphan = await putJson(DATE, RUN_NO_MISSION, 'progress.json', progress);
  check('W10', 'mission.json 없이 progress.json 만 먼저 와도 받는다', orphan.status === 200, `status ${orphan.status}`);
}

// ── 4. 거절 ───────────────────────────────────────────────────────────────────
{
  const broken = await putJson(DATE, RUN, 'mission.json', '{깨진 json');
  check('R1', '깨진 JSON 은 400', broken.status === 400, `status ${broken.status}`);
  const badDate = await putJson('..%2F..', RUN, 'mission.json', {});
  check('R2', '날짜 자리 `..` 는 4xx', badDate.status >= 400 && badDate.status < 500, `status ${badDate.status}`);
  const badRun = await putJson(DATE, '..%2Fescape', 'mission.json', {});
  check('R3', '판 자리 `..` 는 4xx', badRun.status >= 400 && badRun.status < 500, `status ${badRun.status}`);
  const other = await putJson(DATE, RUN, 'other.json', {});
  check('R4', 'mission/progress 밖의 파일 이름은 4xx', other.status >= 400 && other.status < 500, `status ${other.status}`);
  const badImg = await call('POST', `/runs/${DATE}/${RUN}/images/detect/..%2F..%2Fx.jpg`, jpeg, { 'Content-Type': 'image/jpeg' });
  check('R5', '그림 이름 `..` 는 4xx', badImg.status >= 400 && badImg.status < 500, `status ${badImg.status}`);
  const badDir = await call('POST', `/runs/${DATE}/${RUN}/images/other/x.jpg`, jpeg, { 'Content-Type': 'image/jpeg' });
  check('R6', 'detect · robot 밖의 그림 폴더는 4xx', badDir.status >= 400 && badDir.status < 500, `status ${badDir.status}`);
  const empty = await call('POST', `/runs/${DATE}/${RUN}/images/detect/empty.jpg`, Buffer.alloc(0), { 'Content-Type': 'image/jpeg' });
  check('R7', '빈 그림은 400', empty.status === 400, `status ${empty.status}`);
  const missing = await call('GET', `/files/${DATE}/${RUN}/images/detect/none.jpg`);
  check('R8', '없는 파일 GET 은 404', missing.status === 404, `status ${missing.status}`);
  const escape = await call('GET', '/files/..%2F..%2Fetc%2Fpasswd');
  check('R9', '파일 창구 `..` 는 4xx', escape.status >= 400 && escape.status < 500, `status ${escape.status}`);
  const del = await call('DELETE', `/runs/${DATE}/${RUN}/mission.json`);
  check('R10', 'DELETE 는 받지 않는다 (지우는 창구 없음)', del.status >= 400, `status ${del.status}`);
}

// ── 5. 읽기 ───────────────────────────────────────────────────────────────────
{
  const full = await call('GET', `/files/${DATE}/${encodeURIComponent(RUN)}/mission.json`);
  check('G1', 'mission.json GET 이 200', full.status === 200, `status ${full.status}`);
  check('G2', 'mission.json 이 마지막에 쓴 것 (덮어쓰기 반영)', full.json?.label === mission.label, String(full.json?.label));
  check('G3', 'mission.json 에 view 가 그대로', full.json?.view?.tasks?.[0]?.title === '첫 노드', JSON.stringify(full.json?.view)?.slice(0, 80));
  check('G4', 'JSON 의 Content-Type 이 application/json', (full.headers.get('content-type') ?? '').includes('application/json'), String(full.headers.get('content-type')));
  const prog = await call('GET', `/files/${DATE}/${encodeURIComponent(RUN)}/progress.json`);
  check('G5', 'progress.json 이 마지막에 쓴 것', prog.status === 200 && prog.json?.filler === undefined && prog.json?.trace?.length === 1, `status ${prog.status}`);
  const img = await call('GET', `/files/${DATE}/${encodeURIComponent(RUN)}/images/detect/frame_000001_original.jpg`);
  check('G6', '그림 GET 이 올린 바이트 그대로', img.status === 200 && img.bytes.equals(jpeg), `status ${img.status} · ${img.bytes.length}B`);
  check('G7', '그림 Content-Type 이 image/jpeg', (img.headers.get('content-type') ?? '').includes('image/jpeg'), String(img.headers.get('content-type')));
  check('G8', '파일 응답에도 Access-Control-Allow-Origin', img.headers.get('access-control-allow-origin') !== null);

  const list = await call('GET', '/runs');
  const runs = Array.isArray(list.json?.runs) ? list.json.runs : null;
  check('L1', 'GET /api/v1/runs 가 { runs: [...] }', list.status === 200 && runs !== null, `status ${list.status}`);
  const row = runs?.find((r) => r.date === DATE && r.run === RUN);
  check('L2', '방금 쓴 판이 목록에 있다', row !== undefined);
  check('L3', '목록 요약에 view 가 없다', row !== undefined && row.mission !== null && !('view' in row.mission));
  check('L4', '목록 요약이 mission.json 의 나머지 칸을 그대로 준다', row?.mission?.label === mission.label && row?.mission?.done === 1
    && row?.mission?.headSec === 12.5 && row?.mission?.endpoints?.robot === 'ws://example:9001', JSON.stringify(row?.mission)?.slice(0, 120));
  const ctlRow = runs?.find((r) => r.date === DATE && r.run === RUN_CTL);
  check('L5', '조작 판의 recordKind 칸이 목록에 그대로', ctlRow?.mission?.recordKind === 'control');
  check('L6', 'mission.json 이 없는 판은 목록에 안 나온다', runs !== null && !runs.some((r) => r.run === RUN_NO_MISSION));
  const keys = runs?.map((r) => `${r.date}/${r.run}`) ?? [];
  const sorted = [...keys].sort((a, b) => b.localeCompare(a));
  check('L7', '목록이 최근 것 먼저 (날짜/판 이름 내림차순)', keys.length > 0 && keys.every((k, i) => k === sorted[i]));
}

print();
const failed = results.filter((r) => !r.ok);
const optional = new Set(['C5']);
const hard = failed.filter((r) => !optional.has(r.id));
console.log(`\n${results.length - failed.length}/${results.length} 통과${failed.length > 0 ? ` · 실패 ${failed.map((r) => r.id).join(', ')}` : ''}`);
console.log(`검사 판: ${DATE}/${RUN} · ${DATE}/${RUN_CTL} · ${DATE}/${RUN_NO_MISSION}`);
process.exit(hard.length > 0 ? 1 : 0);

function print() {
  for (const r of results) console.log(`${r.ok ? '  ok ' : 'FAIL '} ${r.id.padEnd(4)} ${r.title}${r.ok || r.detail === '' ? '' : `  — ${r.detail}`}`);
}
