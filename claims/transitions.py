"""
Single choke point for every Claim status change.

Nothing in views.py or tasks.py should ever do `claim.status = X; claim.save()`
directly. Always call apply_transition(). That's what guarantees:
  1. Only legal next-statuses are reachable from the current one.
  2. Every change is written to StatusHistory (your audit trail + analytics feed).
  3. "Hold" statuses are handled uniformly — a hold is just a transition like
     any other, so it's trivial to see *when* and *why* a claim got stuck.
"""

from django.db import transaction
from django.utils import timezone

from .models import Claim, StatusHistory

Status = Claim.Status

# Map of current status -> set of statuses it's legal to move to next.
ALLOWED_TRANSITIONS = {
    Status.INGESTED: {Status.VALIDATING},
    Status.VALIDATING: {Status.VALIDATED, Status.VALIDATION_HOLD},
    Status.VALIDATION_HOLD: {Status.VALIDATING},  # re-run after fix/retry

    Status.VALIDATED: {Status.PRICING},
    Status.PRICING: {Status.PRICED, Status.PRICING_HOLD},
    Status.PRICING_HOLD: {Status.PRICING},

    Status.PRICED: {Status.PENDING_APPROVAL},
    Status.PENDING_APPROVAL: {Status.APPROVED, Status.DENIED, Status.PENDED},
    Status.PENDED: {Status.APPROVED, Status.DENIED},  # approver resolves a pended claim

    Status.APPROVED: {Status.PENDING_PAYMENT_APPROVAL},
    Status.PENDING_PAYMENT_APPROVAL: {Status.PAYMENT_APPROVED, Status.PAYMENT_HOLD},
    Status.PAYMENT_HOLD: {Status.PENDING_PAYMENT_APPROVAL},

    Status.PAYMENT_APPROVED: {Status.PAYMENT_SCHEDULED},
    Status.PAYMENT_SCHEDULED: {Status.PAID, Status.PAYMENT_HOLD},

    # DENIED and PAID are terminal — no outgoing transitions.
}


class IllegalTransitionError(Exception):
    pass


@transaction.atomic
def apply_transition(claim: Claim, to_status: str, reason: str = "", actor: str = "system") -> Claim:
    """
    Move `claim` to `to_status` if legal, logging the transition either way.
    Raises IllegalTransitionError if the move isn't allowed from the current status.
    """
    from_status = claim.status
    allowed = ALLOWED_TRANSITIONS.get(from_status, set())

    if to_status not in allowed:
        raise IllegalTransitionError(
            f"Cannot move claim {claim.claim_number} from {from_status} to {to_status}. "
            f"Allowed: {sorted(allowed) or 'none (terminal status)'}"
        )

    claim.status = to_status
    if to_status.endswith("_HOLD"):
        claim.hold_reason = reason
    else:
        # Moving OFF a hold (or anywhere else) — the old hold reason no
        # longer describes the claim's current state, so clear it. The full
        # history (including why it was held) is still preserved in
        # StatusHistory either way; this field is "current hold reason", not a log.
        claim.hold_reason = ""
    claim.updated_at = timezone.now()
    claim.save(update_fields=["status", "hold_reason", "updated_at"])

    StatusHistory.objects.create(
        claim=claim,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        actor=actor,
    )
    return claim


def put_on_hold(claim: Claim, hold_status: str, reason: str, actor: str = "system") -> Claim:
    """Convenience wrapper — same as apply_transition but reads better at call sites."""
    return apply_transition(claim, hold_status, reason=reason, actor=actor)