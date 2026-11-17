"""Check conversation creation through the website proxy, including CSRF and cookies."""

import os

import httpx

with httpx.Client(
    base_url=os.environ.get("WEBSITE_URL", "http://localhost:3000"),
    follow_redirects=True,
) as client:
    session = client.get("/api/session")
    session.raise_for_status()
    response = client.post(
        "/api/conversations",
        json={},
        headers={"X-CSRFToken": session.json()["csrf_token"]},
    )
    print(f"POST /api/conversations: HTTP {response.status_code}")
    assert not response.history, "La ruta API no debe redirigir el POST."
    assert response.status_code == 200, "No se pudo crear la conversación."
    conversation_id = response.json()["id"]
    restored = client.get(f"/api/conversations/{conversation_id}")
    restored.raise_for_status()
    assert restored.json()["id"] == conversation_id
    print("OK: creación y lectura de conversación mediante el website.")
