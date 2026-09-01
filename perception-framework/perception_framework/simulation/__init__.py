"""Virtual terminals and replay sources standing in for physical devices.

implements: AI-C-04, AI-C-08, AI-B-09, AI-B-10

Everything here is an *adapter/provider* implementation, not core logic:
these modules may be deleted from a deployment without touching any
perception/decision/risk/execution code. They exist so the framework's
behaviour under hardware, capability and environment change can be
verified without physical devices (AI-B-09: 검증 목적은 정확도가 아니라
공통 인터페이스·격리 규칙 충족 확인).
"""
