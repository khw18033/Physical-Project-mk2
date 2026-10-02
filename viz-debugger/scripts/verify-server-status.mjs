// verify:server-status (261002 신설 — 서버 칸의 서버 이름 · 서버 자원 · 전체 카메라 판)
//
// 보는 것 다섯.
//  1. 지표 글자(Prometheus 형식)를 뜯어 CPU · 메모리 · 부하 · 디스크 · 가동 시간을 낸다 — CPU 는 두 번 받은 누계의 차이다
//  2. 기계 지표(node_*)가 없는 지표(261002 실측 — 그 서버의 9100 은 Pushgateway)는 「자원 없음」이고 사유가 남는다
//  3. 이름 — 지표가 밝힌 nodename 이 먼저, 없으면 **같은 호스트**의 추론 서버가 밝힌 host, 둘 다 없으면 null(지어내지 않는다)
//  4. 창구는 `/metrics` 로 끝나는 http(s) 주소만 옮긴다 · 지표 주소 칸이 비면 게이트웨이 호스트의 9100 이다
//  5. 전체 카메라 — 하드웨어 패널 제목 줄의 단추 · 화면 80% 이상 · 장비마다 칸 · 추론 고르기는 카드 상세와 같은 부품
//
// 대조군 — 다른 호스트의 추론 서버 이름은 서버 이름이 되면 안 되고, `/metrics` 가 아닌 경로는 창구가 거절해야 한다.

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readSource } from './lib/source.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const read = (...p) => readSource(join(root, ...p));

const failures = [];
const controls = [];

const connections = await load('src', 'shared', 'connections.ts');
const status = await load('src', 'shell', 'serverStatus.ts');
const relay = await load('scripts', 'server-metrics-relay.mjs');

const node = (idle, user) => `# HELP node_cpu_seconds_total x
node_cpu_seconds_total{cpu="0",mode="idle"} ${idle}
node_cpu_seconds_total{cpu="0",mode="user"} ${user}
node_cpu_seconds_total{cpu="1",mode="idle"} ${idle}
node_cpu_seconds_total{cpu="1",mode="user"} ${user}
node_memory_MemTotal_bytes 1.6e+10
node_memory_MemAvailable_bytes 4e+09
node_load1 1.5
node_load5 1.25
node_load15 1
node_filesystem_size_bytes{device="/dev/sda1",fstype="ext4",mountpoint="/"} 1000
node_filesystem_avail_bytes{device="/dev/sda1",fstype="ext4",mountpoint="/"} 250
node_filesystem_size_bytes{device="tmpfs",fstype="tmpfs",mountpoint="/run"} 10
node_time_seconds 200000
node_boot_time_seconds 100000
node_uname_info{domainname="(none)",machine="x86_64",nodename="sysai-server2",release="6.8",sysname="Linux",version="#1"} 1
`;
const PUSHGATEWAY = '# HELP go_goroutines x\ngo_goroutines 12\npushgateway_build_info{version="1.9"} 1\n';

// ── 1 · 2. 뜯기 ────────────────────────────────────────────────────────────────
{
  const first = status.summarizeNode(status.parsePrometheusText(node(100, 100)), null);
  if (first === null) failures.push('node_exporter 지표를 기계 지표로 못 읽는다');
  else {
    if (first.resources.cpuPct !== null) failures.push('한 번 받고 CPU 사용률을 냈다 — 누계 하나로는 못 낸다');
    if (first.resources.cores !== 2) failures.push(`코어 수가 ${first.resources.cores}`);
    if (Math.round(first.resources.memUsedPct) !== 75) failures.push(`메모리 사용률이 ${first.resources.memUsedPct}`);
    if (first.resources.diskUsedPct !== 75) failures.push(`디스크 사용률이 ${first.resources.diskUsedPct} — / 만 봐야 한다`);
    if (first.resources.uptimeS !== 100000 || first.resources.load5 !== 1.25) failures.push('가동 시간 · 부하를 잘못 읽는다');
    if (first.nodename !== 'sysai-server2') failures.push('node_uname_info 의 nodename 을 못 읽는다');
    // 두 번째: 코어마다 idle +10, user +30 → 바쁜 비율 75%
    const second = status.summarizeNode(status.parsePrometheusText(node(110, 130)), first.cpu);
    if (second?.resources.cpuPct !== 75) failures.push(`CPU 사용률이 ${second?.resources.cpuPct} — 75 여야 한다`);
  }
  if (status.summarizeNode(status.parsePrometheusText(PUSHGATEWAY), null) !== null) failures.push('Pushgateway 지표를 기계 지표로 읽었다');
  if (status.parsePrometheusText('깨진 줄\nok_metric NaN\nfine 3').length !== 1) failures.push('모르는 줄을 버리지 않는다');
}

// ── 4. 창구 · 지표 주소 ────────────────────────────────────────────────────────
{
  if (relay.metricsRelayTarget('/other') !== null) failures.push('창구가 남의 경로를 가로챈다');
  const ok = relay.metricsRelayTarget(`/server-metrics?url=${encodeURIComponent('http://10.0.0.1:9100/metrics')}`);
  if (ok?.upstream !== 'http://10.0.0.1:9100/metrics') failures.push('지표 주소를 못 옮긴다');
  const bad = relay.metricsRelayTarget(`/server-metrics?url=${encodeURIComponent('http://10.0.0.1:8765/state')}`);
  if (!bad || !('error' in bad)) failures.push('대조군 실패: /metrics 가 아닌 경로를 옮긴다 — 아무 데나 두드리는 통로가 된다');
  controls.push('/metrics 가 아닌 경로');
  const file = relay.metricsRelayTarget(`/server-metrics?url=${encodeURIComponent('file:///etc/metrics')}`);
  if (!file || !('error' in file)) failures.push('http(s) 가 아닌 주소를 옮긴다');

  connections.saveConnections({ 'gateway.ws': 'ws://100.102.8.102:8765/state?token=x' });
  const auto = status.serverMetricsTarget();
  if (auto?.url !== 'http://100.102.8.102:9100/metrics' || auto.auto !== true) failures.push(`칸이 비었을 때 9100 을 안 두드린다 — ${JSON.stringify(auto)}`);
  connections.saveConnections({ 'gateway.ws': 'ws://100.102.8.102:8765/state', 'gateway.metrics': 'http://10.9.9.9:9100/metrics' });
  if (status.serverMetricsTarget()?.url !== 'http://10.9.9.9:9100/metrics') failures.push('칸에 적은 지표 주소가 안 이긴다');
}

// ── 3. 이름 ────────────────────────────────────────────────────────────────────
{
  const textFetch = (body, relayed = true) => async () => ({
    ok: true, status: 200, headers: { get: (name) => (name === 'X-Metrics-Relay' && relayed ? '1' : null) }, text: async () => body,
  });
  const visionFetch = (host) => async () => ({
    ok: true, status: 200, headers: { get: (name) => (name === 'X-Vision-Relay' ? '1' : null) },
    json: async () => ({ source: 'cam360', port: 10001, host, frames: 1, status: {}, vision: {} }),
  });

  // 지표가 이름을 밝힌다
  connections.saveConnections({ 'gateway.ws': 'ws://100.102.8.102:8765/state' });
  status.resetServerStatus();
  await status.refreshServerStatus(textFetch(node(1, 1)), Date.now, visionFetch('other-name'));
  let s = status.serverStatus();
  if (s.name !== 'sysai-server2' || s.nameFrom !== 'metrics') failures.push(`지표가 밝힌 이름이 안 선다 — ${s.name}/${s.nameFrom}`);
  if (s.resources === null || s.metricsError !== null) failures.push('지표를 읽었는데 자원이 비었다');

  // Pushgateway — 자원 없음 · 이름은 같은 호스트의 추론 서버
  connections.saveConnections({ 'gateway.ws': 'ws://100.102.8.102:8765/state', 'vision.host': 'http://100.102.8.102', 'vision.ports': '10001' });
  status.resetServerStatus();
  await status.refreshServerStatus(textFetch(PUSHGATEWAY), Date.now, visionFetch('sysai-server2'));
  s = status.serverStatus();
  if (s.resources !== null || s.metricsError === null) failures.push('기계 지표가 없는데 자원을 냈거나 사유가 없다');
  if (s.name !== 'sysai-server2' || s.nameFrom !== 'vision') failures.push(`같은 기계의 추론 서버 이름을 못 쓴다 — ${s.name}/${s.nameFrom}`);

  // 대조군 — 추론 서버가 다른 호스트면 그 이름을 서버 이름으로 쓰면 안 된다
  connections.saveConnections({ 'gateway.ws': 'ws://100.102.8.102:8765/state', 'vision.host': 'http://100.1.1.1', 'vision.ports': '10001' });
  status.resetServerStatus();
  await status.refreshServerStatus(textFetch(PUSHGATEWAY), Date.now, visionFetch('someone-else'));
  if (status.serverStatus().name !== null) failures.push('대조군 실패: 다른 기계의 추론 서버 이름을 서버 이름으로 적었다');
  controls.push('다른 호스트의 추론 서버');

  const card = read('src', 'shell', 'ServerCard.tsx');
  if (!/server\.name \?\? t\('srv\.title'\)/.test(card)) failures.push('서버 칸 제목이 서버 이름을 안 쓴다');
  if (!/holdServerStatus\(\)/.test(card)) failures.push('서버 칸이 서버 상태를 안 묻는다');
}

// ── 5. 전체 카메라 ─────────────────────────────────────────────────────────────
{
  const main = read('src', 'main.tsx');
  if (!/<header className="hardware-panel__head"><h2>\{t\('ms\.hardwareCount'[\s\S]{0,400}?t\('acam\.open'\)/.test(main)) failures.push('하드웨어 패널 제목 줄에 전체 카메라 단추가 없다');
  if (!/<AllCamerasOverlay onClose=/.test(main)) failures.push('전체 카메라 판을 안 연다');
  const css = read('src', 'style.css');
  const rule = /\.modal\.all-cams\{([^}]*)\}/.exec(css)?.[1] ?? '';
  const w = Number(/width:(\d+)vw/.exec(rule)?.[1] ?? 0);
  const h = Number(/height:(\d+)vh/.exec(rule)?.[1] ?? 0);
  if (w < 80 || h < 80) failures.push(`전체 카메라 판이 화면의 80% 미만이다 — ${w}vw × ${h}vh`);
  const overlay = read('src', 'views', 'AllCamerasOverlay.tsx');
  if (!/<VisionDeviceSection entityId=\{row\.id\} compact \/>/.test(overlay)) failures.push('전체 카메라 판이 카드 상세의 추론 부품을 안 쓴다 — 고름이 갈라진다');
  if (!/<b>\{row\.id\}<\/b>/.test(overlay)) failures.push('칸마다 장비 id 를 안 적는다 — 장비를 못 가른다');
  if (!/holdAllVisionSources\(\)/.test(overlay)) failures.push('포트를 맞대 볼 /health 를 안 붙잡는다');
  // 261002 — 한 칸 안의 영상 높이가 같고, 장비가 많아도 한 화면에 들어간다.
  const { fitCameraHeight, CAM_MIN_H } = await load('src', 'views', 'cameraFit.ts');
  if (fitCameraHeight(800, [100], 12) !== 700) failures.push('한 줄이면 남는 높이를 다 영상에 주어야 한다');
  if (fitCameraHeight(800, [100, 120], 12) !== 284) failures.push(`두 줄이면 (800 - 12 - 220) / 2 = 284 여야 한다 — ${fitCameraHeight(800, [100, 120], 12)}`);
  const many = Array.from({ length: 4 }, () => 150);
  if (fitCameraHeight(800, many, 12) * 4 + 150 * 4 + 12 * 3 > 800 && fitCameraHeight(800, many, 12) > CAM_MIN_H) failures.push('줄이 넷이면 한 화면을 넘는다');
  if (fitCameraHeight(300, many, 12) !== CAM_MIN_H) failures.push('대조군 실패: 자리가 모자라도 하한 밑으로 줄인다 — 영상을 못 읽는다');
  controls.push('하한 밑으로 안 줄인다');
  if (fitCameraHeight(800, [100], 12, 450) !== 450) failures.push('영상 비율이 필요로 하는 높이보다 키운다 — 검은 띠만 는다');
  if (!/className="all-cams__grid"/.test(overlay) || !/\.all-cams__grid\{[^}]*grid-template-columns:minmax\(0,1fr\)/.test(css)) failures.push('장비가 세로로 안 쌓인다');
  const camRule = /\.modal\.all-cams \.all-cams__feed \.device-cam__canvas,\.modal\.all-cams \.vision-grid \.vision-cell img\{([^}]*)\}/.exec(css)?.[1] ?? '';
  if (!/height:var\(--cam-h/.test(camRule) || !/max-height:none/.test(camRule)) failures.push('바로 받는 영상과 추론 영상이 같은 높이(--cam-h)를 안 쓴다');
  if (!/\.all-cams \.vision-grid\{[^}]*grid-auto-flow:column/.test(css)) failures.push('추론 모델이 여럿이면 아래로 쌓인다 — 높이 계산이 어긋난다');
}

connections.resetConnections();
status.resetServerStatus();

if (failures.length) {
  console.error('❌ verify:server-status');
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}
console.log('✅ 지표 뜯기 — CPU(두 번의 차이) · 메모리 · 부하 · 디스크(/) · 가동 시간 · Pushgateway 는 자원 없음과 사유');
console.log('✅ 서버 이름 — 지표의 nodename → 같은 호스트 추론 서버의 host → 없으면 null · 칸 제목이 그것을 쓴다');
console.log('✅ 창구는 /metrics 만 · 지표 주소 칸이 비면 게이트웨이 호스트의 9100');
console.log('✅ 전체 카메라 — 제목 줄 단추 · 화면 80% 이상 · 장비 id 머리 · 카드 상세와 같은 추론 부품 · 영상 높이 하나(--cam-h)로 한 화면에');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
process.exit(0);
