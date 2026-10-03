"""Unit tests verifying repository skeleton structure."""
from app.web.routes import create_app
from app.engine.guardrails import validate_plan_volume_increase

def test_flask_app_creation():
    app = create_app()
    client = app.test_client()
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert b"TRAINING DASHBOARD" in response.data

def test_volume_guardrail_rule():
    assert validate_plan_volume_increase(50.0, 55.0) is True
    assert validate_plan_volume_increase(50.0, 60.0) is False
