/**
 * src/shell/draftCommit.ts (260922 신설 — 연결 관리 「확인」이 곧 적용)
 *
 * **초안을 끝내는 자리.** 함수 하나뿐이다.
 *
 * `ConnectionsPanel` 안에 인라인으로 둘 수도 있었다. 꺼낸 이유는 `presetChoice.ts` 와 같다 —
 * **판은 JSX 라 검사가 글자로만 읽고, 저장이 무엇을 넘기는지는 글자로 안 드러난다.**
 * 그리고 여기서 틀리면 조용히 틀린다: 실패가 「다른 대상의 주소가 기본값으로 돌아갔다」로
 * 나타나고, 그것을 알아차리는 자리는 며칠 뒤 무대다.
 *
 * ## 무엇이 위험한가 — 저장은 통째로 갈아치운다
 *
 * 저장소는 **덮어쓰는 묶음 하나**를 받는다(`connections.ts`). 대상 하나를 저장한다고
 * `{ 'physical.ws': … }` 처럼 그 대상의 칸만 넘기면 나머지는 「없음」으로 읽혀 기본값으로
 * 돌아간다. 탐지 주소를 손으로 넣어 둔 사람이 로봇 확인을 한 번 누르면 탐지 주소를 잃는다.
 *
 * (저장을 **부르는 것은 연결 관리 하나**다 — `verify:one-broker-address`. 여기서는 넘길
 * 묶음을 만들기만 하고, 그래서 이 파일에 그 호출을 적지 않는다. 주석이라도 적으면 그
 * 규칙이 한 칸 느슨해진다.)
 *
 * 그래서 **지금 쓰는 주소 전부 위에 이 대상의 칸만 얹는다.** 이 함수가 그것이다.
 *
 * ## 안 바뀌었으면 `null`
 *
 * 확인을 누를 때마다 「적용했습니다」가 뜨면 그 문장이 **확인 결과처럼 읽힌다.** 확인의
 * 결과는 그 아래 상태 줄이 말한다. 바뀐 것이 없으면 저장할 것도 알릴 것도 없다.
 */

/**
 * 이 대상의 초안을 지금 주소 묶음에 얹는다.
 *
 * @param current 지금 쓰는 주소 전부 (기본값 위에 사용자 값이 얹힌 결과).
 * @param draft   편집 중인 값. 이 대상의 칸만 꺼내 쓴다.
 * @param keys    이 대상의 칸 키들 (`대상.칸`).
 * @returns 저장에 넘길 묶음. **바뀐 것이 없으면 `null`** 이다.
 */
export function commitDraft(
  current: Readonly<Record<string, string>>,
  draft: Readonly<Record<string, string>>,
  keys: readonly string[],
): Record<string, string> | null {
  const next: Record<string, string> = { ...current };
  let changed = false;
  for (const key of keys) {
    const value = draft[key] ?? '';
    if (value !== (current[key] ?? '')) changed = true;
    next[key] = value;
  }
  return changed ? next : null;
}
