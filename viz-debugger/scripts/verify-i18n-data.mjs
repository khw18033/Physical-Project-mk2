// verify:i18n-data (260918 신설 — 영문화 3단계 §5)
//
// **데이터의 영어가 조용히 낡지 않게 한다.**
//
// 3단계는 화면 문구가 아니라 **대본과 레지스트리가 들고 온 값**을 옮겼다. 사전(`i18n/`)과
// 달리 이쪽은 원본이 자주 바뀐다 — 대본에 태스크 한 줄이 늘면 사이드카는 그대로다.
// 그러면 영문 화면에 그 한 줄만 한국어로 남고, **아무도 모른다.**
//
// 그래서 셋을 본다.
//
//   1. **빠진 것이 없다** — 대본의 표시 자리 한글이 전부 사이드카에 있다
//   2. **죽은 항목이 없다** — 사이드카에 있는데 원본에 없는 한국어 (문장을 고치면 생긴다)
//   3. **레지스트리의 표시 이름마다 `_en` 이 있다** — 별칭도 같이 본다
//
// 표시 자리의 목록은 `scripts/lib/scriptPhrases.mjs` 하나다. 생성기와 이 검사가 **같은
// 잣대**를 봐야 「다 있다」가 참이 된다 — 갈라지면 둘 다 자기 기준으로 초록이 된다.
//
// 대조군 — 사이드카에서 한 줄을 지운 사본과, 원본에 없는 한국어를 넣은 사본이 잡혀야 한다.
import { existsSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readSource } from './lib/source.mjs';
import { displayPhrases, DISPLAY_PATHS } from './lib/scriptPhrases.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const scenarioDir = join(root, 'scenarios');
const registryPath = join(root, '..', 'web-dashboard', 'mock-gateway', 'registry.json');

const failures = [];
const controls = [];

const readJson = (path) => JSON.parse(readSource(path));

/** 대본 원본들 — 사이드카(`.en.json` · `.match.json`)는 대본이 아니다. */
const scripts = readdirSync(scenarioDir)
  .filter((name) => /^MSN-[\d-]+\.json$/.test(name))
  .map((name) => ({ name, data: readJson(join(scenarioDir, name)) }));

// ── 1. 편마다 사이드카가 있고, 빠진 문구가 없다 ──────────────────────────────
{
  let total = 0;
  for (const { name, data } of scripts) {
    const sidecarPath = join(scenarioDir, `${data.missionId}.en.json`);
    if (!existsSync(sidecarPath)) {
      failures.push(`${data.missionId} 의 영어 사이드카가 없다 — 영문 화면에서 이 편이 통째로 한국어다 (${name})`);
      continue;
    }
    const sidecar = readJson(sidecarPath);
    if (sidecar.missionId !== data.missionId) {
      failures.push(`${data.missionId}.en.json 의 missionId 가 다르다 (${sidecar.missionId}) — 조회가 안 걸린다`);
    }
    const phrases = sidecar.phrases ?? {};
    const wanted = displayPhrases(data);
    const missing = [...wanted.keys()].filter((ko) => typeof phrases[ko] !== 'string' || phrases[ko].trim() === '');
    for (const ko of missing) {
      failures.push(`${data.missionId} — 영어가 없는 문구 [${wanted.get(ko)}] 「${ko}」`);
    }
    // 죽은 항목: 사이드카에 있는데 원본에 더는 없는 한국어.
    const dead = Object.keys(phrases).filter((ko) => !wanted.has(ko));
    for (const ko of dead) {
      failures.push(`${data.missionId} — 원본에 없는 항목 「${ko}」 (문장을 고쳤다면 사이드카에서도 지워라)`);
    }
    total += wanted.size;
  }
  console.log(`✅ 대본 ${scripts.length}편 · 표시 문구 ${total}개 — 빠진 것도 죽은 것도 0건 (보는 자리 ${DISPLAY_PATHS.length}가지)`);
}

// ── 2. 영어 조회 규칙이 있다 ─────────────────────────────────────────────────
//
// 없으면 영어로 말했을 때 그 편을 못 고른다. `must` 가 비면 `matchesRule` 이 늘 거짓이라
// **있으나 마나**이므로 그것까지 본다.
{
  for (const { data } of scripts) {
    const sidecarPath = join(scenarioDir, `${data.missionId}.en.json`);
    if (!existsSync(sidecarPath)) continue;
    const m = readJson(sidecarPath).match_en;
    if (m === undefined) { failures.push(`${data.missionId} — match_en 이 없다. 영어로 말하면 이 편을 못 고른다`); continue; }
    if (!Array.isArray(m.must) || m.must.length === 0 || m.must.some((g) => !Array.isArray(g) || g.length === 0)) {
      failures.push(`${data.missionId} — match_en.must 가 비어 있다. matchesRule 이 늘 거짓이라 규칙이 있으나 마나다`);
    }
    if (m.must?.some((g) => g.some((w) => /[가-힣]/.test(String(w))))) {
      failures.push(`${data.missionId} — match_en 에 한글이 있다. 영어 규칙이 아니다`);
    }
  }
  console.log('✅ 영어 조회 규칙 — 편마다 있고 must 가 비지 않았다');
}

// ── 3. 레지스트리의 표시 이름마다 `_en` ──────────────────────────────────────
{
  const reg = readJson(registryPath);
  for (const group of ['zones', 'nodes', 'entities']) {
    for (const item of reg[group] ?? []) {
      if (!item.display_name) continue;
      if (!item.display_name_en) {
        failures.push(`registry ${group}/${item.id} — display_name_en 이 없다 (「${item.display_name}」)`);
      }
      // 별칭은 STT 가 쓴다. 한국어 별칭이 있는데 영어가 없으면 **영어 발화가 그 이름을 못 집는다.**
      const ko = (item.aliases ?? []).filter(Boolean);
      const en = (item.aliases_en ?? []).filter(Boolean);
      if (ko.length > 0 && en.length === 0) {
        failures.push(`registry ${group}/${item.id} — 한국어 별칭 ${ko.length}개인데 aliases_en 이 비었다. 영어 발화가 이 이름을 못 집는다`);
      }
      if (en.some((a) => /[가-힣]/.test(String(a)))) {
        failures.push(`registry ${group}/${item.id} — aliases_en 에 한글이 있다`);
      }
    }
  }
  console.log('✅ 레지스트리 — 표시 이름마다 영어가 있고, 한국어 별칭이 있으면 영어 별칭도 있다');
}

// ── 4. 대조군 ────────────────────────────────────────────────────────────────
{
  const sample = scripts.find((s) => s.data.missionId === 'MSN-260909-01');
  if (sample === undefined) {
    failures.push('대조군을 만들 대본(MSN-260909-01)이 없다 — 이 검사의 잣대를 시험하지 못했다');
  } else {
    const wanted = displayPhrases(sample.data);
    const real = readJson(join(scenarioDir, 'MSN-260909-01.en.json')).phrases;
    const first = [...wanted.keys()][0];

    // ① 한 줄을 지운 사본은 **빠진 것**으로 잡혀야 한다.
    const holed = { ...real };
    delete holed[first];
    const missed = [...wanted.keys()].filter((ko) => typeof holed[ko] !== 'string');
    if (missed.length !== 1 || missed[0] !== first) {
      failures.push('대조군 실패: 사이드카에서 한 줄을 지웠는데 빠진 것으로 안 잡혔다 — 이 검사는 무의미하다');
    } else controls.push('한 줄 지운 사본을 「빠짐」으로 잡는다');

    // ② 원본에 없는 한국어는 **죽은 항목**으로 잡혀야 한다.
    const stale = { ...real, '이 문장은 대본에 없다': 'not in the script' };
    const dead = Object.keys(stale).filter((ko) => !wanted.has(ko));
    if (dead.length !== 1) {
      failures.push('대조군 실패: 원본에 없는 항목을 넣었는데 안 잡혔다');
    } else controls.push('원본에 없는 항목을 「죽은 것」으로 잡는다');

    // ③ 개발 메모(`note`)는 **잡으면 안 된다** — 화면에 안 뜬다.
    if (typeof sample.data.note === 'string' && wanted.has(sample.data.note)) {
      failures.push('대조군 실패: 개발 메모를 표시 문구로 셌다 — 사전이 개발 메모로 부푼다');
    } else controls.push('개발 메모는 세지 않는다');

    // ④ 조회 규칙의 한국어 키워드도 **잡으면 안 된다** — `match_en` 이 따로 든다.
    const keyword = sample.data.match?.must?.[0]?.[0];
    if (typeof keyword === 'string' && wanted.has(keyword)) {
      failures.push('대조군 실패: 조회 규칙 키워드를 표시 문구로 셌다 — 그것은 match_en 의 몫이다');
    } else controls.push('조회 규칙 키워드는 세지 않는다');
  }
}

if (failures.length > 0) {
  console.error(`❌ verify:i18n-data\n- ${failures.join('\n- ')}`);
  console.error('\n   대본을 고치면 그 편의 `MSN-*.en.json` 도 같이 고쳐야 한다.');
  console.error('   원본 키(한국어)는 지우지 않는다 — 영어가 없으면 한국어로 떨어지는 것이 설계다.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
