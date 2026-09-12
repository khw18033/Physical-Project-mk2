// verify:detect-map (260912 신설 — 탐지 연동 2단계-B)
//
// **탐지가 준 모양을 화면이 읽는 모양으로 바꾸는 자리를 지킨다.**
//
// 막으려는 실패 다섯.
//
//  1. **한 칸 밀림** — `rotation_deg / step_deg` 가 칸 번호다. 한 칸 밀려도 화면은 그럴싸하게
//     돌아간다(여덟이 차례로 켜지고 초록도 하나 뜬다). 눈으로는 못 잡는다.
//  2. **점수를 확률로 그리는 것** — 찾은 프레임의 `final_score` 가 0.2696 이다. 「27%」로
//     적으면 「거의 못 찾았다」로 읽히는데, 실제로는 관문 넷을 다 통과한 판정이다.
//  3. **깊이값을 거리로 그리는 것** — 시료가 `distance_cm: 0.0` · 보정범위 밖으로 왔고,
//     자료가 「이 값 대신 도면상 고정 위치까지의 거리를 쓰라」고 직접 적었다.
//  4. **상자 형식** — 탐지는 `[x1,y1,x2,y2]`, 화면은 `[x,y,w,h]`. 우리가 바꾼다(260912 결정).
//  5. **초록이 둘** — 문이 두 방향에서 잡히는 것은 가정이 아니라 측정값이다. 받은 시료에서
//     270도와 315도가 둘 다 찾혔고 점수 차이가 0.0016 이었다.
//
// 재료는 **받은 시료 그대로**다. 지어낸 값으로 검사하면 위의 성질이 통째로 빠진다.
//
// 대조군 포함.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const sample = (...p) => JSON.parse(readFileSync(join(root, '..', 'door_example', 'test', ...p), 'utf8'));

const { indexOfRotation, boxOf, reasonOf, chosenFrame, usableDistanceCm, SCORE_LABEL } =
  await load('src', 'detect', 'parse.ts');

const failures = [];
const controls = [];

const summary = sample('door', 'target_summary.json');
const found113 = sample('door', 'frame_000113', 'evidence.json');
const found132 = sample('door', 'frame_000132', 'evidence.json');
const STEP = 45;
const COUNT = 8;

// ── 1. 각도 → 칸 번호 ───────────────────────────────────────────────────────
{
  const got = summary.frames.map((f) => indexOfRotation(f.rotation_deg, STEP, COUNT));
  if (got.join(',') !== '0,1,2,3,4,5,6,7') failures.push(`여덟 각도가 [${got.join(',')}] 로 옮았다 — 0~7 이어야 한다`);
  // 범위 밖은 버린다 — 없는 칸을 만들어 그리면 화면이 대본보다 커진다.
  for (const deg of [-45, 360, 405]) {
    if (indexOfRotation(deg, STEP, COUNT) !== null) failures.push(`범위 밖 ${deg}도가 칸을 냈다`);
  }
  // 딱 안 떨어지는 각도는 우리가 정할 일이 아니다.
  if (indexOfRotation(44.7, STEP, COUNT) !== null) failures.push('44.7도를 어느 칸으로 몰아넣었다');
  // step_deg 를 45 로 박지 않았는가 — 스캔 파라미터라 화면에서 바뀐다.
  if (indexOfRotation(90, 30, 12) !== 3) failures.push('step_deg 가 45 로 박혀 있다');
}

// ── 2. 초록은 하나 · 실제로 둘이 찾혔다 ─────────────────────────────────────
{
  const hits = summary.frames.filter((f) => f.found);
  if (hits.length !== 2) failures.push(`시료에서 찾힌 각도가 ${hits.length}개다 — 2개여야 한다 (검사가 헛돈다)`);
  const scoreOf = (f) => (f.frame === found113.frame ? found113.final_score : f.frame === found132.frame ? found132.final_score : 0);
  const best = chosenFrame(summary.frames, scoreOf);
  if (best?.rotation_deg !== 270) failures.push(`고른 각도가 ${best?.rotation_deg} 다 — 270도(점수 더 높음)여야 한다`);
  if (indexOfRotation(best.rotation_deg, STEP, COUNT) !== 6) failures.push('270도가 6번 칸이 아니다');
  // 하나도 못 찾으면 **안 고른다.** 임의로 한 방향을 고르면 안 된다.
  if (chosenFrame(summary.frames.map((f) => ({ ...f, found: false })), scoreOf) !== null) {
    failures.push('하나도 못 찾았는데 한 방향을 골랐다');
  }
  // 동점이면 먼저 본 각도 — 같은 판을 다시 그릴 때 답이 바뀌면 안 된다.
  const tied = chosenFrame(summary.frames.filter((f) => f.found), () => 1);
  if (tied?.rotation_deg !== 270) failures.push('동점에서 고른 것이 먼저 본 각도가 아니다');
}

// ── 3. 상자 형식 ───────────────────────────────────────────────────────────
{
  const box = boxOf(found113.box_xyxy);
  const [x1, y1, x2, y2] = found113.box_xyxy;
  if (box === null) failures.push('상자를 못 읽는다');
  else if (box.join(',') !== [x1, y1, x2 - x1, y2 - y1].join(',')) {
    failures.push(`상자가 [${box.join(',')}] 로 왔다 — [x,y,w,h] 여야 한다`);
  }
  // 뒤집힌 상자도 받는다 — 음수 폭은 그리는 쪽에서 사라져 「못 찾았다」와 구별이 안 된다.
  if (boxOf([160, 143, 140, 89])?.join(',') !== '140,89,20,54') failures.push('뒤집힌 상자를 못 바로잡는다');
  for (const bad of [null, [1, 2, 3], [1, 2, 3, NaN]]) {
    if (boxOf(bad) !== null) failures.push(`망가진 상자 ${JSON.stringify(bad)} 를 받아들였다`);
  }
}

// ── 4. 문장은 관문에서 나온다 · 점수는 확률이 아니다 ────────────────────────
{
  const words = reasonOf(found113, true);
  for (const must of ['통과', SCORE_LABEL]) {
    if (!words.includes(must)) failures.push(`판단 문장에 「${must}」 가 없다 — ${words}`);
  }
  // 관문 넷이 다 통과였으니 넷이 다 문장에 있어야 한다.
  const passed = Object.values(found113.mandatory_gates).filter((g) => g.passed).length;
  if (passed !== 4) failures.push(`시료의 통과 관문이 ${passed}개다 — 4개여야 한다 (검사가 헛돈다)`);
  if (words.split('·').length < passed) failures.push(`문장이 관문 ${passed}개를 다 안 담았다 — ${words}`);
  // **퍼센트로 적지 않는다.** 0.2696 을 27% 로 적으면 「거의 못 찾았다」로 읽힌다.
  if (/%/.test(words)) failures.push(`판단 문장이 퍼센트를 쓴다 — ${words}`);
  if (reasonOf(null, false) !== '문 없음') failures.push('못 찾은 각도의 문장이 「문 없음」이 아니다');
  // **찾았는데 안 고른 칸.** 「통과」라고 적으면 통과했다면서 탈락이라 화면이 모순된다.
  // 「문 없음」도 거짓이다 — 문은 거기 있었고 우리가 다른 쪽을 골랐을 뿐이다.
  const loser = reasonOf(found132, true, false);
  if (/통과/.test(loser)) failures.push(`안 고른 칸이 「통과」라고 적힌다 — ${loser}`);
  if (loser === '문 없음') failures.push('안 고른 칸을 「문 없음」이라고 적는다 — 문은 거기 있었다');
  if (!/안 고름/.test(loser)) failures.push(`안 고른 이유가 없다 — ${loser}`);
}

// ── 5. 깊이값을 거리로 그리지 않는다 ────────────────────────────────────────
{
  const hit = summary.frames.find((f) => f.found);
  if (hit.in_valid_calibration_range !== false) failures.push('시료의 보정범위 밖 표시가 사라졌다 — 검사가 헛돈다');
  if (usableDistanceCm(hit) !== null) failures.push('보정범위 밖 깊이값을 거리로 쓴다 — 0.0m 가 화면에 뜬다');
  // 보정범위 안이고 값이 있으면 쓴다.
  if (usableDistanceCm({ ...hit, in_valid_calibration_range: true, distance_cm: 715.4 }) !== 715.4) {
    failures.push('쓸 수 있는 거리까지 버린다');
  }
}

// ── 5-b. 화면이 점수를 퍼센트로 만들지 않는가 (260912 실측) ─────────────────
//
// `reasonOf` 가 퍼센트를 안 써도 **화면이 따로 만들면 소용이 없다.** 실제로 그랬다 —
// 그래프가 `confidence * 100` 으로 「문 있음 · 27%」를 그리고 있었다. 문장을 만드는 쪽만
// 보는 검사는 이것을 못 잡는다.
{
  const graph = readFileSync(join(root, 'src', 'graph', 'TaskGraph.tsx'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  if (/confidence \* 100/.test(graph) || /Math\.round\(cell\.detection\.confidence/.test(graph)) {
    failures.push('화면이 점수를 퍼센트로 만든다 — 0.27 이 「27%」로 보이면 「거의 못 찾았다」로 읽힌다');
  }
  // 대신 탐지가 준 문장을 쓴다.
  if (!/cell\.detection\?\.reason/.test(graph)) {
    failures.push('화면이 판단 문장을 안 쓴다 — 관문에서 조립한 근거가 버려진다');
  }
}

// ── 5-c. 다 보기 전에는 판정하지 않는다 (260912 지시) ───────────────────────
//
// 시료 파일에는 여덟 각도가 다 들어 있다. 그대로 내놓으면 **시작하자마자 정답이 이미
// 정해진 채로** 화면이 뜬다 — 실제 서비스는 한 각도가 끝날 때마다 하나씩 준다.
//
// 그리고 세 각도만 보고 「여기가 제일 높다」고 초록을 켜면, 다섯째에서 더 높은 것이
// 나왔을 때 **초록이 옮겨 다닌다.**
{
  const { sampleRevealed } = await load('src', 'detect', 'DetectClient.ts');
  // 승인 전에는 아무것도 안 봤다.
  if (sampleRevealed(0, 8) !== 0) failures.push('승인 전인데 각도를 봤다고 한다');
  // 한 각도에 4초. 여덟이면 32초쯤 — 로봇이 실제로 도는 시간과 비슷해야 한다.
  if (sampleRevealed(4, 8) !== 1) failures.push(`4초에 ${sampleRevealed(4, 8)}각도 — 1개여야 한다`);
  if (sampleRevealed(31, 8) !== 7) failures.push(`31초에 ${sampleRevealed(31, 8)}각도 — 7개여야 한다`);
  // 넘치지 않는다.
  if (sampleRevealed(9999, 8) !== 8) failures.push('여덟을 넘겨 내놓는다');

  // **시작 전에는 시계가 0이다.** 승인 시각으로 물러나면 승인하고 설명하는 동안 각도가
  // 열려, 눌렀을 때 이미 다 끝난 화면이 된다 — 실제로 그렇게 보였다.
  const session = readFileSync(join(root, 'src', 'physical', 'robotSession.ts'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  if (/startedAtMs \?\? session\.approvedAtMs/.test(session)) {
    failures.push('시작 전 시계가 승인 시각으로 흐른다 — 눌렀을 때 이미 다 열린 화면이 된다');
  }
  if (!/if \(session\.startedAtMs === null\) return 0;/.test(session)) {
    failures.push('시작 전에 시계를 0으로 두지 않는다');
  }

  const bridge = readFileSync(join(root, 'src', 'detect', 'detectBridge.ts'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  if (!/if \(!sweepDone\(count\)\) return null;/.test(bridge)) {
    failures.push('다 보기 전에 초록을 켠다 — 더 높은 각도가 나오면 초록이 옮겨 다닌다');
  }
  // 도는 동안 찾은 각도를 탈락으로 칠하면 안 된다 — 판정이 안 난 것이지 탈락이 아니다.
  if (!/if \(!done && result\.found\) continue;/.test(bridge)) {
    failures.push('도는 동안 찾은 각도를 칠한다 — 초록도 탈락도 아닌데 둘 중 하나로 거짓을 말한다');
  }
  // 근거도 판정 뒤다.
  const views = readFileSync(join(root, 'src', 'detect', 'views', 'DetectViews.tsx'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  if (!/sweepDone\(count\)/.test(views)) failures.push('근거가 판정보다 먼저 뜬다');
}

// ── 5-d. 탐지가 태스크 노드를 민다 (260912 지시) ────────────────────────────
//
// 여덟 칸이 다 차고 초록까지 떠도 **태스크 노드는 그대로 대기**였다. 그러면 마일스톤이
// 안 끝나고 다음 마일스톤으로도 안 넘어간다 — 임무가 거기서 멎는다.
//
// **없는 것을 끝났다고 하지는 않는다.** 이동·정지·종료는 로봇이 움직여야 끝나는 것이고
// 탐지는 그것을 모른다.
{
  const trace = readFileSync(join(root, 'src', 'detect', 'detectTrace.ts'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  for (const node of ['T-A1', 'T-A2', 'T-A3', 'T-A5', 'T-A6', 'T-B1']) {
    if (!trace.includes(node)) failures.push(`탐지가 ${node} 를 안 민다 — 그 노드가 대기로 남아 마일스톤이 안 끝난다`);
  }
  // 로봇이 해야 끝나는 것을 탐지가 끝냈다고 하면 안 된다.
  for (const node of ['T-B2', 'T-B3', 'T-C1']) {
    if (trace.includes(`'${node}'`)) {
      failures.push(`탐지가 ${node} 를 끝냈다고 한다 — 로봇이 움직여야 끝나는 것이다`);
    }
  }
  // 못 고르면 판단이 안 끝난다 — 「문을 찾지 못함」은 완료가 아니다.
  if (!/chosen !== null/.test(trace)) failures.push('못 골랐는데도 판단을 끝냈다고 한다');

  // 이동 버튼이 탐지 경로로도 열려야 한다 — 로봇의 door_turn 만 보면 영영 안 뜬다.
  const cmd = readFileSync(join(root, 'src', 'physical', 'robotCommands.ts'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  if (!/detectState\(\)\.path !== null/.test(cmd)) {
    failures.push('이동 버튼이 탐지 경로를 안 본다 — 경로가 나왔는데 버튼이 안 뜬다');
  }
  // 회전 먼저, 직진 나중 — 돌기 전에 가면 엉뚱한 데로 간다.
  const { pathCommands } = await load('src', 'physical', 'missionLink.ts');
  const left = pathCommands('왼쪽(반시계)으로 90.0도 회전', 90, 6.354);
  if (left.map((c) => c.action).join(',') !== 'turn,move_forward') {
    failures.push(`경로 명령이 [${left.map((c) => c.action).join(',')}] — turn 이 먼저여야 한다`);
  }
  if (left[0]?.parameters?.deg !== -90) failures.push(`왼쪽 회전이 ${left[0]?.parameters?.deg} — 오른쪽이 + 라 -90 이어야 한다`);
  const right = pathCommands('오른쪽(시계)으로 30도 회전', 30, 1);
  if (right[0]?.parameters?.deg !== 30) failures.push('오른쪽 회전의 부호가 틀렸다');
  // 규약 범위 밖은 안 낸다 — 5도 미만·0.05m 미만은 거절당한다.
  if (pathCommands('오른쪽으로 2도', 2, 0.01).length !== 0) failures.push('규약이 안 받는 값을 낸다');
}

// ── 6. 경계 — 탐지를 아는 면이 src/detect/ 하나인가 ─────────────────────────
{
  const { readdirSync, statSync } = await import('node:fs');
  const walk = (dir) => readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : /\.(ts|tsx)$/.test(name) ? [full] : [];
  });
  const strip = (t) => t.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  for (const file of walk(join(root, 'src'))) {
    if (file.includes(join('src', 'detect'))) continue;
    const source = strip(readFileSync(file, 'utf8'));
    if (/\/detect-sample/.test(source)) failures.push(`${file} 에 탐지 시료 경로가 있다 — 경계 밖이다`);
    if (/\/detect\/(results|frame|path|evidence|features)/.test(source)) {
      failures.push(`${file} 에 탐지 엔드포인트가 있다 — 경계 밖이다`);
    }
  }
  // 경계 안에는 실제로 있어야 한다 — 검사가 헛돌지 않게.
  const client = readFileSync(join(root, 'src', 'detect', 'DetectClient.ts'), 'utf8');
  if (!/\/detect-sample/.test(client)) failures.push('DetectClient 에 시료 경로가 없다 — 검사가 헛돈다');
  if (!/\/detect\/results/.test(client)) failures.push('DetectClient 에 엔드포인트가 없다 — 검사가 헛돈다');
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  controls.push(name);
}
{
  // **한 칸 민 사본.** `rotation_deg / step_deg + 1` 로 두면 270도가 7번을 노린다.
  const shifted = (deg) => Math.round(deg / STEP) + 1;
  control('한 칸 민 사본 (rotation/step + 1)', shifted(270) !== indexOfRotation(270, STEP, COUNT));
}
{
  // **점수를 퍼센트로 적은 사본.**
  const asPercent = `${Math.round(found113.final_score * 100)}%`;
  control('점수를 퍼센트로 적은 사본 (27%)', asPercent === '27%' && !reasonOf(found113, true).includes('%'));
}
{
  // **상자를 그대로 쓴 사본.** `[x1,y1,x2,y2]` 를 `[x,y,w,h]` 로 읽으면 폭이 160이 된다.
  const raw = found113.box_xyxy;
  control('상자를 안 바꾼 사본 (x2 를 폭으로)', raw[2] !== boxOf(raw)[2]);
}

if (failures.length) {
  console.error(`❌ verify:detect-map\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 여덟 각도가 0~7 로 옮는다 — 범위 밖·안 떨어지는 각도는 버리고 step_deg 를 안 박았다');
console.log('✅ 시료도 한 각도씩 — 4초에 하나, 여덟을 다 본 뒤에 판정·근거·경로가 나온다');
console.log('✅ 초록은 하나 — 시료에서 실제로 둘이 찾혔고(270·315) 점수 높은 쪽을 고른다, 없으면 안 고른다');
console.log('✅ 상자를 [x,y,w,h] 로 바꾼다 · 판단 문장은 관문 넷에서 나오고 화면도 퍼센트를 안 만든다');
console.log('✅ 보정범위 밖 깊이값을 거리로 안 그린다 (시료는 0.0cm · 범위 밖)');
console.log('✅ 탐지가 태스크 노드를 민다 — 이동·정지·종료는 안 민다(로봇이 해야 끝난다) · 회전 먼저 직진 나중');
console.log('✅ 탐지를 아는 면이 src/detect/ 하나 — 시료 경로·엔드포인트가 경계 밖에 0건');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
