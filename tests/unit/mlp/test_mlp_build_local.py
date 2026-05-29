"""Tests for local predeploy build helpers."""

from __future__ import annotations

from pathlib import Path

from service.build.local import _find_docker_socket, _load_dotenv


def test_load_dotenv_parses_key_value_pairs(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('MLP_API_KEY="mlp-test-key"\nSUPABASE_URL=https://supabase.example.com\n')
    result = _load_dotenv(env_file)
    assert result == {
        "MLP_API_KEY": "mlp-test-key",
        "SUPABASE_URL": "https://supabase.example.com",
    }


def test_load_dotenv_skips_comments_and_blanks(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\n\nKEY=value\n")
    result = _load_dotenv(env_file)
    assert result == {"KEY": "value"}


def test_load_dotenv_returns_empty_for_missing_file(tmp_path: Path) -> None:
    result = _load_dotenv(tmp_path / "nonexistent")
    assert result == {}


def test_find_docker_socket_prefers_user_socket_over_system_socket(
    monkeypatch, tmp_path: Path
) -> None:
    user_socket = tmp_path / ".docker" / "run" / "docker.sock"
    user_socket.parent.mkdir(parents=True)
    user_socket.touch()

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert _find_docker_socket() == f"unix://{user_socket}"
