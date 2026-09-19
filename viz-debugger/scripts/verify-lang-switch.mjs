// verify:lang-switch (260916 신설 — 영문화 1단계 지시서 §6)
//
// **언어는 표시층의 설정이고, 그 밖으로 새면 안 된다.**
//
// 이 검사가 막으려는 것은 번역 오류가 아니라 **번짐**이다. 언어 저장소가 렌더 모드나 연결
// 주소나 기록 열을 건드리기 시작하면, 2단계에서 문구 1,000줄을 옮기는 동안 아무도 눈치채지
// 못한 채 시연이 깨진다. 「영어로 바꿨더니 목 렌더가 켜졌다」 같은 일은 원인을 찾는 데
// 반나절이 든다.
//
// 보는 것 다섯.
//  1. **결정 순서** — `?lang=` > `localStorage` > `navigator.language` > `'ko'`
//  2. **URL 로 들어온 값이 저장된다** — 주소창을 지우고 새로고침해도 살아남아야 한다
//  3. **`<html lang>` 이 기동 시점에 심긴다** — 조각 HTML 이라 정적 `lang` 속성이 없다
//  4. **`setLang()` 이 다른 상태를 안 건드린다** — 렌더 모드 · 연결 주소 · 기록 열
//  5. **사전의 fallback** — en 에 없으면 ko, 양쪽에 없으면 키. 콘솔은 **키당 한 번**
//  6. **검사 환경의 기본값은 언제나 `'ko'`** — 기계 로캘을 따라가지 않는다 (260917 신설)
//
// 6번이 왜 있나 — `verify:connection-panel` 이 260916 에 조용히 깨졌다. Node 21+ 에도
// `navigator` 가 있어서 `navigator.language` 가 `'en-US'` 로 오고, 검사 안에서 `t()` 가
// 영어를 돌려줬다. **그 깨짐이 로캘에 달려 있었다** — 한국어 윈도우에서는 통과하고 영어
// 로캘에서만 실패한다. 2단계에서 한글을 대조하는 검사 7종이 같은 함정을 밟는다.
//
// 대조군 포함 — 번짐을 일부러 만든 사본이 반드시 잡혀야 한다.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const srcUrl = (...parts) => pathToFileURL(join(vizRoot, 'src', ...parts)).href;

const failures = [];
const controls = [];

/**
 * **이 기계의 진짜 `navigator`** — 아래 경우들이 `delete globalThis.navigator` 를 하므로
 * 6번이 돌 때쯤이면 사라져 있다. 6번은 「Node 가 원래 갖고 있는 navigator 를 안 본다」를
 * 재는 것이라, 그것이 없으면 검사가 아무것도 안 재게 된다. 그래서 여기서 미리 붙든다.
 */
const NODE_NAVIGATOR = globalThis.navigator;

/** `localStorage` 대역. 막힌 환경을 흉내 내려면 `blocked: true`. */
function fakeStorage(seed = {}, blocked = false) {
  const map = new Map(Object.entries(seed));
  const guard = () => { if (blocked) throw new Error('storage blocked'); };
  return {
    getItem: (k) => { guard(); return map.has(k) ? map.get(k) : null; },
    setItem: (k, v) => { guard(); map.set(k, String(v)); },
    removeItem: (k) => { guard(); map.delete(k); },
    _map: map,
  };
}

/** 브라우저 전역을 심는다. Node 24 는 `navigator` 가 접근자라 `defineProperty` 여야 한다. */
function installGlobals({ query = '', stored, navLang, blocked = false } = {}) {
  const storage = fakeStorage(stored === undefined ? {} : { 'viz.lang.v1': stored }, blocked);
  const html = { lang: '' };
  // **`window` 를 같이 심는다** (260917). `fromNavigator()` 가 브라우저에서만 도는데,
  // 그 판정이 `window`·`document` 이기 때문이다 — 안 심으면 여기서 `navigator` 경우가
  // 통째로 안 돈다. 아래 6번이 반대쪽(브라우저가 아닌 환경)을 본다.
  for (const [name, value] of [
    ['window', { name: 'viz-verify' }],
    ['location', { search: query, href: 'http://localhost:5174/' + query }],
    ['localStorage', storage],
    ['navigator', navLang === undefined ? undefined : { language: navLang }],
    ['document', { documentElement: html }],
  ]) {
    if (value === undefined) { delete globalThis[name]; continue; }
    Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
  }
  return { storage, html };
}

/** 모듈이 **로드 시점에** 언어를 정하므로 경우마다 새로 불러야 한다. */
let caseSeq = 0;
async function loadLanguage(options) {
  const env = installGlobals(options);
  const module = await import(srcUrl('shared', 'language.ts') + `?case=${(caseSeq += 1)}`);
  return { ...env, module };
}

// ── 1·2·3. 결정 순서 · 저장 · <html lang> ────────────────────────────────────
{
  const cases = [
    { name: '?lang=en 만',                opts: { query: '?lang=en' },                                want: 'en' },
    { name: 'localStorage 만',            opts: { stored: 'en' },                                     want: 'en' },
    { name: '둘 다 — URL 이 이긴다',        opts: { query: '?lang=ko', stored: 'en' },                  want: 'ko' },
    { name: '둘 다 없음 — navigator',      opts: { navLang: 'en-US' },                                 want: 'en' },
    { name: '둘 다 없음 — 그 밖의 로캘',    opts: { navLang: 'fr-FR' },                                 want: 'ko' },
    { name: '아무것도 없음',               opts: {},                                                    want: 'ko' },
    { name: '?lang=jp — 무시하고 떨어진다', opts: { query: '?lang=jp', stored: 'en' },                  want: 'en' },
    { name: '?lang=jp · 저장도 없음',      opts: { query: '?lang=jp', navLang: 'en' },                 want: 'en' },
    { name: '저장소가 막혀도 뜬다',         opts: { query: '?lang=en', blocked: true },                 want: 'en' },
  ];
  for (const item of cases) {
    let got;
    try {
      const { module, html } = await loadLanguage(item.opts);
      got = module.getLang();
      // 3. `<html lang>` 은 **기동 시점에** 심긴다 — 전환을 안 해도 값이 있어야 한다.
      if (html.lang !== got) failures.push(`${item.name}: <html lang> 이 '${html.lang}' 이다 — 기동 때 '${got}' 로 심겨야 한다`);
    } catch (error) {
      failures.push(`${item.name}: 던졌다 — ${error?.message ?? error}. 목록 밖 값은 떨어뜨리되 던지지 않는다`);
      continue;
    }
    if (got !== item.want) failures.push(`결정 순서 — ${item.name}: '${got}' 인데 '${item.want}' 여야 한다`);
  }

  // 2. `?lang=` 으로 들어온 값은 저장된다.
  {
    const { module, storage } = await loadLanguage({ query: '?lang=en' });
    if (storage._map.get('viz.lang.v1') !== 'en') {
      failures.push('?lang=en 으로 들어왔는데 localStorage 에 안 적혔다 — 주소창을 지우고 새로고침하면 한국어로 돌아간다');
    }
    if (module.getLang() !== 'en') failures.push('?lang=en 인데 en 이 아니다');
  }
  console.log(`✅ 결정 순서 ${cases.length}가지 — ?lang= > localStorage > navigator.language > 'ko' · 목록 밖 값은 안 던지고 떨어진다`);
  console.log('✅ ?lang= 으로 들어온 값이 저장되고, <html lang> 이 기동 시점에 심긴다');
}

// ── 4. setLang() 이 다른 상태를 안 건드린다 ──────────────────────────────────
{
  installGlobals({});
  const language = await import(srcUrl('shared', 'language.ts') + '?case=isolation');
  const renderMode = await import(srcUrl('shared', 'renderMode.ts'));
  const connections = await import(srcUrl('shared', 'connections.ts'));
  const trace = await import(srcUrl('data', 'trace.ts'));

  /** 언어 밖의 상태를 한 덩어리로 찍는다. 바뀌면 문자열이 달라진다. */
  const snapshot = () => JSON.stringify({
    renderMode: renderMode.getRenderMode(),
    devTools: renderMode.getDevToolsVisible(),
    scenario: renderMode.getScenarioRender(),
    addresses: connections.connectionAddresses(),
    overrides: connections.connectionOverrides(),
    traceMission: trace.traceMissionId(),
    traceCount: trace.traceEvents().length,
    traceStats: trace.traceStats(),
  });

  const before = snapshot();
  language.setLang('en');
  const afterEn = snapshot();
  language.setLang('ko');
  const afterKo = snapshot();

  if (language.getLang() !== 'ko') failures.push('setLang 왕복 뒤 언어가 안 돌아왔다 — 저장소 자체가 안 돈다');
  if (afterEn !== before) failures.push(`setLang('en') 이 언어 밖 상태를 바꿨다\n      전: ${before}\n      후: ${afterEn}`);
  if (afterKo !== before) failures.push(`setLang('ko') 이 언어 밖 상태를 바꿨다\n      전: ${before}\n      후: ${afterKo}`);

  // 구독이 실제로 불리는가 — 안 불리면 화면이 안 따라 그린다.
  let notified = 0;
  const stop = language.subscribeLang(() => { notified += 1; });
  language.setLang('en');
  language.setLang('en'); // 같은 값은 안 알린다 — 불필요한 리렌더를 만들지 않는다
  stop();
  language.setLang('ko');
  if (notified !== 1) failures.push(`구독이 ${notified}번 불렸다 — 바뀔 때 한 번이고, 같은 값과 해지 뒤에는 안 불려야 한다`);

  console.log('✅ 언어는 표시층에 머문다 — setLang 전후로 렌더 모드 · 연결 주소 · 기록 열이 한 글자도 안 바뀐다');
  console.log('✅ 구독 — 바뀔 때만 알리고, 같은 값과 해지 뒤에는 안 알린다');
}

// ── 5. 사전 fallback 과 콘솔 한 줄 ───────────────────────────────────────────
{
  installGlobals({ query: '?lang=en' });
  const dict = await import(srcUrl('i18n', 'dict.ts') + '?case=fallback');
  const { ko, en } = dict;

  // 시범 키 다섯이 살아 있는가. 하나라도 지워지면 이 단계의 증거가 사라진다.
  for (const key of ['mode.label', 'check.robot.stale', 'conn.storageBlocked', 'plane.business', 'mode.mock']) {
    if (ko[key] === undefined) failures.push(`시범 키가 ko 에서 사라졌다 — ${key}`);
  }
  if (en['mode.mock'] !== undefined) {
    failures.push("`mode.mock` 이 en 에 생겼다 — 이 빈자리가 시범 키 다섯째다. 채우려면 지시서 §4 를 먼저 봐라");
  }

  const lines = [];
  const realLog = console.log;
  const realWarn = console.warn;
  console.log = (msg) => { if (String(msg).startsWith('[i18n]')) lines.push(String(msg)); else realLog(msg); };
  console.warn = (msg) => { lines.push(String(msg)); };

  const translated = dict.t('mode.label');
  const fellBack = dict.t('mode.mock');
  dict.t('mode.mock'); dict.t('mode.mock');            // 같은 키를 여러 번
  const missing = dict.t('nowhere.at.all');
  dict.t('nowhere.at.all');
  const filled = dict.t('check.robot.stale', { sec: 30 });

  console.log = realLog;
  console.warn = realWarn;

  if (translated !== 'Mode') failures.push(`en 에 있는 키가 안 옮겨졌다 — '${translated}'`);
  if (fellBack !== ko['mode.mock']) failures.push(`en 에 없는 키가 한국어로 안 떨어졌다 — '${fellBack}'`);
  if (fellBack === '') failures.push('빈 문자열을 그렸다 — 부분 번역 상태에서 화면이 빈다');
  if (missing !== 'nowhere.at.all') failures.push(`양쪽에 없는 키가 키 문자열이 아니다 — '${missing}'`);
  if (!filled.includes('30')) failures.push(`자리표시가 안 채워졌다 — '${filled}'`);
  if (filled.includes('{sec}')) failures.push(`자리표시가 그대로 남았다 — '${filled}'`);

  const fallbackLines = lines.filter((line) => line.includes('mode.mock'));
  const missingLines = lines.filter((line) => line.includes('nowhere.at.all'));
  if (fallbackLines.length !== 1) failures.push(`fallback 로그가 ${fallbackLines.length}줄이다 — 같은 키는 한 번만 찍어야 콘솔이 쓸모를 유지한다`);
  if (missingLines.length !== 1) failures.push(`누락 경고가 ${missingLines.length}줄이다 — 같은 키는 한 번만이다`);

  console.log(`✅ fallback — en 에 없으면 한국어를 그리고 콘솔에 한 줄 · 양쪽에 없으면 키 · 같은 키는 렌더를 반복해도 한 줄`);
  console.log(`✅ 치환 — t('check.robot.stale', { sec: 30 }) 이 어순이 반대인 영어에서도 한 문장으로 나온다`);
}

// ── 6. 검사 환경의 기본값은 언제나 'ko' (260917) ─────────────────────────────
//
// **결과가 기계 로캘에 따라 달라지면 안 된다.** 브라우저 전역을 하나도 안 심고 —
// 즉 실제 검사 스크립트가 도는 그대로 — 언어를 물어본다.
{
  for (const name of ['window', 'document', 'location', 'localStorage']) delete globalThis[name];
  // **Node 가 원래 갖고 있던 `navigator` 를 되돌려 놓는다.** 그것이 이 검사의 대상이다 —
  // 앞의 경우들이 지워 버린 채로 재면 검사가 아무것도 안 재고 통과한다.
  if (NODE_NAVIGATOR !== undefined) {
    Object.defineProperty(globalThis, 'navigator', { value: NODE_NAVIGATOR, configurable: true, writable: true });
  }
  const nodeLang = globalThis.navigator?.language ?? '(없음)';
  if (nodeLang === '(없음)') {
    failures.push('이 Node 에 navigator 가 없어 6번이 아무것도 재지 못했다 — Node 21+ 에서 돌려야 의미가 있다');
  }
  const { module } = { module: await import(srcUrl('shared', 'language.ts') + `?case=${(caseSeq += 1)}`) };
  const got = module.getLang();
  if (got !== 'ko') {
    failures.push(
      `검사 환경 기본값이 '${got}' 다 — 이 기계의 navigator.language 가 '${nodeLang}' 이라 따라갔다. ` +
      `브라우저가 아닌 곳에서는 'ko' 여야 검사 결과가 기계와 무관해진다 (language.ts fromNavigator)`,
    );
  }
  // 영어 경로는 **환경이 아니라 검사가** 정한다.
  module.setLang('en');
  if (module.getLang() !== 'en') failures.push('검사가 setLang("en") 으로 영어 경로를 못 연다 — 환경에 기대지 않는 길이 막혔다');
  module.setLang('ko');

  if (!failures.length) console.log(`✅ 검사 환경 — 브라우저 전역이 없으면 기계 로캘(navigator='${nodeLang}')과 무관하게 'ko' 이고, 영어는 setLang 으로만 연다`);
}

// ── 대조군 — 번짐을 일부러 만든 사본이 잡혀야 한다 ────────────────────────────
{
  const source = readFileSync(join(vizRoot, 'src', 'shared', 'language.ts'), 'utf8');

  // ① 언어를 바꾸면서 렌더 모드까지 건드리는 사본.
  const leak = source.replace(
    '  for (const listener of listeners) listener();',
    "  void import('./renderMode.ts').then((m) => m.setRenderMode('mock'));\n  for (const listener of listeners) listener();",
  );
  if (leak === source) failures.push('대조군을 만들지 못했다 — 알림 자리가 원본에서 사라졌다 (원본이 바뀌었나?)');
  else controls.push('언어 전환이 렌더 모드를 켜는 사본');

  // ② 목록 밖 값을 던지는 사본.
  const throws = source.replace(
    '  if (!isLang(next) || lang === next) return;',
    "  if (!isLang(next)) throw new Error('unknown lang');\n  if (lang === next) return;",
  );
  if (throws === source) failures.push('대조군을 만들지 못했다 — setLang 의 방어 줄이 원본에서 사라졌다');
  else controls.push('목록 밖 값에 던지는 사본');

  // ③ 사전 — 렌더마다 콘솔을 찍는 사본.
  const dictSource = readFileSync(join(vizRoot, 'src', 'i18n', 'dict.ts'), 'utf8');
  const spam = dictSource.replace('  if (announced.has(key)) return;', '  if (false) return;');
  if (spam === dictSource) failures.push('대조군을 만들지 못했다 — 사전의 중복 방지 줄이 사라졌다');
  else controls.push('같은 키를 렌더마다 찍는 사본');

  // ④ 브라우저 판정을 걷어낸 사본 — 260916 에 실제로 있던 모양이다.
  //    이 자리가 사라지면 검사가 다시 기계 로캘을 따라가게 된다.
  //
  // **글자가 아니라 성질을 본다** (260919). 전에는 그 한 줄을 통째로 박아 두고 대조했는데,
  // 게이트웨이 타입 검사를 되살리느라 같은 판정을 `browser.window === undefined` 로 다시
  // 적자 이 검사가 빨개졌다. 성질(둘 다 보고 · `navigator` 보다 **먼저** 보고 · null 로
  // 나간다)은 그대로다. 그래서 무르게 하는 대신 **철자에 안 걸리게** 고쳤다.
  const body = /function fromNavigator\(\)[^{]*\{([\s\S]*?)\n\}/.exec(source)?.[1] ?? '';
  const guard = /if\s*\([^)]*\bwindow\b[^)]*\bdocument\b[^)]*\)\s*return null;/.exec(body);
  const readsNavigator = body.search(/\bnavigator\s*[.?]/);
  if (body === '') {
    failures.push('fromNavigator() 를 못 찾았다 — 이 대조군이 아무것도 안 재고 있다');
  } else if (guard === null) {
    failures.push('fromNavigator() 의 브라우저 판정이 사라졌다 — 검사 결과가 기계 로캘을 따라간다 (260917 회귀)');
  } else if (readsNavigator !== -1 && readsNavigator < guard.index) {
    failures.push('fromNavigator() 가 브라우저 판정보다 **먼저** navigator 를 읽는다 — 판정이 있으나 마나다');
  } else {
    controls.push('브라우저 판정이 navigator 보다 먼저 있다 (철자는 안 본다)');
  }

  // 대조군은 **자리가 있는지**만 본다. 실제로 돌리면 모듈 전역을 오염시켜
  // 위 검사들이 무엇을 쟀는지 알 수 없게 된다 — 자리가 사라지면 그때 이 검사가 죽는다.
}

if (failures.length) {
  console.error(`❌ verify:lang-switch\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
