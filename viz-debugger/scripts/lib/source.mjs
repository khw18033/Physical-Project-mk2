// scripts/lib/source.mjs (260917 신설 — 검사 위생 지시서 §1)
//
// **소스를 읽는 자리 하나.** 작업본의 줄끝이 무엇이든 검사가 같게 돌아야 한다.
//
// ## 왜 필요했나
//
// 대조군은 원본의 한 조각을 찾아 무력화한 사본을 만든다. 그 조각이 **여러 줄**이면
// 치환 문자열에 `\n` 이 들어간다.
//
// ```js
// source.replace(
//   'let index = this.events.length;\n    while (index > 0 && …',   // ← \n
//   'return this.events.length;',
// )
// ```
//
// 그런데 이 저장소의 소스는 **173개가 CRLF** 이고 LF 는 5개뿐이다. CRLF 파일에서 저 치환은
// 아무것도 못 바꾸고, 검사는 「대조군을 만들지 못했다」로 떨어진다. 한 줄짜리 대조군은
// 멀쩡히 통과하므로 **여러 줄을 찾는 것만 조용히 죽는다.**
//
// `verify:trace-append` 가 그렇게 늘 빨갰고, 그 빨강이 진짜 회귀(`verify:connection-panel`)를
// 가렸다 — 「원래 2개는 빨갛다」가 통했기 때문이다.
//
// ## 저장소 줄끝을 바꾸지 않는 이유
//
// `.gitattributes` 로 통일하면 **173개 파일이 통째로 diff 에 뜬다.** 고쳐야 할 것은
// 작업본이 아니라 **줄끝을 보고 있던 검사** 쪽이다.
//
// 치환 문자열은 안 고친다 — 지금 `\n` 으로 적혀 있는 것이 맞고, 읽는 쪽이 맞춰 주면 된다.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * 검사가 읽는 소스. **줄끝을 LF 로 정규화한다.**
 *
 * 바이트 동일성을 재는 검사(`verify:stt-port`)는 이것을 쓰면 안 된다 — 거기서는 줄끝도
 * 비교 대상이다. 그쪽은 `readFileSync` 를 그대로 쓴다.
 */
export function readSource(...parts) {
  return readFileSync(join(...parts), 'utf8').replace(/\r\n/g, '\n');
}

/**
 * 대조군을 만든다. **치환이 아무것도 안 바꿨으면 그 사실을 말한다.**
 *
 * 각 스크립트가 `if (code === source) failures.push('대조군을 만들지 못했다 — …')` 를
 * 손으로 적고 있었는데, 그 한 줄을 빼먹으면 **대조군이 원본과 같은 채로 통과한다** —
 * 검사가 아무것도 안 재게 된다. 여기 모아 두면 빼먹을 수 없다.
 *
 * @returns 바뀐 소스. 안 바뀌었으면 `null`.
 */
export function mutate(source, from, to) {
  const next = source.replace(from, to);
  return next === source ? null : next;
}
