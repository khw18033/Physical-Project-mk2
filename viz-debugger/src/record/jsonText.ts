/**
 * src/record/jsonText.ts (261119 신설 — 임무 이력 서버가 NUL 문자를 거절한 일)
 *
 * **JSON 글에서 NUL 문자(`\u0000`)를 뺀다.** 임무 이력 서버의 DB(PostgreSQL jsonb)는 문자열 속 `\u0000` 을
 * 받지 못한다(`unsupported Unicode escape sequence` → HTTP 400). JSON 으로는 맞는 값이라 우리 쪽 검사는
 * 지나간다. Pi 가 착륙 직후 전원이 끊기면 실행기 출력(`.out`) 끝이 NUL 바이트로 채워지고, 그 줄이 판에 들어온다.
 *
 * 글을 다시 짜지 않고 이스케이프만 지운다 — 들여쓰기 · 순서가 그대로다. `\\u0000`(역슬래시 글자 + `u0000`)은
 * NUL 이 아니므로 남긴다: 앞의 역슬래시 개수가 짝수일 때만 이스케이프다.
 */

const NUL_ESCAPE = /(?<!\\)((?:\\\\)*)\\u0000/g;

export function stripJsonNul(text: string): string {
  return text.includes('\\u0000') ? text.replace(NUL_ESCAPE, '$1') : text;
}
