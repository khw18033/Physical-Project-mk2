// verify:video-records (261007 신설 — 실시간 화면 녹화 저장 · 3D 가상환경 PC 이름)
//
// **브라우저가 보낸 녹화 조각이 저장소 루트 `video/<날짜>/` 에 한 파일로 남는가.** 막으려는 실패 다섯.
//
//  1. **폴더 밖을 쓰는 것** — 장치 이름 · 모델 이름이 파일 이름에 들어간다. `..` · `/` · `\` 가 끼면 아무 데나 쓴다.
//  2. **조각이 섞이는 것** — 동시 녹화 둘이 같은 초에 시작하면 이름이 같다. 한 파일에 두 녹화가 붙으면 둘 다 못 튼다.
//  3. **조각이 순서대로 안 붙는 것** — 1초 조각이 이어 붙어야 한 영상이다.
//  4. **아무것도 안 찍힌 녹화가 빈 파일로 남는 것** — 확인 창에서 취소하면 폴더가 빈 파일로 찬다.
//  5. **PC 이름을 엉뚱한 기기에서 가져오는 것** — Tailscale 목록에서 주소가 맞는 기기의 이름이어야 한다.
//
// 창구는 임시 폴더에 띄운다. 대조군 포함.

import { createServer } from 'node:http';
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const { videoRecordsMiddleware, safeLabel, tailscaleNameOf, stamp, videoDir } = await import(pathToFileURL(join(root, 'scripts', 'video-records.mjs')).href);
const failures = [];
const check = (ok, message) => { if (!ok) failures.push(message); };

const dir = mkdtempSync(join(tmpdir(), 'video-records-'));
const middleware = videoRecordsMiddleware(dir, async (host) => (host === '100.68.72.33' ? 'DESKTOP-TEST' : null));
const server = createServer((req, res) => middleware(req, res, () => { res.statusCode = 404; res.end('next'); }));
await new Promise((done) => server.listen(0, '127.0.0.1', done));
const origin = `http://127.0.0.1:${server.address().port}`;
const post = async (path, body, type = 'application/octet-stream') => {
  const response = await fetch(`${origin}/video-records/${path}`, { method: 'POST', body, headers: { 'Content-Type': type } });
  return { status: response.status, body: await response.json() };
};

try {
  // ── 0. 기본 폴더는 저장소 루트의 video/ ────────────────────────────────────
  check(videoDir() === resolve(root, '..', 'video'), `기본 폴더가 저장소 루트 video/ 가 아니다: ${videoDir()}`);

  // ── 1. 이름 다듬기 — 폴더 밖으로 못 나간다 ─────────────────────────────────
  const evil = safeLabel('../../etc/passwd');
  check(!evil.includes('/') && !evil.includes('\\') && !evil.startsWith('.'), `「../../etc/passwd」 가 경로 글자를 남겼다: ${evil}`);
  check(safeLabel('go1-001_front') === 'go1-001_front', '멀쩡한 이름을 바꿨다');
  check(safeLabel('C:\\a:b*c?"d<e>f|g h') === 'C-a-b-c-d-e-f-g-h', `Windows 금지 글자가 남았다: ${safeLabel('C:\\a:b*c?"d<e>f|g h')}`);
  check(safeLabel('드론_탐지') === '드론_탐지', '한국어 이름을 지웠다 — 장치 이름이 한국어일 수 있다');
  check(safeLabel('') === 'video' && safeLabel('///') === 'video', '빈 이름에 기본값을 안 줬다');
  // 대조군 — 다듬지 않았다면 경로 글자가 남는다
  check('../../etc/passwd'.includes('/'), '대조군: 원래 이름에 경로 글자가 없다');

  // ── 2 · 3. 동시 녹화 둘 — 이름이 갈리고, 조각이 차례대로 붙는다 ─────────────
  const a = await post('open', JSON.stringify({ label: 'cam', ext: 'mp4' }), 'application/json');
  const b = await post('open', JSON.stringify({ label: 'cam', ext: 'mp4' }), 'application/json');
  check(a.status === 200 && b.status === 200, `열기 실패: ${a.status} ${b.status}`);
  check(a.body.path !== b.body.path, `같은 초의 두 녹화가 같은 파일을 받았다: ${a.body.path}`);
  check(/^video\/\d{6}\/\d{6}_cam(-2)?\.mp4$/.test(a.body.path), `경로 모양이 video/<YYMMDD>/<HHMMSS>_<이름>.mp4 가 아니다: ${a.body.path}`);
  await post(`append?id=${a.body.id}`, Buffer.from('AAA'));
  await post(`append?id=${b.body.id}`, Buffer.from('xx'));
  await post(`append?id=${a.body.id}`, Buffer.from('BBB'));
  const closedA = await post(`close?id=${a.body.id}`);
  const closedB = await post(`close?id=${b.body.id}`);
  const fileA = join(dir, ...closedA.body.path.split('/').slice(1));
  const fileB = join(dir, ...closedB.body.path.split('/').slice(1));
  check(existsSync(fileA) && readFileSync(fileA, 'utf8') === 'AAABBB', `조각이 차례대로 한 파일에 붙지 않았다: ${existsSync(fileA) ? readFileSync(fileA, 'utf8') : '(없음)'}`);
  check(existsSync(fileB) && readFileSync(fileB, 'utf8') === 'xx', '두 번째 녹화의 조각이 섞였다');
  check(closedA.body.bytes === 6, `닫을 때 크기가 틀렸다: ${closedA.body.bytes}`);
  const day = stamp().day;
  check(readdirSync(join(dir, day)).length === 2, '날짜 폴더에 두 파일이 아니다');

  // 닫은 녹화에는 더 못 붙인다
  const late = await post(`append?id=${a.body.id}`, Buffer.from('ZZZ'));
  check(late.status === 404, `닫은 녹화에 조각이 붙었다: ${late.status}`);

  // 형식은 mp4 · webm 만 — 다른 것을 보내면 webm 으로 받는다
  const odd = await post('open', JSON.stringify({ label: 'x', ext: 'exe' }), 'application/json');
  check(odd.body.path.endsWith('.webm'), `허용 안 한 확장자를 그대로 썼다: ${odd.body.path}`);

  // ── 4. 조각 없이 닫은 녹화는 파일을 남기지 않는다 ─────────────────────────────
  const empty = await post('open', JSON.stringify({ label: 'cancelled', ext: 'mp4' }), 'application/json');
  const closedEmpty = await post(`close?id=${empty.body.id}`);
  check(closedEmpty.body.path === null && closedEmpty.body.bytes === 0, '빈 녹화가 경로를 돌려줬다');
  check(!readdirSync(join(dir, day)).some((name) => name.includes('cancelled')), '빈 녹화가 파일로 남았다');

  // ── 5. PC 이름 — 주소가 맞는 기기 ───────────────────────────────────────────
  const status = {
    Self: { HostName: 'LAPTOP-SELF', DNSName: 'laptop-self.tail.ts.net.', TailscaleIPs: ['100.78.11.92'] },
    Peer: {
      a: { HostName: 'DESKTOP-DQDNRF2', DNSName: 'desktop-dqdnrf2.tail.ts.net.', TailscaleIPs: ['100.68.72.33', 'fd7a::1'] },
      b: { HostName: 'raspberrypi', DNSName: 'raspberrypi.tail.ts.net.', TailscaleIPs: ['100.64.0.7'] },
    },
  };
  check(tailscaleNameOf(status, '100.68.72.33') === 'DESKTOP-DQDNRF2', 'IP 로 기기 이름을 못 찾았다');
  check(tailscaleNameOf(status, 'desktop-dqdnrf2') === 'DESKTOP-DQDNRF2', '짧은 DNS 이름으로 못 찾았다');
  check(tailscaleNameOf(status, '100.78.11.92') === 'LAPTOP-SELF', '자기 자신을 못 찾았다');
  check(tailscaleNameOf(status, '10.0.0.1') === null, '없는 주소에 이름을 지어냈다');
  check(tailscaleNameOf(null, '100.68.72.33') === null, 'Tailscale 이 없을 때 이름을 지어냈다');
  const named = await fetch(`${origin}/video-records/host-name?host=100.68.72.33`).then((r) => r.json());
  check(named.name === 'DESKTOP-TEST', `host-name 창구가 조회 결과를 안 돌려줬다: ${JSON.stringify(named)}`);

  // ── 내 주소가 아니면 지나간다 ──────────────────────────────────────────────
  const other = await fetch(`${origin}/mission-records/api/runs`);
  check(other.status === 404 && (await other.text()) === 'next', '남의 주소를 가로챘다');
} finally {
  server.close();
  rmSync(dir, { recursive: true, force: true });
}

if (failures.length > 0) {
  for (const failure of failures) console.error(`❌ ${failure}`);
  process.exit(1);
}
console.log('✅ video-records — 이름 다듬기 · 동시 녹화 분리 · 조각 순서 · 빈 녹화 · PC 이름 조회');
