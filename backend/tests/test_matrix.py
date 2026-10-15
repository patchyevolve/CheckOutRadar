"""Unit tests for Matrix Expansion."""

import pytest
from app.db import crud, connection
from app.matrix.orchestrator import expand_matrix


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_matrix.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(test_db))
    connection.init_db()


def test_expand_matrix_quick_preset():
    audit_id = crud.create_audit(input_url="http://test.com", merchant="Test", preset="quick")
    conditions = expand_matrix(audit_id, preset="quick")

    assert len(conditions) == 4
    # 1 reference
    ref_count = sum(1 for c in conditions if c["is_reference"])
    assert ref_count == 1

    # Check stable keys
    keys = [c["condition_key"] for c in conditions]
    assert "pin:110001|sess:fresh|cart:above_threshold" in keys
    assert "pin:560001|sess:fresh|cart:above_threshold" in keys
    assert "pin:492001|sess:fresh|cart:above_threshold" in keys
    assert "pin:110001|sess:fresh|cart:below_threshold" in keys


def test_expand_matrix_full_preset():
    audit_id = crud.create_audit(input_url="http://test.com", merchant="Test", preset="full")
    conditions = expand_matrix(audit_id, preset="full")

    # 3 pincodes x 2 sessions x 2 tiers = 12 runs
    assert len(conditions) == 12
    ref_count = sum(1 for c in conditions if c["is_reference"])
    assert ref_count == 1


def test_expand_matrix_single_preset():
    audit_id = crud.create_audit(input_url="http://test.com", merchant="Test", preset="single")
    conditions = expand_matrix(audit_id, preset="single")

    assert len(conditions) == 1
    assert conditions[0]["is_reference"] is True
    assert conditions[0]["condition_key"] == "pin:110001|sess:fresh|cart:above_threshold"
