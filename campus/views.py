"""Thin REST adapters; existing global session/MFA/CSRF policy applies."""

from rest_framework.decorators import api_view
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiTypes, OpenApiParameter

from . import services as svc, selectors as sel
from . import serializers as inp


def validated(request, serializer):
    result = serializer(data=request.data)
    result.is_valid(raise_exception=True)
    return result.validated_data


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def overview(request):
    return Response(sel.overview(request.user))


@extend_schema(request=inp.TermInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
def terms(request):
    return Response(sel.term_row(svc.create_term(actor=request.user, **validated(request, inp.TermInput))), status=201)


@extend_schema(request=inp.CourseInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
def courses(request):
    return Response(sel.course_row(svc.create_course(actor=request.user, **validated(request, inp.CourseInput))), status=201)


@extend_schema(request=None, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def archive_term(request, term_id):
    return Response(sel.term_row(svc.archive_term(actor=request.user, term_id=term_id)))


@extend_schema(request=inp.CopyTermInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
def copy_term(request, term_id):
    data = validated(request, inp.CopyTermInput)
    term, projects = svc.copy_term(actor=request.user, term_id=term_id, year=data["year"], name=data["name"], project_ids=data["projects"])
    return Response({"term": sel.term_row(term), "projects": [{"id": p.id, "name": p.name} for p in projects]}, status=201)


@extend_schema(parameters=[OpenApiParameter("q", str), OpenApiParameter("due", str, enum=["open", "today", "week", "overdue", "all"]), OpenApiParameter("page", int)], responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def todos(request):
    return Response(sel.personal_todos(user=request.user, query=request.GET.get("q", ""), due=request.GET.get("due", "open"), page=request.GET.get("page", 1)))


@extend_schema(parameters=[OpenApiParameter("q", str), OpenApiParameter("page", int)], responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def search(request):
    return Response(sel.search(user=request.user, query=request.GET.get("q", ""), page=request.GET.get("page", 1)))


@extend_schema(request=inp.TaskCopyInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
def copy_task(request, project_id, task_id):
    task = svc.copy_task(actor=request.user, project_id=project_id, task_id=task_id, **validated(request, inp.TaskCopyInput))
    return Response({"id": task.id, "title": task.title}, status=201)


@extend_schema(request=inp.TaskBulkInput, responses=OpenApiTypes.OBJECT)
@api_view(["PATCH"])
def bulk_tasks(request, project_id):
    data = validated(request, inp.TaskBulkInput)
    ids = data.pop("tasks")
    tasks = svc.bulk_update_tasks(actor=request.user, project_id=project_id, task_ids=ids, data=data)
    return Response({"updated": len(tasks), "tasks": [task.id for task in tasks]})


@extend_schema(parameters=[OpenApiParameter("page", int)], responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def project_plan(request, project_id):
    return Response(sel.project_plan(user=request.user, project_id=project_id, page=request.GET.get("page", 1)))


@extend_schema(request=inp.CourseLinkInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
def course_link(request, project_id):
    data = validated(request, inp.CourseLinkInput)
    link = svc.link_course(actor=request.user, project_id=project_id, course_id=data["course"], term_id=data["term"])
    return Response(sel.course_link_row(link), status=201)


@extend_schema(request=None, responses={204: None})
@api_view(["DELETE"])
def unlink_course(request, project_id, link_id):
    svc.unlink_course(actor=request.user, project_id=project_id, link_id=link_id)
    return Response(status=204)


@extend_schema(request=inp.TemplateInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
def template(request, project_id):
    data = validated(request, inp.TemplateInput)
    tasks = svc.instantiate_template(actor=request.user, project_id=project_id, template_key=data["template"])
    return Response({"created": len(tasks), "tasks": [t.id for t in tasks]}, status=201)


@extend_schema(request=inp.MilestoneInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
def milestone(request, project_id):
    result = svc.save_milestone(actor=request.user, project_id=project_id, data=validated(request, inp.MilestoneInput))
    return Response(sel.milestone_row(result), status=201)


@extend_schema(request=inp.MilestoneInput, responses=OpenApiTypes.OBJECT)
@api_view(["PATCH"])
def milestone_detail(request, project_id, milestone_id):
    result = svc.save_milestone(actor=request.user, project_id=project_id, milestone_id=milestone_id, data=validated(request, inp.MilestoneInput))
    return Response(sel.milestone_row(result))


@extend_schema(request=inp.TaskPlanInput, responses=OpenApiTypes.OBJECT)
@api_view(["PATCH"])
def task_plan(request, project_id, task_id):
    svc.save_task_plan(actor=request.user, project_id=project_id, task_id=task_id, data=validated(request, inp.TaskPlanInput))
    return Response({"saved": True})


@extend_schema(request=inp.TaskCreateInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
def create_subtask(request, project_id):
    task = svc.create_subtask(actor=request.user, project_id=project_id, **validated(request, inp.TaskCreateInput))
    return Response({"id": task.id, "title": task.title}, status=201)


@extend_schema(request=None, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def request_review(request, project_id, task_id):
    svc.request_review(actor=request.user, project_id=project_id, task_id=task_id)
    return Response({"requested": True})


@extend_schema(request=inp.ReviewInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def review(request, project_id, task_id):
    svc.review_task(actor=request.user, project_id=project_id, task_id=task_id, **validated(request, inp.ReviewInput))
    return Response({"reviewed": True})


@extend_schema(request=inp.ChecklistInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
def checklist(request, project_id, task_id):
    result = svc.save_checklist(actor=request.user, project_id=project_id, task_id=task_id, data=validated(request, inp.ChecklistInput))
    return Response(sel.item_row(result), status=201)


@extend_schema(request=inp.ChecklistInput, responses=OpenApiTypes.OBJECT)
@api_view(["PATCH"])
def checklist_detail(request, project_id, task_id, item_id):
    result = svc.save_checklist(actor=request.user, project_id=project_id, task_id=task_id, item_id=item_id, data=validated(request, inp.ChecklistInput))
    return Response(sel.item_row(result))


@extend_schema(request=inp.AgreementInput, responses=OpenApiTypes.OBJECT)
@api_view(["PUT"])
def agreement(request, project_id):
    svc.save_agreement(actor=request.user, project_id=project_id, **validated(request, inp.AgreementInput))
    return Response({"saved": True})


@extend_schema(request=inp.RevisionInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def confirm_agreement(request, project_id):
    svc.confirm_agreement(actor=request.user, project_id=project_id, **validated(request, inp.RevisionInput))
    return Response({"confirmed": True})


@extend_schema(methods=["GET"], parameters=[OpenApiParameter("q", str), OpenApiParameter("tag", str), OpenApiParameter("page", int)], responses=OpenApiTypes.OBJECT)
@extend_schema(methods=["POST"], request=inp.ResourceInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["GET", "POST"])
def resources(request, project_id):
    if request.method == "GET":
        return Response(sel.resources(user=request.user, project_id=project_id, query=request.GET.get("q", ""), tag=request.GET.get("tag", ""), page=request.GET.get("page", 1)))
    result = svc.save_resource(actor=request.user, project_id=project_id, data=validated(request, inp.ResourceInput))
    return Response(sel.resource_row(result, request.user), status=201)


@extend_schema(methods=["PATCH"], request=inp.ResourceInput, responses=OpenApiTypes.OBJECT)
@extend_schema(methods=["DELETE"], request=None, responses={204: None})
@api_view(["PATCH", "DELETE"])
def resource_detail(request, project_id, resource_id):
    if request.method == "DELETE":
        svc.delete_resource(actor=request.user, project_id=project_id, resource_id=resource_id)
        return Response(status=204)
    result = svc.save_resource(actor=request.user, project_id=project_id, resource_id=resource_id, data=validated(request, inp.ResourceInput))
    return Response(sel.resource_row(result, request.user))


@extend_schema(request=inp.SubmissionInput, responses=OpenApiTypes.OBJECT)
@api_view(["PATCH"])
def submission(request, project_id):
    svc.save_submission(actor=request.user, project_id=project_id, data=validated(request, inp.SubmissionInput))
    return Response({"saved": True})


@extend_schema(request=inp.ChecklistInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
def submission_item(request, project_id):
    item = svc.save_submission_item(actor=request.user, project_id=project_id, data=validated(request, inp.ChecklistInput))
    return Response(sel.item_row(item), status=201)


@extend_schema(request=inp.ChecklistInput, responses=OpenApiTypes.OBJECT)
@api_view(["PATCH"])
def submission_item_detail(request, project_id, item_id):
    item = svc.save_submission_item(actor=request.user, project_id=project_id, item_id=item_id, data=validated(request, inp.ChecklistInput))
    return Response(sel.item_row(item))


@extend_schema(request=inp.RevisionInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def confirm_submission(request, project_id):
    svc.confirm_submission(actor=request.user, project_id=project_id, **validated(request, inp.RevisionInput))
    return Response({"confirmed": True})


@extend_schema(request=inp.ReceiptInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def receipt(request, project_id):
    svc.record_receipt(actor=request.user, project_id=project_id, **validated(request, inp.ReceiptInput))
    return Response({"recorded": True})


@extend_schema(request=inp.LeaveInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def leave(request, project_id):
    data = validated(request, inp.LeaveInput)
    svc.leave_project(actor=request.user, project_id=project_id, handover_user_id=data["handover_user"], new_owner_id=data["new_owner"])
    return Response({"left": True})


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(methods=["POST"], request=inp.JoinLinkInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["GET", "POST"])
def join_links(request, project_id):
    if request.method == "GET": return Response(sel.join_management(user=request.user, project_id=project_id))
    link, token = svc.create_join_link(actor=request.user, project_id=project_id, **validated(request, inp.JoinLinkInput))
    return Response({"id": link.id, "token": token, "expires_at": link.expires_at,
        "join_url": request.build_absolute_uri(f"/app/campus/?join={token}")}, status=201)


@extend_schema(request=None, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def revoke_join(request, project_id, link_id):
    svc.revoke_join_link(actor=request.user, project_id=project_id, link_id=link_id)
    return Response({"revoked": True})


@extend_schema(request=inp.JoinInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
def request_join(request):
    result = svc.request_join(actor=request.user, **validated(request, inp.JoinInput))
    return Response({"id": result.id, "status": result.status}, status=201)


@extend_schema(request=inp.ResolveInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def resolve_join(request, project_id, request_id):
    svc.resolve_join(actor=request.user, project_id=project_id, request_id=request_id, **validated(request, inp.ResolveInput))
    return Response({"resolved": True})
