"""SMART on FHIR authorization-code + PKCE primitives.

Ephemeral state and tokens intentionally stay in process memory; production deployment
must supply a shared encrypted token store before using multiple workers.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.config import settings


@dataclass
class AuthorizationAttempt:
    clinician_id: str
    verifier: str
    expires_at: float


@dataclass
class TokenContext:
    access_token: str
    refresh_token: str | None
    expires_at: float
    patient_id: str | None
    practitioner: str | None


class SMARTFHIRClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport
        self.attempts: dict[str, AuthorizationAttempt] = {}
        self.tokens: dict[str, TokenContext] = {}

    def authorization_owner(self, state: str) -> str | None:
        attempt = self.attempts.get(state)
        if attempt is None or attempt.expires_at < time.time():
            return None
        return attempt.clinician_id

    def _config(self) -> tuple[str, str, str, str]:
        if not settings.FHIR_BASE_URL or not settings.FHIR_CLIENT_ID or not settings.FHIR_REDIRECT_URI:
            raise RuntimeError("FHIR SMART configuration is incomplete.")
        return settings.FHIR_BASE_URL.rstrip("/"), settings.FHIR_CLIENT_ID, settings.FHIR_REDIRECT_URI, settings.FHIR_SCOPES

    async def authorization_url(self, clinician_id: str) -> str:
        base, client_id, redirect_uri, scopes = self._config()
        async with httpx.AsyncClient(transport=self.transport, timeout=10) as client:
            response = await client.get(f"{base}/.well-known/smart-configuration")
            response.raise_for_status()
            discovery = response.json()
        endpoint = discovery.get("authorization_endpoint")
        if not isinstance(endpoint, str) or not endpoint.startswith(("https://", "http://")):
            raise RuntimeError("FHIR SMART authorization endpoint is unavailable.")
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = secrets.token_urlsafe(32)
        self.attempts[state] = AuthorizationAttempt(str(clinician_id), verifier, time.time() + 600)
        params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
                  "scope": scopes, "state": state, "aud": base, "code_challenge": challenge,
                  "code_challenge_method": "S256"}
        return f"{endpoint}?{urlencode(params)}"

    async def exchange_code(self, clinician_id: str, state: str, code: str) -> dict:
        base, client_id, redirect_uri, _ = self._config()
        attempt = self.attempts.pop(state, None)
        if attempt is None or attempt.expires_at < time.time() or attempt.clinician_id != str(clinician_id):
            raise ValueError("SMART authorization state is invalid or expired; re-authentication is required.")
        async with httpx.AsyncClient(transport=self.transport, timeout=10) as client:
            discovery_response = await client.get(f"{base}/.well-known/smart-configuration")
            discovery_response.raise_for_status()
            token_endpoint = discovery_response.json().get("token_endpoint")
            if not isinstance(token_endpoint, str):
                raise RuntimeError("FHIR SMART token endpoint is unavailable.")
            form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                    "client_id": client_id, "code_verifier": attempt.verifier}
            if settings.FHIR_CLIENT_SECRET:
                form["client_secret"] = settings.FHIR_CLIENT_SECRET
            response = await client.post(token_endpoint, data=form)
            response.raise_for_status()
            payload = response.json()
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("FHIR SMART token response is invalid.")
        expires_in = payload.get("expires_in", 0)
        try:
            expires_at = time.time() + max(0, int(expires_in))
        except (TypeError, ValueError):
            expires_at = 0
        fhir_user = payload.get("fhirUser") or payload.get("id_token")
        practitioner = fhir_user if isinstance(fhir_user, str) and "/Practitioner/" in fhir_user else None
        patient_id = payload.get("patient")
        self.tokens[clinician_id] = TokenContext(token, payload.get("refresh_token"), expires_at,
                                                patient_id if isinstance(patient_id, str) else None, practitioner)
        return {"authenticated": True, "expires_at": expires_at, "patient_context": patient_id if isinstance(patient_id, str) else None,
                "practitioner_context": practitioner or "NOT_AVAILABLE", "reauthentication_required": expires_at <= time.time()}

    async def access_token(self, clinician_id: str) -> tuple[str, TokenContext]:
        context = self.tokens.get(clinician_id)
        if context is None:
            raise ValueError("FHIR authorization is unavailable; re-authentication is required.")
        if context.expires_at > time.time() + 30:
            return context.access_token, context
        if not context.refresh_token:
            self.tokens.pop(clinician_id, None)
            raise ValueError("FHIR authorization expired; re-authentication is required.")
        base, client_id, _, _ = self._config()
        async with httpx.AsyncClient(transport=self.transport, timeout=10) as client:
            discovery = await client.get(f"{base}/.well-known/smart-configuration")
            discovery.raise_for_status()
            token_endpoint = discovery.json().get("token_endpoint")
            refresh_form = {"grant_type": "refresh_token", "refresh_token": context.refresh_token, "client_id": client_id}
            if settings.FHIR_CLIENT_SECRET:
                refresh_form["client_secret"] = settings.FHIR_CLIENT_SECRET
            response = await client.post(token_endpoint, data=refresh_form)
            response.raise_for_status()
            payload = response.json()
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            self.tokens.pop(clinician_id, None)
            raise ValueError("FHIR authorization expired; re-authentication is required.")
        context.access_token = token
        context.refresh_token = payload.get("refresh_token") or context.refresh_token
        context.expires_at = time.time() + max(0, int(payload.get("expires_in", 0)))
        return context.access_token, context

    async def fetch_patient_bundle(self, clinician_id: str, patient_id: str | None = None) -> dict:
        base, _, _, _ = self._config()
        token, context = await self.access_token(clinician_id)
        selected_patient = patient_id or context.patient_id
        if not selected_patient or not selected_patient.replace("-", "").replace("_", "").isalnum():
            raise ValueError("FHIR patient context is unavailable; re-authentication is required.")
        if context.patient_id and selected_patient != context.patient_id:
            raise ValueError("Requested patient does not match the authorized SMART patient context.")
        async with httpx.AsyncClient(transport=self.transport, timeout=20) as client:
            response = await client.get(f"{base}/Patient/{selected_patient}/$everything", headers={"Authorization": f"Bearer {token}", "Accept": "application/fhir+json"})
            response.raise_for_status()
            bundle = response.json()
        return bundle


smart_fhir_client = SMARTFHIRClient()
