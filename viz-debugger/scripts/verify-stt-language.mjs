// verify:stt-language (260918 신설 — 영문화 3단계 §5)
//
// **영어로 말하면 영어로 듣는다.**
//
// 화면만 영어가 되고 인식은 한국어로 남으면, 영어 발화가 한국어로 디코딩되어 아무 문장도
// 안 나온다. 그때 화면은 「맞는 대본이 없다」라고만 말하므로 **원인을 못 찾는다.**
// 그 연결이 네 토막이고, 하나라도 끊기면 조용히 그 상태가 된다.
//
//   ① 화면이 `language` 를 싣는가        SttClient.transcribe()
//   ② 서비스가 그 값으로 어휘를 고르는가  service.py → vocab.vocabulary(language)
//   ③ 어휘가 언어별로 **갈리는가**        vocab.py — 두 언어를 한꺼번에 밀지 않는다
//   ④ 엔진은 그대로인가                   engines/*.py 는 `verify:stt-port` 의 몫이고
//                                         여기서는 **안 건드렸음**만 확인한다
//
// ③ 이 이 검사의 핵심이다. 두 언어의 hotword 를 한꺼번에 밀면 서로를 끌어당겨
// 인식을 흐리고, 그건 이 축이 재려는 것(등록 이름이 인식을 돕는가)을 무의미하게 만든다.
//
// 대조군 — 언어를 안 싣는 사본과, 두 언어를 한꺼번에 미는 사본이 잡혀야 한다.
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mutate, readSource } from './lib/source.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const failures = [];
const controls = [];

/** 주석을 지운다 — 사유를 적은 주석이 규칙 위반으로 잡히면 안 된다. */
const code = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*(\/\/|#).*$/gm, '');

// ── 1. 화면이 언어를 싣는다 ──────────────────────────────────────────────────
{
  const client = code(readSource(join(root, 'src', 'stt', 'SttClient.ts')));
  const sends = /body\.append\(\s*'language'/.test(client);
  if (!sends) {
    failures.push("SttClient.transcribe() 가 'language' 를 안 싣는다 — 서비스가 ko 로 떨어져 영어 발화를 한국어로 디코딩한다");
  }
  // **조건 없이** 실어야 한다. `if (options.language)` 로 감싸면 안 고른 경우에 안 나간다.
  if (/if\s*\([^)]*language[^)]*\)\s*body\.append\(\s*'language'/.test(client)) {
    failures.push("'language' 를 조건 안에서 싣는다 — 안 고른 경우에 안 나가고 서비스 기본값(ko)으로 떨어진다");
  }
  console.log('✅ 화면 — transcribe() 가 언어를 조건 없이 싣는다');
}

// ── 2. 인식 언어는 화면 언어와 **따로** 고를 수 있다 ─────────────────────────
{
  const lang = code(readSource(join(root, 'src', 'stt', 'language.ts')));
  for (const [needle, why] of [
    [/'auto'/, '「화면 언어 따름」이 없다 — 화면을 영어로 두고 한국어로 말할 수 없게 된다'],
    [/getLang\(\)/, 'auto 가 화면 언어를 안 읽는다'],
  ]) {
    if (!needle.test(lang)) failures.push(`stt/language.ts — ${why}`);
  }
  // **부를 때마다 읽어야 한다.** 모듈 최상위에 굳히면 셋을 바꿔도 안 따라온다.
  if (!/export function sttLanguage\(\)/.test(lang)) {
    failures.push('stt/language.ts — sttLanguage() 가 함수가 아니다. 상수로 굳히면 언어를 바꿔도 안 변한다');
  }
  const panel = code(readSource(join(root, 'src', 'views', 'UtterancePanel.tsx')));
  if (!/useSttLangChoice\(\)/.test(panel) || !/setSttLangChoice/.test(panel)) {
    failures.push('발화 패널에 인식 언어 셋이 없다 — 화면 언어와 따로 고를 길이 없다');
  }
  console.log('✅ 인식 언어 — 화면 언어와 따로 고르고, 기본은 「화면 언어 따름」이다');
}

// ── 3. 서비스가 그 언어로 어휘를 고른다 ──────────────────────────────────────
{
  const service = code(readSource(join(root, 'stt', 'service.py')));
  if (!/vocab\.vocabulary\(\s*language\s*\)/.test(service)) {
    failures.push('service.py 가 vocabulary() 에 언어를 안 넘긴다 — 영어로 말해도 한국어 어휘를 민다');
  }
  console.log('✅ 서비스 — 요청의 언어로 어휘를 뽑는다');
}

// ── 4. 어휘가 언어별로 갈린다 — **실제로 돌려 본다** ─────────────────────────
//
// 문자열 검사로는 「갈라 놓은 척」을 못 가른다. 파이썬을 불러 두 언어의 어휘를 실제로
// 받아 **겹치는지** 본다.
{
  let ko = null;
  let en = null;
  try {
    const out = execFileSync('python', ['-c', [
      'import sys, json',
      `sys.path.insert(0, ${JSON.stringify(join(root, 'stt'))})`,
      'import vocab',
      'print(json.dumps({l: [t["term"] for t in vocab.vocabulary(l)["terms"]] for l in ("ko", "en")}))',
    ].join('\n')], { encoding: 'utf8', cwd: root });
    const parsed = JSON.parse(out.trim().split('\n').pop());
    ko = parsed.ko;
    en = parsed.en;
  } catch (error) {
    failures.push(`vocab.py 를 돌려 보지 못했다 — ${String(error).slice(0, 200)}`);
  }
  if (ko !== null && en !== null) {
    if (ko.length === 0 || en.length === 0) {
      failures.push(`어휘가 비었다 (ko ${ko.length} · en ${en.length}) — hotword 가 아무것도 안 실린다`);
    }
    const koHasEnglish = ko.some((t) => /^[A-Za-z][A-Za-z\s]*$/.test(t) && /[a-z]{3}/.test(t));
    const enHasKorean = en.some((t) => /[가-힣]/.test(t));
    if (enHasKorean) {
      failures.push('영어 어휘에 한글이 섞였다 — 두 언어를 한꺼번에 밀면 서로를 끌어당겨 인식을 흐린다');
    }
    if (koHasEnglish) {
      failures.push('한국어 어휘에 영어 낱말이 섞였다 — 같은 이유로 안 된다');
    }
    const overlap = ko.filter((t) => en.includes(t));
    // 숫자(503·504)는 양쪽에 있는 것이 맞다 — 그건 언어가 아니다.
    const wordOverlap = overlap.filter((t) => !/^[\d\s]+$/.test(t));
    if (wordOverlap.length > 0) {
      failures.push(`두 언어에 같이 든 낱말 ${wordOverlap.length}건: ${wordOverlap.slice(0, 5).join(' · ')}`);
    }
    // **센 값을 적는다.** 여기 「0건」을 박아 두면 실패했을 때도 초록 줄이 0 이라고 말한다 —
    // 260918 에 실제로 그렇게 적었다가 되돌림 시험에서 드러났다.
    console.log(`✅ 어휘 — ko ${ko.length}개 · en ${en.length}개 · 겹치는 낱말 ${wordOverlap.length}건 (숫자 ${overlap.length - wordOverlap.length}건은 언어가 아니므로 공유해도 된다)`);
  }
}

// ── 5. 엔진은 안 건드렸다 ────────────────────────────────────────────────────
//
// 바이트 동일성 자체는 `verify:stt-port` 가 본다. 여기서는 **이 작업이 그 파일에 언어
// 분기를 심지 않았는지**만 본다 — 심으면 두 벌이 갈라지고 그 검사가 먼저 죽는다.
{
  for (const name of ['base.py', 'faster_whisper.py']) {
    const src = readSource(join(root, 'stt', 'engines', name));
    if (/vocab|aliases_en|display_name_en/.test(src)) {
      failures.push(`stt/engines/${name} 에 어휘 분기가 들어갔다 — 이식본이 원본과 갈라진다 (verify:stt-port)`);
    }
  }
  console.log('✅ 엔진 — 이식본에 어휘·언어 분기를 안 심었다 (바이트 동일성은 verify:stt-port 의 몫)');
}

// ── 6. 대조군 ────────────────────────────────────────────────────────────────
{
  const client = readSource(join(root, 'src', 'stt', 'SttClient.ts'));
  const noLang = mutate(client, "body.append('language', options.language ?? sttLanguage());", '');
  if (noLang === null) {
    failures.push('대조군을 만들지 못했다 — language 를 싣는 줄을 못 찾았다 (원본이 바뀌었나?)');
  } else if (/body\.append\(\s*'language'/.test(code(noLang))) {
    failures.push('대조군 실패: 언어를 안 싣는 사본을 만들었는데 여전히 싣는 것으로 보인다');
  } else controls.push('언어를 안 싣는 사본을 잡는다');

  const vocabSrc = readSource(join(root, 'stt', 'vocab.py'));
  const merged = mutate(vocabSrc, 'alias_field = "aliases_en" if en else "aliases"', 'alias_field = "aliases"');
  if (merged === null) {
    failures.push('대조군을 만들지 못했다 — 어휘를 가르는 줄을 못 찾았다');
  } else if (/aliases_en/.test(merged.split('\n').find((l) => l.includes('alias_field =')) ?? '')) {
    failures.push('대조군 실패: 두 언어를 한꺼번에 미는 사본을 못 만들었다');
  } else controls.push('영어 별칭 대신 한국어를 미는 사본을 만들 수 있다 (그 줄이 갈래의 유일한 자리다)');
}

if (failures.length > 0) {
  console.error(`❌ verify:stt-language\n- ${failures.join('\n- ')}`);
  console.error('\n   화면만 영어가 되고 인식이 한국어로 남으면, 영어 발화에서 아무 문장도 안 나온다.');
  console.error('   그때 화면은 「맞는 대본이 없다」라고만 말하므로 원인을 못 찾는다.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
