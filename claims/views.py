"""
Stage 4 (Verification/Approval) + supporting list/detail views.

Unlike tasks.py, nothing here runs in the background — a CLAIMS_APPROVER
hits these endpoints directly (e.g. from a "Approve" button in the UI).
Every action still goes through apply_transition(), so:
  - an illegal move (e.g. approving an already-PAID claim) is rejected
  - every approve/deny/pend is written to StatusHistory automatically

Each view declares permission_classes from permissions.py, matching the
spec's role permissions. TPA_MANAGER passes every check (see HasRole).
"""

from rest_framework import generics, status as http_status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Claim, Payment, Provider, Member, ServiceLine, IngestionLog
from .serializers import (
    ClaimListSerializer,
    ClaimDetailSerializer,
    ApprovalActionSerializer,
    SubmitPaymentApprovalSerializer,
    SchedulePaymentSerializer,
    IngestionInputSerializer,
    ClaimEditSerializer,
)
from .transitions import apply_transition, IllegalTransitionError, Status
from .permissions import IsSubmitter, IsApprover, IsAnyRole
from .tasks import ingest_claim, retry_claim
from .edi.edi837_parser import parse_837, EDI837ParseError
from .ml.predict import score_claim, ModelNotAvailable


class MeView(APIView):
    """GET /api/me/ — returns the logged-in user's username and role, for the React frontend to store after login."""

    def get(self, request):
        profile = getattr(request.user, "claims_profile", None)
        return Response({
            "username": request.user.username,
            "role": profile.role if profile else None,
        })


def _create_claim_from_ingestion_data(data: dict, raw_payload, source: str) -> Claim:
    """
    Shared by every ingestion path (JSON API, EDI 837 upload, and any future
    one) so a claim is created and kicked off identically no matter how it
    arrived. `data` must already be validated (IngestionInputSerializer's
    validated_data shape). Writes the IngestionLog row and queues ingest_claim.
    """
    provider_data = data["provider"]
    member_data = data["member"]

    provider, _ = Provider.objects.get_or_create(
        provider_id=provider_data["provider_id"],
        defaults={
            "name": provider_data["name"],
            "npi": provider_data.get("npi", ""),
            "is_active": provider_data.get("is_active", True),
        },
    )
    member, _ = Member.objects.get_or_create(
        member_id=member_data["member_id"],
        defaults={
            "name": member_data["name"],
            "membership_effective_date": member_data.get("membership_effective_date"),
            "membership_status": member_data.get("membership_status", "ACTIVE"),
        },
    )

    claim = Claim.objects.create(
        claim_number=data["claim_number"],
        claim_type=data.get("claim_type", ""),
        provider=provider,
        member=member,
        authorization_number=data.get("authorization_number", ""),
        date_of_service=data["date_of_service"],
        total_claim_amount=data.get("total_claim_amount", 0),
    )
    for line in data["service_lines"]:
        ServiceLine.objects.create(
            claim=claim,
            cpt_code=line["cpt_code"],
            description=line.get("description", ""),
            units=line.get("units", 1),
            billed_amount=line["billed_amount"],
        )

    IngestionLog.objects.create(source=source, claim=claim, raw_payload=raw_payload, success=True)

    # Hand off to the background pipeline — validation and pricing run automatically from here.
    ingest_claim.delay(claim.id)

    return claim


class IngestClaimView(APIView):
    """
    POST /api/claims/ingest/
    CLAIMS_SUBMITTER action — Stage 1 (Data Ingestion), manual/API JSON path.
    """

    permission_classes = [IsSubmitter]

    def post(self, request):
        serializer = IngestionInputSerializer(data=request.data)

        if not serializer.is_valid():
            IngestionLog.objects.create(
                source="api", claim=None, raw_payload=request.data,
                success=False, error_message=str(serializer.errors),
            )
            return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

        claim = _create_claim_from_ingestion_data(serializer.validated_data, request.data, "api")
        return Response(ClaimDetailSerializer(claim).data, status=http_status.HTTP_201_CREATED)


class IngestEDI837View(APIView):
    """
    POST /api/claims/ingest-edi837/
    CLAIMS_SUBMITTER action — Stage 1 (Data Ingestion), EDI 837P upload path.
    Accepts either a multipart file upload (field name "file") or the raw
    EDI text as the request body. Parses every CLM (claim) found in the file
    and ingests each one through the SAME creation path as the JSON endpoint,
    so validation/pricing/hold behavior is identical either way.

    Response is 207 Multi-Status: some claims in a batch can succeed while
    others fail (e.g. a duplicate claim_number), each reported individually.
    """

    permission_classes = [IsSubmitter]

    def post(self, request):
        if "file" in request.FILES:
            raw_text = request.FILES["file"].read().decode("utf-8", errors="replace")
        elif request.body:
            raw_text = request.body.decode("utf-8", errors="replace")
        else:
            return Response(
                {"detail": "No file uploaded and no raw EDI content in the request body."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        try:
            parsed_claims = parse_837(raw_text)
        except EDI837ParseError as exc:
            return Response({"detail": f"Could not parse EDI 837 file: {exc}"}, status=http_status.HTTP_400_BAD_REQUEST)

        results = []
        for parsed in parsed_claims:
            serializer = IngestionInputSerializer(data=parsed)
            if not serializer.is_valid():
                IngestionLog.objects.create(
                    source="edi837", claim=None, raw_payload={"parsed": parsed},
                    success=False, error_message=str(serializer.errors),
                )
                results.append({
                    "claim_number": parsed.get("claim_number"), "success": False, "errors": serializer.errors,
                })
                continue

            claim = _create_claim_from_ingestion_data(serializer.validated_data, {"parsed": parsed}, "edi837")
            results.append({"claim_number": claim.claim_number, "claim_id": claim.id, "success": True})

        return Response({"results": results}, status=http_status.HTTP_207_MULTI_STATUS)


class ClaimListView(generics.ListAPIView):
    """GET /api/claims/ — the Claims List page. Supports ?status=PENDING_APPROVAL etc."""

    serializer_class = ClaimListSerializer
    permission_classes = [IsAnyRole]

    def get_queryset(self):
        qs = Claim.objects.select_related("provider", "member").order_by("-updated_at")
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class ClaimDetailView(generics.RetrieveAPIView):
    """GET /api/claims/<id>/ — the Claim Detail page."""

    queryset = Claim.objects.select_related("provider", "member").prefetch_related(
        "service_lines", "status_history"
    )
    serializer_class = ClaimDetailSerializer
    permission_classes = [IsAnyRole]


class _BaseApprovalAction(APIView):
    """Shared plumbing for approve/deny/pend — subclasses set target_status."""

    permission_classes = [IsApprover]
    target_status = None  # set by subclass
    success_reason = "Reviewed"

    def post(self, request, pk):
        try:
            claim = Claim.objects.get(pk=pk)
        except Claim.DoesNotExist:
            return Response({"detail": "Claim not found."}, status=http_status.HTTP_404_NOT_FOUND)

        body = ApprovalActionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        comment = body.validated_data.get("comment", "")

        actor = request.user.username if request.user and request.user.is_authenticated else "unknown"

        try:
            apply_transition(
                claim,
                self.target_status,
                reason=comment or self.success_reason,
                actor=actor,
            )
        except IllegalTransitionError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        return Response(ClaimDetailSerializer(claim).data, status=http_status.HTTP_200_OK)


class ApproveClaimView(_BaseApprovalAction):
    """POST /api/claims/<id>/approve/ — moves PENDING_APPROVAL or PENDED -> APPROVED."""

    target_status = Status.APPROVED
    success_reason = "Approved"


class DenyClaimView(_BaseApprovalAction):
    """POST /api/claims/<id>/deny/ — moves PENDING_APPROVAL or PENDED -> DENIED. Body should include a comment (denial reason)."""

    target_status = Status.DENIED
    success_reason = "Denied"


class PendClaimView(_BaseApprovalAction):
    """POST /api/claims/<id>/pend/ — moves PENDING_APPROVAL -> PENDED (needs more review)."""

    target_status = Status.PENDED
    success_reason = "Pended for further review"


# ---------------------------------------------------------------------------
# Stage 5: Payment
# ---------------------------------------------------------------------------

class SubmitForPaymentApprovalView(APIView):
    """
    POST /api/claims/<id>/submit-payment-approval/
    CLAIMS_SUBMITTER action: APPROVED -> PENDING_PAYMENT_APPROVAL.
    Mirrors the "Submit for Payment Approval" step in the spec's workflow.
    """

    permission_classes = [IsSubmitter]

    def post(self, request, pk):
        try:
            claim = Claim.objects.get(pk=pk)
        except Claim.DoesNotExist:
            return Response({"detail": "Claim not found."}, status=http_status.HTTP_404_NOT_FOUND)

        actor = request.user.username if request.user and request.user.is_authenticated else "unknown"

        try:
            apply_transition(claim, Status.PENDING_PAYMENT_APPROVAL, reason="Submitted for payment approval", actor=actor)
        except IllegalTransitionError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        return Response(ClaimDetailSerializer(claim).data)


class ApprovePaymentView(APIView):
    """POST /api/claims/<id>/approve-payment/ — CLAIMS_APPROVER: PENDING_PAYMENT_APPROVAL -> PAYMENT_APPROVED."""

    permission_classes = [IsApprover]

    def post(self, request, pk):
        try:
            claim = Claim.objects.get(pk=pk)
        except Claim.DoesNotExist:
            return Response({"detail": "Claim not found."}, status=http_status.HTTP_404_NOT_FOUND)

        body = ApprovalActionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        actor = request.user.username if request.user and request.user.is_authenticated else "unknown"

        try:
            apply_transition(
                claim, Status.PAYMENT_APPROVED,
                reason=body.validated_data.get("comment") or "Payment approved", actor=actor,
            )
        except IllegalTransitionError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        return Response(ClaimDetailSerializer(claim).data)


class HoldPaymentView(APIView):
    """POST /api/claims/<id>/hold-payment/ — CLAIMS_APPROVER: PENDING_PAYMENT_APPROVAL -> PAYMENT_HOLD."""

    permission_classes = [IsApprover]

    def post(self, request, pk):
        try:
            claim = Claim.objects.get(pk=pk)
        except Claim.DoesNotExist:
            return Response({"detail": "Claim not found."}, status=http_status.HTTP_404_NOT_FOUND)

        body = ApprovalActionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        comment = body.validated_data.get("comment") or "Payment held for review"
        actor = request.user.username if request.user and request.user.is_authenticated else "unknown"

        try:
            apply_transition(claim, Status.PAYMENT_HOLD, reason=comment, actor=actor)
        except IllegalTransitionError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        return Response(ClaimDetailSerializer(claim).data)


class SchedulePaymentView(APIView):
    """
    POST /api/claims/<id>/schedule-payment/
    CLAIMS_SUBMITTER action: PAYMENT_APPROVED -> PAYMENT_SCHEDULED.
    Body: {"method": "ACH"|"CHECK", "scheduled_payment_date": "YYYY-MM-DD", "reference_number": "..."}
    Creates the Payment row that execute_scheduled_payments (a Celery task) will later pick up and execute.
    """

    permission_classes = [IsSubmitter]

    def post(self, request, pk):
        try:
            claim = Claim.objects.get(pk=pk)
        except Claim.DoesNotExist:
            return Response({"detail": "Claim not found."}, status=http_status.HTTP_404_NOT_FOUND)

        body = SchedulePaymentSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        actor = request.user.username if request.user and request.user.is_authenticated else "unknown"

        try:
            apply_transition(claim, Status.PAYMENT_SCHEDULED, reason="Payment scheduled", actor=actor)
        except IllegalTransitionError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        payment = Payment.objects.create(
            claim=claim,
            method=body.validated_data["method"],
            amount=claim.total_approved_amount or claim.total_claim_amount,
            scheduled_payment_date=body.validated_data["scheduled_payment_date"],
            reference_number=body.validated_data.get("reference_number", ""),
        )

        return Response(ClaimDetailSerializer(claim).data, status=http_status.HTTP_201_CREATED)



# ---------------------------------------------------------------------------
# Predictive analysis
# ---------------------------------------------------------------------------

class ClaimRiskScoreView(APIView):
    """
    GET /api/claims/<id>/risk-score/
    Returns the model's probability that this claim ends up denied or held,
    a LOW/MEDIUM/HIGH level, and up to three plain-English reasons.
    Computed live from the claim's current data every time it's requested.
    """

    permission_classes = [IsAnyRole]

    def get(self, request, pk):
        try:
            claim = Claim.objects.select_related("provider", "member").get(pk=pk)
        except Claim.DoesNotExist:
            return Response({"detail": "Claim not found."}, status=http_status.HTTP_404_NOT_FOUND)

        try:
            result = score_claim(claim)
        except ModelNotAvailable as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(result)



class RetryClaimView(APIView):
    """
    POST /api/claims/<id>/retry/
    Immediately re-checks a claim sitting on VALIDATION_HOLD, PRICING_HOLD,
    or PAYMENT_HOLD — the "Retry Now" button. Does nothing to the claim's
    data; only re-runs the check it failed before. Only useful if something
    actually changed (an edit via EditClaimView, or an external fix like
    reactivating a Provider in Django admin).
    """

    permission_classes = [IsSubmitter]

    HOLD_STATUSES = {"VALIDATION_HOLD", "PRICING_HOLD", "PAYMENT_HOLD"}

    def post(self, request, pk):
        try:
            claim = Claim.objects.get(pk=pk)
        except Claim.DoesNotExist:
            return Response({"detail": "Claim not found."}, status=http_status.HTTP_404_NOT_FOUND)

        if claim.status not in self.HOLD_STATUSES:
            return Response(
                {"detail": f"Claim is not on a hold status (currently {claim.status}); nothing to retry."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        actor = request.user.username if request.user and request.user.is_authenticated else "unknown"
        retry_claim.delay(claim.id, actor=actor)

        return Response({"detail": f"Retry queued for claim {claim.claim_number}."}, status=http_status.HTTP_202_ACCEPTED)


class EditClaimView(APIView):
    """
    PATCH /api/claims/<id>/edit/
    Lets a CLAIMS_SUBMITTER fix the claim-level data that actually caused a
    VALIDATION_HOLD or PRICING_HOLD (missing authorization_number, no service
    lines) — the gap that made claims stuck on hold unrecoverable before this.
    Only allowed while the claim is actually on one of those two holds; other
    fixes (provider/member status) don't belong to the claim and aren't edited here.

    On success, automatically queues a retry — no separate "Retry Now" click needed.
    """

    permission_classes = [IsSubmitter]

    EDITABLE_HOLD_STATUSES = {"VALIDATION_HOLD", "PRICING_HOLD"}

    def patch(self, request, pk):
        try:
            claim = Claim.objects.get(pk=pk)
        except Claim.DoesNotExist:
            return Response({"detail": "Claim not found."}, status=http_status.HTTP_404_NOT_FOUND)

        if claim.status not in self.EDITABLE_HOLD_STATUSES:
            return Response(
                {"detail": f"Claim can only be edited while on VALIDATION_HOLD or PRICING_HOLD (currently {claim.status})."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        serializer = ClaimEditSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if "authorization_number" in data:
            claim.authorization_number = data["authorization_number"]
        if "claim_type" in data:
            claim.claim_type = data["claim_type"]
        claim.save()

        if "service_lines" in data:
            claim.service_lines.all().delete()
            for line in data["service_lines"]:
                ServiceLine.objects.create(
                    claim=claim,
                    cpt_code=line["cpt_code"],
                    description=line.get("description", ""),
                    units=line.get("units", 1),
                    billed_amount=line["billed_amount"],
                )

        actor = request.user.username if request.user and request.user.is_authenticated else "unknown"
        retry_claim.delay(claim.id, actor=actor)

        return Response(ClaimDetailSerializer(claim).data)