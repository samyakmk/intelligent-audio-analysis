from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.domain import (
    BudgetExceeded,
    BudgetReservationUnavailable,
    _cost_once,
    commit_budget,
    release_budget,
    reserve_budget,
    settle_interrupted_budget,
)
from app.models import BudgetReservation, CostEvent, Workspace

from .conftest import login, mutation_headers
from .test_security_lifecycle import fixture_recording_id


def test_canonical_workspace_monthly_budget_environment_name(monkeypatch) -> None:
    monkeypatch.setenv("MAX_AI_SPEND_PER_WORKSPACE_MONTH_USD", "12.34")
    assert Settings.from_environment().workspace_monthly_cost_ceiling_usd == 12.34


def test_inline_sweeper_interval_is_configurable(monkeypatch) -> None:
    monkeypatch.setenv("SWEEPER_INTERVAL_SECONDS", "17.5")
    assert Settings.from_environment().sweeper_interval_seconds == 17.5


def test_budget_reservation_is_idempotent_and_enforces_both_caps(
    client: TestClient,
) -> None:
    login(client)
    with client.app.state.database.session_factory() as db:
        workspace = db.get(Workspace, "workspace-alpha")
        workspace.monthly_spend_limit_usd = 1.0
        db.commit()

        first = reserve_budget(
            db,
            attempt_id="budget-attempt-a",
            workspace_id=workspace.id,
            stage="speech",
            amount_usd=0.4,
            per_request_cap_usd=0.5,
        )
        replay = reserve_budget(
            db,
            attempt_id="budget-attempt-a",
            workspace_id=workspace.id,
            stage="speech",
            amount_usd=0.4,
            per_request_cap_usd=0.5,
        )
        assert replay.id == first.id
        with pytest.raises(ValueError, match="different parameters"):
            reserve_budget(
                db,
                attempt_id="budget-attempt-a",
                workspace_id=workspace.id,
                stage="intelligence",
                amount_usd=0.4,
                per_request_cap_usd=0.5,
            )
        with pytest.raises(BudgetExceeded) as request_error:
            reserve_budget(
                db,
                attempt_id="over-request-cap",
                workspace_id=workspace.id,
                stage="speech",
                amount_usd=0.6,
                per_request_cap_usd=0.5,
            )
        assert request_error.value.code == "request_budget_exceeded"

        reserve_budget(
            db,
            attempt_id="budget-attempt-b",
            workspace_id=workspace.id,
            stage="intelligence",
            amount_usd=0.6,
            per_request_cap_usd=0.6,
        )
        with pytest.raises(BudgetExceeded) as monthly_error:
            reserve_budget(
                db,
                attempt_id="over-monthly-cap",
                workspace_id=workspace.id,
                stage="ask",
                amount_usd=0.01,
                per_request_cap_usd=0.1,
            )
        assert monthly_error.value.code == "workspace_monthly_budget_exceeded"

        assert release_budget(db, attempt_id="budget-attempt-a").status == "released"
        committed = commit_budget(db, attempt_id="budget-attempt-b", actual_usd=0.5)
        assert committed.status == "committed"
        assert commit_budget(db, attempt_id="budget-attempt-b", actual_usd=0.5).id == committed.id
        with pytest.raises(ValueError, match="cannot be released"):
            release_budget(db, attempt_id="budget-attempt-b")
        db.commit()

        reserve_budget(
            db,
            attempt_id="budget-attempt-c",
            workspace_id=workspace.id,
            stage="ask",
            amount_usd=0.5,
            per_request_cap_usd=0.5,
        )
        db.commit()


def test_committed_reservation_hands_off_to_append_only_cost_ledger(
    client: TestClient,
) -> None:
    login(client)
    with client.app.state.database.session_factory() as db:
        reservation = reserve_budget(
            db,
            attempt_id="ledger-handoff",
            workspace_id="workspace-alpha",
            stage="speech",
            amount_usd=0.25,
            per_request_cap_usd=0.25,
        )
        _cost_once(
            db,
            attempt_id=reservation.attempt_id,
            workspace_id=reservation.workspace_id,
            recording_id=None,
            stage=reservation.stage,
            provider="mock.test",
            model_alias="mock",
            resolved_model="mock-v1",
            usage={"units": 1},
            estimated=0.25,
            provenance={"mock": True},
        )
        _cost_once(
            db,
            attempt_id=reservation.attempt_id,
            workspace_id=reservation.workspace_id,
            recording_id=None,
            stage=reservation.stage,
            provider="mock.test",
            model_alias="mock",
            resolved_model="mock-v1",
            usage={"units": 1},
            estimated=0.25,
            provenance={"mock": True},
        )
        commit_budget(db, attempt_id=reservation.attempt_id, actual_usd=0.25)
        db.commit()
        assert (
            db.scalar(
                select(func.count())
                .select_from(CostEvent)
                .where(CostEvent.attempt_id == "ledger-handoff")
            )
            == 1
        )


def test_interrupted_budget_settlement_is_idempotent_and_preserves_ambiguous_spend(
    client: TestClient,
) -> None:
    login(client)
    with client.app.state.database.session_factory() as db:
        workspace = db.get(Workspace, "workspace-alpha")
        workspace.monthly_spend_limit_usd = 1.0
        db.commit()

        ambiguous = reserve_budget(
            db,
            attempt_id="ambiguous-provider-attempt",
            workspace_id=workspace.id,
            stage="speech",
            amount_usd=0.6,
            per_request_cap_usd=0.6,
        )
        db.commit()
        settle_interrupted_budget(
            db,
            attempt_id=ambiguous.attempt_id,
            provider_dispatched=True,
            reason="lost_provider_response",
        )
        settle_interrupted_budget(
            db,
            attempt_id=ambiguous.attempt_id,
            provider_dispatched=False,
            reason="replayed_cleanup",
        )
        assert ambiguous.status == "reconciliation_pending"
        assert ambiguous.release_reason == "ambiguous_provider_outcome:lost_provider_response"
        with pytest.raises(
            BudgetReservationUnavailable, match="must be reconciled before retrying"
        ):
            reserve_budget(
                db,
                attempt_id=ambiguous.attempt_id,
                workspace_id=workspace.id,
                stage="speech",
                amount_usd=0.6,
                per_request_cap_usd=0.6,
            )

        not_dispatched = reserve_budget(
            db,
            attempt_id="pre-dispatch-failure",
            workspace_id=workspace.id,
            stage="intelligence",
            amount_usd=0.3,
            per_request_cap_usd=0.3,
        )
        settle_interrupted_budget(
            db,
            attempt_id=not_dispatched.attempt_id,
            provider_dispatched=False,
            reason="adapter_not_called",
        )
        settle_interrupted_budget(
            db,
            attempt_id=not_dispatched.attempt_id,
            provider_dispatched=False,
            reason="replayed_cleanup",
        )
        assert not_dispatched.status == "released"
        assert not_dispatched.release_reason == "adapter_not_called"
        with pytest.raises(BudgetReservationUnavailable, match="same identity"):
            reserve_budget(
                db,
                attempt_id=not_dispatched.attempt_id,
                workspace_id=workspace.id,
                stage="intelligence",
                amount_usd=0.3,
                per_request_cap_usd=0.3,
            )

        zero_cost = reserve_budget(
            db,
            attempt_id="zero-cost-retry",
            workspace_id=workspace.id,
            stage="regenerate_intelligence",
            amount_usd=0.0,
            per_request_cap_usd=0.1,
        )
        release_budget(db, attempt_id=zero_cost.attempt_id, reason="fixture_failure")
        replay = reserve_budget(
            db,
            attempt_id=zero_cost.attempt_id,
            workspace_id=workspace.id,
            stage="regenerate_intelligence",
            amount_usd=0.0,
            per_request_cap_usd=0.1,
        )
        assert replay.id == zero_cost.id
        assert replay.status == "reserved"
        assert replay.release_reason is None

        with pytest.raises(BudgetExceeded) as monthly_error:
            reserve_budget(
                db,
                attempt_id="blocked-by-ambiguous-spend",
                workspace_id=workspace.id,
                stage="ask",
                amount_usd=0.41,
                per_request_cap_usd=0.5,
            )
        assert monthly_error.value.code == "workspace_monthly_budget_exceeded"
        db.commit()


def test_zero_cost_ask_uses_committed_reservation_and_replay_is_free(
    client: TestClient,
) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)
    ask_session = client.post(
        "/v1/ask-sessions",
        json={"scope": {"type": "recording", "recording_id": recording_id}},
        headers=mutation_headers(csrf, "budget-ask-session"),
    ).json()
    headers = mutation_headers(csrf, "budget-ask-message")
    first = client.post(
        f"/v1/ask-sessions/{ask_session['id']}/messages",
        json={"content": "What was decided?"},
        headers=headers,
    )
    replay = client.post(
        f"/v1/ask-sessions/{ask_session['id']}/messages",
        json={"content": "What was decided?"},
        headers=headers,
    )
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    with client.app.state.database.session_factory() as db:
        rows = db.scalars(
            select(BudgetReservation).where(BudgetReservation.ask_session_id == ask_session["id"])
        ).all()
        assert len(rows) == 1
        assert rows[0].status == "committed"
        assert rows[0].reserved_usd == rows[0].committed_usd == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(CostEvent)
                .where(CostEvent.attempt_id == rows[0].attempt_id)
            )
            == 1
        )
