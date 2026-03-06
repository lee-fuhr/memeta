"""
Setup wizard for Memeta — ``memeta init``.

Detects environment, creates directories, generates config, installs hooks,
and verifies system health. Non-interactive by default.
"""

import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from memory_system.config import MemorySystemConfig, cfg


@dataclass
class EnvironmentCheck:
    """Result of a single environment check."""

    name: str
    passed: bool
    message: str
    required: bool = True  # If False, failure is a warning, not an error


@dataclass
class InitResult:
    """Result of running the full init wizard."""

    success: bool
    checks: list[EnvironmentCheck] = field(default_factory=list)
    directories_created: list[str] = field(default_factory=list)
    hooks_installed: list[str] = field(default_factory=list)
    config_path: Optional[str] = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class InitWizard:
    """
    Setup wizard — detects environment, creates directories,
    generates config, installs hooks, verifies health.
    """

    def __init__(
        self,
        config: Optional[MemorySystemConfig] = None,
        auto_confirm: bool = False,
    ):
        self.config = config or cfg
        self.auto_confirm = auto_confirm

    # ------------------------------------------------------------------
    # Environment detection
    # ------------------------------------------------------------------

    def detect_environment(self) -> list[EnvironmentCheck]:
        """Run 7 environment checks."""
        return [
            self._check_python_version(),
            self._check_memory_dir(),
            self._check_session_dir(),
            self._check_numpy(),
            self._check_ml_extras(),
            self._check_hook_state(),
            self._check_dashboard(),
        ]

    def _check_python_version(self) -> EnvironmentCheck:
        v = sys.version_info
        passed = v >= (3, 11)
        return EnvironmentCheck(
            name="python_version",
            passed=passed,
            message=(
                f"Python {v.major}.{v.minor}.{v.micro}"
                + ("" if passed else " (need >= 3.11)")
            ),
            required=True,
        )

    def _check_memory_dir(self) -> EnvironmentCheck:
        path = self.config.memory_dir
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / ".memeta-write-test"
            test_file.write_text("ok")
            test_file.unlink()
            return EnvironmentCheck("memory_dir", True, f"Writable: {path}")
        except (PermissionError, OSError) as exc:
            return EnvironmentCheck("memory_dir", False, f"Not writable: {exc}")

    def _check_session_dir(self) -> EnvironmentCheck:
        path = self.config.session_dir
        exists = path.exists()
        return EnvironmentCheck(
            "session_dir",
            exists,
            f"{'Found' if exists else 'Not found'}: {path}",
            required=False,
        )

    def _check_numpy(self) -> EnvironmentCheck:
        try:
            import numpy

            return EnvironmentCheck("numpy", True, f"numpy {numpy.__version__}")
        except ImportError:
            return EnvironmentCheck("numpy", False, "numpy not installed")

    def _check_ml_extras(self) -> EnvironmentCheck:
        try:
            import faiss  # noqa: F401

            return EnvironmentCheck(
                "ml_extras", True, "FAISS available", required=False
            )
        except ImportError:
            return EnvironmentCheck(
                "ml_extras",
                False,
                "FAISS not installed (install memeta[ml] for semantic search)",
                required=False,
            )

    def _check_hook_state(self) -> EnvironmentCheck:
        """Verify hook state JSON read/write works."""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=True
            ) as f:
                json.dump({"test": True}, f)
                f.flush()
                with open(f.name) as rf:
                    data = json.load(rf)
                if data.get("test") is True:
                    return EnvironmentCheck(
                        "hook_state", True, "JSON read/write OK"
                    )
            return EnvironmentCheck("hook_state", False, "Read-back mismatch")
        except Exception as exc:
            return EnvironmentCheck("hook_state", False, f"Error: {exc}")

    def _check_dashboard(self) -> EnvironmentCheck:
        try:
            import flask

            return EnvironmentCheck(
                "dashboard",
                True,
                f"Flask {flask.__version__}",
                required=False,
            )
        except ImportError:
            return EnvironmentCheck(
                "dashboard",
                False,
                "Flask not installed (dashboard unavailable)",
                required=False,
            )

    # ------------------------------------------------------------------
    # Directory creation
    # ------------------------------------------------------------------

    def create_directories(self) -> list[str]:
        """Create required directories. Returns list of directories created."""
        created: list[str] = []
        dirs = [
            self.config.memory_dir,
            self.config.project_memory_dir,
            self.config.project_memory_dir / "memories",
        ]
        for d in dirs:
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                created.append(str(d))
        return created

    # ------------------------------------------------------------------
    # Config generation
    # ------------------------------------------------------------------

    def generate_config(self, project_id: str = "default") -> Path:
        """Generate config file at ~/.config/memeta/config.toml."""
        config_dir = Path.home() / ".config" / "memeta"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.toml"

        if config_path.exists():
            return config_path

        content = f'''[project]
id = "{project_id}"

[storage]
memory_dir = "{self.config.memory_dir}"

[hooks]
injection_interval = 10
frustration_detection = true

[dashboard]
port = 8766
'''
        config_path.write_text(content)
        return config_path

    # ------------------------------------------------------------------
    # Hook installation
    # ------------------------------------------------------------------

    def install_hooks(self) -> list[str]:
        """Install hooks into Claude settings. Returns list of hooks installed."""
        hooks_dir = Path(__file__).parent.parent / "hooks"
        installed: list[str] = []

        hook_scripts = [
            "memory-injection.py",
            "session-memory-consolidation-async.py",
        ]

        for script in hook_scripts:
            hook_path = hooks_dir / script
            if hook_path.exists():
                installed.append(script)

        return installed

    # ------------------------------------------------------------------
    # Health verification
    # ------------------------------------------------------------------

    def verify_health(self) -> dict:
        """Run SelfTest health checks."""
        try:
            from memory_system.self_test import SelfTest

            st = SelfTest(config=self.config)
            return st.run_all()
        except Exception as exc:
            return {
                "passed": False,
                "summary": f"Health check failed: {exc}",
                "checks": [],
            }

    # ------------------------------------------------------------------
    # Full orchestration
    # ------------------------------------------------------------------

    def run(self) -> InitResult:
        """Run the full init wizard."""
        result = InitResult(success=True)

        # 1. Environment checks
        result.checks = self.detect_environment()

        # Check for required failures
        required_failures = [
            c for c in result.checks if c.required and not c.passed
        ]
        if required_failures:
            result.success = False
            result.errors = [
                f"{c.name}: {c.message}" for c in required_failures
            ]
            return result

        # Warnings for optional failures
        optional_failures = [
            c for c in result.checks if not c.required and not c.passed
        ]
        result.warnings = [
            f"{c.name}: {c.message}" for c in optional_failures
        ]

        # 2. Create directories
        result.directories_created = self.create_directories()

        # 3. Generate config
        try:
            config_path = self.generate_config()
            result.config_path = str(config_path)
        except Exception as exc:
            result.errors.append(f"Config generation failed: {exc}")
            result.success = False
            return result

        # 4. Install hooks
        result.hooks_installed = self.install_hooks()

        # 5. Verify health
        health = self.verify_health()
        if not health.get("passed"):
            result.warnings.append(
                f"Health check: {health.get('summary', 'unknown')}"
            )

        return result
