# viz-debugger

**통합 가시화 앱.** 탭 여섯이 한 앱에 있다 — 임무 설계·디버깅(본류)과 `web-dashboard`에서 이식해 온 다섯.

```bash
npm install
npm run dev
```

`npm run dev` 하나로 **목 게이트웨이(8790) · 화면(5174) · STT 서비스(8801)** 가 함께 뜬다. 기존 대시보드(5173/8787~8788)나 `stt-lab`(8799)과 포트가 겹치지 않으므로 **동시에 띄워 비교**할 수 있다.

```
① 임무 설계 및 디버깅   ② 구역 현황판   ③ 제어 패널
④ 지표 조회             ⑤ 영상 오버레이  ⑥ 파이프라인 편집기(동결)
```

**`web-dashboard`를 대체하지 않는다.** 그쪽은 한 줄도 고치지 않은 **기준선**으로 계속 산다 — 문제가 생겼을 때 "내가 깼는지 원래 그랬는지"를 가르는 유일한 기준이다. 게이트웨이와 데이터는 목이며 화면 상단에도 그 사실을 표시한다.

## 탭① — 임무 설계 및 디버깅

마일스톤과 노드를 클릭해 다음 계층으로 이동한다. 마일스톤 카드 배정, 그래프 노드 자유 배치, DAG/트리 전환, 노드 더블클릭, 임무 이력 리플레이, 실패 파라미터 수정, 계획 승인·거부(`VZ-U-07`)가 동작한다. 정적 전달본과 논의 항목은 [HANDOFF.md](./HANDOFF.md)에 정리했다.

**탭①만 담는 단독 빌드가 따로 있다** (`npm run build:standalone`). 논문 측정축 D(계측 오버헤드)를 잴 때 다른 탭의 부하가 섞이면 안 되기 때문이고, `verify:standalone`이 그 격리를 강제한다.

## 탭②~⑥ — 이식본

`web-dashboard/src/{data,views}` 를 `src/tabs/` 로 옮긴 것이다. **거의 무수정**이고 고친 곳은 이식 보고서(`reports/2026-08-28_1900_탭이식.md`)에 있다.

- **명령 출구는 하나다.** 탭③의 수동 제어도 탭①의 재실행도 `shared/commandCenter.ts`를 거친다. 4단계 추적(발행→ACK→진행→완료)과 감사 필드가 그 안에 있다.
- **목 게이트웨이도 하나다.** `web-dashboard/mock-gateway/`가 본체가 되고, 옛 10줄짜리 시나리오 재생기가 그 안의 `trace_event` 채널로 접혔다.
- **`registry.json`은 복사하지 않는다.** `web-dashboard/mock-gateway/registry.json`을 경로로 참조한다 — `stt/vocab.py`도 같은 파일을 읽으므로(`REQ-305`) 두 벌이 되면 화면의 장치 목록과 음성 어휘가 갈라진다.

## 음성 인식 (`VZ-L-01`)

발화 패널의 녹음·인식은 **실제로 동작한다.** 파형은 마이크 입력 레벨이고, 인용문은 인식 결과이며, 진행 막대의 앞 두 칸(`음성 수신`·`STT 변환`)은 실제 상태를 따라간다. **뒤 세 칸(`의도 분석`·`마일스톤 분리`·`태스크 생성`)은 아직 목이고 화면에 `목` 배지가 붙어 있다** — `VZ-G-01`·`VZ-G-02`이고 로컬 LLM이 필요하다.

인식 결과는 **고칠 수 있고, 원문과 수정본을 둘 다 보관한다**(`REQ-1303`). 원문만 남기면 오인식을 놓치고 수정본만 남기면 STT 성능을 평가할 수 없다.

### 파이썬 환경

STT는 별도 파이썬 프로세스다(faster-whisper는 CTranslate2 런타임이라 브라우저에서 돌지 않는다). **Python 3.10 이상**이 필요하다.

```powershell
cd viz-debugger\stt
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

이 `.venv`가 있으면 `npm run dev`가 STT 서비스도 함께 띄운다. 자세한 것은 [stt/README.md](./stt/README.md).

**모델 최초 다운로드는 오래 걸린다.** 기본 모델 `large-v3-turbo`를 첫 요청에서 1.5 GB 안팎 내려받으므로, 첫 인식이 몇 분 걸려도 실패가 아니다. 두 번째부터는 캐시된다.

### STT 서비스를 안 띄웠을 때

**화면은 그대로 뜬다.** 음성 기능만 꺼지고, 무엇이 왜 꺼졌는지 패널에 문구가 남으며, **문장을 직접 넣는 경로는 열려 있다**(`VZ-C-02`·`VZ-G-01`). 화면 전체가 죽거나 무한 로딩에 걸리지 않는다. `npm run verify:no-stt`가 이걸 검사한다.

## 검증

```
npm run typecheck
npm run verify:scenario      npm run verify:layout        npm run verify:hierarchy
npm run verify:adapter-swap  npm run verify:transport     npm run verify:single-egress
npm run verify:standalone    npm run verify:stt-port      npm run verify:voice-audit
npm run verify:no-stt        npm run verify:one-gateway   npm run build
```

이식·STT 관련 네 가지가 무엇을 잡는지:

| 스크립트 | 무엇을 잡는가 |
|---|---|
| `verify:stt-port` | 이식한 `stt/engines/*.py`가 `stt-lab` 원본과 **바이트 동일한가** (출처 주석 제외). 두 벌이 조용히 갈라지는 것을 막는다 |
| `verify:voice-audit` | 음성으로 발행된 명령에 `voice` 감사 필드가 빠지면 **실제로 거부되는가**. 통과한 뒤에도 세 수치가 **각각** 실리는가 (`REQ-1305`) |
| `verify:no-stt` | STT가 전부 실패하는 상태에서 화면이 뜨고 수동 입력이 살아 있는가 |
| `verify:one-gateway` | **목 게이트웨이가 하나이고 그 하나가 탭 여섯을 다 채우는가.** 화면만 옮기면 탭②~⑥이 텅 빈 채로 뜨는 것이 이 이식에서 가장 놓치기 쉬웠다 |

넷 다 **음성 대조군**을 포함한다 — 검사를 무력화한 사본이 반드시 실패로 잡히는지까지 확인한다. 검사가 아무것도 못 잡은 채 통과하던 일이 실제로 있었다(`reports/2026-08-28_1036_통합구현_검토.md` B항).
