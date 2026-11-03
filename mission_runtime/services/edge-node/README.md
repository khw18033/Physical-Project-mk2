# 구역 엣지 서비스

말단에서 올라온 업무 데이터를 1차로 받아 후처리·합의·추적·보존을 하는 서비스다.
구역(zone)마다 하나가 돈다.

```text
edge_server.py      수신 진입점
postprocess.py      프레임 결과 후처리
consensus.py        여러 제공자 결과의 합의
object_tracks.py    지속 객체 track 유지
tracking.py         프레임 간 연결
semantic.py         의미 근거 부착
retention.py        보존 기간 관리
common.py           공용 유틸
class_features.*.json  도메인별 클래스 특징·관문·임계 (데이터)
```

`class_features.*.json` 은 **데이터**다. 새 도메인은 파일 하나를 더하는 것이고 코드를
고치는 일이 아니다. 임계는 실측(sweep)으로 정하며, 다른 입력 구성에서 맞춘 값을 그대로
옮겨 적지 않는다(AI-B-01).

## 돌리는 데 필요한 것

`requirements-edge.txt` 와 `config.json`. 캡처 결과·모델 가중치는 이 디렉터리에 두지
않는다(공개 트리 밖).
