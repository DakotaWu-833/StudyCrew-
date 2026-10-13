"""Read-only project questions, with explicit retrieval and generation states."""
import re

from django.core.exceptions import ValidationError

from . import providers
from .policies import require_project
from .retrieval import rank
from .sources import corpus, unchanged


def capabilities(user, project_id):
    require_project(user, project_id)
    try:
        configured = providers.configuration()
    except providers.ProviderUnavailable:
        configured = None
    return {"generation_available": bool(configured), "provider": configured["provider"] if configured else "disabled",
            "source_types": ["files", "meeting_notes"], "supported_files": ["txt", "csv", "pdf", "docx"],
            "max_question_length": 1000, "retrieval": "bm25",
            "notice": ("Answers use project excerpts. Check the cited originals; citations do not guarantee correctness."
                       if configured else "Search project sources now. AI answers will be available after a model is configured.")}


def _retrieve(user, project_id, question, max_sources):
    if not isinstance(question, str):
        raise ValidationError("Use a text question.")
    question = question.strip()
    if not question or len(question) > 1000 or type(max_sources) is not int or not 1 <= max_sources <= 6:
        raise ValidationError("Use a question of 1–1000 characters and 1–6 sources.")
    current, project = require_project(user, project_id)
    rows, warnings, limited = corpus(current, project)
    selected = rank(question, rows, max_sources)
    _recheck(user, project_id, selected)
    result = {"question": question, "sources": [{key: value for key, value in row.items() if not key.startswith("_")}
                                               for row in selected],
              "warnings": warnings, "retrieval": "bm25", "limited": limited}
    return result, selected


def _recheck(user, project_id, rows):
    _, project = require_project(user, project_id)
    if not unchanged(project, rows):
        raise ValidationError("Project sources changed while answering. Please ask again.")


def search(user, project_id, question, max_sources=5):
    result, _ = _retrieve(user, project_id, question, max_sources)
    return result


def ask(user, project_id, question, max_sources=5):
    result, selected = _retrieve(user, project_id, question, max_sources)
    result.update(answer=None, status="no_evidence", model=None)
    if not selected:
        return result
    try:
        configured = providers.configuration()
    except providers.ProviderUnavailable:
        configured = None
    if not configured:
        result["status"] = "model_unavailable"
        return result
    # Authorization and source currency have been checked immediately before egress.
    try:
        answer = providers.generate(result["question"], result["sources"])
    except providers.ProviderUnavailable:
        _recheck(user, project_id, selected)
        result["status"] = "model_unavailable"
        result["warnings"].append("The model service is unavailable. You can still read the matching project sources.")
        return result
    _recheck(user, project_id, selected)
    cited = set(re.findall(r"\[(S\d+)\]", answer)) if isinstance(answer, str) else set()
    allowed = {row["citation"] for row in selected}
    if not cited or not cited <= allowed or len(answer) > 8000:
        result["status"] = "unverified_answer"
        result["warnings"].append("The model did not provide valid source citations. Its answer was withheld; read the sources instead.")
        return result
    result.update(answer=answer, status="answered", model=configured["model"])
    return result
