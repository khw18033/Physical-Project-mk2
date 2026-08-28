/**
 * src/stt/confidence.ts
 *
 * 신뢰도 판정이 일어나는 **유일한 지점** (VZ-L-03 / REQ-1306).
 *
 * ## 값은 아직 정해지지 않았다 — 잠정 · 실측 미완
 *
 * `reports/2026-08-25_1506_stt-model-comparison-lab.md` §주요 판단의 결론이 그대로 남아 있다.
 * "정답·오답·무음·소음, hotwords/VAD 조합을 반복 측정한 뒤 정답 오거부율과 오답 통과율을
 * 비교해야 `REQ-1306` 임계값을 확정할 수 있다." 그 측정은 아직 하지 않았다.
 *
 * 그래서 이 파일이 하는 일은 **값을 정하는 것이 아니라 값이 놓일 자리를 만드는 것**이다.
 * 판정이 여기 한 곳에서만 일어나면, 실측이 끝났을 때 고칠 곳도 여기 하나다.
 *
 * ## 세 수치를 하나로 합치지 않는다
 *
 * Whisper 는 단일 confidence 를 주지 않는다. 세 수치를 가중합해 0~1 점수 하나로 뭉개면
 * 판정은 간단해지지만 **임계를 실측할 근거가 사라진다** — 어느 수치가 걸렀는지 알 수 없고,
 * 가중치 자체가 또 하나의 미확정 값이 되기 때문이다. 그래서 셋을 각각 따로 본다.
 *
 * ## 이 판정이 못 잡는 것 — 알고 남겨 둔다
 *
 * **무음에 대한 반복 환각은 세 수치를 전부 통과한다.** 실측에서 VAD 를 끈 3초 무음 입력이
 * `avg_logprob -0.088` · 평균 단어 확률 `0.933` 으로 나왔다 — 정답 발화보다 좋은 값이다
 * (`reports/2026-08-28_1620_STT이식.md` §실측). 모델이 자기가 만들어낸 반복을 확신한다.
 *
 * 그 케이스를 실제로 거르는 것은 둘이다.
 *   1. **VAD** — 기본으로 켜져 있고, 켜면 세그먼트가 0건이 되어 빈 문자열로 온다.
 *      지금 무음이 거절되는 것은 아래 임계가 아니라 VAD 덕분이다.
 *   2. **`compression_ratio`** — 위 두 경우 각각 `12.42`·`3.48`. 반복을 직접 재는 유일한 수치이고
 *      응답의 `segments[]` 에 이미 실려 온다.
 *
 * 네 번째 축으로 `compression_ratio` 를 넣을지는 **계약 결정과 같이 가야 하는 문제**라
 * (어디에 실을 것인가가 같은 문제다) 여기서 혼자 정하지 않았다. 다음 작업의 미결 항목이다.
 */

import type { SttResult } from './types.ts';

export type Verdict = 'accept' | 'confirm' | 'reject';

export type ConfidenceThresholds = {
  rejectNoSpeechProbAtLeast: number;
  rejectAvgLogprobBelow: number;
  acceptAvgLogprobAtLeast: number;
  acceptMeanWordProbAtLeast: number;
  acceptNoSpeechProbAtMost: number;
};

/**
 * **잠정값. 실측 미완.** 근거의 세기가 항목마다 다르므로 항목별로 적는다.
 *
 * - `rejectNoSpeechProbAtLeast` / `rejectAvgLogprobBelow`
 *   — 근거 있음. faster-whisper 가 자기 디코딩에서 쓰는 문턱 그대로다
 *     (`engines/faster_whisper.py` 의 `NO_SPEECH_THRESHOLD = 0.6`,
 *      `LOG_PROB_THRESHOLD = -1.0`). 엔진이 "이건 말이 아니다 / 이건 못 믿겠다"고
 *     판단하는 선과 화면의 거절선을 다르게 둘 이유가 지금은 없다. 임의로 고른 숫자가
 *     아니라 **엔진의 기본 문턱을 빌려 온 것**이고, 응답의 `applied_options` 에 그 값이
 *     실려 오므로 나중에 분포와 대조할 수 있다.
 * - `acceptAvgLogprobAtLeast` / `acceptMeanWordProbAtLeast` / `acceptNoSpeechProbAtMost`
 *   — **근거 약함. 감이다.** 1~3초짜리 명령 발화 몇 건을 눈으로 보고 "이 정도면 맞더라"
 *     수준에서 잡은 선이다. 정답 오거부율·오답 통과율을 재서 정한 값이 아니다.
 *     실측 전까지 이 선을 근거로 어떤 결정도 정당화하지 않는다.
 *
 * 위 두 묶음의 사이는 전부 `confirm` 이다. **확실하지 않으면 사람에게 묻는다** —
 * 조용히 통과시키는 쪽으로 기울이지 않는다.
 */
export const PROVISIONAL_THRESHOLDS: ConfidenceThresholds = {
  rejectNoSpeechProbAtLeast: 0.6,
  rejectAvgLogprobBelow: -1.0,
  acceptAvgLogprobAtLeast: -0.4,
  acceptMeanWordProbAtLeast: 0.8,
  acceptNoSpeechProbAtMost: 0.2,
};

/** 화면에 그대로 붙는 문구. 값이 잠정이라는 사실을 감추지 않는다. */
export const PROVISIONAL_NOTE = '잠정 — 실측 미완 (VZ-L-03)';

export type ConfidenceDecision = {
  verdict: Verdict;
  /** 어느 수치가 이 판정을 만들었는가. 사람이 재확인할 때 읽는다. */
  reasons: string[];
  /** 판정에 쓰인 세 수치. 뭉치지 않고 그대로 옮긴다. */
  metrics: {
    avgLogprob: number | null;
    noSpeechProb: number | null;
    meanWordProb: number | null;
  };
  provisional: true;
};

/**
 * 세 수치 → `accept` / `confirm` / `reject`.
 *
 * 수치가 없으면(단어가 하나도 안 나온 경우 등) `confirm` 이다. 없는 것을 통과시키지 않는다.
 */
export function decide(result: SttResult, thresholds: ConfidenceThresholds = PROVISIONAL_THRESHOLDS): ConfidenceDecision {
  const metrics = {
    avgLogprob: result.avg_logprob,
    noSpeechProb: result.no_speech_prob,
    meanWordProb: result.mean_word_prob,
  };
  const reasons: string[] = [];
  const base: Omit<ConfidenceDecision, 'verdict'> = { reasons, metrics, provisional: true };

  if (!result.text.trim()) {
    reasons.push('인식된 문장이 비어 있습니다');
    return { ...base, verdict: 'reject' };
  }
  if (metrics.noSpeechProb !== null && metrics.noSpeechProb >= thresholds.rejectNoSpeechProbAtLeast) {
    reasons.push(`no_speech_prob ${metrics.noSpeechProb.toFixed(3)} ≥ ${thresholds.rejectNoSpeechProbAtLeast} — 말소리가 아닐 가능성이 높습니다`);
  }
  if (metrics.avgLogprob !== null && metrics.avgLogprob < thresholds.rejectAvgLogprobBelow) {
    reasons.push(`avg_logprob ${metrics.avgLogprob.toFixed(3)} < ${thresholds.rejectAvgLogprobBelow} — 엔진이 자기 디코딩을 믿지 못하는 구간입니다`);
  }
  if (reasons.length) return { ...base, verdict: 'reject' };

  if (metrics.avgLogprob === null || metrics.noSpeechProb === null || metrics.meanWordProb === null) {
    reasons.push('판정에 필요한 수치가 비어 있습니다 — 사람이 확인해야 합니다');
    return { ...base, verdict: 'confirm' };
  }
  const accepted =
    metrics.avgLogprob >= thresholds.acceptAvgLogprobAtLeast &&
    metrics.meanWordProb >= thresholds.acceptMeanWordProbAtLeast &&
    metrics.noSpeechProb <= thresholds.acceptNoSpeechProbAtMost;
  if (accepted) {
    reasons.push(`세 수치가 모두 잠정 수락 구간입니다 (${PROVISIONAL_NOTE})`);
    return { ...base, verdict: 'accept' };
  }
  if (metrics.avgLogprob < thresholds.acceptAvgLogprobAtLeast) reasons.push(`avg_logprob ${metrics.avgLogprob.toFixed(3)} < ${thresholds.acceptAvgLogprobAtLeast}`);
  if (metrics.meanWordProb < thresholds.acceptMeanWordProbAtLeast) reasons.push(`평균 단어 확률 ${metrics.meanWordProb.toFixed(3)} < ${thresholds.acceptMeanWordProbAtLeast}`);
  if (metrics.noSpeechProb > thresholds.acceptNoSpeechProbAtMost) reasons.push(`no_speech_prob ${metrics.noSpeechProb.toFixed(3)} > ${thresholds.acceptNoSpeechProbAtMost}`);
  return { ...base, verdict: 'confirm' };
}

export const VERDICT_LABEL: Record<Verdict, string> = {
  accept: '수락',
  confirm: '재확인 필요',
  reject: '거절',
};
