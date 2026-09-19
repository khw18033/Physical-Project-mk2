// verify:gateway-i18n (260919 신설 — 영문화 5단계 §1)
//
// **게이트웨이가 요청한 언어로 답한다.**
//
// 4단계까지는 `src/` 만 봤다. 그런데 화면에 뜨는 한국어 중에는 게이트웨이가 **완성된
// 문장으로 보내 준 것**이 있었다 — 승인 팝업의 검증 문장, 제어 패널의 대상 이름,
// 명령 거절 사유. 260919 에 사람이 `?lang=en` 으로 보고 찾았다.
//
// 보는 것 넷.
//  1. 두 사전의 **모양이 맞는다** — en ⊆ ko · 치환자 집합이 같다
//  2. `say('키')` 가 **사전에 실재한다** · 사전에 **죽은 키가 없다**
//  3. 표지가 **전선에서 글자가 된다** — `sayJson()` 을 지나면 객체가 남지 않는다
//  4. 화면이 **언어를 실어 묻는다** — WS 주소와 HTTP 다섯
//
// 서버 콘솔(`log(...)`)은 대상이 아니다. `src/` 의 DEV_ONLY 와 같은 기준이다 —
// 「화면에 뜨는가」이지 「어디에 적히는가」가 아니다.
import { readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { pathToFileURL } from 'node:url';
import { isScratchPath } from './lib/scratch.mjs';
import { readSource } from './lib/source.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const failures = [];
const controls = [];

const { GW_KO } = await load('gateway', 'i18n.ko.ts');
const { GW_EN } = await load('gateway', 'i18n.en.ts');
const { say, sayJson, gwT, inEnglish, langOf } = await load('gateway', 'i18n.ts');

const holes = (s) => new Set([...String(s).matchAll(/\{(\w+)\}/g)].map((m) => m[1]));

// ── 1. 두 사전의 모양이 맞는다 ──────────────────────────────────────────────
{
  for (const key of Object.keys(GW_EN)) {
    if (!(key in GW_KO)) failures.push(`영어 사전의 '${key}' 가 한국어 사전에 없다 — 한국어가 원본이다`);
  }
  for (const [key, en] of Object.entries(GW_EN)) {
    const ko = GW_KO[key];
    if (ko === undefined) continue;
    const a = holes(ko);
    const b = holes(en);
    // **치환자가 어긋나면 값이 통째로 사라진다** — 짝이 한 칸 밀렸다는 가장 이른 자국이다.
    const missing = [...a].filter((h) => !b.has(h));
    const extra = [...b].filter((h) => !a.has(h));
    if (missing.length > 0) failures.push(`'${key}' — 영어에 없는 치환자 {${missing.join('} {')}}`);
    if (extra.length > 0) failures.push(`'${key}' — 한국어에 없는 치환자 {${extra.join('} {')}}`);
  }
  console.log(`✅ 사전 ko ${Object.keys(GW_KO).length} · en ${Object.keys(GW_EN).length} — en ⊆ ko · 치환자 집합이 같다`);
}

// ── 2. `say('키')` 가 실재하고, 사전에 죽은 키가 없다 ───────────────────────
{
  const files = [];
  (function walk(dir) {
    for (const name of readdirSync(dir)) {
      if (name.startsWith('.')) continue;
      const full = join(dir, name);
      if (isScratchPath(full)) continue;
      if (statSync(full).isDirectory()) walk(full);
      else if (/\.ts$/.test(name) && !/^i18n\./.test(name)) files.push(full);
    }
  })(join(root, 'gateway'));

  const used = new Set();
  for (const abs of files) {
    const rel = relative(root, abs).split(sep).join('/');
    const src = readSource(abs);
    for (const m of src.matchAll(/(^|[^A-Za-z0-9_$.])say\(\s*'([^']+)'/g)) {
      used.add(m[2]);
      if (!(m[2] in GW_KO)) failures.push(`${rel}: say('${m[2]}') 인데 한국어 사전에 그 키가 없다 — 화면에 키가 그대로 뜬다`);
    }
  }
  for (const key of Object.keys(GW_KO)) {
    if (!used.has(key)) failures.push(`사전의 '${key}' 를 아무도 안 쓴다 — 지워라 (죽은 키는 번역 검수만 늘린다)`);
  }
  console.log(`✅ say() ${used.size}개 키가 전부 사전에 있고, 사전에 죽은 키가 없다`);
}

// ── 3. 표지가 전선에서 글자가 된다 ──────────────────────────────────────────
{
  const msg = { a: say('zz.probe'), b: [say('zz.probe')], c: { d: say('zz.probe') }, n: 1 };
  for (const lang of ['ko', 'en']) {
    const out = sayJson(msg, lang);
    if (out.includes('__say')) failures.push(`${lang}: 표지가 전선에 그대로 나간다 — 화면이 객체를 글자로 그린다`);
  }
  // 키가 없으면 **키가 드러난다** — 조용히 빈칸이 되면 못 찾는다.
  if (gwT('en', 'zz.missing') !== 'zz.missing') failures.push('없는 키가 키로 안 드러난다');
  controls.push('없는 키는 키로 드러난다');

  // 영어가 없으면 한국어로 떨어진다 (부분 번역 상태에서도 화면이 정상이어야 한다).
  const onlyKo = Object.keys(GW_KO).find((k) => !(k in GW_EN));
  if (onlyKo !== undefined && gwT('en', onlyKo) !== GW_KO[onlyKo]) {
    failures.push(`'${onlyKo}' — 영어가 없는데 한국어로 안 떨어진다`);
  }
  controls.push('영어가 없으면 한국어로 떨어진다');

  // `_en` 고르기 — 원천이 두 벌을 들고 있는 자리 (레지스트리).
  const picked = inEnglish({ display_name: '수문 01', display_name_en: 'Floodgate 01', aliases: ['수문'], aliases_en: ['gate'] });
  if (picked.display_name !== 'Floodgate 01' || picked.aliases[0] !== 'gate' || 'display_name_en' in picked) {
    failures.push('inEnglish() 가 _en 자리를 못 고른다 — 레지스트리 이름이 영문 화면에서 한국어로 남는다');
  }
  const kept = inEnglish({ display_name: '수문 01', display_name_en: '' });
  if (kept.display_name !== '수문 01') failures.push('inEnglish() 가 빈 영어를 골랐다 — 빈칸이 화면에 뜬다');
  controls.push('_en 이 있으면 고르고 비어 있으면 한국어를 남긴다');

  if (langOf('/x?lang=en') !== 'en' || langOf('/x') !== 'ko' || langOf('/x?lang=zz') !== 'ko') {
    failures.push('langOf() 가 주소의 언어를 잘못 읽는다');
  }
  controls.push('주소의 lang 을 읽고 모르는 값은 ko 로 떨어진다');
  console.log('✅ 표지가 전선에서 글자가 된다 — 없는 키는 드러나고, 영어가 없으면 한국어로 떨어진다');
}

// ── 4. 화면이 언어를 실어 묻는다 ────────────────────────────────────────────
//
// 게이트웨이가 아무리 잘 답해도 **묻는 쪽이 안 실으면** 늘 한국어로 온다.
{
  const asked = [
    ['src/transport/index.ts', 'WS 접속 주소'],
    ['src/tabs/data/registry.ts', '레지스트리 조회'],
    ['src/tabs/data/audit.ts', '감사 조회'],
    ['src/tabs/data/metrics.ts', '지표 조회'],
    ['src/shared/commandCenter.ts', '동작 목록 조회'],
  ];
  for (const [rel, what] of asked) {
    const src = readSource(join(root, rel));
    if (!/withLang\s*\(/.test(src)) {
      failures.push(`${rel}: ${what} 가 언어를 안 싣는다 — 영문 화면이 한국어 문장을 받는다`);
    }
  }
  console.log(`✅ 화면이 언어를 싣는다 — WS 접속과 HTTP ${asked.length - 1}곳`);
}

if (failures.length > 0) {
  console.error(`❌ verify:gateway-i18n\n- ${failures.join('\n- ')}`);
  console.error('\n   게이트웨이가 만든 문장은 게이트웨이 사전(`gateway/i18n.ko.ts`·`i18n.en.ts`)에 있어야 한다.');
  console.error('   화면 사전(`src/i18n/`)이 아니다 — 실제 백엔드가 오면 그 자리는 백엔드가 말한다.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
