from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes
from rest_framework.views import APIView
from rest_framework.response import Response
from accounts.policies import require_site_moderator
from projects.models import Project
from projects.policies import require_project_member, is_project_manager
from .models import ProjectPost, PostReply, PostReport
from .discussion_services import save_post, add_reply, remove_content, report_content, moderate_report
from .discussion_serializers import PostInput, ReplyInput, ReportInput, RemoveInput, ModerationInput
from django.core.paginator import Paginator
from django.db.models import Prefetch


def reply_row(reply, post, actor):
    return {"id": str(reply.pk), "author": identity(reply.author),
        "body": reply.body if not reply.removed_at and not post.removed_at else "",
        "removed_at": reply.removed_at, "created_at": reply.created_at,
        "can_remove": actor.pk == reply.author_id or is_project_manager(actor, post.project)}


def identity(user):
    return {"id": str(user.pk), "display_name": user.profile.display_name}


def post_row(post, actor):
    manager = is_project_manager(actor, post.project)
    replies = getattr(post, "initial_replies", None)
    if replies is None:
        replies = list(post.replies.select_related("author__profile").order_by("created_at", "id")[:25])
    reply_count = post.replies.count()
    return {"id": str(post.pk), "project": str(post.project_id), "title": post.title if not post.removed_at else "Removed discussion",
        "body": post.body if not post.removed_at else "", "kind": post.kind, "pinned": post.pinned,
        "mention_ids": post.mention_ids, "author": identity(post.author), "created_at": post.created_at, "updated_at": post.updated_at,
        "removed_at": post.removed_at, "can_edit": actor.pk == post.author_id or manager, "manager": manager,
        "read_only": bool(post.project.archived_at),
        "replies": [reply_row(reply, post, actor) for reply in replies],
        "reply_pagination": {"page": 1, "pages": max(1, (reply_count + 24) // 25), "total": reply_count}}


def get_post(actor, identifier):
    post = get_object_or_404(ProjectPost.objects.select_related("project", "author__profile"), pk=identifier)
    require_project_member(actor, post.project)
    return post


class PostsView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, project_id):
        project = get_object_or_404(Project, pk=project_id)
        require_project_member(request.user, project)
        rows = ProjectPost.objects.filter(project=project).select_related("project", "author__profile").prefetch_related(Prefetch("replies", queryset=PostReply.objects.select_related("author__profile").order_by("created_at", "id")[:25], to_attr="initial_replies"))
        page = Paginator(rows, 15).get_page(request.query_params.get("page", 1))
        return Response({"results": [post_row(row, request.user) for row in page], "page": page.number,
                         "pages": page.paginator.num_pages, "total": page.paginator.count})

    @extend_schema(request=PostInput, responses={201: OpenApiTypes.OBJECT})
    def post(self, request, project_id):
        project = get_object_or_404(Project, pk=project_id)
        serializer = PostInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(post_row(save_post(request.user, project, serializer.validated_data), request.user), status=201)


class PostView(APIView):
    @extend_schema(request=PostInput, responses=OpenApiTypes.OBJECT)
    def patch(self, request, identifier):
        post = get_post(request.user, identifier)
        serializer = PostInput(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(post_row(save_post(request.user, post.project, serializer.validated_data, post), request.user))


class PostRepliesView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, identifier):
        post = get_post(request.user, identifier)
        page = Paginator(post.replies.select_related("author__profile").order_by("created_at", "id"), 25).get_page(request.query_params.get("page", 1))
        return Response({"results": [reply_row(row, post, request.user) for row in page], "page": page.number,
                         "pages": page.paginator.num_pages, "total": page.paginator.count})

    @extend_schema(request=ReplyInput, responses={201: OpenApiTypes.OBJECT})
    def post(self, request, identifier):
        post = get_post(request.user, identifier)
        serializer = ReplyInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        reply = add_reply(request.user, post, serializer.validated_data)
        return Response({"id": reply.pk}, status=201)


class PostRemoveView(APIView):
    @extend_schema(request=RemoveInput, responses={204: None})
    def post(self, request, identifier):
        post = get_post(request.user, identifier)
        serializer = RemoveInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        reply_id = serializer.validated_data.get("reply_id")
        reply = get_object_or_404(PostReply, pk=reply_id, post=post) if reply_id else None
        remove_content(request.user, post, reply)
        return Response(status=204)


class PostReportView(APIView):
    @extend_schema(request=ReportInput, responses={201: OpenApiTypes.OBJECT})
    def post(self, request, identifier):
        post = get_post(request.user, identifier)
        serializer = ReportInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        reply_id = serializer.validated_data.get("reply_id")
        reply = get_object_or_404(PostReply, pk=reply_id, post=post) if reply_id else None
        report = report_content(request.user, post, serializer.validated_data["reason"], reply)
        return Response({"id": report.pk, "ticket_id": report.ticket_id, "detail": "Track this report in Help and feedback."}, status=201)


class PostReportsView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        require_site_moderator(request.user)
        page = Paginator(PostReport.objects.select_related("post", "ticket").order_by("-created_at", "-id"), 25).get_page(request.query_params.get("page", 1))
        return Response({"results": [{"id": row.pk, "ticket_id": row.ticket_id, "title": row.post.title,
            "snapshot": row.snapshot, "description": row.ticket.description, "status": row.ticket.status,
            "resolution": row.ticket.resolution, "created_at": row.created_at} for row in page],
            "page": page.number, "pages": page.paginator.num_pages, "total": page.paginator.count})


class PostModerateView(APIView):
    @extend_schema(request=ModerationInput, responses=OpenApiTypes.OBJECT)
    def post(self, request, identifier):
        require_site_moderator(request.user)
        serializer = ModerationInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = get_object_or_404(PostReport, pk=identifier)
        moderate_report(request.user, report, **serializer.validated_data)
        return Response({"detail": "Report resolved with a recorded reason."})
