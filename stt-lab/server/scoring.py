"""CER / WER 계산.

외부 라이브러리를 쓰지 않는다. 편집거리는 40줄이면 되고, `jiwer` 같은 걸 끌어오면
정규화 규칙이 라이브러리 기본값에 숨어서 "이 CER은 어떤 규칙으로 잰 값인가"를
문서로 설명할 수 없게 된다. 여기서는 규칙이 전부 이 파일 안에 보인다.

한국어는 교착어라 어절 단위 WER이 실제 인식 품질보다 나쁘게 나온다("로봇을"/"로봇은"이
통째로 오답). 그래서 **음절 단위 CER을 기본**으로 하고, WER은 참고치로만 둔다.
자모 CER은 종성 하나 틀린 것(`했다`/`핬다`)과 글자가 통째로 틀린 것을 구분해 준다.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"

_HANGUL_BASE = 0xAC00
_HANGUL_LAST = 0xD7A3

# 문장부호. 명령 인식에서는 보통 지우는 게 맞지만, 근거를 남기려면 양쪽을 봐야 하므로
# 지울지 말지는 호출자가 토글로 정한다.
_PUNCT = re.compile(r"[.,!?;:\"'`~^\-_/\\()\[\]{}<>·…‥「」『』“”‘’]")


def normalize(text: str, *, strip_punctuation: bool = True) -> str:
    """비교 전 정규화.

    - 유니코드 NFC: 자모가 분리된 채로 들어온 문자열(macOS 업로드 등)이 통째로 오답이 되는 걸 막는다.
    - 앞뒤 공백 제거, 연속 공백 1칸.
    - 문장부호 제거는 선택. Whisper는 마침표를 잘 붙이는데, 명령 인식에서 그건 오답이 아니다.
    """
    text = unicodedata.normalize("NFC", text or "")
    if strip_punctuation:
        text = _PUNCT.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def decompose_jamo(text: str) -> list[str]:
    """한글 음절을 초·중·종성으로 분해한다. 한글이 아닌 글자는 그대로 둔다."""
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if _HANGUL_BASE <= code <= _HANGUL_LAST:
            offset = code - _HANGUL_BASE
            out.append(_CHO[offset // 588])
            out.append(_JUNG[(offset % 588) // 28])
            jong = _JONG[offset % 28]
            if jong != " ":
                out.append(jong)
        else:
            out.append(ch)
    return out


def edit_distance(ref: list[str] | str, hyp: list[str] | str) -> int:
    """레벤슈타인 거리. 두 줄짜리 DP — 짧은 발화라 메모리 최적화가 목적이 아니라 명확함이 목적이다."""
    ref, hyp = list(ref), list(hyp)
    if not ref:
        return len(hyp)
    previous = list(range(len(ref) + 1))
    for j, h in enumerate(hyp, start=1):
        current = [j]
        for i, r in enumerate(ref, start=1):
            current.append(
                min(
                    previous[i] + 1,  # 삭제
                    current[i - 1] + 1,  # 삽입
                    previous[i - 1] + (r != h),  # 치환
                )
            )
        previous = current
    return previous[-1]


def _rate(ref_units: list[str], hyp_units: list[str]) -> dict[str, Any]:
    distance = edit_distance(ref_units, hyp_units)
    total = len(ref_units)
    return {
        "distance": distance,
        "ref_len": total,
        "hyp_len": len(hyp_units),
        # 정답이 비면 분모가 0이다. 이때는 "가설이 비었으면 0, 아니면 1"이 유일하게 말이 된다.
        "rate": (distance / total) if total else (0.0 if not hyp_units else 1.0),
    }


def score(reference: str, hypothesis: str, *, strip_punctuation: bool = True) -> dict[str, Any]:
    """CER(음절) · CER(자모) · WER 을 한 번에 낸다.

    셋을 같이 보는 이유: 음절 CER만 보면 "종성 하나 틀림"과 "단어를 통째로 놓침"이
    비슷한 숫자로 보인다. 어느 쪽인지에 따라 F13에서 할 일이 다르다 —
    전자는 임계값 조정, 후자는 hotwords 보강이다.
    """
    ref = normalize(reference, strip_punctuation=strip_punctuation)
    hyp = normalize(hypothesis, strip_punctuation=strip_punctuation)

    # 음절 CER 에서는 공백을 세지 않는다. 띄어쓰기는 명령 인식의 정오와 무관한데
    # 글자 수의 15%쯤을 차지해서 CER을 통째로 흐린다.
    ref_chars = [c for c in ref if not c.isspace()]
    hyp_chars = [c for c in hyp if not c.isspace()]

    cer = _rate(ref_chars, hyp_chars)
    jamo = _rate(decompose_jamo("".join(ref_chars)), decompose_jamo("".join(hyp_chars)))
    wer = _rate(ref.split(), hyp.split())

    return {
        "reference_normalized": ref,
        "hypothesis_normalized": hyp,
        "strip_punctuation": strip_punctuation,
        "cer": round(cer["rate"], 4),
        "cer_detail": cer,
        "cer_jamo": round(jamo["rate"], 4),
        "cer_jamo_detail": jamo,
        "wer": round(wer["rate"], 4),
        "wer_detail": wer,
        "exact_match": ref == hyp,
    }
