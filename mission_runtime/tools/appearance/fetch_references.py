#!/usr/bin/env python3
"""기종별 외형 참조영상을 웹에서 모아 온다.

implements: AI-E-01, AI-S-04, AI-L-09
tests: tests/test_appearance_classifier.py

이 배치가 실제로 가진 장비의 "기종"을 외형으로 가르려면 그 기종을 찍은 사진이
먼저 있어야 한다. 그 사진은 제조사·언론·판매처의 저작물이라 공개 트리에 커밋하지
않는다 — 내려받는 자리는 `local/appearance/<class>/` 이고 공개되는 것은 거기서
뽑은 벡터(config/device_appearance_classes.*.json)뿐이다.

어디서 가져올지는 코드가 아니라 `reference_sources.json` 이 정한다. 새 기종이
들어올 때 고쳐야 하는 것이 스크립트라면 그것은 이미 특정 제품을 코드에 박은
것이다(원칙 #1).

## 정직하게 세는 것이 이 스크립트의 일이다

내려받은 것 중에는 열리지 않는 파일, 아이콘만큼 작은 그림, 같은 사진의 다른
해상도가 섞여 있다. 그것을 그대로 참조영상으로 세면 "기종마다 12 장 확보" 같은
숫자가 만들어지고, 그 숫자가 사전 구축과 분류 품질 판단의 근거가 된다. 그래서
탈락 사유를 파일별로 `sources.json` 에 남기고 집계도 탈락분과 분리해 적는다.

## 웹 사진이 먼저고 현장 사진이 나중이다

운용 초기에는 제품 사진밖에 없다. 나중에 같은 장비를 현장에서 찍은 사진이 생기면
그쪽이 훨씬 좋은 근거다 — 조명·각도·배경이 실제 운용과 같기 때문이다. 그래서
현장 사진은 `local/appearance/<class>/field/` 에 그냥 넣으면 되고, 이 스크립트는
거기를 건드리지 않는다. 사전을 처음부터 다시 만들 필요도 없다
(`build_dictionary.py --append`: 이미 임베딩한 사진은 그대로 두고 새 것만 더한다).

## 내려받은 것은 데이터이고 코드가 아니다

받은 파일은 `local/appearance/<class>/` 안에만 두고 이 스크립트는 그 밖에 둔다.
받은 디렉터리 안에서 인터프리터를 띄우면 거기 놓인 `json.py` 가 `import json`
으로 실행된다 — 경로는 항상 인자로 받고, 받은 내용을 실행하지 않는다.

사용법:

    python3 tools/appearance/fetch_references.py \\
        --sources tools/appearance/reference_sources.json \\
        --out-dir ../local/appearance
    python3 tools/appearance/fetch_references.py ... --contact-sheet   # 사람 검수용
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

#: Commons API 와 상점은 봇처럼 보이는 요청을 거절한다. 연락처를 남기는 것은
#: Wikimedia 의 요구이기도 하다 — 그런데 그 연락처가 **개인 메일**이면 공개 저장소에
#: 개인정보가 실린다. 그래서 값은 환경변수로 받고, 기본값은 어느 개인도 가리키지
#: 않는 프로젝트 이름이다. 배치하는 쪽이 닿을 수 있는 주소나 저장소 URL 을 넣는다.
CONTACT_ENV = "MISSION_RUNTIME_CONTACT"
DEFAULT_CONTACT = f"mission_runtime/tools/appearance; set {CONTACT_ENV} to a project contact"
USER_AGENT = (f"mission-runtime-appearance-fetch/1.1 "
              f"({os.environ.get(CONTACT_ENV) or DEFAULT_CONTACT})")
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

#: 출처가 라이선스를 말해 주지 않을 때의 값. **추측하지 않는다** — 추측한 라이선스는
#: 기록이 없는 것보다 나쁘다. 이 값이 남아 있는 참조영상은 소유자가 확인할 거리다.
LICENCE_UNDETERMINED = "undetermined"

#: 짧은 변 기준 하한. 이보다 작은 그림은 로고·아이콘이거나 CLIP 입력(224)에
#: 올리려면 확대해야 하는 것들이라 원형 벡터의 근거로 쓰지 않는다.
MIN_SHORT_SIDE = 160
#: 같은 사진의 다른 해상도·재압축본을 잡기 위한 지문 크기. 바이트 해시만 쓰면
#: `_1024x1024` 변형이 전부 다른 사진으로 세어진다.
FINGERPRINT_SIDE = 32

REASON_HTTP = "http_error"
REASON_NOT_DECODABLE = "not_a_decodable_image"
REASON_TOO_SMALL = "short_side_below_minimum"
REASON_DUPLICATE = "duplicate_of_already_kept_image"
#: 열리고 크기도 충분하지만 **그 기종이 아니다**. 자동으로는 알 수 없고 사람이
#: 격자 그림을 보고 판정한 것만 여기 들어온다.
REASON_NOT_THIS_CLASS = "excluded_by_human_review"

#: 현장에서 찍어 넣는 사진의 자리. 이 스크립트는 여기를 **읽지도 지우지도 않는다**
#: — 웹 사진은 다시 받을 수 있지만 현장 사진은 다시 찍어야 하고, 둘의 출처가
#: 섞이면 "제품 사진으로만 만든 원형"인지 아닌지를 나중에 알 수 없다.
#: `build_dictionary.py` 가 여기 있는 것을 origin=field_capture 로 읽어 더한다.
FIELD_DIR = "field"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Kept:
    file_name: str
    source_url: str
    page_url: str
    fetched_at: str
    width: int
    height: int
    sha256: str
    #: 출처 쪽이 **말한** 라이선스. 모르면 LICENCE_UNDETERMINED 이고 지어내지 않는다.
    licence: str = LICENCE_UNDETERMINED
    #: CC-BY 계열이 요구하는 저작자 표시. 요구하지 않는 라이선스에서는 빈 문자열이다.
    attribution: str = ""
    #: 그 라이선스를 어디서 읽었는지. 사람이 되짚을 수 있어야 기록이 기록이다.
    licence_source: str = ""
    #: 라이선스가 아니라 사람이 적어 둔 메모. 둘을 한 칸에 담으면 메모가 라이선스로 읽힌다.
    source_note: str = ""
    #: 해상도·재압축에 둔감한 지문. 적어 두지 않으면 덧붙이기 실행이 이미 가진
    #: 사진의 다른 해상도본을 새 사진으로 세고, 그 중복이 점수를 만든다.
    fingerprint: str = ""


@dataclass
class Rejected:
    source_url: str
    reason: str
    detail: str = ""


@dataclass
class ClassOutcome:
    class_name: str
    label: str
    identity: str
    kept: list[Kept] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    candidate_count: int = 0
    #: 덧붙이기 실행에서 지난 실행이 이미 가지고 있던 장수. 새로 받은 것은
    #: `len(kept) - carried_over` 다 — 둘을 한 숫자로 내면 "이번에 무엇이
    #: 늘었나"에 답할 수 없고, 그 답이 사전 보강의 효과 판단 근거다.
    carried_over: int = 0

    @property
    def added(self) -> int:
        return len(self.kept) - self.carried_over


# ---------------------------------------------------------------------------
# 출처 종류별 후보 수집 — 각 함수는 `Candidate` 를 낸다
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """받을 후보 1 건과 **그 사진의 출처 기록**.

    라이선스를 사진과 같은 걸음에 따라오게 둔다. 나중에 따로 모으려 하면 그때는
    페이지가 바뀌어 있거나 사라져 있고, 공개된 벡터만 출처 없이 남는다.
    """

    image_url: str
    page_url: str = ""
    referer: str = ""
    licence: str = LICENCE_UNDETERMINED
    attribution: str = ""
    licence_source: str = ""
    source_note: str = ""


def _get(url: str, *, timeout: float = 45.0, attempts: int = 4,
         referer: str = "") -> bytes:
    """한 번 받아 온다. 429 는 거절이 아니라 "천천히 하라"는 말이다.

    여기서 물러서지 않으면 Wikimedia 쪽 사진이 통째로 빠진 채 "확보 12 장" 같은
    집계가 나오고, 그 집계는 출처가 한쪽으로 쏠렸다는 사실을 감춘다.
    """
    headers = {"User-Agent": USER_AGENT}
    if referer:
        # 상품 사진을 상세 페이지 밖에서 바로 요청하면 거절하는 상점이 있다.
        headers["Referer"] = referer
    delay = 2.0
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")  # pragma: no cover


def _excluded(title: str, patterns: list[str]) -> bool:
    lowered = title.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def _strip_html(value: str) -> str:
    """Commons 의 Artist 칸은 링크가 섞인 HTML 이다. 표시용 글자만 남긴다."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def commons_provenance(meta: dict) -> tuple[str, str]:
    """Commons 의 extmetadata 에서 (라이선스, 저작자 표시) 를 뽑는다.

    CC-BY 계열은 **이름을 밝히는 조건으로** 쓰게 해 주는 라이선스다. 라이선스 이름만
    적고 저작자를 버리면 그 조건을 지키지 않은 것이 된다.
    """
    licence = str((meta.get("LicenseShortName") or {}).get("value", "")).strip()
    artist = _strip_html(str((meta.get("Artist") or {}).get("value", "")))
    credit = _strip_html(str((meta.get("Credit") or {}).get("value", "")))
    attribution = ", ".join(part for part in (artist, credit) if part and part != "Own work")
    return (licence or LICENCE_UNDETERMINED, attribution)


def _commons_candidates(params: dict, source: dict) -> list[Candidate]:
    """Commons API 한 번 호출의 결과를 후보로 바꾼다.

    `iiprop=extmetadata` 로 라이선스와 저작자를 함께 받아 둔다 — 나중에 "이 벡터는
    어떤 사진에서 나왔고 그 사진을 쓸 수 있는가"를 되짚을 수 있어야 한다.
    """
    base = {
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
    }
    url = f"{COMMONS_API}?{urllib.parse.urlencode({**base, **params})}"
    payload = json.loads(_get(url))
    pages = (payload.get("query") or {}).get("pages") or {}
    exclude = list(source.get("exclude_title_patterns", []))
    out: list[Candidate] = []
    for page in pages.values():
        title = page.get("title", "")
        if _excluded(title, exclude):
            continue
        info = (page.get("imageinfo") or [{}])[0]
        image_url = info.get("url")
        if not image_url:
            continue
        licence, attribution = commons_provenance(info.get("extmetadata") or {})
        description = info.get("descriptionurl", "")
        out.append(Candidate(image_url, description, licence=licence,
                             attribution=attribution, licence_source=description))
    return out


def _shopify_product_candidates(url: str) -> list[Candidate]:
    """Shopify 상품 페이지의 `.json` 은 갤러리 전체를 그대로 준다.

    상품 페이지 HTML 을 긁으면 로고·배너·추천상품 썸네일이 함께 들어온다 — 어느
    상점인지와 무관하게 쓸 수 있는 공개 엔드포인트가 있으니 그쪽을 쓴다.
    """
    product = json.loads(_get(url.rstrip("/") + ".json"))["product"]
    # 상점 페이지는 라이선스를 말하지 않는다. 말하지 않은 것을 "저작권 있음"으로도
    # "써도 됨"으로도 적지 않고 **미확인**으로 둔다.
    return [Candidate(image["src"], url, licence_source=url)
            for image in product.get("images", [])]


def _shopify_collection_candidates(source: dict) -> list[Candidate]:
    url = source["url"].rstrip("/") + "/products.json?limit=250"
    products = json.loads(_get(url)).get("products", [])
    must = [m.lower() for m in source.get("title_must_match", [])]
    exclude = list(source.get("exclude_title_patterns", []))
    out: list[Candidate] = []
    for product in products:
        title = product.get("title", "")
        lowered = title.lower()
        if must and not all(m in lowered for m in must):
            continue
        if _excluded(title, exclude):
            continue
        for image in product.get("images", []):
            out.append(Candidate(image["src"], source["url"], licence_source=source["url"]))
    return out


def collect_candidates(source: dict) -> list[Candidate]:
    kind = source["kind"]
    if kind == "commons_category":
        return _commons_candidates(
            {"generator": "categorymembers", "gcmtitle": source["category"],
             "gcmlimit": "100", "gcmtype": "file"}, source)
    if kind == "commons_search":
        return _commons_candidates(
            {"generator": "search", "gsrsearch": source["query"],
             "gsrnamespace": "6", "gsrlimit": "50"}, source)
    if kind == "shopify_product":
        return _shopify_product_candidates(source["url"])
    if kind == "shopify_collection":
        return _shopify_collection_candidates(source)
    if kind == "image_urls":
        page = source.get("page_url", "")
        return [Candidate(u, page, source.get("referer", ""),
                          # 선언이 라이선스를 적었으면 그것을 쓰고, 아니면 미확인이다.
                          # `source_note` 는 사람이 적은 메모일 뿐 라이선스가 아니다.
                          licence=source.get("licence") or LICENCE_UNDETERMINED,
                          attribution=source.get("attribution", ""),
                          licence_source=source.get("licence_source") or page,
                          source_note=source.get("license_note", ""))
                for u in source["urls"]]
    raise ValueError(f"unknown source kind: {kind}")


# ---------------------------------------------------------------------------
# 검증 — 열리는 사진인가, 쓸 만큼 큰가, 이미 가진 것과 같은 사진인가
# ---------------------------------------------------------------------------


def _fingerprint(bgr) -> str:
    """해상도·재압축에 둔감한 지문. 같은 사진의 변형을 한 장으로 센다."""
    import cv2
    import numpy as np

    small = cv2.resize(bgr, (FINGERPRINT_SIDE, FINGERPRINT_SIDE), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return hashlib.sha256(np.ascontiguousarray(gray).tobytes()).hexdigest()


def _decode(raw: bytes):
    import cv2
    import numpy as np

    return cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)


def _carry_over(class_dir: Path, outcome: ClassOutcome,
                excluded_urls: set[str]) -> tuple[set[str], set[str], set[str]]:
    """지난 실행이 보관한 사진을 그대로 이어받고 그 지문을 돌려준다.

    덧붙이기의 핵심은 **파일 이름이 바뀌지 않는 것**이다. 이름이 바뀌면
    `build_dictionary.py --append` 가 같은 사진을 처음 보는 것으로 취급해 다시
    인코딩하고, 그 이름에 붙어 있던 운영자 가중치(AI-L-03)도 함께 사라진다.
    """
    previous = class_dir / "sources.json"
    if not previous.exists():
        return set(), set(), set()
    payload = json.loads(previous.read_text(encoding="utf-8"))
    bytes_seen: set[str] = set()
    fingerprints: set[str] = set()
    urls: set[str] = set()
    for entry in payload.get("references", []):
        path = class_dir / entry["file_name"]
        if entry.get("source_url", "").split("?", 1)[0] in excluded_urls:
            # 사람이 격자 그림을 보고 "이건 이 기종이 아니다"라고 판정한 사진이다.
            # 이미 받아 둔 것이라고 남겨 두면 검수가 **이전 실행에만** 적용되고,
            # 틀린 참조영상은 그 자리에 계속 앉아 점수를 만든다.
            path.unlink(missing_ok=True)
            outcome.rejected.append(Rejected(entry.get("source_url", ""), REASON_NOT_THIS_CLASS,
                                             "removed by a later review"))
            continue
        if not path.exists():
            # 적혀 있지만 없는 사진은 이어받을 수 없다. 조용히 세면 "15 장
            # 확보"가 사실이 아닌 채로 남는다.
            continue
        fingerprint = entry.get("fingerprint") or ""
        if not fingerprint:
            # 지문을 적기 전에 받은 사진들. 파일이 여기 있으니 다시 잴 수 있다.
            import cv2

            image = cv2.imread(str(path))
            fingerprint = "" if image is None else _fingerprint(image)
        outcome.kept.append(Kept(
            entry["file_name"], entry.get("source_url", ""), entry.get("page_url", ""),
            entry.get("fetched_at", ""), int(entry.get("width", 0)),
            int(entry.get("height", 0)), entry.get("sha256", ""),
            entry.get("license_note", ""), fingerprint))
        bytes_seen.add(entry.get("sha256", ""))
        if fingerprint:
            fingerprints.add(fingerprint)
        urls.add(entry.get("source_url", "").split("?", 1)[0])
    outcome.carried_over = len(outcome.kept)
    # 지난 실행의 거절 기록도 이어받는다 — 사람이 "이건 이 기종이 아니다"라고
    # 판정한 이력이 실행마다 리셋되면 그 검수는 매번 처음부터다.
    outcome.rejected.extend(
        Rejected(row.get("source_url", ""), row.get("reason", ""), row.get("detail", ""))
        for row in payload.get("rejected", []))
    return bytes_seen, fingerprints, urls


def fetch_class(class_spec: dict, out_root: Path, *, limit: int,
                pause_s: float, append: bool = False) -> ClassOutcome:
    class_name = class_spec["class_name"]
    outcome = ClassOutcome(class_name, class_spec.get("label", class_name),
                           class_spec.get("identity", "confirmed"))
    class_dir = out_root / class_name
    class_dir.mkdir(parents=True, exist_ok=True)
    previous = class_dir / "sources.json"
    # 사람이 보고 "이건 이 기종이 아니다"라고 판정한 것들. 손으로 지우면 다음
    # 실행에서 되살아나므로 **선언으로** 둔다 — 검수 결과도 재현 가능해야 한다.
    excluded_urls = {u.split("?", 1)[0] for u in class_spec.get("exclude_image_urls", [])}
    if append:
        seen_bytes, seen_fingerprints, seen_urls = _carry_over(class_dir, outcome, excluded_urls)
    else:
        # 지난 실행이 **자기가 받았다고 적어 둔 것만** 지운다. 디렉터리를 통째로
        # 비우면 현장에서 찍어 넣은 사진(field/)과 손으로 넣은 것까지 사라진다 —
        # 웹 사진은 다시 받을 수 있지만 현장 사진은 다시 찍어야 한다.
        if previous.exists():
            for entry in json.loads(previous.read_text(encoding="utf-8")).get("references", []):
                (class_dir / entry["file_name"]).unlink(missing_ok=True)
            previous.unlink()
        seen_bytes, seen_fingerprints, seen_urls = set(), set(), set()
    (class_dir / "contact_sheet.png").unlink(missing_ok=True)
    (class_dir / FIELD_DIR).mkdir(exist_ok=True)

    candidates: list[tuple[str, str, str, str]] = []
    for source in class_spec.get("sources", []):
        try:
            candidates.extend(collect_candidates(source))
        except Exception as exc:  # 한 출처가 막혀도 나머지는 계속 모은다
            outcome.rejected.append(
                Rejected(str(source.get("url") or source.get("category")
                             or source.get("query") or source["kind"]),
                         REASON_HTTP, f"{type(exc).__name__}: {exc}"))
    outcome.candidate_count = len(candidates)

    taken_names = {kept.file_name for kept in outcome.kept}
    for image_url, page_url, license_note, referer in candidates:
        if len(outcome.kept) >= limit:
            break
        if image_url.split("?", 1)[0] in excluded_urls:
            outcome.rejected.append(Rejected(image_url, REASON_NOT_THIS_CLASS))
            continue
        if image_url.split("?", 1)[0] in seen_urls:
            # 이미 가진 사진의 주소다. 다시 받아도 같은 바이트이고, 받는 쪽
            # 서버를 두드릴 이유가 없다.
            continue
        try:
            raw = _get(image_url, referer=referer)
        except Exception as exc:
            outcome.rejected.append(Rejected(image_url, REASON_HTTP, f"{type(exc).__name__}: {exc}"))
            continue
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen_bytes:
            outcome.rejected.append(Rejected(image_url, REASON_DUPLICATE, "identical bytes"))
            continue
        bgr = _decode(raw)
        if bgr is None:
            outcome.rejected.append(Rejected(image_url, REASON_NOT_DECODABLE, f"{len(raw)} bytes"))
            continue
        height, width = bgr.shape[:2]
        if min(height, width) < MIN_SHORT_SIDE:
            outcome.rejected.append(
                Rejected(image_url, REASON_TOO_SMALL, f"{width}x{height}"))
            continue
        fingerprint = _fingerprint(bgr)
        if fingerprint in seen_fingerprints:
            outcome.rejected.append(
                Rejected(image_url, REASON_DUPLICATE, "same image at another size"))
            continue

        seen_bytes.add(digest)
        seen_fingerprints.add(fingerprint)
        seen_urls.add(image_url.split("?", 1)[0])
        # 파일 이름은 내려받은 쪽이 정한 이름을 쓰지 않는다 — 원격이 정한 이름이
        # 경로를 타고 나가지 못하게 우리 쪽 규칙으로만 만든다. 번호는 이미 쓰인
        # 것을 건너뛴다: 덧붙이기에서 번호를 다시 쓰면 기존 사진을 덮어쓴다.
        index = len(outcome.kept)
        while any(name.startswith(f"{class_name}_{index:02d}_") for name in taken_names):
            index += 1
        file_name = f"{class_name}_{index:02d}_{digest[:10]}.jpg"
        taken_names.add(file_name)
        import cv2

        cv2.imwrite(str(class_dir / file_name), bgr)
        outcome.kept.append(Kept(file_name, image_url, page_url, _now(),
                                 width, height, digest, license_note, fingerprint))
        if pause_s:
            time.sleep(pause_s)

    _write_sources_json(class_dir, class_spec, outcome)
    return outcome


def _dedupe_rejected(rows: list[Rejected]) -> list[Rejected]:
    """같은 주소·같은 사유의 거절은 한 번만 적는다. 실행을 거듭할 때마다 같은
    줄이 쌓이면 거절 집계가 커지면서 "무엇이 왜 빠졌나"가 묻힌다."""
    seen: set[tuple[str, str]] = set()
    out: list[Rejected] = []
    for row in rows:
        key = (row.source_url, row.reason)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _write_sources_json(class_dir: Path, class_spec: dict, outcome: ClassOutcome) -> None:
    payload = {
        "class_name": outcome.class_name,
        "label": outcome.label,
        "identity": outcome.identity,
        "identity_note": class_spec.get("identity_note", ""),
        "built_at": _now(),
        "min_short_side": MIN_SHORT_SIDE,
        "counts": {
            "candidates": outcome.candidate_count,
            "kept": len(outcome.kept),
            "carried_over": outcome.carried_over,
            "added_this_run": outcome.added,
            "rejected": len(deduped := _dedupe_rejected(outcome.rejected)),
        },
        "references": [vars(k) for k in outcome.kept],
        "rejected": [vars(r) for r in deduped],
    }
    (class_dir / "sources.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_contact_sheet(class_dir: Path, *, columns: int = 5, tile: int = 220) -> Path | None:
    """사람이 한 눈에 보고 "이건 이 기종이 아니다"를 걸러내도록 격자 그림을 만든다.

    자동 검증으로는 '열리는 사진인가'까지만 알 수 있다. 그 사진이 정말 그 기종을
    찍은 것인지는 보지 않고는 알 수 없고, 보지 않은 채로 원형을 만들면 틀린
    원형이 설명까지 그럴듯하게 만들어 낸다.
    """
    import cv2
    import numpy as np

    files = sorted(class_dir.glob("*.jpg"))
    files += sorted(q for q in (class_dir / FIELD_DIR).glob("*")
                    if q.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not files:
        return None
    rows = (len(files) + columns - 1) // columns
    sheet = np.full((rows * tile, columns * tile, 3), 255, dtype=np.uint8)
    for index, path in enumerate(files):
        image = cv2.imread(str(path))
        if image is None:
            continue
        scale = tile / max(image.shape[:2])
        resized = cv2.resize(image, (max(1, int(image.shape[1] * scale)),
                                     max(1, int(image.shape[0] * scale))))
        y = (index // columns) * tile
        x = (index % columns) * tile
        sheet[y:y + resized.shape[0], x:x + resized.shape[1]] = resized
        cv2.putText(sheet, f"{index:02d}", (x + 4, y + tile - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
    target = class_dir / "contact_sheet.png"
    cv2.imwrite(str(target), sheet)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sources", required=True, type=Path,
                        help="기종별 출처 선언 JSON (tools/appearance/reference_sources.json)")
    parser.add_argument("--out-dir", required=True, type=Path,
                        help="기종별 디렉터리를 만들 뿌리 (공개하지 않는 local/appearance)")
    parser.add_argument("--class", dest="only", action="append", default=None,
                        help="이 기종만 받는다(여러 번 줄 수 있다)")
    parser.add_argument("--limit", type=int, default=15,
                        help="기종당 보관할 최대 장수 (기본 15)")
    parser.add_argument("--pause", type=float, default=0.3,
                        help="요청 사이 대기 초 — 출처 서버를 두드리지 않기 위한 것")
    parser.add_argument("--contact-sheet", action="store_true",
                        help="기종마다 사람 검수용 격자 그림을 함께 만든다")
    parser.add_argument("--append", action="store_true",
                        help="이미 받아 둔 사진은 그대로 두고 새 출처의 사진만 더한다 "
                             "(파일 이름이 유지돼 build_dictionary.py --append 가 "
                             "임베딩과 운영자 가중치를 이어받는다)")
    args = parser.parse_args(argv)

    spec = json.loads(args.sources.read_text(encoding="utf-8"))
    out_root = args.out_dir.expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    outcomes: list[ClassOutcome] = []
    for class_spec in spec["classes"]:
        if args.only and class_spec["class_name"] not in args.only:
            continue
        outcome = fetch_class(class_spec, out_root, limit=args.limit,
                              pause_s=args.pause, append=args.append)
        outcomes.append(outcome)
        if args.contact_sheet:
            write_contact_sheet(out_root / outcome.class_name)

    print(f"{'class':<20}{'kept':>6}{'new':>5}{'cand':>7}{'rej':>6}  identity")
    for outcome in outcomes:
        print(f"{outcome.class_name:<20}{len(outcome.kept):>6}{outcome.added:>5}"
              f"{outcome.candidate_count:>7}{len(outcome.rejected):>6}  {outcome.identity}")
    unfit = [o.class_name for o in outcomes if not o.kept]
    if unfit:
        # 0 장은 실패가 아니라 보고해야 하는 사실이다(AI-S-04).
        print(f"\nno reference image at all (will be reported unfit): {', '.join(unfit)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
