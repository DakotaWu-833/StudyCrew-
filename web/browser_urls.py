from django.urls import path
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_GET
from pathlib import Path
from django.conf import settings
from django.shortcuts import render
import json
import re


@require_GET
def manifest(request):
    response = JsonResponse({"id": "/", "name": "StudyCrew", "short_name": "StudyCrew", "start_url": "/app/",
        "scope": "/", "display": "standalone", "background_color": "#ffffff", "theme_color": "#1d6658",
        "icons": [{"src": f"/static/workspace/pwa/icon-{size}.png", "sizes": f"{size}x{size}", "type": "image/png", "purpose": "any maskable"} for size in (192, 512)]})
    response["Cache-Control"] = "public, max-age=3600"
    return response


@require_GET
def worker(request):
    response = HttpResponse((Path(settings.BASE_DIR) / "web" / "service-worker.js").read_text(encoding="utf-8"), content_type="application/javascript")
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
def offline_shell(request):
    from web.views import _workspace_asset_version
    response = render(request, "web/offline_workspace.html", {"workspace_css_version": _workspace_asset_version("workspace.css"), "workspace_js_version": _workspace_asset_version("main.js")})
    response["Cache-Control"] = "public, max-age=0, must-revalidate"
    return response


@require_GET
def offline_assets(request):
    from web.views import _workspace_asset_version
    root = Path(settings.BASE_DIR) / "static" / "workspace"
    try:
        data = json.loads((root / ".vite" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return JsonResponse({"assets": []})
    entry = next((key for key, value in data.items() if value.get("isEntry")), None)
    offline = next((key for key in data if key.endswith("/OfflineTasksPage.tsx")), None)
    visited, files = set(), set()
    def visit(key):
        if not key or key in visited or key not in data:
            return
        visited.add(key); value = data[key]
        files.add(value["file"]); files.update(value.get("css", []))
        for child in value.get("imports", []):
            visit(child)
    visit(entry); visit(offline)
    assets = ["/offline-workspace/"]
    for filename in sorted(files):
        if not re.fullmatch(r"(?:main\.js|workspace\.css|assets/[A-Za-z0-9_.-]+\.(?:js|css))", filename):
            continue
        version = f"?v={_workspace_asset_version(filename)}" if filename in {"main.js", "workspace.css"} else ""
        assets.append(f"/static/workspace/{filename}{version}")
    return JsonResponse({"assets": assets})


urlpatterns = [path("manifest.webmanifest", manifest), path("service-worker.js", worker),
               path("offline-workspace/", offline_shell), path("offline-assets.json", offline_assets)]
