"""
Worker-driven pipeline. Each stage is its own Celery task that:
  1. Pulls one claim (by id) into a "processing" status.
  2. Runs its checks.
  3. Either advances the claim and kicks off the next task, or holds it.

This is the "worker-based approach running in background, automating steps
as they qualify, with a hold that stops progression on failure" your manager
described. Wiring it as small chained tasks (rather than one big task) means
you can retry, monitor, and scale each stage independently, and Stage 6
analytics can query StatusHistory to see exactly where claims are getting stuck.

Celery setup (once, in your Django project):
    pip install celery redis
    # settings.py
    CELERY_BROKER_URL = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND = "redis://localhost:6379/0"
    # celery.py in your project package, then:
    #   app.autodiscover_tasks()
Run a worker with: celery -A your_project worker -l info
"""

from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import Claim, ServiceLine, Payment
from .transitions import apply_transition, put_on_hold, Status


# ---------------------------------------------------------------------------
# Stage 1 -> 2: kick off validation right after ingestion
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def ingest_claim(self, claim_id: int):
    """Entry point once a claim row exists with status=INGESTED."""
    claim = Claim.objects.get(id=claim_id)
    apply_transition(claim, Status.VALIDATING, reason="Ingestion complete, starting validation")
    validate_claim.delay(claim_id)


# ---------------------------------------------------------------------------
# Stage 2: Validation
# ---------------------------------------------------------------------------

def _run_validation_checks(claim: Claim) -> list[str]:
    """
    Returns a list of failure reasons. Empty list = claim passes validation.
    Stub the checks you don't have real data sources for yet — the point
    right now is the pipeline shape, not every rule being fully implemented.
    """
    failures = []

    if claim.member.membership_status != "ACTIVE":
        failures.append(f"Member {claim.member.member_id} is not active")

    if claim.member.membership_effective_date and claim.date_of_service < claim.member.membership_effective_date:
        failures.append("Date of service is before membership effective date")

    if not claim.provider.is_active:
        failures.append(f"Provider {claim.provider.provider_id} is inactive")

    if not claim.authorization_number:
        failures.append("Missing authorization number")

    # Duplicate detection: same member + provider + date of service already in the pipeline
    duplicate_exists = (
        Claim.objects.filter(
            member=claim.member,
            provider=claim.provider,
            date_of_service=claim.date_of_service,
        )
        .exclude(id=claim.id)
        .exclude(status__in=[Status.DENIED])
        .exists()
    )
    if duplicate_exists:
        failures.append("Duplicate claim detected for this member/provider/date of service")

    if not claim.service_lines.exists():
        failures.append("Claim has no service lines")

    return failures


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def validate_claim(self, claim_id: int):
    claim = Claim.objects.select_related("member", "provider").get(id=claim_id)

    failures = _run_validation_checks(claim)

    if failures:
        put_on_hold(claim, Status.VALIDATION_HOLD, reason="; ".join(failures))
        return  # stop here — does NOT proceed to pricing

    apply_transition(claim, Status.VALIDATED, reason="All validation checks passed")
    price_claim.delay(claim_id)


# ---------------------------------------------------------------------------
# Stage 3: Pricing
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def price_claim(self, claim_id: int):
    claim = Claim.objects.get(id=claim_id)
    apply_transition(claim, Status.PRICING, reason="Pricing started")

    try:
        total_approved = 0
        for line in claim.service_lines.all():
            # Placeholder pricing logic — swap in the real fee-schedule /
            # Medicare-Medicaid lookup later. For now: allowed = billed,
            # approved = allowed (no manual adjustment applied yet).
            line.allowed_amount = line.billed_amount
            line.approved_amount = line.allowed_amount
            line.save(update_fields=["allowed_amount", "approved_amount"])
            total_approved += line.approved_amount

        claim.total_approved_amount = total_approved
        claim.save(update_fields=["total_approved_amount"])

    except Exception as exc:
        put_on_hold(claim, Status.PRICING_HOLD, reason=f"Pricing failed: {exc}")
        return

    apply_transition(claim, Status.PRICED, reason="Pricing calculated")
    apply_transition(claim, Status.PENDING_APPROVAL, reason="Submitted for approval")
    # From here, a CLAIMS_APPROVER acts via the API/UI — not a worker —
    # so the pipeline pauses until a human calls approve/deny/pend.


# ---------------------------------------------------------------------------
# Retry sweep: periodically re-attempt claims sitting in a *_HOLD status
# (wire this to Celery beat, e.g. every 30 minutes)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Stage 5: Payment execution
# ---------------------------------------------------------------------------

def _generate_eop_text(payment: Payment) -> str:
    """Placeholder EOP (Explanation of Payment) generator — swap for a real PDF/template later."""
    claim = payment.claim
    return (
        f"EOP for Claim {claim.claim_number}\n"
        f"Member: {claim.member.name} ({claim.member.member_id})\n"
        f"Provider: {claim.provider.name} ({claim.provider.provider_id})\n"
        f"Amount Paid: {payment.amount}\n"
        f"Method: {payment.method}   Reference: {payment.reference_number or 'N/A'}\n"
        f"Payment Date: {payment.scheduled_payment_date}\n"
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def execute_payment(self, payment_id: int):
    """
    Executes a single scheduled payment (simulates calling an ACH/check processor).
    Wire this to run when a payment's scheduled_payment_date is reached — either
    called directly for "pay now", or picked up by the periodic sweep below for
    future-dated payments.
    """
    payment = Payment.objects.select_related("claim").get(id=payment_id)
    claim = payment.claim

    try:
        if not payment.reference_number:
            raise ValueError("Missing payment reference number")
        # Placeholder for a real ACH/check processor call. Replace this block
        # with the actual integration when Stage 5's "API integration to
        # automate ACH/Check issuance" is ready.

        payment.status = Payment.Status.PAID
        payment.executed_at = timezone.now()
        payment.eop_text = _generate_eop_text(payment)
        payment.save(update_fields=["status", "executed_at", "eop_text"])

    except Exception as exc:
        payment.status = Payment.Status.FAILED
        payment.failure_reason = str(exc)
        payment.save(update_fields=["status", "failure_reason"])
        put_on_hold(claim, Status.PAYMENT_HOLD, reason=f"Payment execution failed: {exc}")
        return

    apply_transition(claim, Status.PAID, reason=f"Payment executed via {payment.method}, ref {payment.reference_number}")


@shared_task
def execute_due_payments():
    """
    Periodic sweep (wire to Celery beat, e.g. daily) — finds PAYMENT_SCHEDULED
    claims whose Payment.scheduled_payment_date has arrived and executes them.
    This is what makes "future-dated payment scheduling" actually happen
    automatically instead of needing someone to click a button on the day.
    """
    today = timezone.now().date()
    due_payments = Payment.objects.filter(
        status=Payment.Status.SCHEDULED,
        scheduled_payment_date__lte=today,
        claim__status=Status.PAYMENT_SCHEDULED,
    )
    for payment in due_payments:
        execute_payment.delay(payment.id)


@shared_task
def retry_claim(claim_id: int, actor: str = "system"):
    """
    Re-checks a SINGLE claim currently sitting on a hold. This does not fix
    anything by itself — it re-runs the same check the claim failed before,
    against the claim's CURRENT data. So it only helps if something changed
    since the hold: the claim was edited (see EditClaimView), or an external
    fix was made (e.g. the provider was reactivated in Django admin).

    Used two ways:
      - by retry_stale_holds below, on a timer, for claims that have been
        stuck for a while (maybe something changed and nobody re-checked).
      - directly by RetryClaimView, for an immediate "Retry Now" button.
    """
    claim = Claim.objects.select_related("member", "provider").get(id=claim_id)

    if claim.status == Status.VALIDATION_HOLD:
        apply_transition(claim, Status.VALIDATING, reason="Retry requested", actor=actor)
        validate_claim.delay(claim.id)
    elif claim.status == Status.PRICING_HOLD:
        apply_transition(claim, Status.PRICING, reason="Retry requested", actor=actor)
        price_claim.delay(claim.id)
    elif claim.status == Status.PAYMENT_HOLD:
        # A failed/held payment needs a fresh approval + a corrected Payment
        # record (new reference number, etc.) via schedule-payment — not a
        # blind re-execution of the same broken payment. Sending it back to
        # PENDING_PAYMENT_APPROVAL restarts that human-in-the-loop path.
        apply_transition(claim, Status.PENDING_PAYMENT_APPROVAL, reason="Retry requested — re-approval needed", actor=actor)
    # Any other status: nothing to retry, silently no-op.


@shared_task
def retry_stale_holds(older_than_minutes: int = 30):
    cutoff = timezone.now() - timedelta(minutes=older_than_minutes)
    stale_ids = Claim.objects.filter(
        status__in=[Status.VALIDATION_HOLD, Status.PRICING_HOLD, Status.PAYMENT_HOLD],
        updated_at__lte=cutoff,
    ).values_list("id", flat=True)

    for claim_id in stale_ids:
        retry_claim.delay(claim_id)