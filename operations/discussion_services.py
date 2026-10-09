"""Private project discussions, explicit mentions and support-backed moderation."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.policies import require_site_moderator
from projects.models import ProjectMembership
from projects.policies import require_project_member, require_project_manager, is_project_manager
from .models import ProjectPost, PostReply, PostReport, OperationAudit, UserBlock
from .services import consume_rate, create_ticket, resolve_ticket, _scheduled_alert


def write_access(actor, project):
    require_project_member(actor, project)
    if project.archived_at:
        raise ValidationError("Archived project discussions are read-only.")
    if not consume_rate("discussion-write", str(actor.pk), limit=40, seconds=3600):
        raise ValidationError("Please wait before posting again.")


def mentions_for(actor, project, identifiers):
    identifiers = {str(value) for value in identifiers}
    members = list(ProjectMembership.objects.active().filter(project=project, user__is_active=True).select_related("user__profile"))
    valid = {str(row.user_id) for row in members}
    if not identifiers <= valid:
        raise ValidationError({"mention_ids": "Mention only current members of this project."})
    return [row.user for row in members if str(row.user_id) in identifiers and row.user_id != actor.pk]


def notify(actor, post, source, users):
    for user in users:
        if UserBlock.objects.filter(user=user, blocked=actor).exists():
            continue
        _scheduled_alert(user=user, project=post.project, category="comment_mention",
            title=f"{actor.profile.display_name} mentioned you"[:200],
            body=f"Open {post.title} to read the project discussion.",
            path=f"/app/projects/{post.project_id}/updates/", key=f"post-mention:{source.pk}:{source.updated_at.isoformat()}:{user.pk}",
            target_type="post_reply" if isinstance(source, PostReply) else "post",
            target_id=source.pk, revision=source.updated_at.isoformat())


@transaction.atomic
def save_post(actor, project, values, post=None):
    write_access(actor, project)
    if post:
        post = ProjectPost.objects.select_for_update().get(pk=post.pk, project=project)
        if post.removed_at:
            raise ValidationError("This discussion has been removed.")
        expected = values.pop("expected_updated_at", None)
        if expected != post.updated_at:
            raise ValidationError("This discussion changed. Reload it before saving your edit.")
        manager = is_project_manager(actor, project)
        if post.author_id != actor.pk and not manager:
            raise PermissionDenied("Only the author or a project manager can edit this discussion.")
        if "pinned" in values and values["pinned"] != post.pinned:
            require_project_manager(actor, project)
    else:
        post = ProjectPost(project=project, author=actor)
    if values.get("kind", post.kind) == "announcement" or values.get("pinned", post.pinned):
        require_project_manager(actor, project)
    users = mentions_for(actor, project, values.get("mention_ids", post.mention_ids))
    for key, value in values.items():
        setattr(post, key, [str(item) for item in value] if key == "mention_ids" else value)
    post.full_clean()
    post.save()
    notify(actor, post, post, users)
    OperationAudit.objects.create(actor=actor, action="project_post_saved", target_id=post.pk, metadata={"project": str(project.pk)})
    return post


@transaction.atomic
def add_reply(actor, post, values):
    write_access(actor, post.project)
    post = ProjectPost.objects.select_for_update().get(pk=post.pk)
    if post.removed_at:
        raise ValidationError("This discussion has been removed.")
    users = mentions_for(actor, post.project, values.get("mention_ids", []))
    reply = PostReply(post=post, author=actor, body=values["body"], mention_ids=[str(user.pk) for user in users])
    reply.full_clean()
    reply.save()
    notify(actor, post, reply, users)
    return reply


@transaction.atomic
def remove_content(actor, post, reply=None):
    write_access(actor, post.project)
    source = PostReply.objects.select_for_update().get(pk=reply.pk, post=post) if reply else ProjectPost.objects.select_for_update().get(pk=post.pk)
    if source.author_id != actor.pk:
        require_project_manager(actor, post.project)
    if source.removed_at:
        raise ValidationError("This content is already removed.")
    source.removed_at = timezone.now()
    source.save(update_fields=["removed_at", "updated_at"])
    OperationAudit.objects.create(actor=actor, action="project_content_removed", target_id=source.pk, metadata={"project": str(post.project_id)})


@transaction.atomic
def report_content(actor, post, reason, reply=None):
    require_project_member(actor, post.project)
    if reply and reply.post_id != post.pk:
        raise ValidationError("This reply belongs to another discussion.")
    source = reply or post
    if source.removed_at:
        raise ValidationError("This content has already been removed.")
    snapshot = f"{post.title}\n{source.body}"[:2200]
    ticket = create_ticket(actor, {"category": "appeal", "subject": f"Project content report: {post.title}"[:160],
        "description": f"Report reason: {reason}\n\nReported content (retained for review):\n{snapshot}\n\nProject: {post.project_id}; discussion: {post.pk}"[:4000]})
    return PostReport.objects.create(post=post, reply=reply, ticket=ticket, snapshot=snapshot)


@transaction.atomic
def moderate_report(actor, report, hide, reason):
    require_site_moderator(actor)
    report = PostReport.objects.select_for_update().select_related("post__author", "reply", "ticket").get(pk=report.pk)
    if report.ticket.status == "resolved":
        raise ValidationError("This report is already resolved.")
    if hide:
        source = report.reply or report.post
        source.removed_at = timezone.now()
        source.save(update_fields=["removed_at", "updated_at"])
    resolve_ticket(actor, report.ticket, {"status": "resolved", "resolution": reason})
    OperationAudit.objects.create(actor=actor, action="project_report_resolved", target_id=report.pk,
                                  metadata={"hidden": hide, "reason": reason})
    return report
