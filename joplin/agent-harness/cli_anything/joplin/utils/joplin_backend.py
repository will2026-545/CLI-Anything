import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class BackendConfig:
    binary: str = "joplin"
    profile: Optional[str] = None


def find_joplin(binary: str = "joplin") -> str:
    path = shutil.which(binary)
    if path:
        return path
    raise RuntimeError(
        "Joplin terminal binary not found in PATH. Install Joplin CLI and ensure `joplin` is executable."
    )


_BENIGN_NODE_WARNING_MARKERS = (
    ("dep0040", "punycode"),
    ("dep0169", "url.parse"),
)


def _line_is_benign_node_warning(line: str) -> bool:
    """Return True for Node.js deprecation warnings that Joplin emits on stderr.

    These warnings are emitted on every invocation by Node 20+ when Joplin's
    dependencies still use the deprecated builtin modules. They never indicate
    a real Joplin failure, but they are noisy on stderr.
    """
    lowered = line.lower()
    if "deprecationwarning" not in lowered and "experimentalwarning" not in lowered:
        return False
    return any(all(marker in lowered for marker in markers) for markers in _BENIGN_NODE_WARNING_MARKERS)


def _strip_benign_node_warnings(text: str) -> str:
    """Drop benign Node warning lines while preserving any real diagnostic text."""
    if not text:
        return ""
    kept = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _line_is_benign_node_warning(line):
            continue
        kept.append(raw_line)
    return "\n".join(kept).strip()


def run_joplin_command(args: list[str], config: BackendConfig, timeout: int = 120) -> dict:
    binary = find_joplin(config.binary)
    cmd = [binary]
    if config.profile:
        cmd += ["--profile", config.profile]
    cmd += args

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Joplin command timed out after {timeout}s") from e

    stdout_raw = proc.stdout or ""
    stderr_raw = proc.stderr or ""
    stdout = _strip_benign_node_warnings(stdout_raw)
    stderr = _strip_benign_node_warnings(stderr_raw)

    result = {
        "command": cmd,
        "returncode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }

    if proc.returncode != 0:
        # After stripping known-benign Node warnings, anything left on stderr or
        # stdout is a real Joplin error and must surface as a failure. We only
        # treat the exit as success when there is no remaining diagnostic text.
        if stderr or stdout:
            raise RuntimeError(stderr or stdout)

    return result


def run_joplin_json(args: list[str], config: BackendConfig, timeout: int = 120) -> dict:
    command_args = args if "--format" in args or "-f" in args else args + ["--format", "json"]
    raw = run_joplin_command(command_args, config, timeout=timeout)
    text = raw["stdout"]
    if not text:
        return {"raw": raw, "data": None}

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {"text": text}

    return {"raw": raw, "data": data}
