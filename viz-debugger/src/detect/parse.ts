/**
 * src/detect/parse.ts (260912 신설)
 *
 * **탐지가 준 모양 → 화면이 읽는 모양.** 바꾸는 자리는 여기 하나다.
 *
 * ## 각도는 「스캔 시작이 0도」다 (260912 결정)
 *
 * 화면이 고른 방향을 말할 때 로봇의 `yaw_deg` 를 쓰지 않는다. 스캔을 시작한 자세를 0도로
 * 두고 거기서 몇 도를 돌았는지로 말한다 — 그것이 탐지의 `rotation_deg` 와 같은 축이다.
 *
 * 도면 기준의 **실제 방위**(`absolute_bearing_deg`)는 없애지 않는다. 근거에만 적는다.
 * 두 값이 섞이면 화면이 엉뚱한 쪽을 가리키고, **틀렸다는 것이 눈에 안 보인다.**
 *
 * ## 한 칸 밀림
 *
 * `rotation_deg / step_deg` 가 우리 칸 번호다. 로봇의 `step` 은 1부터이고 탐지의
 * `rotation_deg` 는 0부터다. 한 칸 밀려도 화면은 그럴싸하게 돌아간다 — 여덟이 차례로
 * 켜지고 초록도 하나 뜬다. 눈으로는 못 잡는다. `verify:detect-map` 이 그것부터 본다.
 */

import { t } from '../i18n/dict.ts';
import type { DetectFeatures, DetectFrame, DetectFrameEvidence, DetectGate } from './types.ts';

/**
 * **각도 → 칸 번호.** 범위 밖이면 null — 없는 칸을 만들어 그리면 화면이 대본보다 커진다.
 *
 * `step_deg` 를 45 로 박지 않는다. 스캔 파라미터라 화면에서 바뀐다.
 */
export function indexOfRotation(rotationDeg: number, stepDeg: number, count: number): number | null {
  if (!Number.isFinite(rotationDeg) || stepDeg <= 0) return null;
  const raw = rotationDeg / stepDeg;
  // 45.0 처럼 딱 떨어지는 값만 받는다. 44.7 은 어느 칸인지 우리가 정할 일이 아니다.
  if (Math.abs(raw - Math.round(raw)) > 1e-6) return null;
  const index = Math.round(raw);
  return index >= 0 && index < count ? index : null;
}

/**
 * **`[x1,y1,x2,y2]` → `[x,y,w,h]`.** 탐지가 저 모양으로 주고 화면은 이 모양을 쓴다
 * (260912 결정 — 우리가 바꾼다).
 *
 * 뒤집힌 상자(x2 < x1)도 받는다. 음수 폭은 그리는 쪽에서 사라져 버려서 「탐지가 못 찾았다」와
 * 구별되지 않는다.
 */
export function boxOf(xyxy: readonly number[] | null | undefined): number[] | null {
  if (!Array.isArray(xyxy) || xyxy.length !== 4 || xyxy.some((n) => !Number.isFinite(n))) return null;
  const [x1, y1, x2, y2] = xyxy as number[];
  return [Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1)];
}

/**
 * 화면에 적을 **점수의 이름**. `final_score` 는 특징 여덟 중 최고값이지 확률이 아니다.
 *
 * 0.2696 을 「신뢰도 27%」로 적으면 보는 사람은 「거의 못 찾았다」로 읽는다. 실제로는
 * 관문 넷을 다 통과한 **확실한** 판정이다. 이름을 바꾸는 것만으로 그 오독이 사라진다.
 */
/**
 * **키를 담는다.** 최상위 상수라 여기서 `t()` 를 부르면 로드 시점 언어로 굳는다 —
 * 언어 버튼으로 바꿔도 안 따라온다 (지시서 §1 · 260919 에 이 모양 29자리를 고쳤다).
 */
export const SCORE_LABEL_KEY = 'dps.1';

/** 관문 하나를 사람이 읽는 한 조각으로. 통과 여부와 **왜**를 같이 적는다. */
export function gateWords(name: string, gate: DetectGate): string {
  if (gate.winning_color !== undefined) return t('dps.color', { value: strip(gate.winning_color) });
  if (gate.winning_shape !== undefined) return t('dps.shape', { value: strip(gate.winning_shape) });
  if (gate.similarity !== undefined) {
    return t('dps.similarity', { value: gate.similarity.toFixed(2) }) + (gate.threshold_min === undefined ? '' : `/${gate.threshold_min}`);
  }
  if (gate.median_saturation !== undefined) {
    return t('dps.saturation', { value: gate.median_saturation }) + (gate.min_saturation === undefined ? '' : `/${gate.min_saturation}`);
  }
  return name;
}

/** `a door's light blue color` → `light blue`. 앞뒤의 군더더기를 뗀다. */
function strip(phrase: string): string {
  return phrase.replace(/^a[n]? .*?'s /, '').replace(/^(a|an) /, '').replace(/ (color|shape)$/, '');
}

/**
 * **한국어 한 문장을 우리가 만든다** (260912 결정 — 탐지 쪽이 안 준다).
 *
 * 통과한 관문을 그대로 늘어놓는다. 지어내지 않는다 — 여기 적히는 것은 전부 받은 값이다.
 * 근거를 더 보려면 칸을 열면 특징 여덟 점수가 다 있다.
 */
export function reasonOf(
  evidence: DetectFrameEvidence | null,
  found: boolean,
  chosen = true,
): string {
  if (!found) return t('dps.2');
  const score = evidence === null ? null : `${t(SCORE_LABEL_KEY)} ${evidence.final_score.toFixed(2)}`;

  /**
   * **찾았는데 안 고른 칸.** 초록은 하나이므로 나머지는 탈락으로 그려지는데, 거기에
   * 「관문 통과」라고 적으면 **화면이 스스로 모순된다** — 통과했다면서 탈락이다.
   *
   * 문이 두 방향에서 잡히는 것은 측정값이다(시료의 270·315). 그때 「문 없음」이라고
   * 적는 것도 거짓이다 — 문은 거기 있었고 우리가 다른 쪽을 골랐을 뿐이다.
   */
  if (!chosen) return t('dps.candidateNotChosen') + (score === null ? '' : ` · ${score}`);

  if (evidence === null) return t('dps.3');
  const gates = Object.entries(evidence.mandatory_gates ?? {});
  const passed = gates.filter(([, gate]) => gate.passed).map(([name, gate]) => gateWords(name, gate));
  if (passed.length === 0) return t('dps.doorFound', { score: score ?? '' });
  return t('dps.gatesPassed', { gates: passed.join(' · '), score: score ?? '' });
}

/**
 * **초록이 될 칸.** 찾은 것 중 점수가 가장 높은 하나다.
 *
 * 문이 두 방향에서 잡히는 것은 **가정이 아니라 측정값**이다 — 받은 시료에서 270도와
 * 315도가 둘 다 `found` 였고 점수 차이가 0.0016 이었다. 흔들리면 초록이 옮겨 다닌다.
 * 그래서 **동점이면 먼저 본 각도**를 쓴다. 같은 판을 다시 그릴 때 답이 바뀌면 안 된다.
 *
 * 하나도 못 찾았으면 null 이다. **임의로 한 방향을 고르지 않는다** — 그때는 「문을 찾지
 * 못함」에서 멈추는 것이 맞다.
 */
export function chosenFrame(
  frames: readonly DetectFrame[],
  scoreOf: (frame: DetectFrame) => number,
): DetectFrame | null {
  let best: DetectFrame | null = null;
  let bestScore = -Infinity;
  for (const frame of frames) {
    if (!frame.found) continue;
    const score = scoreOf(frame);
    if (score > bestScore) { bestScore = score; best = frame; }
  }
  return best;
}

/**
 * 깊이값을 거리로 그려도 되는가. **문에서는 안 된다.**
 *
 * 시료가 `distance_cm: 0.0` · `in_valid_calibration_range: false` 로 왔고, 자료가 직접
 * 「도면상 고정 위치가 있는 랜드마크는 이 값 대신 고정 위치까지의 거리를 쓴다」고 적었다.
 * 그대로 「0.0m」로 그리면 거짓이다.
 */
export function usableDistanceCm(frame: DetectFrame): number | null {
  if (frame.in_valid_calibration_range !== true) return null;
  if (typeof frame.distance_cm !== 'number' || frame.distance_cm <= 0) return null;
  return frame.distance_cm;
}

/**
 * **「무엇을 그 클래스라고 물었나」를 화면이 읽는 모양으로** (260919).
 *
 * 탐지가 주는 `features_sent.json` 은 **클래스로 묶여 있다.**
 *
 *     { "door": { "features_compared": [...], … }, "_all_searched_classes": ["door", "pedestal"] }
 *
 * 그런데 `DetectFeatures` 는 **한 클래스의 평평한 모양**이다. 받는 자리가 검사 없이
 * `getJson<DetectFeatures>` 로 타입만 씌우고 있어서, `features_compared` 가 `undefined`
 * 인 채로 화면까지 갔다. 판단 근거를 **확대**했을 때만 그 값을 읽으므로 — 그때만 터졌다.
 * 더블클릭하면 사이트가 튕기던 것이 이것이다(260919 에 사람이 찾았다. 한·영 무관).
 *
 * 기록에도 묶인 모양 그대로 들어가 있다(45판 전부). 그래서 **다시보기도 여기를 거친다** —
 * 그러지 않으면 옛 기록은 영영 못 연다.
 *
 * 못 읽는 모양이면 `null` 이다. 화면은 `features === null` 을 이미 다루고 있다 —
 * **반쪽짜리 객체를 넘기는 것보다 없다고 말하는 편이 낫다.**
 */
export function normalizeFeatures(raw: unknown, target = 'door'): DetectFeatures | null {
  if (raw === null || typeof raw !== 'object') return null;
  const box = raw as Record<string, unknown>;
  // 묶인 모양이면 그 클래스를 꺼낸다. 평평한 모양이면 그대로 본다.
  const inner = (box[target] !== null && typeof box[target] === 'object' ? box[target] : box) as Record<string, unknown>;
  const list = inner.features_compared;
  if (!Array.isArray(list) || list.some((v) => typeof v !== 'string')) return null;
  return {
    target_class: typeof inner.target_class === 'string' ? inner.target_class : target,
    requested_by_command: inner.requested_by_command === true,
    is_localization_landmark: inner.is_localization_landmark === true,
    features_compared: list as readonly string[],
  };
}
