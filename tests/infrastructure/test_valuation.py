"""Contracts for model output, property validation and provider failures."""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from realestate.api import valuation
from realestate.hermes.sessions import TurnResult
from starlette.requests import Request


def facts(**changes: Any) -> valuation.PropertyFacts:
    return valuation.PropertyFacts.model_validate({
        "property_type": "Casa", "municipality": "Zapopan, Jalisco",
        "neighborhood": "Jardines del Valle", "land_m2": 180,
        "construction_m2": 220, "bedrooms": 3, "bathrooms": 2.5,
        "parking": 2, "condition": "Bueno", **changes,
    })


def test_property_requires_construction_and_land_has_no_rooms() -> None:
    with pytest.raises(ValidationError):
        facts(construction_m2=0)
    with pytest.raises(ValidationError):
        facts(property_type="Terreno")
    assert facts(property_type="Terreno", construction_m2=0, bedrooms=0,
                 bathrooms=0, parking=0).land_m2 == 180


@pytest.mark.parametrize("host,origin,allowed", [
    ("127.0.0.1:8080", "http://localhost:8080", True),
    ("localhost:8080", "http://127.0.0.1:8080", True),
    ("localhost:8080", "http://[::1]:8080", True),
    ("localhost:8080", "http://localhost:8080", True),
    ("product:8080", "http://localhost:8080", True),
    ("localhost:8080", "http://localhost:9999", False),
    ("localhost:8080", "https://localhost:8080", False),
    ("localhost:8080", "https://evil.example", False),
    ("localhost:8080", "http://localhost.evil.example:8080", False),
    ("localhost:8080", "null", False),
])
async def test_browser_origin_validation(
    monkeypatch: pytest.MonkeyPatch, host: str, origin: str, allowed: bool
) -> None:
    called = False

    async def turn(*args: Any, **kwargs: Any) -> TurnResult:
        nonlocal called
        called = True
        return TurnResult(text=json.dumps({
            "minimum_mxn": 3000000, "central_mxn": 3500000,
            "maximum_mxn": 4000000,
            "explanation": "Estimación basada en características proporcionadas.",
            "factors": ["Ubicación", "Superficie"], "assumptions": ["Buen estado"],
        }))

    monkeypatch.setattr(valuation, "run_turn", turn)
    request = Request({
        "type": "http", "method": "POST", "scheme": "http",
        "path": "/opinion-de-valor/generar", "root_path": "",
        "headers": [(b"host", host.encode()), (b"origin", origin.encode())],
        "server": ("127.0.0.1", 8080),
        "app": SimpleNamespace(state=SimpleNamespace(
            hermes=object(), settings=SimpleNamespace(site_public_origin="http://localhost:8080"),
        )),
    })
    if allowed:
        result = await valuation.generate(facts(), request, object())  # type: ignore[arg-type]
        assert result["central_mxn"] == 3500000
        assert called
    else:
        with pytest.raises(HTTPException) as error:
            await valuation.generate(facts(), request, object())  # type: ignore[arg-type]
        assert error.value.status_code == 403
        assert error.value.detail == "Origen no autorizado."
        assert not called


@pytest.mark.parametrize("mode", ["valid", "inverted", "tool", "malformed", "timeout"])
async def test_generation_contract(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    async def turn(*args: Any, **kwargs: Any) -> TurnResult:
        assert kwargs["profile"] == "valuation"
        assert args[1].hermes_session_id == ""
        if mode == "timeout":
            raise TimeoutError
        body = {"minimum_mxn": 3000000, "central_mxn": 3500000,
                "maximum_mxn": 4000000, "explanation": "Estimación basada en las características proporcionadas.",
                "factors": ["Ubicación", "Superficie"], "assumptions": ["Documentación en regla"]}
        if mode == "inverted":
            body["minimum_mxn"] = 5000000
        return TurnResult(text="invalid" if mode == "malformed" else json.dumps(body),
                          tools_used=["some_tool"] if mode == "tool" else [])

    monkeypatch.setattr(valuation, "run_turn", turn)
    request = SimpleNamespace(headers={}, app=SimpleNamespace(state=SimpleNamespace(hermes=object())))
    if mode == "valid":
        result = await valuation.generate(facts(), request, object())  # type: ignore[arg-type]
        assert result["central_mxn"] == 3500000
        assert result["price_per_m2"] == round(3500000 / 220)
        assert "sin comparables" in str(result["methodology"])
    else:
        with pytest.raises(HTTPException) as error:
            await valuation.generate(facts(), request, object())  # type: ignore[arg-type]
        assert error.value.status_code == 502
