// verify:physical-port (260910 신설 — 하드웨어 연동 지시서 §7)
//
// **로봇을 아는 면이 `src/physical/` 하나인가.**
//
// `verify:stt-port` · `verify:gen-port` 와 같은 검사이고 같은 이유다. 주소·토픽·장비 id 가
// 두 곳에 적히는 순간, 브로커를 옮기거나 중앙 서버 경유로 바꿀 때 한쪽만 고쳐지고
// 나머지는 옛 주소로 붙는다. 그때 화면은 「붙었다」고 말하면서 아무것도 못 받는다.
//
// 무엇이 경계 안에 있어야 하는가:
//   · MQTT 주소 (ws://pi7.local:9001 · 192.168.50.172)
//   · 토픽 문자열 (terminal/.../downlink · uplink)
//   · 하드웨어 장비 id (go1-001) — 화면·대본은 robot-01 을 쓴다
//   · mqtt / protobufjs 라이브러리 자체
//
// 대조군 포함 — 경계 밖에 한 줄을 주입한 사본이 반드시 실패로 잡히는지까지 본다.

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isScratchPath } from './lib/scratch.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const srcDir = join(root, 'src');
const BOUNDARY = join('src', 'physical');

const failures = [];
const controls = [];

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    // 남의 대조군 잔여물을 내 판정에 넣지 않는다 (260917 — 검사 위생 §3①).
    if (isScratchPath(full)) continue;
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.(ts|tsx)$/.test(name)) out.push(full);
  }
  return out;
}

/** 경계 밖에 있으면 안 되는 것들. */
const FORBIDDEN = [
  { pattern: /pi7\.local/, what: 'MQTT 브로커 이름' },
  { pattern: /192\.168\.50\.172/, what: '랩 Wi-Fi 고정 IP' },
  // 드론(pi3)도 같은 규칙이다 (260921). 기계가 둘이 됐는데 한쪽만 막으면, 새로 붙는
  // 쪽 주소가 경계 밖으로 새 나가는 것을 아무도 안 잡는다.
  //
  // **테일넷을 통째로 막지 않는다** — `src/detect/` 가 같은 테일넷의 다른 기계를 쓰고
  // 그것은 그 경계 안에 있는 것이 맞다(`verify:capability-source` 와 같은 규칙).
  { pattern: /pi3\.local/, what: '드론 MQTT 브로커 이름' },
  { pattern: /pi3\.tailcb6bfb/, what: '드론 테일넷 이름' },
  { pattern: /192\.168\.50\.254|100\.85\.243\.54/, what: '드론 브로커 IP' },
  { pattern: /terminal\/[^\s'"`]*\/(downlink|uplink)/, what: 'MQTT 명령 토픽' },
  // 장비 상태 토픽도 경계 안에 있어야 한다 (260910). 구역 이름이 바뀌면 한 곳만 고친다.
  { pattern: /zoneA\/\+\/\+\//, what: 'MQTT 장비 상태 토픽' },
  { pattern: /\bgo1-001\b/, what: '하드웨어 장비 id' },
  { pattern: /from\s+['"]mqtt['"]|import\(['"]mqtt['"]\)/, what: 'mqtt 라이브러리 import' },
  { pattern: /from\s+['"]protobufjs/, what: 'protobufjs import' },
];

function scan(files, { skipBoundary = true } = {}) {
  const hits = [];
  for (const file of files) {
    const rel = relative(root, file);
    if (skipBoundary && rel.startsWith(BOUNDARY)) continue;
    const source = readFileSync(file, 'utf8');
    for (const { pattern, what } of FORBIDDEN) {
      if (pattern.test(source)) hits.push(`${rel}: ${what} 이 경계 밖에 있다`);
    }
  }
  return hits;
}

const files = walk(srcDir);
failures.push(...scan(files));

// 경계 파일이 실제로 존재하고 그 안에 주소가 있는가 — 검사가 헛돌지 않게.
{
  const client = join(srcDir, 'physical', 'PhysicalClient.ts');
  const source = readFileSync(client, 'utf8');
  if (!/pi7\.local/.test(source)) failures.push('PhysicalClient.ts 에 기본 주소가 없다 — 검사가 헛돈다');
  if (!/terminal\//.test(source)) failures.push('PhysicalClient.ts 에 명령 토픽이 없다 — 검사가 헛돈다');
  if (!/zoneA\//.test(source)) failures.push('PhysicalClient.ts 에 장비 상태 토픽이 없다 — 검사가 헛돈다');
  if (!/registerConnectionDefault\(\s*'physical'/.test(source)) {
    failures.push("PhysicalClient.ts 가 'physical' 연결 기본값을 심지 않는다");
  }
}

// 연결 대상이 등록됐는가 — 화면의 「연결 관리」가 이 주소를 고칠 수 있어야 한다.
{
  const source = readFileSync(join(srcDir, 'shared', 'connections.ts'), 'utf8');
  if (!/id:\s*'physical'/.test(source)) failures.push("connections.ts 에 'physical' 대상이 없다");
  // 주소 자체는 경계 파일이 심는다 — 여기 fallback 은 화면이 그릴 대비값이다.
}

/**
 * 주소를 **짐작해 넣지 않았는가** (§2 · 지시서가 못박은 자리).
 *
 * ## 260921 — 규칙이 한 단계 세졌다
 *
 * 전에는 발표장 자리를 **빈 프리셋**으로 두고 「url 이 비어 있어야 한다」를 봤다. IP 를
 * 받으면 그 한 줄만 채우려던 것인데, 기계가 둘이 되면서 목록이 여덟이 됐고 그중 둘이
 * 고를 수 없는 줄이었다 — **무대에서 여덟 중 하나를 고르는 것은 고르는 게 아니라 찾는 것**이다.
 *
 * 그래서 목록을 테일넷 둘 + 직접 입력으로 줄이고 규칙을 이렇게 바꿨다:
 *
 *   > **주소를 모르면 프리셋을 아예 안 만든다.** 필요하면 직접 입력에 넣는다.
 *
 * 옛 규칙(빈 줄은 고를 수 없다)을 **포함하면서 더 세다** — 빈 줄 자체가 없어야 하므로
 * 지어낸 주소가 들어갈 자리도 같이 사라진다.
 */
{
  const source = readFileSync(join(srcDir, 'physical', 'presets.ts'), 'utf8');
  const blanks = [...source.matchAll(/id:\s*'([^']+)'[^}]*url:\s*'([^']*)'/g)]
    .filter(([, id, url]) => id !== 'manual' && url.trim() === '')
    .map(([, id]) => id);
  if (blanks.length > 0) {
    failures.push(`빈 프리셋이 있다 — ${blanks.join(' · ')} · 주소를 모르면 줄을 만들지 말고 직접 입력을 쓴다`);
  }
  // 검사가 헛돌지 않게 — 프리셋이 실제로 있어야 한다.
  if (!/id:\s*'manual'/.test(source)) failures.push('presets.ts 에 직접 입력 자리가 없다');
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  controls.push(name);
}
{
  // 경계 밖 파일에 토픽을 한 줄 심은 셈 치고 같은 규칙을 돌린다.
  const injected = "const t = 'terminal/go1-001/downlink';";
  const hits = FORBIDDEN.filter(({ pattern }) => pattern.test(injected));
  control('경계 밖에 명령 토픽 주입', hits.length >= 2);
  control('경계 밖에 장비 상태 토픽 주입',
    FORBIDDEN.some(({ pattern }) => pattern.test("client.subscribe('zoneA/+/+/state')")));
}
{
  const injected = "import mqtt from 'mqtt';";
  control('경계 밖에 mqtt import 주입', FORBIDDEN.some(({ pattern }) => pattern.test(injected)));
}
{
  // 경계 안을 포함해 훑으면 반드시 걸려야 한다 — 규칙이 실제로 무언가를 보고 있다는 뜻.
  control('경계를 포함해 훑으면 걸린다', scan(files, { skipBoundary: false }).length > 0);
}
{
  // 빈 프리셋 규칙 — 주소를 모르는 줄을 심은 사본이 잡혀야 한다.
  const blanksOf = (source) => [...source.matchAll(/id:\s*'([^']+)'[^}]*url:\s*'([^']*)'/g)]
    .filter(([, id, url]) => id !== 'manual' && url.trim() === '');
  control('빈 프리셋을 심은 사본', blanksOf("{ id: 'venue', labelKey: 'x', url: '', whyKey: 'y' },").length === 1);
  // 반대 대조군 — 직접 입력은 원래 비어 있다. 그것까지 잡으면 규칙이 못 쓰게 된다.
  control('직접 입력은 안 잡는다', blanksOf("{ id: 'manual', labelKey: 'x', url: '', whyKey: 'y' },").length === 0);
}

if (failures.length) {
  console.error(`❌ verify:physical-port\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 로봇을 아는 면이 src/physical/ 하나 — 주소·토픽·go1-001·mqtt·protobufjs 가 경계 밖에 0건 (${files.length}개 파일)`);
console.log('✅ 연결 대상 physical 등록됨 · 빈 프리셋 0건 — 주소를 모르면 줄을 안 만든다 (지어내지 않았다)');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
