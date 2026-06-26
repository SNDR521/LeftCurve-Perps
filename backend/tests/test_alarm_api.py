"""API tests for /api/alarms (Tasks 7-8, Alarms Phase 1).

Auth note: this app uses session-cookie auth (not Bearer tokens).
The ``auth_client`` fixture logs in and maintains the session cookie
automatically via FastAPI's TestClient, so no explicit auth headers
are needed on individual requests.
"""


def test_create_list_toggle_delete_alarm(auth_client):
    r = auth_client.post("/api/alarms", json={
        "symbol": "btcusdt", "market": "CRYPTO", "condition": "CROSS_UP", "value": 72000,
    })
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    assert r.json()["symbol"] == "BTCUSDT"
    assert r.json()["status"] == "ACTIVE"

    lst = auth_client.get("/api/alarms").json()
    assert any(a["id"] == aid for a in lst)

    r = auth_client.patch(f"/api/alarms/{aid}", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    assert auth_client.delete(f"/api/alarms/{aid}").status_code == 200
    assert all(a["id"] != aid for a in auth_client.get("/api/alarms").json())


def test_bad_condition_rejected(auth_client):
    r = auth_client.post("/api/alarms", json={"symbol": "BTCUSDT", "condition": "RSI"})
    assert r.status_code == 422


def test_patch_expires_at_iso_does_not_crash(auth_client):
    r = auth_client.post("/api/alarms", json={"symbol": "BTCUSDT", "condition": "GTE", "value": 100})
    aid = r.json()["id"]
    r = auth_client.patch(f"/api/alarms/{aid}", json={"expires_at": "2099-12-31T00:00:00"})
    assert r.status_code == 200, r.text
    assert r.json()["expires_at"].startswith("2099-12-31")


def test_patch_bad_status_rejected(auth_client):
    r = auth_client.post("/api/alarms", json={"symbol": "BTCUSDT", "condition": "GTE", "value": 100})
    aid = r.json()["id"]
    r = auth_client.patch(f"/api/alarms/{aid}", json={"status": "BANANA"})
    assert r.status_code == 422


def test_reactivation_reenables_even_with_explicit_false(auth_client):
    r = auth_client.post("/api/alarms", json={"symbol": "BTCUSDT", "condition": "GTE", "value": 100})
    aid = r.json()["id"]
    r = auth_client.patch(f"/api/alarms/{aid}", json={"status": "ACTIVE", "enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["status"] == "ACTIVE"


def test_bad_trigger_mode_rejected(auth_client):
    r = auth_client.post("/api/alarms", json={"symbol": "BTCUSDT", "condition": "GTE", "value": 100, "trigger_mode": "REPEAT"})
    assert r.status_code == 422


def test_every_trigger_mode_accepted(auth_client):
    r = auth_client.post("/api/alarms", json={"symbol": "BTCUSDT", "condition": "GTE", "value": 100, "trigger_mode": "EVERY"})
    assert r.status_code == 200 and r.json()["trigger_mode"] == "EVERY"


def test_position_alarm_accepted(auth_client):
    r = auth_client.post("/api/alarms", json={"target_type": "POSITION", "symbol": "BTCUSDT",
        "condition": "NEAR_STOP", "value": 1.5, "params": {"unit": "PCT"}})
    assert r.status_code == 200, r.text


def test_plan_alarm_accepted_without_symbol(auth_client):
    r = auth_client.post("/api/alarms", json={"target_type": "PLAN", "condition": "PLAN_LOSS_LIMIT"})
    assert r.status_code == 200, r.text


def test_condition_must_match_target(auth_client):
    r = auth_client.post("/api/alarms", json={"target_type": "PLAN", "condition": "CROSS_UP", "value": 1})
    assert r.status_code == 422
    r = auth_client.post("/api/alarms", json={"target_type": "SYMBOL", "symbol": "BTCUSDT", "condition": "NEAR_STOP", "value": 1})
    assert r.status_code == 422


def test_position_alarm_without_symbol_rejected(auth_client):
    r = auth_client.post("/api/alarms", json={"target_type": "POSITION", "condition": "NEAR_STOP", "value": 1.5})
    assert r.status_code == 422


def test_position_alarm_without_value_rejected(auth_client):
    r = auth_client.post("/api/alarms", json={"target_type": "POSITION", "symbol": "BTCUSDT", "condition": "LIQ_DIST"})
    assert r.status_code == 422


def test_symbol_alarm_without_value_rejected(auth_client):
    r = auth_client.post("/api/alarms", json={"target_type": "SYMBOL", "symbol": "BTCUSDT", "condition": "GTE"})
    assert r.status_code == 422


def test_position_alarm_equity_rejected(auth_client):
    r = auth_client.post("/api/alarms", json={"target_type": "POSITION", "symbol": "AAPL",
        "market": "EQUITY", "condition": "NEAR_STOP", "value": 1.5})
    assert r.status_code == 422
