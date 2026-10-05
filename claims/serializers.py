from rest_framework import serializers

from .models import Claim, ServiceLine, StatusHistory, Provider, Member, Payment


class ServiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceLine
        fields = [
            "id", "cpt_code", "description", "units",
            "billed_amount", "allowed_amount", "approved_amount",
        ]


class StatusHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = StatusHistory
        fields = ["from_status", "to_status", "reason", "actor", "created_at"]


class ProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Provider
        fields = ["provider_id", "name", "npi", "is_active"]


class MemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = Member
        fields = ["member_id", "name", "membership_effective_date", "membership_status"]


class ClaimListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for the Claims List page — no nested detail."""

    provider_name = serializers.CharField(source="provider.name", read_only=True)
    member_name = serializers.CharField(source="member.name", read_only=True)

    class Meta:
        model = Claim
        fields = [
            "id", "claim_number", "provider_name", "member_name",
            "date_of_service", "total_claim_amount", "status",
            "assigned_user", "updated_at",
        ]


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id", "method", "amount", "scheduled_payment_date",
            "reference_number", "status", "eop_text",
            "executed_at", "failure_reason", "created_at",
        ]


class ClaimDetailSerializer(serializers.ModelSerializer):
    """Full serializer for the Claim Detail page — nests everything."""

    provider = ProviderSerializer(read_only=True)
    member = MemberSerializer(read_only=True)
    service_lines = ServiceLineSerializer(many=True, read_only=True)
    status_history = StatusHistorySerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta:
        model = Claim
        fields = [
            "id", "claim_number", "claim_type", "provider", "member",
            "authorization_number", "date_of_service",
            "total_claim_amount", "total_approved_amount",
            "status", "hold_reason", "assigned_user",
            "service_lines", "status_history", "payments",
            "created_at", "updated_at",
        ]


class ApprovalActionSerializer(serializers.Serializer):
    """Request body for approve/deny/pend/approve-payment/hold-payment actions."""

    comment = serializers.CharField(required=False, allow_blank=True, default="")


class SubmitPaymentApprovalSerializer(serializers.Serializer):
    """Currently no extra fields needed — kept as its own serializer so it's easy to extend later."""

    comment = serializers.CharField(required=False, allow_blank=True, default="")


class SchedulePaymentSerializer(serializers.Serializer):
    """Request body for POST /claims/<id>/schedule-payment/."""

    method = serializers.ChoiceField(choices=Payment.Method.choices)
    scheduled_payment_date = serializers.DateField()
    reference_number = serializers.CharField(required=False, allow_blank=True, default="")


# ---------------------------------------------------------------------------
# Editing a held claim
# ---------------------------------------------------------------------------

class ClaimEditServiceLineSerializer(serializers.Serializer):
    """Same shape as ingestion's service line input — used to fully replace a held claim's lines."""

    cpt_code = serializers.CharField(max_length=20)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    units = serializers.IntegerField(required=False, default=1, min_value=1)
    billed_amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class ClaimEditSerializer(serializers.Serializer):
    """
    Request body for PATCH /claims/<id>/edit/. Only covers fields that are
    actually claim-level fixable causes of a hold (missing auth number, no
    service lines). Provider/member status — the OTHER common hold causes —
    live on Provider/Member, not the claim, and are fixed via Django admin
    (as you just did), then unstuck with the retry endpoint, not this one.

    All fields optional: send only what you're changing. service_lines, if
    sent, REPLACES the claim's existing lines entirely (delete + recreate) —
    it's not a partial merge.
    """

    authorization_number = serializers.CharField(max_length=50, required=False, allow_blank=True)
    claim_type = serializers.CharField(max_length=50, required=False, allow_blank=True)
    service_lines = ClaimEditServiceLineSerializer(many=True, required=False)


# ---------------------------------------------------------------------------
# Stage 1: Ingestion
# ---------------------------------------------------------------------------

class ProviderInputSerializer(serializers.Serializer):
    provider_id = serializers.CharField(max_length=50)
    name = serializers.CharField(max_length=255)
    npi = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    is_active = serializers.BooleanField(required=False, default=True)


class MemberInputSerializer(serializers.Serializer):
    member_id = serializers.CharField(max_length=50)
    name = serializers.CharField(max_length=255)
    membership_effective_date = serializers.DateField(required=False, allow_null=True, default=None)
    membership_status = serializers.ChoiceField(
        choices=["ACTIVE", "INACTIVE", "TERMED"], required=False, default="ACTIVE"
    )


class ServiceLineInputSerializer(serializers.Serializer):
    cpt_code = serializers.CharField(max_length=20)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    units = serializers.IntegerField(required=False, default=1, min_value=1)
    billed_amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class IngestionInputSerializer(serializers.Serializer):
    """
    Request body for POST /api/claims/ingest/. Nests provider, member, and
    service lines so a single ingestion call can create everything a new
    claim needs, matching the spec's "claim, authorization, enrollment,
    and encounter data ingestion" requirement.
    """

    claim_number = serializers.CharField(max_length=50)
    claim_type = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    authorization_number = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    date_of_service = serializers.DateField()
    total_claim_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=0)

    provider = ProviderInputSerializer()
    member = MemberInputSerializer()
    service_lines = ServiceLineInputSerializer(many=True)

    def validate_claim_number(self, value):
        if Claim.objects.filter(claim_number=value).exists():
            raise serializers.ValidationError(f"A claim with claim_number '{value}' already exists.")
        return value

    def validate_service_lines(self, value):
        if not value:
            raise serializers.ValidationError("At least one service line is required.")
        return value

