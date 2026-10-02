// verify:gateway-wire (260919 신설 — 영문화 5단계 §2)
//
// **게이트웨이를 실제로 띄워, 영문 화면이 받는 것에 한국어가 없는지 본다.**
//
// 정적으로는 못 가린다. `gateway/` 의 한글은 428건인데 그중 화면에 닿는 것은 78건뿐이었다 —
// 나머지는 서버 콘솔·`/health`·화면이 안 부르는 엔드포인트다. 그것까지 옮기면 사전이 부풀고
// 「이건 어디 뜨느냐」를 다음 사람이 매번 다시 묻는다.
//
// 그래서 **화면이 실제로 쓰는 길만 두드려** 받은 것을 본다. 260919 에 이 방법으로
// 승인 팝업·제어 패널·장치 이름의 한국어를 찾았고, 같은 방법으로 안 닿는 것을 가렸다.
//
// 대조군 — 표지를 안 지나는 한글을 심으면 반드시 잡혀야 한다.
import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const { WebSocket } = createRequire(pathToFileURL(join(root, 'package.json')).href)('ws');

const PORT = Number(process.env.VERIFY_WIRE_PORT ?? 8894);
const failures = [];
const controls = [];

/**
 * **영문 화면이 받아도 되는 한국어.** 줄마다 왜인지가 붙어 있다.
 *
 * 갈래는 셋뿐이다.
 *   ① 사람 이름 — 번역하는 것이 아니다
 *   ② 데이터 파일 안의 **문서**(`note`·`generated_by`) — 화면이 안 그린다
 *   ③ 대본·발화가 준 **값** — 3단계 사이드카가 맡는 자리이지 게이트웨이의 말이 아니다
 */
const KEPT = [
  [/^김현우$/, '감사 기록의 조작자 — **사람 이름**이다'],
  [/note$/, '레지스트리 데이터 안의 문서용 메모 — 화면이 안 그린다 (렌더 자리 없음)'],
  [/generated_by$/, '레지스트리가 자기 출처를 적은 줄 — 화면이 안 그린다'],
  [/origin\.comment$/, '좌표계 설명 주석 — 화면이 안 그린다'],
  [/matched_keywords\[/, '발화에서 잘라 낸 **사용자의 말** — 옮길 대상이 아니다'],
  [/payload\.detail$/, '대본 제목·발화 문장이 값으로 들어간 문장 (틀은 영어다 — 아래 §2 가 본다)'],
  [/^ws:command_ack\.message$/, '같은 문장이 ACK 로도 간다 — 틀은 영어다 (§2)'],
  [/^http:\/audit\.records\[\d+\]\.detail$/, '같은 문장이 감사 기록으로도 남는다 — 틀은 영어다 (§2)'],
  [/provenance\[\d+\]\.detail$/, '같음 — 발화 문장이 값으로 들어간다'],
  [/validations\[\d+\]\.detail$/, '같음 — 맞은 키워드가 값으로 들어간다'],
  [/script\.title$/, '대본 제목 — 대본 데이터의 것이다 (3단계 사이드카)'],
  [/evidence\.mission\.title$/, '대본 제목 — 같음'],
  [/utterance/, '사용자가 말한 문장 그대로'],
];

const han = /[가-힣]/;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const server = spawn(process.execPath, ['gateway/server.ts'], {
  cwd: root, stdio: ['ignore', 'ignore', 'inherit'],
  env: { ...process.env, MOCK_PORT: String(PORT), VIZ_SCENARIO_SPEED: '40' },
});
const stop = () => { if (!server.killed) server.kill(); };
process.on('exit', stop);

/** 받은 것에서 한글이 든 자리를 모은다. */
function scan(where, node, out, path = '') {
  if (typeof node === 'string') {
    if (han.test(node)) out.push({ at: `${where}${path}`, text: node });
    return;
  }
  if (Array.isArray(node)) { node.forEach((v, i) => scan(where, v, out, `${path}[${i}]`)); return; }
  if (node !== null && typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) scan(where, v, out, `${path}.${k}`);
  }
}

async function main() {
  for (let i = 0; i < 60; i += 1) {
    try { const r = await fetch(`http://127.0.0.1:${PORT}/registry`); if (r.ok) break; } catch { /* 아직 */ }
    await sleep(250);
  }

  const found = [];
  const ws = new WebSocket(`ws://127.0.0.1:${PORT}?lang=en`);
  await new Promise((res, rej) => {
    const timer = setTimeout(() => rej(new Error('게이트웨이에 못 붙었다')), 10000);
    ws.on('open', () => { clearTimeout(timer); res(); });
    ws.on('error', (e) => { clearTimeout(timer); rej(e); });
  });
  ws.on('message', (raw) => {
    let m; try { m = JSON.parse(String(raw)); } catch { return; }
    scan(`ws:${m.type ?? '?'}`, m, found);
  });

  const send = (o) => ws.send(JSON.stringify(o));
  send({ type: 'subscribe', id: 'all', selector: { entity: '*', node: '*', channel: '*' }, scope: 'all' });
  await sleep(1200);

  // 발화 → 대본 매칭 → 계획 제안 (승인 팝업의 근거가 여기서 나온다)
  send({
    type: 'command',
    command: {
      client_request_id: 'wire-1', action: 'mission_from_utterance',
      entity: 'MSN-260909-01', node: 'zone-503', params: { text: '저기 문 쪽으로 가', confidence: 0.9 },
    },
  });
  await sleep(2000);

  // 명령 — 접수·진행·거절
  send({ type: 'command', command: { client_request_id: 'wire-2', action: 'open_gate', entity: 'actuator-01', node: 'zone-503', params: {} } });
  send({ type: 'command', command: { client_request_id: 'wire-3', action: 'nope', entity: 'actuator-01', node: 'zone-503', params: {} } });
  send({ type: 'nonsense' });
  send({ type: 'subscribe', id: 'bad', selector: 'not-an-object', scope: 'all' });
  await sleep(1500);

  const base = `http://127.0.0.1:${PORT}`;
  for (const [label, url] of [
    ['/registry', `${base}/registry?lang=en`],
    ['/actions', `${base}/actions?entity=actuator-01&lang=en`],
    ['/audit', `${base}/audit?limit=20&lang=en`],
    ['/metrics/query', `${base}/metrics/query?lang=en&entity=edge-node-a&metric=cpu_pct&mode=raw&range_min=180`],
    ['/role', `${base}/role?lang=en`],
  ]) {
    try { scan(`http:${label}`, await (await fetch(url)).json(), found); } catch (e) { failures.push(`${label} 를 못 읽었다 — ${e.message}`); }
  }

  ws.close();
  stop();
  return found;
}

const found = await main().catch((e) => { failures.push(String(e?.message ?? e)); stop(); return []; });

// ── 1. 영문 화면이 받는 것에 못박히지 않은 한국어가 없다 ────────────────────
{
  let kept = 0;
  const loose = [];
  for (const hit of found) {
    const rule = KEPT.find(([re]) => re.test(hit.at) || re.test(hit.text));
    if (rule === undefined) loose.push(hit);
    else kept += 1;
  }
  for (const hit of loose.slice(0, 8)) {
    failures.push(`${hit.at} 가 한국어다 — 「${hit.text.length > 60 ? `${hit.text.slice(0, 60)}…` : hit.text}」`);
  }
  if (loose.length > 8) failures.push(`그 밖 ${loose.length - 8}건`);
  console.log(`✅ 영문 접속이 받은 한글 ${found.length}건이 전부 못박힌 자리다 (남겨야 하는 것 ${kept}건 · 아닌 것 ${loose.length}건)`);
}

// ── 2. 문장의 **틀**은 영어다 ───────────────────────────────────────────────
//
// §1 의 예외 중에는 「값만 한국어인 문장」이 있다 — 대본 제목·발화 문장이 값으로 들어간다.
// 그 자리가 통째로 한국어로 돌아가면 §1 은 여전히 통과한다. 그래서 **틀**을 따로 본다.
{
  const framed = found.filter((h) => /payload\.detail$|provenance\[\d+\]\.detail$|command_ack\.message$|records\[\d+\]\.detail$/.test(h.at));
  if (framed.length === 0) {
    failures.push('틀을 검사할 문장을 하나도 못 받았다 — 이 검사가 아무것도 안 재고 있다');
  }
  for (const hit of framed) {
    // 영어 틀이면 라틴 문자가 넉넉히 섞여 있다. 통째로 한국어면 거의 없다.
    const latin = (hit.text.match(/[A-Za-z]/g) ?? []).length;
    if (latin < 10) failures.push(`${hit.at} 의 **틀까지** 한국어다 — 「${hit.text.slice(0, 60)}…」`);
  }
  console.log(`✅ 값만 한국어인 문장 ${framed.length}건의 틀이 영어다`);
}

// ── 3. 대조군 ───────────────────────────────────────────────────────────────
{
  // 잣대가 실제로 한글을 잡는가.
  const probe = [];
  scan('ws:test', { a: { b: '한국어 문장' } }, probe);
  if (probe.length !== 1 || probe[0].at !== 'ws:test.a.b') {
    failures.push('대조군 실패: 중첩된 한글을 못 잡는다 — 이 검사는 무의미하다');
  } else controls.push('중첩된 한글을 자리까지 짚는다');

  scan('ws:test', { a: 'plain english' }, probe);
  if (probe.length !== 1) failures.push('대조군 실패: 영어를 한글로 셌다');
  else controls.push('영어는 안 센다');

  // 못박힌 자리가 실제로 걸러지는가 (사람 이름).
  if (!KEPT.some(([re]) => re.test('김현우'))) failures.push('대조군 실패: 사람 이름 예외가 안 걸린다');
  else controls.push('사람 이름은 통과시킨다');
}

if (failures.length > 0) {
  console.error(`❌ verify:gateway-wire\n- ${failures.join('\n- ')}`);
  console.error('\n   게이트웨이가 만든 문장은 `say()` 로 담아 `gateway/i18n.ko.ts`·`i18n.en.ts` 에 넣어라.');
  console.error('   남겨야 하는 것이라면 이 파일의 `KEPT` 에 **사유와 함께** 적어라.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
process.exit(0);
