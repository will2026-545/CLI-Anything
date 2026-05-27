"""Wire-format tests for cli_anything.browser.utils.domshell_backend.

These tests patch the async ``_call_execute`` helper and assert the exact
command string sent to the DOMShell ``domshell_execute`` tool, so wire-format
regressions (quoting, command names, multi-line layout, restore ordering)
fail loudly.
"""

import pytest
from unittest.mock import AsyncMock, call, patch

from cli_anything.browser.utils import domshell_backend as backend


# ── grep: command string and call sequencing ──────────────────────────


@patch.object(backend, "_call_execute", new_callable=AsyncMock)
def test_grep_unrooted_produces_single_grep_call(mock_call):
    """Unrooted grep dispatches one ``grep <pattern>`` call."""
    mock_call.return_value = {}

    backend.grep("Login")

    assert mock_call.call_args_list == [call("grep Login", False)]


@patch.object(backend, "_call_execute", new_callable=AsyncMock)
def test_grep_rooted_produces_three_calls_in_order(mock_call):
    """Rooted grep dispatches cd → grep → cd-back, in that order."""
    mock_call.return_value = {}

    backend.grep("Login", path="/main", prev="/")

    assert mock_call.call_args_list == [
        call("cd /main", False),
        call("grep Login", False),
        call("cd /", False),
    ]


@patch.object(backend, "_call_execute", new_callable=AsyncMock)
def test_grep_rooted_restores_cwd_when_grep_raises(mock_call):
    """If grep errors mid-flight, the trailing cd-back still runs (try/finally)."""
    mock_call.side_effect = [
        {},                            # cd /main → success
        RuntimeError("grep blew up"),  # grep → raise
        {},                            # cd / (restore) — required
    ]

    with pytest.raises(RuntimeError, match="grep blew up"):
        backend.grep("Login", path="/main", prev="/")

    assert mock_call.call_count == 3
    assert mock_call.call_args_list[-1] == call("cd /", False)


@patch.object(backend, "_call_execute", new_callable=AsyncMock)
def test_grep_rooted_short_circuits_when_cd_errors(mock_call):
    """If the initial cd reports an error, grep is skipped and no restore is sent."""
    mock_call.return_value = {"isError": True, "error": "no such path"}

    result = backend.grep("Login", path="/missing", prev="/")

    # Only the initial cd ran; grep + restore were skipped.
    assert mock_call.call_args_list == [call("cd /missing", False)]
    assert result == {"isError": True, "error": "no such path"}


@patch.object(backend, "_call_execute", new_callable=AsyncMock)
def test_grep_rooted_quotes_path_with_spaces(mock_call):
    """Paths with whitespace are shell-quoted before interpolation."""
    mock_call.return_value = {}

    backend.grep("Login", path="/path with spaces", prev="/")

    cd_cmd = mock_call.call_args_list[0].args[0]
    # shlex.quote single-quotes anything containing whitespace.
    assert cd_cmd == "cd '/path with spaces'"


@patch.object(backend, "_call_execute", new_callable=AsyncMock)
def test_grep_pattern_with_shell_metacharacters_quoted(mock_call):
    """Patterns with shell metacharacters get quoted (no injection via grep)."""
    mock_call.return_value = {}

    backend.grep("$(rm -rf /)")

    grep_cmd = mock_call.call_args_list[0].args[0]
    # shlex.quote will single-quote the dangerous payload.
    assert grep_cmd == "grep '$(rm -rf /)'"


def test_grep_rejects_positional_path():
    """grep(pattern, path) — positional path raises TypeError.

    Pre-migration callers writing ``grep("Login", True)`` to mean
    ``use_daemon=True`` must not silently get ``path=True``.
    """
    with pytest.raises(TypeError):
        backend.grep("Login", True)  # type: ignore[misc]


def test_grep_rejects_positional_use_daemon():
    """Even the third positional slot is blocked."""
    with pytest.raises(TypeError):
        backend.grep("Login", "/main", "/", True)  # type: ignore[misc]


def test_grep_keyword_use_daemon_still_works():
    """Keyword call against the new signature still type-checks at call time."""
    with patch.object(backend, "_call_execute", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = {}
        backend.grep("Login", use_daemon=True)
        assert mock_call.call_args_list == [call("grep Login", True)]


# ── type_text: focus+type pairing and newline injection guard ─────────


@patch.object(backend, "_call_execute", new_callable=AsyncMock)
def test_type_text_emits_focus_then_type_in_one_call(mock_call):
    """type_text builds a single multi-line ``focus … \\ntype …`` execute call."""
    mock_call.return_value = {}

    backend.type_text("search_input", "machine learning")

    assert mock_call.call_args_list == [
        call("focus search_input\ntype 'machine learning'", False),
    ]


def test_type_text_rejects_newline_in_text():
    """``\\n`` in text would inject a new DOMShell command — must raise."""
    with pytest.raises(ValueError, match="newline"):
        backend.type_text("search_input", "line1\nline2")


def test_type_text_rejects_carriage_return_in_text():
    """``\\r`` is just as dangerous as ``\\n`` for DOMShell's line splitter."""
    with pytest.raises(ValueError, match="newline"):
        backend.type_text("search_input", "line1\rline2")


def test_type_text_rejects_newline_in_path():
    """A newline in the path argument also injects — guard both fields."""
    with pytest.raises(ValueError, match="newline"):
        backend.type_text("input\nclick /admin", "anything")


# ── grep: newline guard on rooted multi-step path ─────────────────────


def test_grep_rejects_newline_in_path():
    """Rooted grep interpolates path into a multi-line cd/grep/cd — reject newlines."""
    with pytest.raises(ValueError, match="newline"):
        backend.grep("Login", path="/main\nclick /admin", prev="/")


def test_grep_rejects_newline_in_pattern():
    with pytest.raises(ValueError, match="newline"):
        backend.grep("Login\nclick /admin", path="/main", prev="/")


def test_grep_rejects_newline_in_prev():
    with pytest.raises(ValueError, match="newline"):
        backend.grep("Login", path="/main", prev="/\nclick /admin")
