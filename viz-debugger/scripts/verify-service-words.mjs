// verify:service-words (260919 신설 — 영문화 5단계 §4)
//
// **탐지 서비스가 한국어로 말한다.** 그 말이 영문 화면에 그대로 뜨지 않게 한다.
//
// 이 서비스는 **우리 저장소에 없다** — 탐지 파트의 PC에서 도는 별도 프로그램이라
// 「영어로도 말해 달라」고 고칠 수가 없다. 게이트웨이(우리 것)와 다른 점이 이것이다.
// 그래서 받은 문장을 우리가 옮기고, **원문은 로그의 상세 줄에 남긴다**(260919 결정).
//
// 보는 것 넷.
//  1. **기록 45판에서 실제로 받은 문장**이 전부 덮인다 — 서비스가 새 말을 뱉으면 여기가 빨개진다
//  2. **한국어 화면은 한 글자도 안 달라진다** — `ko` 면 입력을 그대로 돌려준다
//  3. **숫자가 살아 있다** — 각도·거리가 문장을 옮기다 사라지면 안 된다
//  4. **모르는 문장은 지어내지 않는다** — 한국어 그대로 통과시킨다
import { readdirSync, existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const failures = [];
const controls = [];

const { serviceWords, isTranslated } = await load('src', 'i18n', 'serviceWords.ts');

/** 화면이 그리는 자리. 기록에서 이 넷만 모은다 — 나머지는 기록 안의 값이고 화면에 안 뜬다. */
function screenBound(src) {
  if (src === null || src === undefined) return [];
  return [
    src.turn_instruction,
    src.path_mode_words,
    src.reason,
    ...(src.fallback_chain ?? []).map((s) => s.detail),
  ].filter((v) => typeof v === 'string' && v !== '');
}

// ── 1. 실제로 받은 문장이 전부 덮인다 ───────────────────────────────────────
{
  const seen = new Set();
  const histRoot = join(root, '..', 'mission-history');
  let runs = 0;
  if (existsSync(histRoot)) {
    for (const day of readdirSync(histRoot)) {
      for (const run of readdirSync(join(histRoot, day))) {
        const file = join(histRoot, day, run, 'progress.json');
        if (!existsSync(file)) continue;
        runs += 1;
        const detect = JSON.parse(readFileSync(file, 'utf8')).detect;
        if (detect === undefined || detect === null) continue;
        for (const src of [detect.path, detect.pathFailureDetail]) {
          for (const line of screenBound(src)) seen.add(line);
        }
      }
    }
  }

  const left = [...seen].filter((k) => /[가-힣]/.test(serviceWords(k, 'en')));
  for (const k of left.slice(0, 6)) {
    failures.push(`못 옮기는 문장 — 「${k.length > 70 ? `${k.slice(0, 70)}…` : k}」`);
  }
  if (left.length > 6) failures.push(`그 밖 ${left.length - 6}건`);
  if (seen.size === 0) failures.push('기록에서 문장을 하나도 못 모았다 — 이 검사가 아무것도 안 재고 있다');
  console.log(`✅ 기록 ${runs}판의 서로 다른 문장 ${seen.size}가지 — 못 옮긴 것 ${left.length}건`);
}

// ── 2. 한국어 화면은 한 글자도 안 달라진다 ──────────────────────────────────
{
  const samples = [
    '왼쪽(반시계)으로 55.5도 회전',
    '도면 위 로봇 자리에서 목표까지 산출 (B -- 문만으로 추정한 위치)',
    '문 거리 582.8cm(겉보기 크기) · 문 방위 122.0도(bearing_refinement)',
  ];
  for (const one of samples) {
    if (serviceWords(one, 'ko') !== one) failures.push(`ko 에서 글자가 바뀐다 — 「${one}」`);
  }
  console.log(`✅ 한국어 화면 — 표본 ${samples.length}건이 입력 그대로다`);
}

// ── 3. 숫자가 살아 있다 ─────────────────────────────────────────────────────
{
  const cases = [
    ['왼쪽(반시계)으로 55.5도 회전', ['55.5']],
    ['오른쪽(시계)으로 122.1도 회전', ['122.1']],
    ['문 거리 582.8cm(겉보기 크기) · 문 방위 122.0도(bearing_refinement)', ['582.8', '122.0']],
    ['추정 위치 (159.4, 104.4)cm가 단상 안', ['159.4', '104.4']],
    ['단상 관측 2프레임', ['2']],
  ];
  for (const [ko, numbers] of cases) {
    const en = serviceWords(ko, 'en');
    for (const n of numbers) {
      if (!en.includes(n)) failures.push(`숫자 ${n} 이 사라졌다 — 「${ko}」 → 「${en}」`);
    }
  }
  console.log(`✅ 숫자 — 표본 ${cases.length}건에서 각도·거리가 전부 살아남는다`);
}

// ── 4. 대조군 ───────────────────────────────────────────────────────────────
{
  // 모르는 문장은 **지어내지 않는다.**
  const unknown = '탐지가 난생처음 보는 말을 했다';
  if (serviceWords(unknown, 'en') !== unknown) {
    failures.push('모르는 문장을 건드렸다 — 지어내면 안 된다');
  } else controls.push('모르는 문장은 한국어 그대로 통과시킨다');

  if (isTranslated(unknown, 'en')) failures.push('못 옮긴 문장을 옮겼다고 말한다 — 원문이 두 번 뜬다');
  else controls.push('못 옮긴 문장은 「옮겼다」고 말하지 않는다');

  if (isTranslated('왼쪽(반시계)으로 55.5도 회전', 'ko')) {
    failures.push('한국어 화면에서 「옮겼다」고 말한다 — 원문이 중복으로 뜬다');
  } else controls.push('한국어 화면에서는 원문을 안 보탠다');

  if (!isTranslated('왼쪽(반시계)으로 55.5도 회전', 'en')) {
    failures.push('옮긴 문장을 「안 옮겼다」고 말한다 — 원문이 안 남는다');
  } else controls.push('옮긴 문장에만 원문을 보탠다');

  // 이어진 문장이 통째로 옮겨지는가 (조각을 잇는 자리).
  const composite = '경로 산출 실패 -- 문이 어느 프레임에서도 검출되지 않음 -- 갈 방향이 없다';
  if (/[가-힣]/.test(serviceWords(composite, 'en'))) {
    failures.push(`이어진 문장의 조각이 남는다 — 「${serviceWords(composite, 'en')}」`);
  } else controls.push('` -- ` 로 이어진 조각도 전부 옮긴다');
}

if (failures.length > 0) {
  console.error(`❌ verify:service-words\n- ${failures.join('\n- ')}`);
  console.error('\n   탐지 서비스가 새 문장을 뱉으면 `src/i18n/serviceWords.ts` 의 `RULES` 에 더해라.');
  console.error('   모르는 문장은 한국어로 나간다 — 그것이 안전한 기본값이다.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
