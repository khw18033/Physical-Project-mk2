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
  if (/(?:const|let|var|function)\s+t\b|\(\s*t\s*[,:)]|,\s*t\s*[,:)]/.test(blankComments(src))) {
    return { moves: [], hard: raw.map((line, i) => ({ line: i + 1, text: line.trim() })).filter((r) => /[가-힣]/.test(r.text)), phrases: [], blocked: "이 파일은 `t` 라는 이름을 이미 쓴다 — 기계가 안 건드린다" };
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
      moves.push({ line: idx + 1, from: `'${ko}'`, to: `t('${keyFor(ko)}')`, ko, kind: 'str' });
    }

    // ── 쉬운 자리 ② 태그 사이에 한글만 있는 JSX 텍스트 ────────────────────
    //
    //    `>다시 받기<` 는 되고 `>탐지 {n}건<` 은 안 된다 — 뒤엣것은 보간식이 섞여
    //    있어 기계가 가르면 「탐지」와 「건」이라는 조각이 생긴다.
    for (const m of line.matchAll(/>([^<>{}]*[가-힣][^<>{}]*)<(?=[/A-Za-z])/g)) {
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
