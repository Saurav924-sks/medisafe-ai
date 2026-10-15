import asyncio
import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core.config import settings
from app.interop.fhir.smart import SMARTFHIRClient


def test_smart_authorization_uses_pkce_and_tokens_stay_server_side(monkeypatch):
    monkeypatch.setattr(settings, "FHIR_BASE_URL", "https://synthetic.example/fhir")
    monkeypatch.setattr(settings, "FHIR_CLIENT_ID", "synthetic-client")
    monkeypatch.setattr(settings, "FHIR_CLIENT_SECRET", None)
    monkeypatch.setattr(settings, "FHIR_REDIRECT_URI", "https://app.example/callback")
    monkeypatch.setattr(settings, "FHIR_SCOPES", "launch/patient openid fhirUser patient/*.read")
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("smart-configuration"):
            return httpx.Response(200, json={"authorization_endpoint": "https://synthetic.example/auth", "token_endpoint": "https://synthetic.example/token"})
        return httpx.Response(200, json={"access_token": "synthetic-secret-token", "refresh_token": "synthetic-refresh", "expires_in": 3600, "patient": "synthetic-patient", "fhirUser": "https://synthetic.example/Practitioner/synthetic-practitioner"})

    async def exercise():
        client = SMARTFHIRClient(httpx.MockTransport(handler))
        url = await client.authorization_url("synthetic-clinician")
        params = parse_qs(urlparse(url).query)
        assert params["code_challenge_method"] == ["S256"]
        assert params["scope"] == ["launch/patient openid fhirUser patient/*.read"]
        result = await client.exchange_code("synthetic-clinician", params["state"][0], "synthetic-code")
        assert result["patient_context"] == "synthetic-patient"
        assert result["practitioner_context"].endswith("synthetic-practitioner")
        assert "synthetic-secret-token" not in str(result)
        form = parse_qs(requests[-1].content.decode())
        verifier = form["code_verifier"][0]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        assert challenge == params["code_challenge"][0]
        assert (await client.access_token("synthetic-clinician"))[0] == "synthetic-secret-token"
        context = client.tokens["synthetic-clinician"]
        context.expires_at = 0
        assert (await client.access_token("synthetic-clinician"))[0] == "synthetic-secret-token"
        context.refresh_token = None
        context.expires_at = 0
        with pytest.raises(ValueError, match="re-authentication is required"):
            await client.access_token("synthetic-clinician")
    asyncio.run(exercise())


def test_smart_authorization_state_cannot_be_replayed_by_another_clinician(monkeypatch):
    monkeypatch.setattr(settings, "FHIR_BASE_URL", "https://synthetic.example/fhir")
    monkeypatch.setattr(settings, "FHIR_CLIENT_ID", "synthetic-client")
    monkeypatch.setattr(settings, "FHIR_CLIENT_SECRET", None)
    monkeypatch.setattr(settings, "FHIR_REDIRECT_URI", "https://app.example/callback")
    token_requests = []

    def handler(request):
        if request.url.path.endswith("smart-configuration"):
            return httpx.Response(200, json={"authorization_endpoint": "https://synthetic.example/auth", "token_endpoint": "https://synthetic.example/token"})
        token_requests.append(request)
        return httpx.Response(200, json={"access_token": "synthetic-access-token", "expires_in": 3600})

    async def exercise():
        client = SMARTFHIRClient(httpx.MockTransport(handler))
        url = await client.authorization_url("synthetic-clinician-a")
        state = parse_qs(urlparse(url).query)["state"][0]
        with pytest.raises(ValueError, match="state is invalid or expired"):
            await client.exchange_code("synthetic-clinician-b", state, "synthetic-code")
        with pytest.raises(ValueError, match="state is invalid or expired"):
            await client.exchange_code("synthetic-clinician-a", state, "synthetic-code")
        assert token_requests == []

    asyncio.run(exercise())


def test_fhir_analysis_rejects_malformed_bundle_without_parsing(client):
    response = client.post("/api/v1/fhir/analyze", json={"resourceType": "Bundle", "entry": [{"resource": {"resourceType": "MedicationRequest", "id": "synthetic-x"}}]}, headers={"X-API-Key": "synthetic-test-api-key", "X-Clinician-ID": "1"})
    assert response.status_code == 422
    assert any(item["path"] == "resource.status" for item in response.json()["detail"]["issues"])


def test_fhir_analysis_requires_clinician_identity(client):
    response = client.post("/api/v1/fhir/analyze", json={"resourceType": "Bundle", "entry": []}, headers={"X-API-Key": "synthetic-test-api-key"})
    assert response.status_code == 401

