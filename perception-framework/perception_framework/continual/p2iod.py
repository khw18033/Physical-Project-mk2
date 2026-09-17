"""P2IOD-style parameterized-prompt fusion (magnitude/sign task-vector decomposition).

implements: AI-L-04, AI-L-05

docs/obsidian/papers/p2iod.md 검증 근거(§3 "Parameterized Prompt Fusion",
수식 (8)): task vector v_t = theta_t - theta_{t-1}^f 를 magnitude mu_t = |v_t|와
sign gamma_t = sgn(v_t)로 분해한 뒤 (i) magnitude 상위 top-k/l 파라미터는 새 task
값으로 우선 보존, (ii) 부호가 이전과 일치하는 나머지는 평균, (iii) 그 외(부호 충돌)는
이전 값을 유지하는 4단계 규칙 + L1 sparse loss를 결합한다.

This module reproduces ONLY that parameter-fusion decision rule as a pure numpy
operation over plain vectors. It does NOT reproduce:
  - the parameterized-prompt MLP bottleneck / decoder self-attention injection
    structure that the paper actually trains (Deformable-DETR / Co-DETR);
  - the pseudo-labeling co-occurring-object mining used to generate training
    signal for the prompt network;
  - any training loop, optimizer, or the L1 sparse loss's gradient-side effect
    on which parameters become sparse in the first place (only the fusion-time
    zeroing step, "sparsity_threshold", is modeled here as a decision rule);
  - PASCAL VOC / MS COCO or any real dataset, detector, or reported AP number.

`prior_params` / `new_task_delta` are plain numpy vectors the caller supplies;
this module makes no assumption about what they represent (adapter weights,
prompt-network parameters, or any other consolidatable state) per AI-C-04/05
(no concrete model architecture is hardcoded here).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TaskVectorFusionResult:
    fused_params: np.ndarray
    kept_from_prior: int  # count of indices where sign conflict kept prior value unchanged
    averaged_sign_consistent: int  # count of indices where sign-consistent averaging was applied
    critical_preserved: int  # count of top-k/l magnitude "critical" indices preserved from new task
    sparsity_applied: int  # count of indices zeroed out by the L1-style sparsification step


def fuse_task_vectors(
    prior_params: np.ndarray,
    new_task_delta: np.ndarray,
    *,
    top_k_fraction: float = 0.1,
    sparsity_threshold: float | None = None,
) -> TaskVectorFusionResult:
    """Fuse a new task's parameter delta into prior params without overwrite-or-average.

    Steps (paper note, applied literally to 1-D vectors):
      1. critical mask = indices of the top_k_fraction largest |new_task_delta|
         entries. These always take the fully-updated value
         (prior_params + new_task_delta) unchanged -- the new task's most
         important updates always survive fusion.
      2. For every other index: if sign(new_task_delta[i]) agrees with
         sign(prior_params[i]) (same direction, or prior is ~0 so there is no
         old direction to conflict with), the fused value is the average of
         prior_params[i] and (prior_params[i] + new_task_delta[i]). If the
         signs disagree, the update is fighting an established old-task
         direction, so prior_params[i] is kept unchanged (protects old-task
         knowledge from a conflicting overwrite).
      3. If sparsity_threshold is given, any fused value outside the critical
         set with |value| below the threshold is zeroed (L1-style
         sparsification applied only at fusion time, as a decision rule --
         not the paper's training-time L1 loss term itself).

    Raises ValueError if the two vectors are not equal-length 1-D arrays or if
    top_k_fraction is outside [0, 1].
    """
    prior = np.asarray(prior_params, dtype=float)
    delta = np.asarray(new_task_delta, dtype=float)
    if prior.ndim != 1 or delta.ndim != 1:
        raise ValueError("prior_params and new_task_delta must be 1-D vectors")
    if prior.shape != delta.shape:
        raise ValueError("prior_params and new_task_delta must have the same shape")
    if not 0.0 <= top_k_fraction <= 1.0:
        raise ValueError("top_k_fraction must be in [0, 1]")
    if not np.isfinite(prior).all() or not np.isfinite(delta).all():
        raise ValueError("prior_params and new_task_delta must be finite")

    n = prior.shape[0]
    fully_updated = prior + delta

    # Step 1: critical mask = top_k_fraction largest |delta| entries.
    critical_mask = np.zeros(n, dtype=bool)
    k = int(round(top_k_fraction * n))
    if k > 0:
        critical_indices = np.argsort(np.abs(delta))[-k:]
        critical_mask[critical_indices] = True

    fused = np.empty(n, dtype=float)
    fused[critical_mask] = fully_updated[critical_mask]

    # Step 2: for non-critical indices, sign-gated averaging vs. keep-prior.
    other_mask = ~critical_mask
    prior_sign = np.sign(prior)
    delta_sign = np.sign(delta)
    # "prior is ~0" means there is no established old-task direction to
    # conflict with, so treat it as sign-consistent (average).
    sign_consistent = other_mask & ((prior_sign == 0) | (prior_sign == delta_sign))
    sign_conflict = other_mask & ~sign_consistent

    fused[sign_consistent] = 0.5 * (prior[sign_consistent] + fully_updated[sign_consistent])
    fused[sign_conflict] = prior[sign_conflict]

    # Step 3: optional L1-style sparsification, never touching the critical set.
    sparsity_mask = np.zeros(n, dtype=bool)
    if sparsity_threshold is not None:
        if sparsity_threshold < 0:
            raise ValueError("sparsity_threshold must be non-negative")
        sparsity_mask = other_mask & (np.abs(fused) < sparsity_threshold)
        fused[sparsity_mask] = 0.0

    return TaskVectorFusionResult(
        fused_params=fused,
        kept_from_prior=int(np.count_nonzero(sign_conflict)),
        averaged_sign_consistent=int(np.count_nonzero(sign_consistent & ~sparsity_mask)),
        critical_preserved=int(np.count_nonzero(critical_mask)),
        sparsity_applied=int(np.count_nonzero(sparsity_mask)),
    )
