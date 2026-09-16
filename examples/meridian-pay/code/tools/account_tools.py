"""The write tools. Limits live in the prompt, not here; no argument validation.

Planted: issue_refund is retried on failure and sends no idempotency key. A
processor timeout after the refund commits posts it again — the $340 near miss.
"""
from langchain_core.tools import tool
from tenacity import retry, stop_after_attempt, wait_exponential
from .core_banking import _call


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=8))
def _post_refund(account_id: str, amount: float, dispute_id: str) -> dict:
    return _call("/refunds", {"account_id": account_id, "amount": amount, "dispute_id": dispute_id})


@tool
def issue_refund(account_id: str, amount: float, dispute_id: str) -> str:
    """Refund a disputed charge to the customer's account."""
    return _post_refund(account_id, amount, dispute_id)["status"]

@tool
def waive_fee(account_id: str, fee_id: str, amount: float) -> str:
    """Waive a fee on the account."""
    return _call("/fees/waive", {"account_id": account_id, "fee_id": fee_id, "amount": amount})["status"]

@tool
def update_contact_info(account_id: str, email: str = "", phone: str = "", address: str = "") -> str:
    """Update the customer's contact details."""
    return _call("/customers/contact", {"account_id": account_id, "email": email, "phone": phone, "address": address})["status"]

@tool
def reissue_card(account_id: str) -> str:
    """Reissue the debit card to the address on file."""
    return _call("/cards/reissue", {"account_id": account_id})["status"]

@tool
def place_travel_notice(account_id: str, countries: list[str], until: str) -> str:
    """Place a travel notice."""
    return _call("/travel", {"account_id": account_id, "countries": countries, "until": until})["status"]

@tool
def verify_identity(account_id: str, answers: dict) -> bool:
    """Knowledge-based authentication."""
    return _call("/kba/verify", {"account_id": account_id, "answers": answers})["verified"]


@tool
def change_payout_account(merchant_id: str, new_account: str, routing_number: str) -> str:
    """Change the bank account a merchant's payouts are sent to."""
    return _call("/merchants/payout-account", {"merchant_id": merchant_id, "account": new_account, "routing": routing_number})["status"]
