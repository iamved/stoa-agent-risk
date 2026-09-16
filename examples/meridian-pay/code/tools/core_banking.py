"""Core-banking client. One static API key from the secrets manager, shared by every agent."""
import os
import boto3
import requests

_secrets = boto3.client("secretsmanager")
API_KEY = _secrets.get_secret_value(SecretId="core-banking/api-key")["SecretString"]
BASE = "https://core.meridian.internal/v2"

def _call(path: str, payload: dict) -> dict:
    r = requests.post(f"{BASE}{path}", json=payload, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10)
    r.raise_for_status()
    return r.json()
