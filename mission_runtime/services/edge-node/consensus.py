"""두 OVD 모델의 **합의**로 확정을 정의한다.

implements: AI-S-03, AI-S-04, AI-E-04, AI-C-04, AI-C-15, AI-B-01

**왜 합의인가**(사용자 제안 2026-09-21, 선행 연구와 같은 방식): 단일 모델의 conf는
"이 모델이 얼마나 확신하는가"이지 "근거가 충분한가"가 아니다. AI-S-03이 그 둘을
따로 평가하라고 요구하는 지점이 정확히 여기다. 서로 다른 어휘·학습·구조를 가진 두
모델이 같은 자리에서 같은 것을 말하면, 그것은 한 모델이 높은 점수를 준 것과 질이
다른 근거다.

같은 프레임 실측(2026-09-21, 실내 로봇 실험실):

    대상          YOLOE prompt-free      YOLO-World 텍스트     합의
    회색 의자     computer chair 0.87    office chair 0.45     O
    걸린 백팩     computer chair 0.83    backpack 0.55         X  ← YOLOE 오답
    음료병        bottle 0.71            bottle 0.56           O
    검은 의자     computer chair 0.61    person 0.53           X  ← World 오답
    흰 캐비닛     flipchart 0.94         whiteboard 0.35       X
    키보드        keyboard 0.32          keyboard 0.27         O

**두 모델은 서로 다른 곳에서 틀린다.** 그래서 교집합이 각자보다 낫다. 특히 YOLOE는
0.94/0.87처럼 높은 conf로 틀리므로 임계를 올리는 것으로는 이 오답을 거를 수 없다.

두 모델의 역할은 대칭이 아니다:
  * prompt-free 쪽은 **도메인을 모르는 상태로** 넓게 본다. 어휘 설계 없이 새 현장에
    투입할 수 있어야 한다는 요구(AI-C-15)를 이쪽이 감당한다.
  * 텍스트 프롬프트 쪽은 **그 현장에서 볼 것**으로 좁힌다. 어휘는 설정이며 코드가
    아니다.

합의하지 않은 검출은 버리지 않는다. `tentative`로 남아 어느 모델이 무엇을 말했는지
함께 실린다 — 관리자가 두 근거를 나란히 보고 판단할 수 있어야 한다(AI-L-03).
"""

from __future__ import annotations

from common import iou

# **"몇 개가 합의하면 확정인가" 의 주인은 프레임워크다**(2026-11-05 통합 2단계).
#
# 이 파일은 그 수를 숫자로 적지 않았다 — 쌍으로만 동작하면서 "둘이 합의하면
# confident" 를 **구조로** 들고 있었다. 적지 않은 규칙이 적힌 규칙보다 안전한 것은
# 아니다: `object_record.CONFIRMING_GROUPS` 가 3 이 되는 날 프레임워크의 승격 관문은
# 셋을 요구하는데 이 파일은 여전히 둘에 confident 를 붙이고, 둘 다 자기 시험을
# 통과한다. 그래서 수를 **가져와서** 판정에 쓴다.
#
# 쌍을 N 개로 일반화하는 것은 다른 작업이다(그때 `perception/multisource.py` 가
# 짝이다). 지금 하는 것은 **그 수의 주인을 하나로 모으는 것**뿐이다.
from mission_runtime.perception.object_record import CONFIRMING_GROUPS

# 라벨 비교에서 의미를 갖지 않는 토큰. 이것만 겹치는 것은 합의로 보지 않는다.
STOPWORDS = {"a", "an", "the", "of", "with", "and", "computer", "office",
             "electronic", "small", "large", "indoor", "outdoor"}


def _tokens(label: str) -> set[str]:
    return {t for t in str(label).lower().replace("-", " ").replace("_", " ").split()
            if t and t not in STOPWORDS}


def concept_key(label: str, synonyms: dict | None = None) -> str:
    """라벨을 **비교 가능한 개념 키**로 정규화한다. 합의 판정의 유일한 규칙이다.

    합의를 말단에서 판정하려면 말단이 라벨 비교 규칙을 알아야 하는데, 같은 규칙을
    두 곳에 두면 반드시 어긋난다(이 저장소에서 `background_classes`가 실제로 그렇게
    어긋난 적이 있다). 그래서 **규칙은 여기 한 곳에만** 두고 말단에는 정규화된 키만
    보낸다. 말단은 문자열이 같은지만 본다.

    키는 **머리 명사**다. 영어 복합명사는 뒤가 머리이므로 마지막 내용 토큰을 쓴다:

        computer chair / office chair      → chair    (같다)
        storage box / cardboard box        → box      (같다)
        computer monitor                   → monitor  (chair와 다르다)
        window blind                       → blind

    수식어(`computer`, `office`...)는 STOPWORDS로 빠지므로 `computer chair`와
    `computer monitor`가 수식어만으로 묶이는 일이 없다. 머리 명사로 못 잡는
    짝(`couch`/`sofa`)은 설정의 `synonyms`에 명시한다 — 규칙을 코드에 늘리지 않는다.
    """
    la = str(label).lower().strip()
    for name, group in (synonyms or {}).items():
        if isinstance(group, list) and la in {str(x).lower() for x in group}:
            return f"syn:{name}"
    toks = [t for t in la.replace("-", " ").replace("_", " ").split()
            if t and t not in STOPWORDS]
    return toks[-1] if toks else la


def labels_agree(a: str, b: str, synonyms: dict | None = None) -> bool:
    """두 라벨이 같은 것을 가리키는가 — `concept_key`가 같은가로 정의한다.

    규칙이 하나뿐이어야 엣지의 판정과 말단의 판정이 갈라지지 않는다.
    """
    return concept_key(a, synonyms) == concept_key(b, synonyms)


def merge_by_consensus(primary, secondary, cfg_ovd: dict):
    """두 검출 목록을 합쳐 `verdict`를 정한다.

    primary   = prompt-free(도메인 무관). secondary = 텍스트 프롬프트(도메인 어휘).
    반환: (검출 목록, 통계). 각 검출은
        verdict   "confident"(합의) | "tentative"(단독)
        sources   기여한 모델 이름들
        agree_iou 합의한 두 박스의 IoU (합의일 때만)
        alt       상대 모델이 말한 라벨·conf (합의일 때만)

    박스는 **conf가 높은 쪽**을 쓴다. 두 기하를 평균하면 어느 모델도 내놓지 않은
    좌표가 만들어지고, 그것은 관측이 아니다(AI-S-03).
    """
    thr = float(cfg_ovd.get("agree_iou", 0.5))
    syn = cfg_ovd.get("synonyms") or {}
    floor = float(cfg_ovd.get("agree_min_conf", 0.0))

    used_b: set[int] = set()
    out = []
    n_agree = 0
    for da in primary:
        best_j, best_v = -1, thr
        for j, db in enumerate(secondary):
            if j in used_b:
                continue
            v = iou(da["box"], db["box"])
            if v >= best_v and labels_agree(da["label"], db["label"], syn):
                best_j, best_v = j, v
        if best_j >= 0:
            db = secondary[best_j]
            win, lose = (da, db) if da["conf"] >= db["conf"] else (db, da)
            sources = ["prompt_free", "text_prompt"]
            # 합의한 소스 수가 프레임워크가 요구하는 독립 지지 수에 닿는가. 지금
            # 모델이 둘이라 참이지만, 요구 수가 올라가면 여기서 먼저 걸린다 —
            # 그러면 `tentative` 로 남고 버려지지는 않는다(AI-S-04, AI-L-03).
            if (min(da["conf"], db["conf"]) >= floor
                    and len(sources) >= CONFIRMING_GROUPS):
                n_agree += 1
                out.append({**win, "verdict": "confident",
                            "sources": sources,
                            "agree_iou": round(best_v, 3),
                            "alt": {"label": lose["label"],
                                    "conf": round(lose["conf"], 3)}})
                # **합의로 받아들였을 때만** secondary 를 소비한다. 전에는 짝을 찾은
                # 시점에 소비해서, 라벨은 맞았지만 floor 를 못 넘은 쌍의 secondary 가
                # **조용히 사라졌다**(검출 둘이 들어가 하나만 나왔고, 통계는
                # `secondary: 1` 이라 적으면서 산출에는 없었다). 이 파일 머리말이
                # "합의하지 않은 검출은 버리지 않는다" 고 약속한 자리다 — 확정하지
                # 못한 관측을 지우면 관리자가 두 근거를 나란히 볼 길이 사라지고
                # 학습 후보로 올릴 길도 사라진다(AI-S-04, AI-L-03).
                used_b.add(best_j)
                continue
        out.append({**da, "verdict": "tentative", "sources": ["prompt_free"]})

    for j, db in enumerate(secondary):
        if j not in used_b:
            out.append({**db, "verdict": "tentative", "sources": ["text_prompt"]})

    stats = {"primary": len(primary), "secondary": len(secondary),
             "agreed": n_agree,
             "tentative": sum(1 for d in out if d["verdict"] == "tentative")}
    return out, stats
