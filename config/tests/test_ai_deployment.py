"""Source-level AI deployment guards; no downloads, model calls or Docker runs."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "deployment/ai"
SCRIPTS = (ROOT / "scripts/Setup-StudyCrewAI.ps1", ROOT / "scripts/Start-StudyCrewAI.ps1")


class AIDeploymentSourceTests(SimpleTestCase):
    def setUp(self):
        self.setup = SCRIPTS[0].read_text(encoding="utf-8")
        self.start = SCRIPTS[1].read_text(encoding="utf-8")
        self.compose = (PACK / "compose.yaml").read_text(encoding="utf-8")
        self.dockerfile = (PACK / "Dockerfile").read_text(encoding="utf-8")
        self.guide = (PACK / "README.md").read_text(encoding="utf-8")

    def test_model_download_is_pinned_to_official_release_and_checksum(self):
        expected_sha = "e5ecff02dfc7cae8ddf6d6b7a7ac5f727ffeedf4491f44ae75ff5b0820dbbbd5"
        self.assertIn(expected_sha, self.setup)
        self.assertIn("https://api.github.com/repos/ollama/ollama/releases/tags/v0.40.3", self.setup)
        self.assertIn("https://github.com/ollama/ollama/releases/download/v0.40.3/ollama-windows-amd64.zip", self.setup)
        self.assertIn(".digest -ne", self.setup)
        self.assertGreaterEqual(self.setup.count("Get-FileHash -LiteralPath"), 2)
        self.assertLess(self.setup.index("Get-FileHash -LiteralPath $aiSetupArchive"), self.setup.index("ExtractToDirectory"))
        self.assertNotIn("latest/download", self.setup)
        self.assertNotRegex(self.dockerfile, r"(?i)FROM\s+\S+:latest\b")
        self.assertIn("FROM ollama/ollama:0.40.3", self.dockerfile)

    def test_native_runtime_and_model_blobs_use_workspace_drive(self):
        for source in (self.setup, self.start):
            self.assertIn("'var\\ai'", source)
            self.assertRegex(source, r"(?m)^\s*\$env:OLLAMA_MODELS = \$ai(?:Setup|Start)Models$")
            self.assertNotRegex(source, r"(?i)C:\\.*(?:models|ollama)")
            self.assertNotRegex(source, r"(?i)\$env:(?:HOME|USERPROFILE)\s*=")
        self.assertIn("ollama-v0.40.3\\ollama.exe", self.start)
        self.assertIn("Its model-store drive is unknown", self.setup)
        self.assertIn("No models will be pulled", self.setup)

    def test_model_services_reject_network_listeners_and_use_only_loopback(self):
        for source in (self.setup, self.start):
            self.assertIn("GetActiveTcpListeners()", source)
            self.assertIn("[Net.IPAddress]::IsLoopback", source)
            self.assertIn("$env:OLLAMA_HOST = '127.0.0.1:11434'", source)
            self.assertNotIn("0.0.0.0", source)
            self.assertIn("-NoProxy -MaximumRedirection 0", source)
        self.assertIn("runserver', \"127.0.0.1:$Port\"", self.start)

    def test_native_cleanup_uses_owned_process_objects_and_process_only_environment(self):
        for source in (self.setup, self.start):
            self.assertIn(".Kill($true)", source)
            self.assertIn(".Dispose()", source)
            self.assertIn("SetEnvironmentVariable", source)
            self.assertNotRegex(source, r"(?i)\b(?:Stop-Process|taskkill|setx|New-Service|Register-ScheduledTask)\b")
            self.assertNotRegex(source, r"(?i)SetEnvironmentVariable\([^\n]*['\"](?:User|Machine)['\"]")
            self.assertNotRegex(source, r"(?im)^\s*\$HOME\s*=")
        self.assertIn("$aiStartOwned += $aiStartModelProcess", self.start)
        self.assertIn("$aiStartOwned += $aiStartApplication", self.start)
        self.assertIn("$aiStartOwned += $aiStartWorker", self.start)
        self.assertIn("$aiStartProcess = $aiStartOwned[$aiStartIndex]", self.start)

    def test_setup_checks_extraction_and_cleanup_boundaries_before_recursive_operations(self):
        self.assertIn("$aiSetupAbsolute.StartsWith($aiSetupBoundary", self.setup)
        self.assertIn("FileAttributes]::ReparsePoint", self.setup)
        self.assertIn("$aiSetupEntryPath.StartsWith($aiSetupStageBoundary", self.setup)
        self.assertIn("$aiSetupEntryType -eq 0xA000", self.setup)
        self.assertRegex(self.setup, r"Assert-AISetupPath \$aiSetupStage[^\n]*\n\s*Assert-AISetupPath \$aiSetupRuntime[^\n]*\n\s*Move-Item -LiteralPath")
        self.assertRegex(self.setup, r"\$aiSetupCleanup = Assert-AISetupPath \$aiSetupStage\s+Remove-Item -LiteralPath \$aiSetupCleanup -Recurse")

    def test_startup_uses_explicit_local_models_and_synthetic_warmup(self):
        for source in (self.setup, self.start):
            self.assertIn("'qwen3.5:9b-q4_K_M'", source)
            self.assertIn("'qwen3-embedding:0.6b'", source)
            self.assertIn("think = $false", source)
            self.assertIn("num_ctx = 8192", source)
            self.assertIn("num_predict = 16", source)
            self.assertIn("Reply only READY.", source)
            self.assertIn("/api/embed", source)
            self.assertIn("$env:OLLAMA_NO_CLOUD = 'true'", source)
            self.assertIn("$env:OLLAMA_NOHISTORY = 'true'", source)
            self.assertIn("$env:OLLAMA_DEBUG_LOG_REQUESTS = 'false'", source)
            self.assertIn("$env:OLLAMA_NUM_PARALLEL = '1'", source)
        for setting, value in (("RAG_RETRIEVAL_MODE", "hybrid"), ("RAG_DISABLE_THINKING", "true"),
                               ("RAG_NUM_CTX", "8192"), ("RAG_MAX_OUTPUT_TOKENS", "1200")):
            self.assertIn(f"$env:{setting} = '{value}'", self.start)
        self.assertIn("$env:DJANGO_DEBUG = 'false'", self.start)

    def test_docker_inference_has_only_loopback_port_and_internal_network(self):
        published = re.findall(r'(?m)^\s+- "(.*11434.*)"$', self.compose)
        self.assertEqual(published, ["127.0.0.1:11434:11434"])
        self.assertRegex(self.compose, r"inference:\s+internal: true")
        self.assertIn("capabilities: [gpu]", self.compose)
        self.assertIn("driver: nvidia", self.compose)
        self.assertEqual(self.compose.count("read_only: true"), 2)
        self.assertEqual(self.compose.count("no-new-privileges:true"), 2)
        self.assertIn("cap_drop: [ALL]", self.compose)
        self.assertIn("OLLAMA_MODEL_DIR:?", self.compose)
        self.assertNotIn("privileged: true", self.compose)

    def test_provisioning_has_separate_egress_without_publishing_an_api(self):
        provisioning = self.compose.split("  model-download:", 1)[1].split("\nnetworks:", 1)[0]
        self.assertIn("profiles: [setup]", provisioning)
        self.assertIn("- downloads", provisioning)
        self.assertNotIn("ports:", provisioning)
        self.assertIn("OLLAMA_HOST: 127.0.0.1:11434", provisioning)
        helper = (PACK / "provision-models.sh").read_text(encoding="utf-8")
        self.assertIn("model_server_pid=$!", helper)
        self.assertIn('kill "$model_server_pid"', helper)
        self.assertNotRegex(helper, r"\b(?:pkill|killall)\b")
        attributes = (PACK / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.sh text eol=lf", attributes)

    def test_image_context_does_not_copy_application_secrets_or_private_data(self):
        self.assertIn("context: .", self.compose)
        copies = re.findall(r"(?m)^COPY\s+(.+)$", self.dockerfile)
        self.assertEqual(copies, ["provision-models.sh /provision-models.sh"])
        self.assertNotIn(".env", self.dockerfile)
        self.assertNotIn("/var", self.dockerfile)
        self.assertNotIn("DB_PASSWORD", self.compose)
        self.assertNotIn("EMAIL_HOST_PASSWORD", self.compose)

    def test_ai_env_overlay_does_not_weaken_existing_production_guards(self):
        overlay = (PACK / "studycrew-ai.env.example").read_text(encoding="utf-8")
        names = re.findall(r"(?m)^([A-Z_]+)=", overlay)
        self.assertTrue(names)
        self.assertTrue(all(name.startswith("RAG_") for name in names))
        for instruction in ("deploy/postgresql/permissions.sql", "deployment/postgresql/launch-permissions.sql",
                            "deployment/uwsgi-privacy.ini", "SMTP", "TLS", "required malware scanning"):
            self.assertIn(instruction, self.guide)
        self.assertIn("not pgvector", self.guide)
        self.assertIn("not evidence", self.guide)
        self.assertIn("No local Docker/NVIDIA-container test", self.guide)

    def test_powershell_parser_accepts_scripts_and_all_helpers_start_hidden(self):
        powershell = shutil.which("pwsh")
        if not powershell:
            self.skipTest("PowerShell 7 is needed for AST-only script verification.")
        checker = r'''
param([string]$RepositoryRoot)
$reports = foreach ($file in @('Setup-StudyCrewAI.ps1', 'Start-StudyCrewAI.ps1')) {
    $tokens = $null; $errors = $null
    $tree = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $RepositoryRoot "scripts/$file"), [ref]$tokens, [ref]$errors)
    $processCommands = @($tree.FindAll({ param($node) $node -is [System.Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'Start-Process' }, $true) | ForEach-Object { $_.Extent.Text })
    @{ file = $file; errors = @($errors | ForEach-Object Message); process_commands = $processCommands }
}
ConvertTo-Json -InputObject @($reports) -Depth 5 -Compress
'''
        with tempfile.TemporaryDirectory() as temporary:
            helper = Path(temporary) / "parse-ai-scripts.ps1"
            helper.write_text(checker, encoding="utf-8")
            result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-File", str(helper), str(ROOT)],
                                    capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        reports = json.loads(result.stdout)
        self.assertEqual(len(reports), 2)
        counts = {"Setup-StudyCrewAI.ps1": 1, "Start-StudyCrewAI.ps1": 3}
        for report in reports:
            with self.subTest(script=report["file"]):
                self.assertEqual(report["errors"], [])
                self.assertEqual(len(report["process_commands"]), counts[report["file"]])
                for command in report["process_commands"]:
                    self.assertIn("-WindowStyle Hidden", command)
                    self.assertIn("-PassThru", command)
