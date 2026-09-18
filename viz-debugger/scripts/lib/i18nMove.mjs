// scripts/lib/i18nMove.mjs (260918 신설 — 영문화 4단계)
//
// **쉬운 자리는 기계가 옮기고, 어려운 자리는 목록으로 내놓는다.**
//
// 4단계는 71개 파일 1,000여 건이다. 자리마다 손으로 닻을 찍으면 그 자체가 병목이고,
// 닻을 잘못 찍어 **조용히 아무것도 안 바뀌는** 사고가 앞 단계에서 이미 두 번 있었다.
//
// 그래서 가르는 기준을 하나 둔다.
//
//   쉬운 자리   한글만 든 문자열 리터럴 · 한글만 든 JSX 텍스트   → 기계가 옮긴다
//   어려운 자리 보간식이 섞인 것 · 태그가 가운데 있는 것          → **손으로** 옮긴다
//
// 어려운 자리를 기계에 맡기면 조각이 생긴다. 조각은 영어 어순에서 못 잇는다 —
// 그것이 이 저장소가 1단계부터 지켜 온 규칙이고, 여기서 깨면 뒤에 못 고친다.
//
// 이 파일은 **옮기지 않는다.** 무엇을 어떻게 바꿀지 목록으로 내놓기만 하고, 쓰는 쪽이
// 그 목록을 보고 적용한다. 그래야 적용 전에 사람이 한 번 읽을 수 있다.

/** 주석을 지우되 **줄 구조와 열 위치를 지킨다** — 자리를 되짚어야 하므로 길이가 같아야 한다. */
export function blankComments(src) {
  let out = '';
  let i = 0;
  let inBlock = false;
  while (i < src.length) {
    const c = src[i];
    if (inBlock) {
      if (c === '*' && src[i + 1] === '/') { inBlock = false; out += '  '; i += 2; continue; }
      out += c === '\n' ? '\n' : ' ';
      i += 1;
      continue;
    }
    if (c === '"' || c === "'" || c === '`') {
      out += c;
      i += 1;
      while (i < src.length && src[i] !== c) {
        if (src[i] === '\\') { out += src[i] + (src[i + 1] ?? ''); i += 2; continue; }
        out += src[i];
        i += 1;
      }
      out += src[i] ?? '';
      i += 1;
      continue;
    }
    if (c === '/' && src[i + 1] === '*') { inBlock = true; out += '  '; i += 2; continue; }
    if (c === '/' && src[i + 1] === '/') {
      const end = src.indexOf('\n', i);
      const stop = end < 0 ? src.length : end;
      out += ' '.repeat(stop - i);
      i = stop;
      continue;
    }
    out += c;
    i += 1;
  }
  return out;
}

/**
 * 이 따옴표가 **자바스크립트 값 자리에 있는가.**
 *
 * ## 260918 — 네 번째 사각. 이것만은 화면에 그대로 떴다
 *
 * ```jsx
 *   <p>… <strong>fault + online</strong>은 합치면 '정상'으로 보이고,{' '}
 * //                                                ^^^^^^ JS 문자열이 아니다
 * ```
 *
 * JSX 텍스트 안에서 **따옴표로 인용한 말**이다. 기계가 이것을 코드로 읽고 `t('dg.22')`
 * 로 바꿨고, 그건 JSX 안에서 **글자 그대로** 렌더된다 — 화면에 `t('dg.22')` 가 떴다.
 * 앞의 사각 셋은 조각을 만드는 정도였는데 이것은 눈에 보이는 고장이다.
 *
 * 그래서 **값 자리인지**를 본다. 여는 따옴표 바로 앞이 `(`·`,`·`[`·`=`·`:`·`?`·`&&`·
 * `||`·`??` 이거나 줄의 첫 글자일 때만 값이다. `합치면 '정상'` 처럼 앞이 글자면 아니다.
 */
function isJsValue(line, index) {
  const before = line.slice(0, index).trimEnd();
  if (before === '') return true;
  return /[([{,=:?]$|&&$|\|\|$|\?\?$|\breturn$|=>$/.test(before);
}

/**
 * 이 따옴표가 **`+` 로 잇는 문장의 조각인가.**
 *
 * ## 260918 — 다섯 번째 사각
 *
 * ```ts
 *   : 'frame_ref 무시 → 표시 프레임 #' + alignment.displayFrame + '에 #' + primary.detectionFrame + …
 *   ? '연계 ' + b.link.link_confidence.toFixed(2)
 * ```
 *
 * **문법으로는 멀쩡한 문자열 리터럴**이라 위 `isJsValue` 를 통과한다. 그런데 앞뒤가
 * `+` 로 이어져 있으면 그것은 값이 아니라 **문장의 토막**이다. 「연계 」만 사전에 넣으면
 * 영어에서 `Link 0.87` 의 어순을 만들 수 없다 — 치환이 있는 한 문장이어야 한다.
 *
 * 그래서 여는 따옴표 앞이나 닫는 따옴표 뒤에 `+` 가 붙어 있으면 사람 몫으로 넘긴다.
 */
function concatFragment(line, start, end) {
  return /\+\s*$/.test(line.slice(0, start)) || /^\s*\+/.test(line.slice(end));
}

/** 이 글이 **개발자에게만 보이는가.** `throw new Error(…)` 의 속은 화면에 안 뜬다. */
function devOnly(line, index) {
  const before = line.slice(0, index);
  return /throw new Error\($/.test(before.trimEnd()) || /throw new Error\(\s*$/.test(before);
}

/**
 * 한 파일에서 **기계가 옮길 수 있는 자리**를 찾는다.
 *
 * 돌려주는 것은 `{ line, from, to, ko }` 의 목록이다. `from` 은 파일에 **그대로 있는**
 * 글이고 `to` 는 바꿔 넣을 글이다 — 쓰는 쪽이 `replace` 한 번으로 적용한다.
 */
export function easyMoves(src, prefix) {
  const raw = src.split('\n');
  const clean = blankComments(src).split('\n');
  const moves = [];
  const hard = [];
  const seen = new Map();

  /**
   * **`t` 라는 이름이 이미 쓰이는 파일인가.**
   *
   * `physical/NavFacts.tsx` 는 `const t = feed.telemetry` 로 `t` 를 쓴다. 거기에
   * `import { t }` 를 넣으면 지역 이름이 import 를 가려 `t('nav.1')` 이 **텔레메트리를
   * 호출하려 든다.** 타입 검사가 잡아 주기는 했지만, 기계가 그런 파일을 건드리면 안 된다 —
   * 이름을 바꿀지 `t` 를 다른 이름으로 들여올지는 사람이 정할 일이다.
   */
  /**
   * **타입 표기는 이름을 가리지 않는다** (260919 수습).
   *
   * 처음에는 `\(\s*t\s*[,:)]` 까지 잡았는데, 그러면 이런 줄이 걸린다.
   *
   * ```ts
   *   this.client as { publish?: (t: string, p: Uint8Array, o: unknown) => void }
   * //                            ^^^^^^^^^ 타입 안의 매개변수 이름이다. 값이 아니다
   * ```
   *
   * `PhysicalClient.ts` 가 이것 하나로 통째로 사람 몫이 됐다 — 실제 표시 한글은 **넷**인데
   * 77줄로 보고했다. 진짜 가리는 것은 **값을 묶는 자리**뿐이다: `const/let/var t =` 와
   * 화살표·함수의 `(t)` · `(t,`.
   */
  const code = blankComments(src);
  if (/\b(?:const|let|var)\s+t\s*=|\bfunction\s+t\b|\(\s*t\s*\)\s*=>|\(\s*t\s*,/.test(code)) {
    // **주석은 빼고 센다.** 안 그러면 이 저장소의 긴 한글 주석이 전부 「사람 몫」으로 뜬다.
    const lines = code.split('\n');
    return {
      moves: [],
      hard: raw
        .map((line, i) => ({ line: i + 1, text: line.trim() }))
        .filter((r) => /[가-힣]/.test(lines[r.line - 1] ?? '')),
      phrases: [],
      blocked: '이 파일은 `t` 라는 이름을 이미 쓴다 — 기계가 안 건드린다',
    };
  }

  /** 같은 글은 같은 키를 쓴다 — 한 파일 안에서 같은 말이 두 키가 되면 사전이 부푼다. */
  const keyFor = (ko) => {
    if (seen.has(ko)) return seen.get(ko);
    const key = `${prefix}.${seen.size + 1}`;
    seen.set(ko, key);
    return key;
  };

  clean.forEach((line, idx) => {
    /**
     * **보간 템플릿이 있는 줄은 통째로 사람 몫이다.**
     *
     * ```ts
     *   `${clock(t)} · ${sec}초 전${age > FRESH ? ' (낡음 — 지금 값으로 치지 않습니다)' : ''}`
     * //                                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ 조각이다
     * ```
     *
     * 이 줄의 `'…'` 만 떼어 옮기면 「 (낡음 …)」이라는 **문장의 꼬리**가 사전에 들어간다.
     * 조각은 영어 어순에서 못 잇는다 — 1단계부터 지켜 온 규칙이고, 기계가 여기서 깨면
     * 뒤에 못 고친다. 그래서 그런 줄은 쉬운 자리를 하나도 안 만든다.
     */
    if (/`[^`]*\$\{/.test(line) && /[가-힣]/.test(line)) {
      hard.push({ line: idx + 1, text: raw[idx].trim() });
      return;
    }

    // ── 쉬운 자리 ① 한글만 든 문자열 리터럴 (보간식 없음) ─────────────────
    for (const m of line.matchAll(/'([^'\\\n]*)'/g)) {
      const ko = m[1];
      if (!/[가-힣]/.test(ko)) continue;
      if (devOnly(line, m.index)) continue;
      if (!isJsValue(line, m.index) || concatFragment(line, m.index, m.index + m[0].length)) {
        hard.push({ line: idx + 1, text: raw[idx].trim() });
        continue;
      }
      moves.push({ line: idx + 1, from: `'${ko}'`, to: `t('${keyFor(ko)}')`, ko, kind: 'str' });
    }

    // ── 쉬운 자리 ② 태그 사이에 한글만 있는 JSX 텍스트 ────────────────────
    //
    //    `>다시 받기<` 는 되고 `>탐지 {n}건<` 은 안 된다 — 뒤엣것은 보간식이 섞여
    //    있어 기계가 가르면 「탐지」와 「건」이라는 조각이 생긴다.
    const runs = [...line.matchAll(/>([^<>{}]*[가-힣][^<>{}]*)<(?=[/A-Za-z])/g)];

    /**
     * **한 줄에 한글 토막이 둘 이상이면 통째로 사람 몫이다.**
     *
     * ```jsx
     *   <Explain>같은 구독을 유지한 채 역할에 맞춰 <strong>표시 깊이만</strong> 바꾼다 (VZ-U-03)</Explain>
     * //          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^          ^^^^^^^^^^^^^        ^^^^^^^^^^^^^^^^
     * ```
     *
     * **한 문장이 태그에 셋으로 갈려 있다.** 토막마다 키를 주면 사전에 「바꾼다 (VZ-U-03)」
     * 같은 꼬리가 들어가고, 영어 어순에서는 그 셋을 다시 이을 수 없다.
     *
     * 이런 자리는 `<Rich>` 의 `**굵게**` 로 **한 문장을 한 키**에 담아야 하고, 그 판단은
     * 사람이 한다. 260918 에 `RiskPanel` 에서 실제로 이 모양을 만들었다가 되돌렸다.
     */
    if (runs.length > 1) {
      // 위 ①에서 이 줄에 담아 둔 자리도 **도로 뺀다** — 어려운 줄은 통째로 사람 몫이다.
      for (let k = moves.length - 1; k >= 0; k -= 1) if (moves[k].line === idx + 1) moves.splice(k, 1);
      hard.push({ line: idx + 1, text: raw[idx].trim() });
      return;
    }

    for (const m of runs) {
      const ko = m[1];
      if (ko.trim() === '') continue;
      const trimmed = ko.trim();
      const pad = [ko.slice(0, ko.indexOf(trimmed[0])), ko.slice(ko.indexOf(trimmed[0]) + trimmed.length)];
      moves.push({
        line: idx + 1,
        from: `>${ko}<`,
        to: `>${pad[0]}{t('${keyFor(trimmed)}')}${pad[1]}<`,
        ko: trimmed,
        kind: 'jsx',
      });
    }

    // ── 어려운 자리 — 사람이 봐야 한다 ────────────────────────────────────
    //
    // `line` 은 **주석을 지운** 줄이다. 원문(`raw`)으로 보면 이 저장소의 긴 한글 주석이
    // 전부 사람 몫으로 뜬다 — 그건 옮길 대상이 아니다.
    if (/[가-힣]/.test(line) && !moves.some((mv) => mv.line === idx + 1 && line.includes(mv.from))) {
      hard.push({ line: idx + 1, text: raw[idx].trim() });
    } else if (/[가-힣]/.test(line)) {
      // 한 줄에 쉬운 자리와 어려운 자리가 같이 있을 수 있다.
      let rest = line;
      for (const mv of moves.filter((x) => x.line === idx + 1)) rest = rest.replace(mv.from, '');
      if (/[가-힣]/.test(rest)) hard.push({ line: idx + 1, text: raw[idx].trim() });
    }
  });

  return { moves, hard, phrases: [...seen.entries()].map(([ko, key]) => ({ key, ko })) };
}
