"""
Core data model for the TPA claims pipeline.

Design notes:
- Claim.status is the single source of truth for where a claim sits in the
  pipeline. Never set it directly from views/tasks — always go through
  transitions.apply_transition() so every change is validated + logged.
- "*_HOLD" statuses are terminal-but-resumable: a claim sits there until a
  human or a retry moves it back into the flow. They are what your manager
  meant by "hold that should stop claims moving forward".
- Every status change is written to StatusHistory, which doubles as your
  audit trail and feeds the Stage 6 analytics (turnaround time, denial
  rates, etc.) for free.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class UserProfile(models.Model):
    """
    One row per Django User, carrying their TPA role. TPA_MANAGER is a
    superset of the other two (spec: "Perform both submitter and approver
    actions") — permissions.py encodes that, not this model.
    """

    class Role(models.TextChoices):
        CLAIMS_SUBMITTER = "CLAIMS_SUBMITTER", "Claims Submitter"
        CLAIMS_APPROVER = "CLAIMS_APPROVER", "Claims Approver"
        TPA_MANAGER = "TPA_MANAGER", "TPA Manager"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="claims_profile")
    role = models.CharField(max_length=20, choices=Role.choices)

    def __str__(self):
        return f"{self.user.username} ({self.role})"


class Provider(models.Model):
    provider_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    npi = models.CharField(max_length=20, blank=True)  # National Provider ID
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.provider_id} - {self.name}"


class Member(models.Model):
    member_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    membership_effective_date = models.DateField(null=True, blank=True)
    membership_status = models.CharField(
        max_length=20,
        choices=[("ACTIVE", "Active"), ("INACTIVE", "Inactive"), ("TERMED", "Termed")],
        default="ACTIVE",
    )

    def __str__(self):
        return f"{self.member_id} - {self.name}"


class Claim(models.Model):
    class Status(models.TextChoices):
        INGESTED = "INGESTED", "Ingested"
        VALIDATING = "VALIDATING", "Validating"
        VALIDATED = "VALIDATED", "Validated"
        VALIDATION_HOLD = "VALIDATION_HOLD", "Validation Hold"
        PRICING = "PRICING", "Pricing"
        PRICED = "PRICED", "Priced"
        PRICING_HOLD = "PRICING_HOLD", "Pricing Hold"
        PENDING_APPROVAL = "PENDING_APPROVAL", "Pending Approval"
        APPROVED = "APPROVED", "Approved"
        DENIED = "DENIED", "Denied"
        PENDED = "PENDED", "Pended"
        PENDING_PAYMENT_APPROVAL = "PENDING_PAYMENT_APPROVAL", "Pending Payment Approval"
        PAYMENT_APPROVED = "PAYMENT_APPROVED", "Payment Approved"
        PAYMENT_SCHEDULED = "PAYMENT_SCHEDULED", "Payment Scheduled"
        PAID = "PAID", "Paid"
        PAYMENT_HOLD = "PAYMENT_HOLD", "Payment Hold"

    claim_number = models.CharField(max_length=50, unique=True)
    claim_type = models.CharField(max_length=50, blank=True)
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name="claims")
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="claims")
    authorization_number = models.CharField(max_length=50, blank=True)
    date_of_service = models.DateField()
    total_claim_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_approved_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    status = models.CharField(max_length=32, choices=Status.choices, default=Status.INGESTED)
    hold_reason = models.TextField(blank=True)

    assigned_user = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["member", "date_of_service"]),  # duplicate-claim lookups
        ]

    def __str__(self):
        return f"{self.claim_number} [{self.status}]"


class ServiceLine(models.Model):
    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="service_lines")
    cpt_code = models.CharField(max_length=20)
    description = models.CharField(max_length=255, blank=True)
    units = models.PositiveIntegerField(default=1)
    billed_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    allowed_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    approved_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.claim.claim_number} - {self.cpt_code}"


class StatusHistory(models.Model):
    """Append-only audit trail. One row per transition attempt (success or hold)."""

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=32, blank=True)
    to_status = models.CharField(max_length=32)
    reason = models.TextField(blank=True)
    actor = models.CharField(max_length=100, default="system")  # "system" for worker-driven steps
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.claim.claim_number}: {self.from_status} -> {self.to_status}"


class IngestionLog(models.Model):
    """One row per ingested claim or per failed ingestion attempt."""

    source = models.CharField(max_length=50, default="manual")  # manual / file / api
    claim = models.ForeignKey(Claim, on_delete=models.SET_NULL, null=True, blank=True, related_name="ingestion_logs")
    raw_payload = models.JSONField()
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Payment(models.Model):
    """
    Stage 5 (Payment). One row per payment attempt on a claim.

    A claim normally has one Payment record, created at "Schedule Payment"
    time (PAYMENT_APPROVED -> PAYMENT_SCHEDULED) and then executed
    (PAYMENT_SCHEDULED -> PAID) by the execute_scheduled_payments worker task.
    If execution fails, the Claim goes to PAYMENT_HOLD and a NEW Payment row
    is created the next time scheduling is retried — so this table doubles
    as the "payment audit history" the spec asks for; never edit a row after
    the fact, create a new one.
    """

    class Method(models.TextChoices):
        ACH = "ACH", "ACH"
        CHECK = "CHECK", "Check"

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=10, choices=Method.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    scheduled_payment_date = models.DateField()
    reference_number = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)

    eop_text = models.TextField(blank=True)  # generated Explanation of Payment
    executed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.claim.claim_number} - {self.method} {self.amount} [{self.status}]"