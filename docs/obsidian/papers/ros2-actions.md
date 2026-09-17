# ROS 2 Actions Design

## 메타데이터
- categories: Goal Acceptance/Rejection, Feedback/Result 분리, Cancel Request, Goal 상태 머신
- domain: [[전송·프로토콜]], [[로보틱스·다중로봇]]
- source: Biggs, Geoffrey, Perron, Jacob, Loretz, Shane. "Actions." ROS 2 Design (Open Robotics/ROS 2 project), Date Written 2019-03, Last Modified 2020-05.
- url: https://design.ros2.org/articles/actions.html
- year: 2020 (Last Modified 기준; 최초 작성은 2019-03)
- authors: Geoffrey Biggs, Jacob Perron, Shane Loretz
- venue: ROS 2 Design (design.ros2.org)

## 1. 핵심 요약
- Actions는 응답에 상당한 시간이 걸릴 수 있는 요청을 위한 통신 패턴으로, topic(단방향 broadcast)·service(동기 request-response)로는 다루기 어려운 진행 상황 추적·최종 결과 수신·중도 취소를 지원한다.
- Action 인터페이스는 Goal/Feedback/Result 세 부분으로 정의되며, wire 구조는 3개의 service(Send Goal, Cancel Goal, Get Result)와 2개의 topic(Feedback, Status)으로 구성된다.
- Goal ID는 ROS 1과 달리 ROS 2에서는 action client가 UUID로 생성하는 것으로 고정되어, 서버 측 생성 시 발생할 수 있는 충돌 문제를 피한다.
- Goal 상태 머신은 ACCEPTED/EXECUTING/CANCELING/SUCCEEDED/ABORTED/CANCELED 6개 상태로 명시적으로 정의된다.
- REJECTED는 상태 머신의 상태가 아니라 Send Goal Service 응답의 accepted/rejected 값으로만 표현되며, 상태 머신 자체는 서버가 goal을 accept한 경우에만 시작된다.

## 2. 문서 목적
- 해결하려는 문제: 장시간 실행되는 요청에 대해 진행 상황 통지, 최종 결과 수신, 완료 전 취소를 topic/service만으로 구현하면 임시방편적이고 일관성 없는 구조가 되는 문제.
- 기술적 목표: goal 전달·수락/거부·진행 추적·취소·결과 반환을 하나의 표준 Action 인터페이스와 goal 상태 머신으로 통일하는 것.
- 다루는 범위: Action Client/Server의 역할 정의, Action Interface Definition(Goal/Feedback/Result), 3 service + 2 topic wire 구조, goal 상태 머신, Goal ID 생성 정책, 설계 시 검토했던 대안과 그 기각 사유.

## 3. 핵심 개념 상세
### Goal
- 원문 표현: "This describes what the action should achieve and how it should do it. It is sent to the action server when it is requested to execute an action."
- 정의: action이 달성해야 할 목표와 방법을 기술하며, action 실행이 요청될 때 action server로 전달되는 데이터.
- 역할: 장시간 실행되는 원격 명령을 다루는 시스템에서, "무엇을 어떻게 수행할지"를 요청 메시지 하나에 담아 실행 주체에 전달하는 설계의 원형이 된다.

### Action Client / Action Server
- 원문 표현: "An action server provides an action... advertising the action to other ROS entities, accepting or rejecting goals from one or more action clients, executing the action when a goal is received and accepted, and sending the result of a completed action." / "An action client sends one or more goals (an action to be performed) and monitors their progress... sending goals to the action server, optionally monitoring the user-defined feedback, and optionally requesting that the action server cancel an active goal."
- 정의: goal을 보내고 진행 상황을 관찰하는 client, goal을 수락/거부하고 실행·결과 반환을 책임지는 server로 역할이 분리된 두 엔터티.
- 역할: "명령을 보내는 쪽"과 "수락 여부·실행·결과를 판정하는 쪽"의 역할을 분리하는 것은, 로봇·IoT 장치·원격 작업 시스템 등 다양한 분산 제어 시스템에서 명령 발신자와 실행 주체 사이의 책임 경계를 명확히 하는 데 널리 쓰이는 설계 패턴이다.

### Goal Acceptance/Rejection
- 원문 표현: "The state machine is only started if the action server accepts the goal."
- 정의: action server가 goal을 받으면 즉시 실행을 시작하는 것이 아니라 먼저 수락/거부를 판정하고, 수락된 경우에만 상태 머신이 시작되는 절차. Send Goal Service 응답에는 "whether goal was accepted or rejected and the time when the goal was accepted"가 포함된다.
- 역할: 요청을 받았다는 사실과 그 요청의 실행을 시작했다는 사실을 구분해야 하는 시스템에서, 거부(rejection)를 별도의 실행 상태가 아니라 최초 응답의 boolean 필드로만 표현하는 설계에 근거를 제공한다. 이렇게 하면 상태 머신은 실제로 실행이 시작된 요청만 추적하면 되어 상태 종류가 단순해진다.

### Feedback / Result 분리
- 원문 표현: "This describes the progress towards completing an action. It is sent to the client of the action from the action server between commencing action execution and prior to the action completing."(Feedback) / "This describes the outcome of an action. It is sent from the server to the client when the action execution ends, whether successfully or not."(Result)
- 정의: 실행 중 진행 상황을 알리는 Feedback과, 실행 종료 시점에 성공/실패 여부와 함께 전달되는 Result를 별도 채널(topic vs service)로 분리하는 설계.
- 역할: 장시간 실행되는 작업을 다루는 시스템에서, 진행 중 상태 갱신과 최종 결과를 별도 채널·메시지 타입으로 분리하면 소비자가 필요에 따라 진행 상황만 구독하거나 최종 결과만 기다리도록 선택할 수 있어, 두 종류의 정보가 뒤섞여 생기는 처리 로직의 복잡도를 줄일 수 있다.

### Cancel Request
- 원문 표현: "The purpose of this service is to request the cancellation of one or more goals on the action server." / "cancel_goal - Request that the action server stop processing the goal. A transition only occurs if the action server accepts the request to cancel the goal."
- 정의: client가 goal 취소를 요청하고, server가 그 취소 요청 자체를 수락해야만 CANCELING 상태로 전이가 일어나는 절차. 응답에는 "response code and a list of goals that have transitioned to the CANCELING state"가 포함된다.
- 역할: 취소 요청에 대한 응답이 "실행이 즉시 멈췄다"는 의미가 아니라 "취소 절차에 들어가는 것을 수락했다"는 의미로 한정되는 설계에 근거를 제공한다. 물리적 동작이나 장시간 작업처럼 즉각 중단이 불가능한 시스템에서, 취소 요청의 수락과 실제 중단 완료를 구분해야 할 때 유용한 패턴이다.

### Goal 상태 머신
- 원문 표현: "ACCEPTED - The goal has been accepted and is awaiting execution." / "EXECUTING - The goal is currently being executed by the action server." / "CANCELING - The client has requested that the goal be canceled and the action server has accepted the cancel request." / "SUCCEEDED - The goal was achieved successfully by the action server." / "ABORTED - The goal was terminated by the action server without an external request." / "CANCELED - The goal was canceled after an external request from an action client."
- 정의: 활성 상태(ACCEPTED/EXECUTING/CANCELING) 3개와 종결 상태(SUCCEEDED/ABORTED/CANCELED) 3개로 구성된 goal 생명주기 상태 머신.
- 역할: 장시간 실행되는 원격 작업의 생명주기를 활성 상태와 종결 상태로 나누어 명시적으로 정의하는 상태 머신 설계의 참조 모델로 널리 쓰인다. 활성 상태(수락됨/실행 중/취소 중)와 종결 상태(성공/중단/취소됨)를 구분하면, 클라이언트가 작업이 더 이상 변하지 않는 시점을 명확히 판단할 수 있다.

## 4. 구조 및 흐름
1. Action client가 Goal ID(UUID)를 생성해 Goal과 함께 Send Goal Service로 action server에 전송한다.
2. Action server가 goal을 accept/reject 중 하나로 판정해 응답한다. accept된 경우에만 상태 머신이 ACCEPTED 상태로 시작된다.
3. Server가 `execute` 전이를 통해 EXECUTING 상태로 넘어가며 goal 처리를 시작한다.
4. Server는 실행 중 Feedback Topic으로 진행 상황을 client에 지속적으로 publish한다.
5. Client가 필요 시 Cancel Goal Service를 호출하며, server가 취소 요청을 accept하면 CANCELING 상태로 전이한다.
6. 최종적으로 서버가 `succeed`/`abort`/`canceled` 중 하나의 전이를 발생시켜 SUCCEEDED/ABORTED/CANCELED 종결 상태에 도달하고, client는 Get Result Service를 호출해 최종 Result를 받는다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|---|---|
| Actions는 장시간 실행 요청에 topic/service보다 적합한 통신 패턴이다 | "Actions are useful when a response may take a significant length of time. They allow a client to track the progress of a request, get the final outcome, and optionally cancel the request before it completes." |
| goal 거부는 상태가 아니라 수락 절차의 응답으로 표현되어야 한다 | "The state machine is only started if the action server accepts the goal." — 즉 거부된 goal은 애초에 상태 머신에 진입하지 않는다 |
| Goal ID는 client가 생성하는 편이 충돌 위험을 줄인다 | 설계 검토("Alternatives considered")에서 server-side goal ID 생성 방식이 기각되고 client 생성(UUID) 방식이 채택됨 |

## 6. 한계 및 부족한 점
- 문서 자체가 명시하는 미해결 사항: "Bridging between ROS 1 and ROS 2" 절이 본문에 "TODO"로만 남아 있어 ROS 1↔ROS 2 action 호환 방안은 이 설계 문서 수준에서 완결되지 않았다.
- 설계 검토 단계에서 "actions in rmw layer"(action을 미들웨어 계층에 직접 넣는 방안)가 "DDS가 service/topic보다 뛰어난 미들웨어 기능을 제공하지 않고 rmw 구현 복잡도만 늘린다"는 이유로 기각되었다. 이는 특정 미들웨어 프로토콜 전체를 도입하지 않고 상태 의미론(goal 수락/거부, 상태 머신, feedback/result 분리)만 다른 시스템에 이식하려는 설계에서 참고할 수 있는 선례다 — 프로토콜 구현체 전체를 가져오면 그 미들웨어 특유의 기술 종속성(DDS/RMW 등)도 함께 옮겨오기 때문이다.

## 7. 원문 기반 핵심 문장
> "Actions are useful when a response may take a significant length of time. They allow a client to track the progress of a request, get the final outcome, and optionally cancel the request before it completes."
