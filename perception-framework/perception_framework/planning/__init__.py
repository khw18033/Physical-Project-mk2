"""Zone task -> edge-local executable subtask decomposition.

implements: AI-D-03 인접 (Milestone -> Task 분해)

관할 경계(docs/integration/subtask-handoff-to-visualization.md §계층 경계 확정
2026-08-28): Goal→Milestone→Task→Action Item 계층에서 Milestone/Task는 AI
소관으로 확정됐다. AI-D-01/02(서브태스크=Action Item 생성·검증)은 2026-08-26에
가시화 파트로 이관되어 그 구현·테스트·계약은 삭제됐다. 이 패키지의
`TaskDecomposer`는 삭제된 AI-D-01/02 구현의 복원이 아니라, AI가 계속 소관하는
Task 분해 계층의 별도 설계다.
"""
