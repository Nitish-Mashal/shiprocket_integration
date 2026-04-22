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

                frappe.db.commit()

            except Exception as e:
                frappe.log_error("Tracking Loop Error", str(e))

    except Exception as e:
        frappe.log_error("Tracking Main Error", str(e))


# ✅ CLEAN WEBHOOK (NO sr / shiprocket in name)
@frappe.whitelist(allow_guest=True)
def webhook_listener():
    try:
        # 🔐 TOKEN VALIDATION
        expected_token = frappe.conf.get("shiprocket_webhook_token")
        received_token = frappe.get_request_header("x-api-key")

        if expected_token and received_token != expected_token:
            frappe.log_error("Invalid Webhook Token", str(received_token))
            return "Unauthorized"

        # 📦 GET PAYLOAD
        data = frappe.request.get_json()
        frappe.log_error("WEBHOOK DATA", str(data))

        # 🔍 EXTRACT ORDER ID
        order_id = (
            data.get("order_id")
            or data.get("order", {}).get("order_id")
        )

        # 🔍 EXTRACT STATUS
        status = (
            data.get("current_status")
            or data.get("shipment_status")
            or data.get("status")
        )

        awb = data.get("awb") or data.get("awb_code")
        courier = data.get("courier_name")

        if not order_id or not status:
            frappe.log_error("Webhook Missing Data", str(data))
            return "Missing Data"

        if not frappe.db.exists("Sales Order", order_id):
            frappe.log_error("Sales Order Not Found", order_id)
            return "Order Not Found"

        sales_order = frappe.get_doc("Sales Order", order_id)

        # 🔄 STATUS MAP
        status_map = {
            "new": "Pending",
            "created": "Pending",
            "shipped": "Shipped",
            "in transit": "In Transit",
            "out for delivery": "In Transit",
            "delivered": "Delivered",
            "cancelled": "Cancelled",
            "canceled": "Cancelled",
            "rto": "RTO"
        }

        status_lower = (status or "").lower()
        mapped_status = "Pending"

        for key in status_map:
            if key in status_lower:
                mapped_status = status_map[key]
                break

        # ✅ UPDATE ORDER
        frappe.db.set_value("Sales Order", order_id, {
            "custom_shipment_status": mapped_status,
            "custom_shiprocket_awb": awb,
            "custom_courier_name": courier,
            "custom_tracking_url": (
                f"https://shiprocket.co/tracking/{awb}" if awb else ""
            )
        })

        frappe.db.commit()

        frappe.log_error("WEBHOOK STATUS UPDATED", f"{order_id} → {mapped_status}")

        # 🚨 CANCEL ERP ORDER IF NEEDED
        if mapped_status in ["Cancelled", "RTO"] and sales_order.docstatus == 1:
            try:
                sales_order.cancel()
                frappe.db.commit()
                frappe.log_error("ERP CANCELLED", order_id)
            except Exception as e:
                frappe.log_error("Cancel Failed", str(e))

        return "OK"

    except Exception as e:
        frappe.log_error("Webhook Error", str(e))
        return "Error"