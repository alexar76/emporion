"""The namespace changes without replacing an installed signer's identity or state."""

from pathlib import Path

import pytest
from oracle_core.signing import Signer

from symmartys.capabilities import Runtime, build_spec
from symmartys.config import setting, signing_key_path


@pytest.fixture(autouse=True)
def clean_identity_settings(monkeypatch):
    for name in ("SYMMARTYS_SIGNING_KEY_PATH", "EMPORION_SIGNING_KEY_PATH",
                 "SYMMARTYS_STATE_DIR", "EMPORION_STATE_DIR"):
        monkeypatch.delenv(name, raising=False)


def test_new_setting_takes_precedence_and_explicit_empty_values_do_not_revive_legacy(monkeypatch):
    monkeypatch.setenv("EMPORION_CORS_ORIGINS", "https://old.example")
    monkeypatch.setenv("SYMMARTYS_CORS_ORIGINS", "")
    assert setting("CORS_ORIGINS", "fallback") == ""


def test_legacy_configuration_is_supported_with_a_warning_without_logging_values(monkeypatch, caplog):
    monkeypatch.setenv("EMPORION_PUBLIC_URL", "https://private-configuration.example")
    assert setting("PUBLIC_URL") == "https://private-configuration.example"
    assert "EMPORION_PUBLIC_URL" in caplog.text and "SYMMARTYS_PUBLIC_URL" in caplog.text
    assert "private-configuration" not in caplog.text


def test_explicit_legacy_signing_path_is_retained(monkeypatch, tmp_path, caplog):
    existing = tmp_path / "existing-key"
    monkeypatch.setenv("EMPORION_SIGNING_KEY_PATH", str(existing))
    assert signing_key_path() == existing
    assert "legacy configuration" in caplog.text
    chosen = tmp_path / "chosen-key"
    monkeypatch.setenv("SYMMARTYS_SIGNING_KEY_PATH", str(chosen))
    assert signing_key_path() == chosen


def test_existing_key_and_mldsa_companion_files_survive_the_rename(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("SYMMARTYS_STATE_DIR", str(tmp_path))
    legacy = tmp_path / "emporion_signing_key"
    original = Signer(legacy, pqc=True)
    saved = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    spec = build_spec(Runtime())
    assert Path(spec.signing_key_path) == legacy
    migrated = Signer(spec.signing_key_path, pqc=True)
    assert migrated.public_key_b64 == original.public_key_b64
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == saved
    assert not (tmp_path / "symmartys_signing_key").exists()
    assert "Reusing the existing legacy signing key" in caplog.text


def test_two_default_keys_require_an_explicit_operator_choice(monkeypatch, tmp_path):
    monkeypatch.setenv("SYMMARTYS_STATE_DIR", str(tmp_path))
    (tmp_path / "emporion_signing_key").touch()
    current = tmp_path / "symmartys_signing_key"
    current.touch()
    with pytest.raises(ValueError, match="Both current and legacy signing keys"):
        signing_key_path()
    monkeypatch.setenv("SYMMARTYS_SIGNING_KEY_PATH", str(current))
    assert signing_key_path() == current


def test_empty_explicit_key_path_is_refused(monkeypatch):
    monkeypatch.setenv("SYMMARTYS_SIGNING_KEY_PATH", "")
    with pytest.raises(ValueError, match="must name a signing key file"):
        signing_key_path()


def test_fresh_install_uses_new_key_namespace_without_creating_anything_during_resolution(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert signing_key_path() == Path("data/symmartys_signing_key")
    assert list(tmp_path.iterdir()) == []


def test_manifest_spec_uses_only_new_product_and_capability_names(monkeypatch, tmp_path):
    monkeypatch.setenv("SYMMARTYS_SIGNING_KEY_PATH", str(tmp_path / "k"))
    spec = build_spec(Runtime())
    assert spec.product_id == "symmartys" and spec.version == "0.5.0"
    assert spec.name.startswith("SYMMARTYS")
    assert len(spec.capabilities) == 16
    assert all(cap.product_id == "symmartys" and cap.capability_id.startswith("symmartys.")
               for cap in spec.capabilities)
