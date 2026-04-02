import frappe
import requests
from .auth import get_shiprocket_token


def update_tracking_status():
    try:
        token = get_shiprocket_token()

        orders = frappe.get_all(
            "Sales Order",
            filters={"custom_shiprocket_shipment_id": ["is", "set"]},
            fields=["name", "custom_shiprocket_shipment_id"]
        )

        for order in orders:
            try:
                url = f"https://apiv2.shiprocket.in/v1/external/courier/track?shipment_id={order.custom_shiprocket_shipment_id}"

                headers = {"Authorization": f"Bearer {token}"}

                res = requests.get(url, headers=headers)

                if res.status_code != 200:
                    frappe.log_error("Tracking Error", res.text)
                    continue

                data = res.json()

                tracking = data.get("tracking_data", {})
                shipment_track = tracking.get("shipment_track", [])

                if not shipment_track:
                    continue

                latest = shipment_track[0]

                frappe.db.set_value("Sales Order", order.name, {
                    "custom_shipment_status": latest.get("current_status"),
                    "custom_shiprocket_awb": tracking.get("awb_code"),
                    "custom_courier_name": tracking.get("courier_name"),
                    "custom_tracking_url": f"https://shiprocket.co/tracking/{tracking.get('awb_code')}" if tracking.get("awb_code") else ""
                })

            except Exception as e:
                frappe.log_error("Tracking Loop Error", str(e))

    except Exception as e:
        frappe.log_error("Tracking Main Error", str(e))