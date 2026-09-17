# Sigstore Cosign

## 메타데이터
- categories: Container Image Signing, Keyless Signing, OIDC 기반 Ephemeral Key, Fulcio/Rekor
- domain: [[관측·보안]]
- source: Sigstore 프로젝트. "Signing Containers." Sigstore/Cosign Documentation, 확인 시점 2026-09; 보완: sigstore/cosign GitHub README.
- url: https://docs.sigstore.dev/cosign/signing/signing_with_containers/
- year: 확인 필요 (지속 갱신 문서)
- authors: Sigstore 프로젝트 (Cosign 기여자)
- venue: Sigstore Documentation / GitHub (sigstore/cosign)

## 1. 핵심 요약
- sigstore/cosign GitHub README는 Cosign을 "Signing OCI containers (and other artifacts) using Sigstore!"로 소개하며 "Cosign is developed as part of the sigstore project."라고 명시한다.
- 공식 문서는 keyless signing을 "You can use Cosign to sign containers with ephemeral keys by authenticating with an OIDC (OpenID Connect) protocol supported by Sigstore."로 설명하며, 현재 지원 IdP는 "Google, GitHub, or Microsoft"이다.
- 서명 명령은 `cosign sign $IMAGE`(keyless) 또는 `cosign sign --key cosign.key $IMAGE`(key 기반)로 확인된다.
- Fulcio(인증서 발급)와 Rekor(transparency log)가 keyless 서명 인프라의 구성요소로 GitHub README에서 언급되지만, 이번 fetch에서 두 컴포넌트 각각의 상세 동작을 설명하는 원문 문장은 확인하지 못했다(확인 필요).

## 2. 문서 목적
- 해결하려는 문제: 컨테이너 이미지가 빌드된 이후 변조되지 않았는지, 실제로 신뢰할 수 있는 주체가 만든 이미지인지 확인할 방법이 없는 공급망 신뢰 문제.
- 기술적 목표: 장기 보관 키 관리 부담 없이(keyless) OIDC 신원 인증만으로 컨테이너 이미지에 서명하고, 이후 그 서명을 검증할 수 있게 하는 것.
- 다루는 범위: `cosign sign`/`cosign sign --key`를 이용한 컨테이너 이미지 서명, OIDC 기반 keyless 인증 흐름, 서명 검증(`cosign verify`, `cosign verify-attestation`) 명령의 존재.

## 3. 핵심 개념 상세
### Cosign (컨테이너 서명 도구)
- 원문 표현: "Signing OCI containers (and other artifacts) using Sigstore!" (GitHub README) / "Cosign is developed as part of the sigstore project." (GitHub README)
- 정의: OCI 컨테이너(및 기타 아티팩트)에 대한 서명·검증을 수행하는 Sigstore 프로젝트의 하위 도구.
- 역할: 실행 감사(audit)에 컨테이너 버전 정보(예: 어댑터 버전)만이 아니라 image digest, 설정 버전, 계약 버전을 함께 연결하고 싶을 때, Cosign으로 image signature를 추가하면 공급망 보안 수준을 한 단계 높일 수 있다. 이런 서명 체계는 대개 필수 요구사항이라기보다 선택적 확장으로 도입되는 경우가 많다.

### Keyless Signing
- 원문 표현: "You can use Cosign to sign containers with ephemeral keys by authenticating with an OIDC (OpenID Connect) protocol supported by Sigstore." / "Currently, you can authenticate with Google, GitHub, or Microsoft."
- 정의: 장기 보관 개인키 대신, OIDC 신원 공급자 인증 결과로 발급된 단기(ephemeral) 키로 서명하는 방식.
- 역할: 폐쇄망(air-gapped) 환경에서 운용되는 시스템과는 직접적인 긴장 관계에 있다 — keyless signing은 기본적으로 공개 OIDC 제공자(Google/GitHub/Microsoft)와 Sigstore의 공개 Fulcio/Rekor 인프라에 대한 외부 연결을 전제하므로, 외부 인터넷 연결을 기능 동작의 전제로 두지 않는 배포 환경에서는 그대로 쓸 수 없고 내부 CA·내부 transparency log 또는 key 기반 서명(`--key`)으로 대체해야 한다.

### 서명·검증 명령
- 원문 표현: "$ cosign sign $IMAGE" / "$ cosign sign --key cosign.key $IMAGE" / "$ cosign sign --key <some provider>://<some key> $IMAGE"
- 정의: 이미지 참조를 인자로 받아 서명을 생성하는 CLI 명령. `--key`로 로컬 키 파일이나 KMS provider URI를 지정할 수 있다. 검증 명령의 구체 verbatim 예시는 이번 fetch 범위에서 확인하지 못했으며, `cosign verify`/`cosign verify-attestation` 명령의 존재만 확인되었다(확인 필요).
- 역할: 컨테이너 이미지 서명 체계를 도입한다면, "어떤 code/image가 실제 실행되는가"를 판정하는 최종 근거가 서명 검증 결과가 된다. 이를 실질적으로 강제하려면 오케스트레이터의 배포 파이프라인이 이미지를 pull하기 전에 서명을 검증하는 admission 단계가 별도로 필요하다(이 문서 범위 밖의 구성).

## 4. 구조 및 흐름
1. (Keyless) 개발자가 `cosign sign $IMAGE`를 실행하면 Cosign이 OIDC 제공자(Google/GitHub/Microsoft)로 신원 인증을 요구한다.
2. 인증이 완료되면 ephemeral key pair가 생성되고, 이를 이용해 이미지 manifest에 대한 서명이 만들어진다.
3. 서명은 이미지가 저장된 OCI 레지스트리에 함께 저장된다(구체 저장 방식의 원문 확인은 이번 fetch 범위 밖).
4. (Key 기반) 사전에 생성된 키(`cosign.key`) 또는 KMS provider URI를 `--key`로 지정해 동일하게 서명할 수 있다.
5. 검증 측은 `cosign verify`(또는 attestation 검증 시 `cosign verify-attestation`)로 서명이 유효한 신원·키로 생성됐는지 확인한다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| Cosign은 Sigstore 프로젝트의 일부로 OCI 컨테이너 서명을 수행하는 도구다 | GitHub README: "Signing OCI containers (and other artifacts) using Sigstore!" / "Cosign is developed as part of the sigstore project." |
| Cosign은 장기 키 관리 없이 OIDC 인증만으로 서명할 수 있다(keyless) | "You can use Cosign to sign containers with ephemeral keys by authenticating with an OIDC (OpenID Connect) protocol supported by Sigstore." |
| 현재 keyless 인증은 특정 공개 IdP로 한정된다 | "Currently, you can authenticate with Google, GitHub, or Microsoft." |

## 6. 한계 및 부족한 점
- 공식 문서가 스스로 명시하는 한계: 이번 fetch 범위에서는 Cosign 자체가 명시하는 한계·트레이드오프 서술(예: 성능, 저장소 요구사항)을 확인하지 못했다(확인 필요). 다만 keyless 인증 지원 IdP가 "Google, GitHub, or Microsoft"로 한정된다는 점은 문서가 스스로 밝힌 제약이다.
- 일반적으로 결정적인 한계: keyless signing은 공개 OIDC 제공자와 Sigstore의 공개 Fulcio(인증서 발급)/Rekor(transparency log) 인프라에 대한 외부 연결을 전제로 하므로, "공개 인터넷에 대한 나가는 연결을 기능 동작의 전제로 두지 않는다"는 폐쇄망 운용 원칙과 정면으로 부딪힌다. 폐쇄망 환경에서는 (a) key 기반 서명(`--key`, 내부 KMS)으로 전환하거나 (b) 자체 호스팅 Fulcio/Rekor를 운용해야 하며, 이 문서만으로는 자체 호스팅 방법이 확인되지 않는다(확인 필요).
- Cosign 서명·검증 자체는 대부분의 조직에서 필수 요구사항이라기보다 선택적 확장으로 도입되는 경우가 많다. 즉 서명 절차를 도입하기로 결정하더라도, 오케스트레이터의 이미지 pull 단계에서 서명을 강제하는 admission 로직은 별도로 설계해야 실제로 효력을 갖는다.

## 7. 원문 기반 핵심 문장
> "You can use Cosign to sign containers with ephemeral keys by authenticating with an OIDC (OpenID Connect) protocol supported by Sigstore."
