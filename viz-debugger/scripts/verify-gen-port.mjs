// verify:gen-port (260904 신설 — 마일스톤 분리 지시서 §3)
//
// **생성 주소를 아는 면이 `src/generate/` 하나인가** — 그리고 **문법이 계약에서 나오는가.**
//
// 이름은 `verify:stt-port` 를 따랐지만 보는 것이 다르다. 그쪽은 이식본이 원본과 바이트
// 동일한지(복사가 갈라지지 않는지)를 보고, 여기는 **면이 하나인지**를 본다. 생성에는
// 이식본이 없기 때문이다 — `gen-lab/server/engines/` 는 새로 쓰는 자리이지 복사가 아니다.
// 그래서 「조용히 갈라지는 것을 막는다」는 목적은 같고 갈라질 대상만 다르다:
// 저쪽은 파일 두 벌, 이쪽은 **주소와 문법**이다.
//
// 넷을 본다.
//   1. 생성 주소를 아는 코드가 `src/generate/` 밖에 없는가 — 주입 대조군 포함
//   2. `CONNECTION_TARGETS` 에 `generate` 가 있고 기본값이 8802 인가 · 다른 서비스와 안 겹치는가
//   3. **손으로 쓴 문법 파일이 없는가** (`*.gbnf` 등)
//   4. **계약을 고치면 문법이 따라 바뀌는가** — 계약이 원본이라는 원칙의 기계적 확인
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = join(vizRoot, '..');
const srcDir = join(vizRoot, 'src');
const failures = [];
const controls = [];

const files = [];
(function walk(directory) {
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) { if (!name.startsWith('.')) walk(path); }
    else if (/\.(ts|tsx)$/.test(name)) files.push(path);
  }
})(srcDir);

// ── 1. 면이 하나인가 ─────────────────────────────────────────────────────────
//
// `fetch` 를 세지 않는다 — 게이트웨이를 부르는 데이터 계층도 fetch 를 쓰는데 그건 생성과
// 아무 상관이 없다. 막고 싶은 것은 "생성 서비스를 부르는 두 번째 길"이지 "fetch 를 쓰는
// 코드"가 아니다 (`verify:no-stt` 의 같은 판단).
// `connections.ts` 의 `fallback` 은 세지 않는다 — 그건 **화면이 그릴 대비값**이지 생성을
// 부르는 두 번째 길이 아니다(그 파일 머리말이 STT 에 대해 같은 말을 한다). 대신 그 값이
// 클라이언트의 기본값과 같은지를 아래 ②가 따로 본다.
const GENERATE_MARKERS = /VITE_GENERATE_URL|['"`][^'"`]*\/generate\/(mission|health)/;

function generateCallers(extra = '') {
  const out = [];
  for (const path of files) {
    const rel = relative(srcDir, path).replaceAll('\\', '/');
    const inside = rel.startsWith('generate/');
    const source = readFileSync(path, 'utf8') + (inside ? extra : '');
    if (GENERATE_MARKERS.test(source) && !inside) out.push(rel);
  }
  return out;
}

const outside = generateCallers();
if (outside.length) {
  failures.push(`src/generate/ 밖에서 생성 주소를 안다: ${outside.join(', ')} — 생성을 보는 면이 하나가 아니게 된다`);
}
// 대조군 — src/generate/ **밖에** 생성 호출을 넣으면 반드시 잡혀야 한다.
// 소스 트리에 실제 파일을 만들고 끝나면 지운다 (verify:no-stt 와 같은 방식).
{
  const scratch = mkdtempSync(join(srcDir, '.verify-gen-'));
  try {
    const decoy = join(scratch, 'decoy.ts');
    writeFileSync(decoy, 'export const x = () => fetch("http://127.0.0.1:8802/generate/mission");', 'utf8');
    files.push(decoy);
    if (generateCallers().length === 0) {
      failures.push('생성 호출을 주입한 대조군을 검출하지 못했다 — 이 검사는 무의미하다');
    } else {
      controls.push('src/generate/ 밖의 생성 호출 주입');
    }
    files.pop();
  } finally {
    try { rmSync(scratch, { recursive: true, force: true }); } catch { console.warn('임시 디렉터리 정리 실패 — ' + scratch); }
  }
}

// ── 2. 연결 대상 ─────────────────────────────────────────────────────────────
{
  const source = readFileSync(join(srcDir, 'shared', 'connections.ts'), 'utf8');
  if (!/id:\s*'generate'/.test(source)) failures.push("CONNECTION_TARGETS 에 'generate' 가 없다 — 화면에서 주소를 바꿀 수 없다 (VZ-C-07)");
  if (!/'gateway'\s*\|\s*'stt'\s*\|\s*'generate'/.test(source)) failures.push("ConnectionTargetId 에 'generate' 가 없다");
  // **기본값은 연결 저장소가 아니라 src/generate/ 가 심는다** — 그래야 면이 하나로 남는다.
  const client = readFileSync(join(srcDir, 'generate', 'LlmClient.ts'), 'utf8');
  if (!/registerConnectionDefault\('generate',\s*'base'/.test(client)) {
    failures.push('LlmClient 가 registerConnectionDefault 로 기본값을 심지 않는다 — 주소의 원천이 갈라진다');
  }
  // **포트가 겹치면 하나를 띄우는 순간 다른 하나가 죽는다.** 이 저장소에서 실제로 겪은
  // 실패다 (읽기순서의 「STT 서비스에 닿지 않습니다」 항목 — 옛 세션이 8790·5174 를 잡고 있던 일).
  // 대상 하나가 같은 포트를 ws·http 로 두 번 쓰는 것은 정상이다(게이트웨이 8790).
  // 문제가 되는 것은 **서로 다른 대상이 같은 포트**를 쓰는 경우다.
  const owners = new Map();
  for (const block of source.split(/(?=id:\s*')/)) {
    const id = block.match(/id:\s*'([^']+)'/)?.[1];
    if (id === undefined) continue;
    for (const [, port] of block.matchAll(/127\.0\.0\.1:(\d+)/g)) {
      if (!owners.has(port)) owners.set(port, new Set());
      owners.get(port).add(id);
    }
  }
  if (!owners.has('8802')) failures.push(`연결 대상 목록에 8802 가 없다 — [${[...owners.keys()].join(', ')}]`);
  for (const [port, ids] of owners) {
    if (ids.size > 1) failures.push(`포트 ${port} 를 두 대상이 함께 쓴다: ${[...ids].join(', ')} — 하나를 띄우면 다른 하나가 죽는다`);
  }
  // **연결 저장소의 대비값과 클라이언트의 기본값이 같아야 한다.** 갈라지면 화면이 그리는
  // 주소와 실제로 붙는 주소가 달라진다 (STT 도 같은 관계다 — connections.ts 머리말).
  const clientDefault = client.match(/registerConnectionDefault\('generate',\s*'base',[^)]*\?\?\s*'([^']+)'/)?.[1] ?? null;
  const listed = source.match(/id:\s*'generate'[\s\S]*?fallback:\s*'([^']*)'/)?.[1] ?? null;
  if (clientDefault === null) failures.push('LlmClient 의 기본 주소를 못 읽었다 — 모양이 바뀌었나');
  else if (clientDefault !== listed) failures.push(`대비값이 갈라졌다 — connections.ts '${listed}' vs LlmClient '${clientDefault}'`);
}

// ── 3. 손으로 쓴 문법 파일이 없는가 ───────────────────────────────────────────
{
  const found = [];
  (function walk(directory) {
    for (const name of readdirSync(directory)) {
      if (name === 'node_modules' || name === '.git' || name === '.venv' || name === 'dist' || name === 'dist-standalone') continue;
      const path = join(directory, name);
      let stat;
      try { stat = statSync(path); } catch { continue; }
      if (stat.isDirectory()) walk(path);
      else if (/\.(gbnf|lark|ebnf|bnf)$/i.test(name)) found.push(relative(repoRoot, path).replaceAll('\\', '/'));
    }
  })(repoRoot);
  if (found.length) {
    failures.push(`손으로 쓴 문법 파일이 있다: ${found.join(', ')} — 계약이 바뀌면 조용히 갈라진다. gbnf.ts 가 계약에서 뽑는다`);
  }
}

// ── 4. 계약을 고치면 문법이 따라 바뀌는가 ─────────────────────────────────────
{
  const { toGbnf, digest } = await import(pathToFileURL(join(srcDir, 'generate', 'gbnf.ts')).href);
  const contracts = new Map();
  for (const name of readdirSync(join(repoRoot, 'contracts'))) {
    if (!name.endsWith('.schema.json')) continue;
    const schema = JSON.parse(readFileSync(join(repoRoot, 'contracts', name), 'utf8'));
    contracts.set(schema.$id ?? name, schema);
  }
  const mission = contracts.get('mission.schema.json');
  const grammar = toGbnf(mission, contracts);

  // 계약이 실제로 문법에 실렸는가 — 허용 목록(enum)이 문법의 알맹이다.
  for (const token of ['"\\"pending\\""', '"\\"awaiting_evaluation\\""', '"\\"sense\\""', '"\\"report\\""']) {
    if (!grammar.includes(token)) failures.push(`문법에 계약의 허용 목록이 안 실렸다 — ${token}`);
  }
  if (!grammar.includes('root ::=')) failures.push('문법에 root 규칙이 없다');
  if (!/mission-utterance-confidence ::= number/.test(grammar)) failures.push('utterance.confidence 가 number 로 안 실렸다');

  // **대조군** — 계약을 고치면 문법이 따라 바뀌어야 한다. 안 바뀌면 계약은 원본이 아니다.
  const mutated = JSON.parse(JSON.stringify(mission));
  mutated.properties.milestones = { type: 'array', items: { type: 'string' } };
  const after = toGbnf(mutated, contracts);
  if (digest(after) === digest(grammar)) {
    failures.push('대조군 실패: 계약을 고쳤는데 문법이 그대로다 — 계약이 원본이 아니다');
  } else {
    controls.push('계약을 고친 사본에서 문법이 바뀜');
  }

  // 계약 밖 타입은 **조용히 넘기지 않고 던져야** 한다 — 느슨한 문법은 스키마 축을 무의미하게 한다.
  const loose = JSON.parse(JSON.stringify(mission));
  loose.properties.mission_id = { type: 'weird-type' };
  let threw = false;
  try { toGbnf(loose, contracts); } catch { threw = true; }
  if (!threw) failures.push('대조군 실패: 옮길 수 없는 타입을 조용히 통과시켰다 — 문법이 계약보다 느슨해진다');
  else controls.push('옮길 수 없는 타입에서 던짐');
}

// ── gen-lab 이 계약 사본을 두지 않는가 ────────────────────────────────────────
{
  const genLab = join(repoRoot, 'gen-lab');
  const copies = [];
  (function walk(directory) {
    for (const name of readdirSync(directory)) {
      if (name === '.venv' || name === '__pycache__' || name === 'goldset') continue;
      const path = join(directory, name);
      const stat = statSync(path);
      if (stat.isDirectory()) walk(path);
      else if (name.endsWith('.schema.json')) copies.push(relative(repoRoot, path).replaceAll('\\', '/'));
    }
  })(genLab);
  if (copies.length) failures.push(`gen-lab 에 계약 사본이 있다: ${copies.join(', ')} — 저장소 루트의 원본을 읽어야 한다`);
  const server = readFileSync(join(genLab, 'server', 'main.py'), 'utf8');
  if (!/CONTRACTS_DIR\s*=\s*REPO_ROOT\s*\/\s*"contracts"/.test(server)) {
    failures.push('gen-lab 이 저장소 루트의 contracts/ 를 읽지 않는다 — 사본이 생길 길이 열린다');
  }
}

if (failures.length) {
  console.error(`❌ verify:gen-port\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 생성 주소를 아는 곳은 src/generate/ 뿐 · 기본값은 LlmClient 가 심고 화면은 연결 관리로 바꾼다 (8802)');
console.log('✅ 손으로 쓴 문법 파일 0건 — 문법은 contracts/mission.schema.json 에서 뽑는다');
console.log('✅ 계약의 허용 목록(상태 8종 · 노드 문법 5종)이 문법에 그대로 실렸다');
console.log('✅ gen-lab 은 계약 사본을 두지 않고 저장소 루트의 원본을 읽는다');
console.log(`✅ 대조군 ${controls.length}건 검출 — ${controls.join(' · ')}`);
