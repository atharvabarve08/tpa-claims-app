"""
claims/urls.py — routes for the Claims List / Detail / Approval endpoints.

Wire this into your project's main urls.py (see setup steps below):
    path('api/', include('claims.urls'))
"""

from django.urls import path

from .views import (
    MeView, IngestClaimView, IngestEDI837View, ClaimRiskScoreView, ClaimListView, ClaimDetailView, ApproveClaimView, DenyClaimView, PendClaimView,
    SubmitForPaymentApprovalView, ApprovePaymentView, HoldPaymentView, SchedulePaymentView,
    RetryClaimView, EditClaimView,
)
from .analytics import AnalyticsDashboardView

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("claims/ingest/", IngestClaimView.as_view(), name="claim-ingest"),
    path("claims/ingest-edi837/", IngestEDI837View.as_view(), name="claim-ingest-edi837"),
    path("claims/", ClaimListView.as_view(), name="claim-list"),
    path("claims/<int:pk>/", ClaimDetailView.as_view(), name="claim-detail"),
    path("claims/<int:pk>/risk-score/", ClaimRiskScoreView.as_view(), name="claim-risk-score"),
    path("claims/<int:pk>/retry/", RetryClaimView.as_view(), name="claim-retry"),
    path("claims/<int:pk>/edit/", EditClaimView.as_view(), name="claim-edit"),
    path("claims/<int:pk>/approve/", ApproveClaimView.as_view(), name="claim-approve"),
    path("claims/<int:pk>/deny/", DenyClaimView.as_view(), name="claim-deny"),
    path("claims/<int:pk>/pend/", PendClaimView.as_view(), name="claim-pend"),

    # Stage 5: Payment
    path("claims/<int:pk>/submit-payment-approval/", SubmitForPaymentApprovalView.as_view(), name="claim-submit-payment-approval"),
    path("claims/<int:pk>/approve-payment/", ApprovePaymentView.as_view(), name="claim-approve-payment"),
    path("claims/<int:pk>/hold-payment/", HoldPaymentView.as_view(), name="claim-hold-payment"),
    path("claims/<int:pk>/schedule-payment/", SchedulePaymentView.as_view(), name="claim-schedule-payment"),

    # Stage 6: Analytics
    path("analytics/dashboard/", AnalyticsDashboardView.as_view(), name="analytics-dashboard"),
]