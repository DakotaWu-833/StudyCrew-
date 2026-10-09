from rest_framework.decorators import api_view
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from . import selectors as sel, serializers as inp, services as svc
from .recommendations import recommendations as recommended_listings


def validated(request, serializer, *, partial=False):
    value = serializer(data=request.data, partial=partial)
    value.is_valid(raise_exception=True)
    return value.validated_data


@extend_schema(parameters=[OpenApiParameter("projects_page", int), OpenApiParameter("mine_page", int), OpenApiParameter("applications_page", int)], responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def overview(request):
    return Response(sel.overview(user=request.user, params=request.GET))


@extend_schema(parameters=[inp.RecommendationPreferences, OpenApiParameter("page", int)], responses=OpenApiTypes.OBJECT, operation_id="recruiting_recommendations_list")
@api_view(["GET"])
def recommendations(request):
    preferences = inp.RecommendationPreferences(data=request.GET)
    preferences.is_valid(raise_exception=True)
    response = Response(recommended_listings(user=request.user, overrides=preferences.validated_data, page=request.GET.get("page", 1)))
    response["Cache-Control"] = "private, no-store"
    return response


@extend_schema(parameters=[OpenApiParameter("q", str), OpenApiParameter("course", str), OpenApiParameter("university", str), OpenApiParameter("skill", str), OpenApiParameter("cooperation", str), OpenApiParameter("saved", bool), OpenApiParameter("page", int)], request=inp.RecruitmentInput, responses=OpenApiTypes.OBJECT)
@extend_schema(methods=["GET"], operation_id="recruiting_listings_list")
@api_view(["GET", "POST"])
def listings(request):
    if request.method == "GET": return Response(sel.listings(user=request.user, params=request.GET))
    row = svc.publish(actor=request.user, data=validated(request, inp.RecruitmentInput))
    return Response(sel.detail(user=request.user, listing_id=row.pk), status=201)


@extend_schema(request=inp.RecruitmentEdit, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "PATCH"])
def detail(request, listing_id):
    if request.method == "PATCH": svc.edit(actor=request.user, listing_id=listing_id, data=validated(request, inp.RecruitmentEdit, partial=True))
    return Response(sel.detail(user=request.user, listing_id=listing_id))


@extend_schema(request=None, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def close(request, listing_id):
    svc.change_state(actor=request.user, listing_id=listing_id)
    return Response(sel.detail(user=request.user, listing_id=listing_id))


@extend_schema(request=None, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def reopen(request, listing_id):
    svc.change_state(actor=request.user, listing_id=listing_id, reopen=True)
    return Response(sel.detail(user=request.user, listing_id=listing_id))


@extend_schema(request=inp.ApplicationInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
def apply(request, listing_id):
    row = svc.apply(actor=request.user, listing_id=listing_id, **validated(request, inp.ApplicationInput))
    return Response(sel.application_row(row, request.user), status=201)


@extend_schema(parameters=[OpenApiParameter("page", int)], responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def applications(request, listing_id):
    return Response(sel.applications(user=request.user, listing_id=listing_id, page=request.GET.get("page", 1)))


@extend_schema(request=inp.DecisionInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def decision(request, application_id):
    row = svc.decide(actor=request.user, application_id=application_id, **validated(request, inp.DecisionInput))
    return Response(sel.application_row(row, request.user, include_card=False))


@extend_schema(request=None, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def withdraw(request, application_id):
    row = svc.withdraw(actor=request.user, application_id=application_id)
    return Response(sel.application_row(row, request.user))


@extend_schema(request=None, responses={204: None})
@api_view(["POST", "DELETE"])
def bookmark(request, listing_id):
    svc.bookmark(actor=request.user, listing_id=listing_id, save=request.method == "POST")
    return Response(status=204)


@extend_schema(request=inp.ReportInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
def report(request, listing_id):
    row = svc.report(actor=request.user, listing_id=listing_id, **validated(request, inp.ReportInput))
    return Response({"id": row.pk, "status": row.status}, status=201)


@extend_schema(parameters=[OpenApiParameter("page", int)], responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def reports(request):
    return Response(sel.reports(user=request.user, page=request.GET.get("page", 1)))


@extend_schema(request=inp.ModerationInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def resolve_report(request, report_id):
    row = svc.moderate(actor=request.user, report_id=report_id, **validated(request, inp.ModerationInput))
    return Response(sel.report_row(row))

