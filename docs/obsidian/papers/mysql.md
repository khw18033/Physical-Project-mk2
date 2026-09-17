# MySQL 8.4 Reference Manual

## 메타데이터
- categories: Relational Database, ACID Transaction, LTS Release, InnoDB Storage Engine
- domain: [[배포·오케스트레이션]]
- source: Oracle Corporation. "MySQL 8.4 Reference Manual." MySQL Documentation, 2026(access, revision 84858).
- url: https://dev.mysql.com/doc/refman/8.4/en/
- year: 확인 필요(Reference Manual 페이지에는 "Document generated on: 2026-08-31 (revision: 84858)"만 확인됨, MySQL 8.4 GA 발표 연도는 이번 페치 범위에서 별도 확인하지 않음)
- authors: Oracle Corporation
- venue: MySQL 공식 Reference Manual (dev.mysql.com/doc/refman)

## 1. 핵심 요약
- MySQL은 "the most popular Open Source SQL database management system"으로, Oracle Corporation이 개발·배포·지원한다.
- MySQL은 관계형 데이터베이스(relational database)로, 데이터를 하나의 저장소가 아니라 별도 테이블로 나누어 저장하고 테이블 간 관계 규칙(one-to-one, one-to-many, unique 등)을 강제한다.
- MySQL 8.4는 LTS(Long Term Support) 계열 릴리스이며, 문서 자체가 `mysql_upgrade_history` 파일에서 각 설치가 "LTS series or an Innovation series" 중 어느 쪽인지 기록한다고 명시한다. MySQL 공식 릴리스 모델 문서는 LTS 계열이 Oracle Lifetime Support Policy를 따라 5년의 premier support와 3년의 extended support를 받는다고 설명한다.
- InnoDB 등 MySQL의 컴포넌트는 ACID(Atomicity, Consistency, Isolation, Durability) 모델을 준수하도록 설계되어, 소프트웨어 크래시나 하드웨어 오작동 같은 예외 상황에서도 데이터가 손상되거나 결과가 왜곡되지 않도록 한다.

## 2. 문서 목적
- 해결하려는 문제: 구조화된 데이터를 안전하게(중복·모순·유실 없이) 저장하고 트랜잭션 단위로 일관되게 조작해야 하는 문제.
- 기술적 목표: SQL(Structured Query Language)을 이용해 관계형 데이터 모델(테이블/뷰/행/열)에 접근하는 표준화된 방법을 제공하고, InnoDB 스토리지 엔진을 통해 ACID 트랜잭션 보장을 제공하는 것.
- 다루는 범위: MySQL이란 무엇인가에 대한 개론, 관계형 데이터베이스 개념, SQL 개념, MySQL 8.4 릴리스가 속한 LTS/Innovation 릴리스 모델, ACID 모델 구성요소별(원자성/일관성/격리성/지속성) 설명과 관련 기능(autocommit, COMMIT/ROLLBACK, isolation level, doublewrite buffer 등).

## 3. 핵심 개념 상세
### Relational Database (관계형 데이터베이스)
- 원문 표현: "A relational database stores data in separate tables rather than putting all the data in one big storeroom. ... You set up rules governing the relationships between different data fields, such as one-to-one, one-to-many, unique, required or optional, and \"pointers\" between different tables. The database enforces these rules, so that with a well-designed database, your application never sees inconsistent, duplicate, orphan, out-of-date, or missing data."
- 정의: 데이터를 단일 저장소가 아니라 여러 테이블로 나누어 저장하고, 테이블 간 관계 규칙을 데이터베이스 시스템이 강제로 지키게 하는 데이터 모델.
- 역할: 명령·접수·최종 결과처럼 서로 참조 관계를 갖는 여러 종류의 레코드를 하나의 저장소에 뒤섞지 않고, 각 개체를 별도 테이블로 나누면서도 그 사이의 참조 무결성을 데이터베이스 수준에서 강제해야 하는 업무 감사(audit) 저장소 일반에 적합한 데이터 모델을 제공한다.

### LTS(Long Term Support) Release
- 원문 표현: "An LTS series follows the Oracle Lifetime Support Policy, which includes 5 years of premier support and 3 years of extended support." / "If your environment requires a stable set of features and a longer support period."
- 정의: 새 기능·동작 변경보다 안정성과 장기 지원을 우선하는 MySQL 릴리스 계열로, Innovation 계열(최신 기능 위주, 빠른 업그레이드 주기)과 대비되는 트랙.
- 역할: 업무 감사 저장소처럼 장기간 운영되며 잦은 기능 변경보다 안정성이 중요한 backend에는 최신 기능 위주의 Innovation 계열보다 LTS 트랙이 적합하다는 근거가 된다.
- 관련 원문: `mysql_upgrade_history` 파일이 "information about the MySQL server version installed, when it was installed, and whether the release was part of an LTS series or an Innovation series"를 기록한다는 서술에서도 LTS/Innovation 구분이 MySQL 자체의 공식 운영 개념임이 확인된다.

### ACID 트랜잭션
- 원문 표현: "The ACID model is a set of database design principles that emphasize aspects of reliability that are important for business data and mission-critical applications." / "MySQL includes components such as the InnoDB storage engine that adhere closely to the ACID model so that data is not corrupted and results are not distorted by exceptional conditions such as software crashes and hardware malfunctions."
- 정의: Atomicity(원자성)·Consistency(일관성)·Isolation(격리성)·Durability(지속성) 네 가지 속성을 만족하도록 설계된 데이터베이스 신뢰성 원칙. InnoDB 스토리지 엔진이 이를 구현한다.
- 역할: 명령이나 트랜잭션의 접수·실행·완료 결과를 감사(audit) 목적으로 저장할 때, 단위 작업의 원자성과 지속성이 보장되어야 이후의 책임 추적·재현이 유효하다는 근거가 된다.

### 트랜잭션 관련 세부 속성 (Atomicity/Isolation)
- 원문 표현: "The atomicity aspect of the ACID model mainly involves InnoDB transactions." / "The isolation aspect of the ACID model mainly involves InnoDB transactions, in particular the isolation level that applies to each transaction."
- 정의: 원자성은 `autocommit`, `COMMIT`, `ROLLBACK` 등 트랜잭션 완결 처리와 관련되고, 격리성은 트랜잭션마다 적용되는 isolation level(`SET TRANSACTION` 등)과 InnoDB locking으로 구현된다.
- 역할: 동일 레코드에 대한 갱신 요청이 동시에 여러 건 들어와도 서로 충돌하거나 중간 상태를 노출하지 않도록 하는 격리 수준 설정의 근거가 된다.

## 4. 구조 및 흐름
1. 클라이언트(애플리케이션)가 SQL문을 통해 관계형 데이터 모델(데이터베이스/테이블/행/열)에 접근한다.
2. 데이터 변경은 InnoDB 스토리지 엔진의 트랜잭션 단위로 처리되며, `autocommit` 설정 또는 명시적 `COMMIT`/`ROLLBACK`으로 원자성이 결정된다.
3. 동시에 여러 트랜잭션이 접근할 때는 트랜잭션별 isolation level에 따라 격리성이 적용된다.
4. 내부적으로 InnoDB doublewrite buffer, crash recovery 등의 메커니즘이 크래시 상황에서도 일관성(consistency)을 보호한다.
5. 커밋된 데이터는 doublewrite buffer, `innodb_flush_log_at_trx_commit`, `sync_binlog` 등 설정과 하드웨어(저장장치 write buffer, UPS 등)에 의해 지속성(durability)이 보장된다.
6. 설치된 MySQL 버전이 LTS 계열인지 Innovation 계열인지는 `mysql_upgrade_history` 파일에 기록되어 이후 업그레이드 경로 판단에 사용된다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| MySQL은 세계에서 가장 널리 쓰이는 오픈소스 SQL 데이터베이스 관리 시스템이다 | 공식 소개 문구: "The world's most popular open source database" / "MySQL, the most popular Open Source SQL database management system, is developed, distributed, and supported by Oracle Corporation." |
| MySQL(InnoDB)은 크래시·하드웨어 오작동 상황에서도 데이터 무결성을 유지하도록 ACID 모델을 따른다 | "MySQL includes components such as the InnoDB storage engine that adhere closely to the ACID model so that data is not corrupted and results are not distorted by exceptional conditions such as software crashes and hardware malfunctions." |
| MySQL 8.4는 안정성과 장기 지원을 우선하는 LTS 계열이다 | 릴리스 모델 문서: "If your environment requires a stable set of features and a longer support period." 및 "An LTS series follows the Oracle Lifetime Support Policy, which includes 5 years of premier support and 3 years of extended support." |

## 6. 한계 및 부족한 점
- 이번 WebFetch 범위에서는 MySQL 8.4가 GA(정식 출시)된 정확한 연도·날짜는 확인하지 못했다. Reference Manual 페이지에서 확인된 것은 문서 생성일("Document generated on: 2026-08-31")뿐이며, 이는 릴리스일이 아니다. "확인 필요."
- ACID 모델의 네 속성 중 Consistency와 Durability에 대한 상세 메커니즘(doublewrite buffer 동작 원리 등)은 이번 페치에서 항목 이름과 관련 변수만 확인했고, 내부 알고리즘 수준의 상세 설명은 확인하지 못했다.
- 공식 문서가 스스로 명시하는 한계로는, 매뉴얼이 "MySQL 8.4 through 8.4.11"까지의 기능을 다루며 "may include documentation of features of MySQL versions that have not yet been released"라고 명시한다 — 즉 문서에 아직 정식 출시되지 않은 기능이 포함될 수 있다는 점을 스스로 경고한다. 또한 "This manual describes features that are not included in every edition of MySQL 8.4; such features may not be included in the edition of MySQL 8.4 licensed to you"라고 명시해, 문서에 기술된 기능이 실제 사용 중인 edition에는 없을 수 있다는 제약을 밝힌다.

## 7. 원문 기반 핵심 문장
> "MySQL includes components such as the InnoDB storage engine that adhere closely to the ACID model so that data is not corrupted and results are not distorted by exceptional conditions such as software crashes and hardware malfunctions."
