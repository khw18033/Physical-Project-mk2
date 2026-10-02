/**
 * src/stt/availability.ts
 *
 * **STT 서비스가 없어도 화면이 뜬다** 는 제약을 코드로 붙잡아 두는 곳 (VZ-C-02 / VZ-G-01).
 *
 * 이 판단을 화면 컴포넌트 안에 조건문으로 흩어 놓으면, 나중에 누가 조건 하나를 넓히면서
 * 수동 입력까지 같이 잠가도 아무도 모른다. 그래서 **"무엇이 켜지고 무엇이 꺼지는가"를
 * 의존 없는 순수 함수 하나**로 뽑아 두고, `verify:no-stt` 가 이 함수를 실제로 불러 검사한다.
 */

export type SttStatus = 'probing' | 'ready' | 'unavailable';

export type UtteranceCapabilities = {
  /** 마이크 녹음 버튼 */
  canRecord: boolean;
  /** 녹음·파일을 서비스로 보내는 경로 */
  canTranscribe: boolean;
  /**
   * 사람이 문장을 직접 넣는 길. **타입이 `true` 로 고정되어 있다.**
   * 상태에 따라 잠글 수 있게 만들면 언젠가 잠기기 때문이다.
   */
  manualInput: true;
  /**
   * 무엇이 왜 꺼졌는지 — **사전 키**. 화면이 `t()` 로 푼다 (260918).
   *
   * **이 파일은 의존이 없다**(`verify:no-stt`·`verify:no-llm` 이 그대로 불러 쓴다).
   * 여기서 `t()` 를 부르면 사전과 언어 모듈이 딸려 들어와 그 성질이 깨진다 — 그래서
   * 키만 돌려주고 푸는 것은 읽는 자리의 몫이다.
   */
  noteKey: string | null;
  /**
   * `probe()` 가 돌려준 **실패 사유 한 줄**. 우리가 쓴 문장이 아니므로 키가 없다 —
   * 화면이 위 문장 뒤에 그대로 붙인다.
   */
  noteDetail: string | null;
};

/**
 * `detail` — `probe()` 가 돌려준 **실패 사유 한 줄** (260901 요구 3).
 *
 * 늘어나는 것은 `note` 의 내용뿐이다. 켜고 끄는 판단(특히 `manualInput`)은 이 값에
 * **영향받지 않는다** — 사유를 못 만들었다고 수동 입력이 잠기면 안 된다.
 */
export function capabilities(
  status: SttStatus,
  mediaRecorderSupported: boolean,
  detail?: string | null,
): UtteranceCapabilities {
  const manualInput = true as const;
  if (status === 'unavailable') {
    return {
      canRecord: false,
      canTranscribe: false,
      manualInput,
      // 사유가 있으면 붙인다 — 「서비스가 없다」와 「떠 있는데 브라우저가 막았다」는
      // 고치는 방법이 전혀 다른데 8/31까지는 화면에서 구별되지 않았다.
      noteKey: 'stt.avail.unreachable',
      noteDetail: detail !== null && detail !== undefined && detail.length > 0 ? detail : null,
    };
  }
  if (status === 'probing') {
    return { canRecord: false, canTranscribe: false, manualInput, noteKey: 'stt.avail.checking', noteDetail: null };
  }
  if (!mediaRecorderSupported) {
    return {
      canRecord: false,
      canTranscribe: true,
      manualInput,
      noteKey: 'stt.avail.noRecorder',
      noteDetail: null,
    };
  }
  return { canRecord: true, canTranscribe: true, manualInput, noteKey: null, noteDetail: null };
}
