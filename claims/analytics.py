"""
Stage 6 (Analytics & Reporting).

One GET endpoint that returns every dashboard metric from the spec in a
single response, since a real dashboard UI would fire one request and
render several widgets from it. Filters (date range, status, provider,
member, claim type) apply to the "claims universe" the metrics are computed
over — e.g. filtering by provider gives you that provider's numbers only.

GET /api/analytics/dashboard/
Query params (all optional):
  start_date=2026-01-01&end_date=2026-12-31   (filters on date_of_service)
  status=PENDING_APPROVAL
  provider=PRV001                              (provider_id)
  member=MEM001                                (member_id)
  claim_type=Institutional
"""

from django.db.models import Count, Sum, Avg, F
from django.db.models.functions import TruncDate, TruncMonth
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Claim, Payment, StatusHistory
from .permissions import IsManager


def _filtered_claims(request):
    qs = Claim.objects.select_related("provider", "member")

    start_date = request.query_params.get("start_date")
    end_date = request.query_params.get("end_date")
    status = request.query_params.get("status")
    provider = request.query_params.get("provider")
    member = request.query_params.get("member")
    claim_type = request.query_params.get("claim_type")

    if start_date:
        qs = qs.filter(date_of_service__gte=start_date)
    if end_date:
        qs = qs.filter(date_of_service__lte=end_date)
    if status:
        qs = qs.filter(status=status)
    if provider:
        qs = qs.filter(provider__provider_id=provider)
    if member:
        qs = qs.filter(member__member_id=member)
    if claim_type:
        qs = qs.filter(claim_type=claim_type)

    return qs


def _status_events_by_date(to_status: str, claim_ids):
    """Count of StatusHistory rows moving TO `to_status`, grouped by day, restricted to claim_ids."""
    return list(
        StatusHistory.objects.filter(to_status=to_status, claim_id__in=claim_ids)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )


def _avg_turnaround_hours(claims_qs):
    """
    Average time from claim creation to first terminal decision (APPROVED, DENIED, or PAID).
    Computed in Python over StatusHistory rather than pure SQL — dataset sizes here are
    small enough that clarity matters more than squeezing this into one aggregate query.
    """
    terminal_statuses = {"APPROVED", "DENIED", "PAID"}
    durations = []

    claims = claims_qs.prefetch_related("status_history")
    for claim in claims:
        history = sorted(claim.status_history.all(), key=lambda h: h.created_at)
        if not history:
            continue
        start = claim.created_at
        terminal_event = next((h for h in history if h.to_status in terminal_statuses), None)
        if terminal_event:
            durations.append((terminal_event.created_at - start).total_seconds() / 3600)

    if not durations:
        return None
    return round(sum(durations) / len(durations), 2)


class AnalyticsDashboardView(APIView):
    permission_classes = [IsManager]

    def get(self, request):
        claims = _filtered_claims(request)
        claim_ids = list(claims.values_list("id", flat=True))

        total_claims_received = claims.count()

        claims_by_status = list(claims.values("status").annotate(count=Count("id")).order_by("-count"))

        claims_approved_by_date = _status_events_by_date("APPROVED", claim_ids)
        claims_denied_by_date = _status_events_by_date("DENIED", claim_ids)
        claims_pended_by_date = _status_events_by_date("PENDED", claim_ids)

        claims_pending_approval = claims.filter(status="PENDING_APPROVAL").count()

        payments = Payment.objects.filter(claim_id__in=claim_ids, status=Payment.Status.PAID)
        payment_volume = payments.count()
        payment_amount_total = payments.aggregate(total=Sum("amount"))["total"] or 0
        payment_amount_by_period = list(
            payments.annotate(period=TruncMonth("executed_at"))
            .values("period")
            .annotate(total=Sum("amount"))
            .order_by("period")
        )

        provider_analysis = list(
            claims.values("provider__provider_id", "provider__name")
            .annotate(
                claim_count=Count("id"),
                total_billed=Sum("total_claim_amount"),
                total_approved=Sum("total_approved_amount"),
            )
            .order_by("-claim_count")
        )

        member_analysis = list(
            claims.values("member__member_id", "member__name")
            .annotate(
                claim_count=Count("id"),
                total_billed=Sum("total_claim_amount"),
                total_approved=Sum("total_approved_amount"),
            )
            .order_by("-claim_count")
        )

        avg_turnaround_hours = _avg_turnaround_hours(claims)

        return Response({
            "total_claims_received": total_claims_received,
            "claims_by_status": claims_by_status,
            "claims_approved_by_date": claims_approved_by_date,
            "claims_denied_by_date": claims_denied_by_date,
            "claims_pended_by_date": claims_pended_by_date,
            "claims_pending_approval": claims_pending_approval,
            "payment_volume": payment_volume,
            "payment_amount_total": payment_amount_total,
            "payment_amount_by_period": payment_amount_by_period,
            "provider_analysis": provider_analysis,
            "member_analysis": member_analysis,
            "avg_turnaround_hours": avg_turnaround_hours,
        })