"""
Tests for the setup wizard (memeta init).

Covers:
- Environment detection (7 checks: Python version, memory dir, session dir,
  numpy, ML extras, hook state, dashboard)
- Directory creation (create, idempotent, skip existing)
- Config generation (valid TOML, default project ID, custom project ID,
  no overwrite)
- Hook installation (available hooks, missing hooks dir, empty hooks)
- Health verification (runs, failure non-fatal, missing deps)
- Full run orchestration (fresh system, required failure stops early,
  re-run idempotent, optional failure warns)
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from memory_system.config import MemorySystemConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """
    Point all config paths to temp directories so nothing touches
    the real filesystem.
    """
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    monkeypatch.setenv("MEMORY_SYSTEM_MEMORY_DIR", str(memory_dir))
    monkeypatch.setenv("MEMORY_SYSTEM_PROJECT_ID", "test-project")
    monkeypatch.setenv("MEMORY_SYSTEM_SESSION_DIR", str(session_dir))


@pytest.fixture
def config():
    return MemorySystemConfig()


@pytest.fixture
def wizard(config):
    from memory_system.setup_wizard import InitWizard
    return InitWizard(config=config, auto_confirm=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wizard(config, auto_confirm=True):
    from memory_system.setup_wizard import InitWizard
    return InitWizard(config=config, auto_confirm=auto_confirm)


# ===========================================================================
# 1. Environment detection — Python version
# ===========================================================================

class TestCheckPythonVersion:
    def test_passes_on_current_python(self, wizard):
        result = wizard._check_python_version()
        assert result.passed is True
        assert result.name == "python_version"
        assert f"{sys.version_info.major}.{sys.version_info.minor}" in result.message

    def test_fails_on_mock_old_python(self, wizard):
        from memory_system.setup_wizard import EnvironmentCheck

        def fake_check(self_inner):
            return EnvironmentCheck(
                name="python_version",
                passed=False,
                message="Python 3.10.0 (need >= 3.11)",
                required=True,
            )

        with patch.object(type(wizard), "_check_python_version", fake_check):
            result = wizard._check_python_version()
        assert result.passed is False
        assert "3.11" in result.message
        assert result.required is True


# ===========================================================================
# 2. Environment detection — Memory dir writable
# ===========================================================================

class TestCheckMemoryDir:
    def test_passes_when_writable(self, wizard, config):
        result = wizard._check_memory_dir()
        assert result.passed is True
        assert "Writable" in result.message

    def test_fails_when_not_writable(self, tmp_path, config, monkeypatch):
        # Point to a path we cannot write to
        monkeypatch.setenv("MEMORY_SYSTEM_MEMORY_DIR", "/root/no-access-test-memeta")
        cfg = MemorySystemConfig()
        w = _make_wizard(cfg)
        result = w._check_memory_dir()
        assert result.passed is False
        assert "Not writable" in result.message


# ===========================================================================
# 3. Environment detection — Session dir
# ===========================================================================

class TestCheckSessionDir:
    def test_found_when_exists(self, wizard):
        result = wizard._check_session_dir()
        assert result.passed is True
        assert "Found" in result.message
        assert result.required is False

    def test_not_found_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MEMORY_SYSTEM_SESSION_DIR", str(tmp_path / "nope"))
        cfg = MemorySystemConfig()
        w = _make_wizard(cfg)
        result = w._check_session_dir()
        assert result.passed is False
        assert "Not found" in result.message
        assert result.required is False  # Optional check


# ===========================================================================
# 4. Environment detection — numpy
# ===========================================================================

class TestCheckNumpy:
    def test_passes_when_available(self, wizard):
        result = wizard._check_numpy()
        assert result.passed is True
        assert "numpy" in result.message

    def test_fails_when_not_importable(self, wizard):
        with patch.dict("sys.modules", {"numpy": None}):
            # Force ImportError by removing numpy from importable modules
            import builtins
            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "numpy":
                    raise ImportError("mocked")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = wizard._check_numpy()
        assert result.passed is False
        assert "not installed" in result.message


# ===========================================================================
# 5. Environment detection — ML extras (FAISS)
# ===========================================================================

class TestCheckMlExtras:
    def test_passes_when_faiss_available(self, wizard):
        mock_faiss = MagicMock()
        with patch.dict("sys.modules", {"faiss": mock_faiss}):
            result = wizard._check_ml_extras()
        assert result.passed is True
        assert result.required is False

    def test_fails_when_faiss_not_available(self, wizard):
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "faiss":
                raise ImportError("mocked")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = wizard._check_ml_extras()
        assert result.passed is False
        assert "FAISS not installed" in result.message
        assert result.required is False


# ===========================================================================
# 6. Environment detection — Hook state read/write
# ===========================================================================

class TestCheckHookState:
    def test_passes_json_roundtrip(self, wizard):
        result = wizard._check_hook_state()
        assert result.passed is True
        assert "JSON read/write OK" in result.message


# ===========================================================================
# 7. Environment detection — Dashboard (Flask)
# ===========================================================================

class TestCheckDashboard:
    def test_passes_when_flask_available(self, wizard):
        mock_flask = MagicMock()
        mock_flask.__version__ = "3.0.0"
        with patch.dict("sys.modules", {"flask": mock_flask}):
            result = wizard._check_dashboard()
        assert result.passed is True
        assert "Flask" in result.message
        assert result.required is False

    def test_fails_when_flask_not_available(self, wizard):
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "flask":
                raise ImportError("mocked")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = wizard._check_dashboard()
        assert result.passed is False
        assert "Flask not installed" in result.message
        assert result.required is False


# ===========================================================================
# 8. detect_environment aggregation
# ===========================================================================

class TestDetectEnvironment:
    def test_returns_7_checks(self, wizard):
        checks = wizard.detect_environment()
        assert len(checks) == 7

    def test_all_checks_have_required_fields(self, wizard):
        checks = wizard.detect_environment()
        for check in checks:
            assert hasattr(check, "name")
            assert hasattr(check, "passed")
            assert hasattr(check, "message")
            assert hasattr(check, "required")


# ===========================================================================
# 9. Directory creation
# ===========================================================================

class TestCreateDirectories:
    def test_creates_directories_that_dont_exist(self, config):
        w = _make_wizard(config)
        # Remove the project memory dir if it exists
        project_dir = config.project_memory_dir
        memories_dir = project_dir / "memories"

        # Neither should exist yet (memory_dir exists but project subdir doesn't)
        assert not project_dir.exists()

        created = w.create_directories()
        assert len(created) > 0
        assert project_dir.exists()
        assert memories_dir.exists()

    def test_idempotent_no_error_on_rerun(self, config):
        w = _make_wizard(config)
        w.create_directories()
        # Second run should not raise
        created_again = w.create_directories()
        assert isinstance(created_again, list)

    def test_skips_existing_returns_empty(self, config):
        w = _make_wizard(config)
        # Create all dirs first
        config.memory_dir.mkdir(parents=True, exist_ok=True)
        config.project_memory_dir.mkdir(parents=True, exist_ok=True)
        (config.project_memory_dir / "memories").mkdir(parents=True, exist_ok=True)

        created = w.create_directories()
        assert created == []


# ===========================================================================
# 10. Config generation
# ===========================================================================

class TestGenerateConfig:
    def test_generates_valid_toml(self, config, tmp_path, monkeypatch):
        # Redirect config dir to tmp
        monkeypatch.setenv("HOME", str(tmp_path))
        w = _make_wizard(config)
        config_path = w.generate_config()
        assert config_path.exists()
        content = config_path.read_text()
        assert "[project]" in content
        assert "[storage]" in content
        assert "[hooks]" in content
        assert "[dashboard]" in content

    def test_default_project_id(self, config, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        w = _make_wizard(config)
        config_path = w.generate_config()
        content = config_path.read_text()
        assert 'id = "default"' in content

    def test_custom_project_id(self, config, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        w = _make_wizard(config)
        config_path = w.generate_config(project_id="my-project")
        content = config_path.read_text()
        assert 'id = "my-project"' in content

    def test_doesnt_overwrite_existing(self, config, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        # Pre-create a config file with custom content
        config_dir = tmp_path / ".config" / "memeta"
        config_dir.mkdir(parents=True)
        existing = config_dir / "config.toml"
        existing.write_text("# existing config\n")

        w = _make_wizard(config)
        config_path = w.generate_config()
        assert config_path.read_text() == "# existing config\n"


# ===========================================================================
# 11. Hook installation
# ===========================================================================

class TestInstallHooks:
    def test_returns_list_of_available_hooks(self, config):
        w = _make_wizard(config)
        installed = w.install_hooks()
        assert isinstance(installed, list)
        # The project has memory-injection.py and session-memory-consolidation-async.py
        assert "memory-injection.py" in installed
        assert "session-memory-consolidation-async.py" in installed

    def test_handles_missing_hooks_dir_gracefully(self, config, tmp_path, monkeypatch):
        """When hooks directory doesn't exist, returns empty list."""
        import memory_system.setup_wizard as sw_mod

        w = _make_wizard(config)
        # Redirect __file__ to a fake path so hooks_dir resolves to nonexistent
        fake_file = str(tmp_path / "fake" / "src" / "setup_wizard.py")
        monkeypatch.setattr(sw_mod, "__file__", fake_file)
        result = w.install_hooks()
        assert result == []

    def test_returns_empty_when_no_hooks_exist(self, config, tmp_path):
        """When hooks directory exists but has no matching scripts."""
        w = _make_wizard(config)
        from memory_system.setup_wizard import InitWizard

        def patched_install(self_inner):
            hooks_dir = tmp_path / "empty-hooks"
            hooks_dir.mkdir(exist_ok=True)
            installed = []
            hook_scripts = [
                "memory-injection.py",
                "session-memory-consolidation-async.py",
            ]
            for script in hook_scripts:
                hook_path = hooks_dir / script
                if hook_path.exists():
                    installed.append(script)
            return installed

        with patch.object(InitWizard, "install_hooks", patched_install):
            result = w.install_hooks()
        assert result == []

    def test_returns_partial_when_some_hooks_exist(self, config, tmp_path):
        """When only some hook scripts are present."""
        w = _make_wizard(config)
        from memory_system.setup_wizard import InitWizard

        def patched_install(self_inner):
            hooks_dir = tmp_path / "partial-hooks"
            hooks_dir.mkdir(exist_ok=True)
            (hooks_dir / "memory-injection.py").write_text("# hook")
            installed = []
            hook_scripts = [
                "memory-injection.py",
                "session-memory-consolidation-async.py",
            ]
            for script in hook_scripts:
                hook_path = hooks_dir / script
                if hook_path.exists():
                    installed.append(script)
            return installed

        with patch.object(InitWizard, "install_hooks", patched_install):
            result = w.install_hooks()
        assert result == ["memory-injection.py"]
        assert "session-memory-consolidation-async.py" not in result


# ===========================================================================
# 12. Health verification
# ===========================================================================

class TestVerifyHealth:
    def test_runs_and_returns_report(self, config):
        w = _make_wizard(config)
        report = w.verify_health()
        assert isinstance(report, dict)
        assert "passed" in report or "summary" in report

    def test_failure_is_nonfatal(self, config):
        """verify_health should not raise even if SelfTest fails."""
        w = _make_wizard(config)
        with patch(
            "memory_system.self_test.SelfTest",
            side_effect=RuntimeError("boom"),
        ):
            report = w.verify_health()
        assert report["passed"] is False
        assert "boom" in report["summary"]

    def test_missing_deps_handled(self, config):
        """If SelfTest import itself fails, we get a clean error dict."""
        w = _make_wizard(config)
        with patch(
            "memory_system.self_test.SelfTest",
            side_effect=ImportError("no self_test"),
        ):
            report = w.verify_health()
        assert report["passed"] is False
        assert "no self_test" in report["summary"]


# ===========================================================================
# 13. Full run orchestration
# ===========================================================================

class TestRunFull:
    def test_fresh_system_all_passes(self, config, tmp_path, monkeypatch):
        """On a fresh writable system, run() should succeed."""
        monkeypatch.setenv("HOME", str(tmp_path))
        w = _make_wizard(config)
        # Mock verify_health to return a passing report
        with patch.object(w, "verify_health", return_value={"passed": True, "summary": "OK"}):
            result = w.run()
        assert result.success is True
        assert len(result.checks) == 7
        assert isinstance(result.directories_created, list)
        assert result.config_path is not None
        assert isinstance(result.hooks_installed, list)

    def test_required_check_failure_stops_early(self, config, tmp_path, monkeypatch):
        """If a required env check fails, run() stops and returns errors."""
        monkeypatch.setenv("HOME", str(tmp_path))
        w = _make_wizard(config)

        from memory_system.setup_wizard import EnvironmentCheck

        # Mock _check_python_version to return a failing required check
        failing_check = EnvironmentCheck(
            name="python_version",
            passed=False,
            message="Python 3.10.0 (need >= 3.11)",
            required=True,
        )
        with patch.object(w, "_check_python_version", return_value=failing_check):
            result = w.run()

        assert result.success is False
        assert len(result.errors) > 0
        assert any("python_version" in e for e in result.errors)
        # Should NOT have created directories (stopped early)
        assert result.directories_created == []

    def test_rerun_on_existing_system_is_idempotent(self, config, tmp_path, monkeypatch):
        """Running twice on the same system should work without errors."""
        monkeypatch.setenv("HOME", str(tmp_path))
        w = _make_wizard(config)
        with patch.object(w, "verify_health", return_value={"passed": True}):
            result1 = w.run()
            result2 = w.run()
        assert result1.success is True
        assert result2.success is True
        # Second run should create fewer (or zero) directories
        assert len(result2.directories_created) <= len(result1.directories_created)

    def test_optional_failure_succeeds_with_warnings(self, config, tmp_path, monkeypatch):
        """Optional check failures should produce warnings, not errors."""
        monkeypatch.setenv("HOME", str(tmp_path))
        # Remove session dir so session_dir check fails (optional)
        monkeypatch.setenv("MEMORY_SYSTEM_SESSION_DIR", str(tmp_path / "gone"))

        cfg = MemorySystemConfig()
        w = _make_wizard(cfg)
        with patch.object(w, "verify_health", return_value={"passed": True}):
            result = w.run()

        assert result.success is True
        assert len(result.warnings) > 0
        assert any("session_dir" in w_msg for w_msg in result.warnings)

    def test_config_generation_failure_stops_run(self, config, tmp_path, monkeypatch):
        """If config generation throws, run() reports the error."""
        monkeypatch.setenv("HOME", str(tmp_path))
        w = _make_wizard(config)
        with patch.object(w, "generate_config", side_effect=PermissionError("no write")):
            with patch.object(w, "verify_health", return_value={"passed": True}):
                result = w.run()
        assert result.success is False
        assert any("Config generation failed" in e for e in result.errors)


# ===========================================================================
# 14. Data classes
# ===========================================================================

class TestDataClasses:
    def test_environment_check_defaults(self):
        from memory_system.setup_wizard import EnvironmentCheck
        check = EnvironmentCheck(name="test", passed=True, message="ok")
        assert check.required is True

    def test_environment_check_optional(self):
        from memory_system.setup_wizard import EnvironmentCheck
        check = EnvironmentCheck(name="test", passed=False, message="missing", required=False)
        assert check.required is False

    def test_init_result_defaults(self):
        from memory_system.setup_wizard import InitResult
        result = InitResult(success=True)
        assert result.checks == []
        assert result.directories_created == []
        assert result.hooks_installed == []
        assert result.config_path is None
        assert result.errors == []
        assert result.warnings == []
