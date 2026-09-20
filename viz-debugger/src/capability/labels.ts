/**
 * src/capability/labels.ts (260920 신설 — 기능 상태 패널 이식)
 *
 * **상대의 어휘를 푸는 자리.** 우리 사전(`src/i18n/dict.ts`)과 **다른 사전**이다.
 *
 * | | 원천 | 누가 고치나 |
 * |---|---|---|
 * | `t('cap.title')` | `src/i18n/{ko,en}.ts` | 우리 |
 * | `capLabel(labels.functions, 'go_to_door', lang)` | `GET /api/labels` | 상대(AI 파트) |
 * |  | ← `config/status_ui.labels.json` | |
 *
 * 둘을 한 사전에 합치면 상대가 기능을 하나 늘릴 때마다 우리 사전을 고쳐야 하고, 고치지
 * 않으면 화면에 키가 뜬다. `registry.json` 을 사본 없이 참조하는 것과 같은 규칙이다.
 *
 * **모르는 ID 는 원문을 그대로 적는다** — 전달본이 「신규 role·kind 에도 화면이 유지되도록
 * 한다」고 적은 자리다. 빈칸으로 두면 무엇이 빠졌는지 아무도 모른다.
 */

import type { Lang } from '../shared/language.ts';
import type { CapLabelGroup } from './types.ts';

/** 한 ID 의 표시 이름. 그 언어가 없으면 다른 언어, 둘 다 없으면 ID 원문. */
export function capLabel(group: CapLabelGroup, id: string, lang: Lang): string {
  const pair = group[id];
  if (pair === undefined) return id;
  const first = lang === 'en' ? pair.en : pair.ko;
  const second = lang === 'en' ? pair.ko : pair.en;
  return first ?? second ?? id;
}

/**
 * 사유 토큰 한 줄. **번역 문구를 조건식에 쓰지 않는다**(전달본) — 화면은 토큰으로 판단하고
 * 글자는 여기서만 만든다. 모르는 토큰은 원문이 뜨고, 그게 상대에게 물어볼 단서가 된다.
 */
export function capReason(
  group: CapLabelGroup, token: string | null, raw: string | null, lang: Lang, data: string | null = null,
): string | null {
  // **알맹이를 잃지 않는다** (260920 실측). 토큰만 옮기면 「필요한 태그가 없음」까지만
  // 말하고 *어느* 태그인지가 사라진다 — 고칠 수 있게 하는 값은 그쪽이다.
  if (token !== null) {
    const label = capLabel(group, token, lang);
    return data === null || data === '' ? label : `${label} — ${data}`;
  }
  return raw;
}
