# Nav2 Collision Monitor

## 메타데이터
- categories: Emergency-Stop 수준 충돌 감시, Action Model(Stop·Slowdown·Limit·Approach), CPU-level Software Safety 경계
- domain: [[로보틱스·다중로봇]]
- source: Open Navigation LLC. "Collision Monitor." Nav2 Documentation (Jazzy).
- url: https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/core_servers/collision_monitor/
- year: 확인 안 됨 (ROS 2 "Jazzy" 배포판 대상의 지속 갱신 공식 문서)
- authors: Open Navigation LLC / Nav2 프로젝트 기여자
- venue: 공식 문서 (Nav2 Documentation)

## 1. 핵심 요약
- Collision Monitor는 costmap과 trajectory planner를 우회해 센서로부터 들어오는 데이터를 직접 소비하여, emergency-stop 수준에서 잠재적 충돌을 감시·예방하는 nav2_collision_monitor 패키지의 노드다.
- Stop, Slowdown, Limit, Approach 네 가지 action model을 제공하며, 각각 정지, 속도 비율 감소, 선형·각속도 상한 제한, 예측적 감속이라는 서로 다른 개입 강도를 갖는다.
- 감시 영역(zone)은 임의 polygon, robot footprint, circle, 혹은 명령 속도에 따라 형태가 바뀌는 VelocityPolygon으로 정의할 수 있다.
- LaserScan, PointCloud2, Range, Costmap 등 여러 형식의 소스를 직접 구독하며, 속도에 영향을 주지 않고 탐지 사실만 알리는 Collision Detector라는 동반 노드도 존재한다.
- 공식 문서는 이 기능이 CPU 수준에서 일반 센서로 동작하는 소프트웨어 기능일 뿐, 인증된 hard real-time safety 시스템을 대체하지 않는다고 명시한다.

## 2. 문서 목적
- 해결하려는 문제: costmap·planner·controller로 이어지는 표준 navigation pipeline은 여러 처리 단계를 거치므로 지연이 발생할 수 있고, 그 사이 근접한 장애물에 대한 즉각적 대응이 늦어질 위험이 있다.
- 기술적 목표: costmap·trajectory planner 파이프라인과 분리된 별도의 저지연 감시 계층을 두어, 센서 원시 데이터를 직접 소비해 임박한 충돌 상황에서 속도 명령을 즉시 제한·정지시키는 것.
- 다루는 범위: Collision Monitor·Collision Detector 노드의 역할 구분, Stop/Slowdown/Limit/Approach 네 가지 action model의 정의, 감시 zone의 형상 종류, 사용 가능한 소스 데이터 타입, 그리고 이 기능이 제공하는 안전 보장의 명시적 범위(safety certification 경계).

## 3. 핵심 개념 상세
### Collision Monitor
- 원문 표현: "performs several collision avoidance related tasks using incoming data from the sensors, bypassing the costmap and trajectory planners, to monitor for and prevent potential collisions at the emergency-stop level."
- 정의: costmap과 trajectory planner를 거치지 않고 센서 원시 데이터를 직접 소비해 충돌을 감시·예방하는 별도의 노드.
- 역할: 상위 계획 단계의 지연이나 실패와 무관하게, 최하위 emergency-stop 수준에서 속도 명령을 즉시 제한함으로써 충돌 회피의 마지막 보호 계층 역할을 한다.

### Collision Detector (동반 노드)
- 원문 표현: "does not affect the robot's velocity" / "only inform[s] that data from the configured sources has been detected."
- 정의: Collision Monitor와 유사하게 센서 데이터를 직접 감시하지만, 속도를 제어하지 않고 설정된 소스에서 데이터가 감지되었다는 사실만 알리는 노드.
- 역할: 충돌 회피 개입 없이 순수 감시·알림 용도로 사용할 수 있는, Collision Monitor와 분리된 관측 전용 대안을 제공한다.

### Action Model: Stop / Slowdown / Limit / Approach
- 원문 표현: "Define a zone and a point threshold. If min_points or more obstacle points appear inside this area, stop the robot until the obstacles will disappear." (Stop) / "Define a zone around the robot and slow the maximum speed for a slowdown_ratio, if min_points or more points will appear inside the area." (Slowdown) / "Define a zone around the robot and restricts the maximum linear and angular velocities to linear_limit and angular_limit values accordingly." (Limit) / "Using the current robot speed, estimate the time to collision to sensor data. If the time is less than time_before_collision seconds, the robot will slow such that it is now at least time_before_collision seconds to collision." (Approach)
- 정의: 감시 zone 내 장애물 포인트 수 또는 예상 충돌 시간을 기준으로, 로봇을 정지시키거나 최대 속도를 비율로 줄이거나 선형·각속도 상한을 제한하거나 목표 여유시간을 확보하도록 선제적으로 감속시키는 네 가지 개입 정책.
- 역할: 정적 근접 장애물, 좁은 통로, 예측적 접근 등 상황에 따라 서로 다른 강도의 속도 개입 정책을 선택적으로 구성할 수 있게 한다.

### 직접 센서 데이터 소비
- 원문 표현: "Laser scanners (sensor_msgs::msg::LaserScan messages), PointClouds (sensor_msgs::msg::PointCloud2 messages), IR/Sonars (sensor_msgs::msg::Range messages), Costmap (nav2_msgs::msg::Costmap messages)."
- 정의: LaserScan, PointCloud2, Range, Costmap 등 여러 형식의 센서·맵 메시지를 감시 소스로 직접 구독하는 방식.
- 역할: 특정 센서 한 종류에 의존하지 않고 사용 가능한 근접 감지 소스를 조합해 zone 침범 여부를 판단할 수 있게 한다.

### CPU-level Software Safety 경계
- 원문 표현: "However, this node is done at the CPU level with any form of sensor. As such, this does not provide hard real-time safety certifications, but uses the same types of techniques with the same types of data for users that do not have safety-rated laser sensors."
- 정의: Collision Monitor는 인증된 safety-rated 스캐너·컨트롤러가 수행하는 hard real-time 안전 시스템이 아니라, 일반 CPU에서 일반 센서 데이터로 유사한 기법을 재현하는 소프트웨어 기능이라는 명시적 범위 한정.
- 역할: 인증된 안전 하드웨어가 없는 사용자에게 유사한 보호 기법을 제공하되, 그 보장 수준이 인증된 hard real-time safety 시스템과 다르다는 것을 사용자가 명확히 인지하도록 한다.

## 4. 구조 및 흐름
1. Collision Monitor/Detector 노드가 LaserScan, PointCloud2, Range, Costmap 등 설정된 소스를 costmap·trajectory planner 파이프라인을 거치지 않고 직접 구독한다.
2. 설정된 zone(임의 polygon, robot footprint, circle, 또는 명령 속도에 따라 형태가 바뀌는 VelocityPolygon) 내부에 소스 포인트가 얼마나 존재하는지 매 주기 확인한다.
3. Stop/Slowdown/Limit action model은 min_points 임계값과 zone 침범 여부로 즉시 정지·감속·속도상한 적용 여부를 판단한다.
4. Approach action model은 현재 속도와 센서 데이터로 예상 충돌 시간을 계산해, time_before_collision만큼의 여유가 확보되도록 선제적으로 감속시킨다.
5. Collision Monitor는 판단 결과에 따라 최종 velocity command를 제한·override해 로봇 제어계로 전달하고, Collision Detector는 속도 개입 없이 탐지 사실만 별도로 알린다.

## 5. 핵심 주장과 근거
| 주장 | 근거 |
|------|------|
| costmap·planner와 분리된 저지연 감시 계층이 필요하다 | "performs several collision avoidance related tasks using incoming data from the sensors, bypassing the costmap and trajectory planners, to monitor for and prevent potential collisions at the emergency-stop level" |
| 상황별로 서로 다른 강도의 개입 정책이 필요하다 | Stop/Slowdown/Limit/Approach 네 가지 action model이 각각 정지, 속도비율 감소, 속도상한 제한, 예측적 감속으로 구분되어 제공됨 |
| 이 기능은 인증된 hard real-time safety 시스템을 대체하지 않는다 | "this does not provide hard real-time safety certifications, but uses the same types of techniques with the same types of data for users that do not have safety-rated laser sensors" |

## 6. 한계 및 부족한 점
- 공식 문서(Rolling 배포판의 configuring 하위 문서)가 스스로 명시한다: "However, this node is done at the CPU level with any form of sensor. As such, this does not provide hard real-time safety certifications, but uses the same types of techniques with the same types of data for users that do not have safety-rated laser sensors." 즉 safety-rated scanner/controller를 사용하는 인증된 hard-real-time safety 시스템이 아니라 CPU-level software function이라는 한계를 문서 자체가 명시한다.
- 확인한 범위에서 이 CPU-level 한계에 대한 명시적 disclaimer 문장은 Jazzy 배포판의 Collision Monitor 개요 문서(configuration_guide)에서는 확인되지 않았고, Rolling 배포판의 configuring_collision_monitor_node 하위 문서에서만 확인되었다. 즉 배포판·페이지에 따라 안전 경계에 대한 설명 수준이 다르다.
- 감시 zone·threshold(min_points, slowdown_ratio, time_before_collision 등)는 사용자가 직접 설정해야 하며, 확인한 문서 범위 내에서는 설정값의 적절성을 자동으로 검증하는 절차는 명시되어 있지 않다.

## 7. 원문 기반 핵심 문장
> "However, this node is done at the CPU level with any form of sensor. As such, this does not provide hard real-time safety certifications, but uses the same types of techniques with the same types of data for users that do not have safety-rated laser sensors."
