import frappe
import requests
from datetime import timedelta
from frappe.utils import now_datetime, get_datetime


def get_shiprocket_token():
    settings = frappe.get_single("Shiprocket Settings")

    if settings.token and settings.token_expiry:
        if now_datetime() < get_datetime(settings.token_expiry):
            return settings.token

    url = "https://apiv2.shiprocket.in/v1/external/auth/login"

    payload = {
        "email": settings.email,
        "password": settings.get_password("password")
    }

    response = requests.post(url, json=payload)

    if response.status_code != 200:
        frappe.throw(f"Shiprocket Auth Failed: {response.text}")

    data = response.json()

    if not data.get("token"):
        frappe.throw("Shiprocket Authentication Failed")

    settings.token = data["token"]
    settings.token_expiry = now_datetime() + timedelta(hours=9)
    settings.save(ignore_permissions=True)

    return settings.token