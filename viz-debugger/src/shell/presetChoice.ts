/**
 * src/shell/presetChoice.ts (260921 신설 — 연결 관리 프리셋 고르기)
 *
 * **프리셋 칸이 무엇으로 보이고, 고르면 무엇이 일어나는가.** 두 함수뿐이다.
 *
 * `ConnectionsPanel` 안의 `<select>` 에 인라인으로 들어 있던 식을 꺼냈다. 꺼낸 이유는
 * 거기 **버그가 하나 있었는데 검사가 그것을 볼 방법이 없었기** 때문이다 — 판은 JSX 라
 * 검사가 글자로만 읽고, 고르는 동작은 글자로 안 드러난다.
 *
 * ## 무엇이 틀렸었나 (260921 — 사람이 화면에서 찾아냈다)
 *
 * 「직접 입력」을 골라도 **아무 일도 안 일어났다.** 목록이 곧바로 옛 프리셋으로 되돌아간다.
 *
 * ```js
 * // 전
 * value={presets.find((p) => p.url === draft[key])?.id ?? 'manual'}
 * onChange={(e) => { const p = find(e.target.value); if (p && p.url) setDraft(p.url); }}
 * //                                                        ^^^^^ 직접 입력은 url 이 '' 이라 여기서 걸린다
 * ```
 *
 * 「직접 입력」의 `url` 은 빈 문자열이다 — 고를 주소가 없다는 뜻이고 그건 맞다. 그런데
 * `if (p.url)` 이 그걸 거짓으로 읽어 `setDraft` 를 안 부르고, 주소가 안 바뀌니 `value` 를
 * 내는 식이 **여전히 옛 프리셋을 찾아낸다.** 고른 것이 화면에 안 남는다.
 *
 * 주소를 손으로 고치면 그때는 어느 프리셋과도 안 맞아서 「직접 입력」으로 넘어갔다 —
 * 그래서 「고칠 때만 되는」 것처럼 보였다.
 *
 * ## 고친 방식 — 고른 것을 **기억한다**
 *
 * 고름은 주소에서 되풀이해 유도할 수 없다. 「직접 입력」은 **주소가 아니라 사람의 뜻**이라
 * 주소만 보고는 알 수 없기 때문이다 — 손으로 친 주소가 우연히 프리셋과 같을 수도 있고,
 * 그때 목록이 제멋대로 프리셋으로 바뀌면 고쳐 쓰던 사람이 놀란다.
 *
 * 그래서 「직접 입력을 골랐다」를 따로 들고 있고, 프리셋을 다시 고르면 풀린다.
 *
 * **주소는 안 건드린다.** 직접 입력으로 넘어갈 때 칸을 비우면 지금 주소를 잃는다 —
 * 대개는 그 주소를 조금 고치려고 직접 입력을 고르는 것이다.
 */

/** 이 함수들이 쓰는 만큼. 프리셋 타입 셋(로봇·탐지·기능 상태·영상)이 다 이 모양이다. */
export type PresetLike = { id: string; url: string };

/** 손으로 넣는 자리의 id. 프리셋 목록 넷이 다 이 이름을 쓴다. */
export const MANUAL_ID = 'manual';

/**
 * 지금 **고른 것으로 보여야 할** id.
 *
 * 사람이 직접 입력을 골랐으면 그것이 이긴다 — 주소가 우연히 프리셋과 같아도 그렇다.
 * 아니면 주소로 찾고, 어느 것과도 안 맞으면 직접 입력이다(주소를 손으로 고친 경우).
 */
export function selectedPresetId(
  presets: readonly PresetLike[],
  url: string,
  manual: boolean,
): string {
  if (manual) return MANUAL_ID;
  // 빈 주소는 **어느 프리셋도 아니다.** 값이 빈 프리셋과 짝지으면 안 된다.
  if (url === '') return MANUAL_ID;
  return presets.find((preset) => preset.url === url)?.id ?? MANUAL_ID;
}

/**
 * 하나를 골랐다. 무엇이 바뀌는가.
 *
 * @returns `manual` 은 「직접 입력을 골랐다」를 기억할 값이고, `url` 은 주소 칸에 넣을 것이다.
 *          **`url` 이 `null` 이면 주소를 안 건드린다.**
 */
export function applyPresetChoice(
  presets: readonly PresetLike[],
  id: string,
): { manual: boolean; url: string | null } {
  if (id === MANUAL_ID) return { manual: true, url: null };
  const preset = presets.find((p) => p.id === id);
  // 값이 빈 프리셋(아직 주소가 없는 자리)은 넣을 것이 없다 — 화면이 고를 수 없게 막아 두지만,
  // 막힌 것을 어떻게든 골랐다면 주소를 비우는 것보다 그대로 두는 편이 낫다.
  if (preset === undefined || preset.url === '') return { manual: false, url: null };
  return { manual: false, url: preset.url };
}
