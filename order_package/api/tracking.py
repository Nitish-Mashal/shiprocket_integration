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


# ✅ CLEAN WEBHOOK
@frappe.whitelist(allow_guest=True)
def tracking_update():
    try:
        # 🔐 TOKEN VALIDATION
        expected_token = frappe.conf.get("shiprocket_webhook_token")
        received_token = frappe.get_request_header("x-api-key")

        if expected_token and received_token != expected_token:
            frappe.log_error("Invalid Webhook Token", str(received_token))
            return "Unauthorized"

        # 📦 GET PAYLOAD
        data = frappe.request.get_json() or {}

        # 🔍 EXTRACT ORDER ID
        order_id = (
            data.get("channel_order_id")
            or data.get("order", {}).get("channel_order_id")
            or data.get("order_id")
            or data.get("order", {}).get("order_id")
        )

        # 🔍 EXTRACT STATUS
        status = (
            data.get("current_status")
            or data.get("shipment_status")
            or data.get("status")
            or data.get("order_status")
        )

        shipment_id = data.get("shipment_id")
        awb = data.get("awb") or data.get("awb_code")
        courier = data.get("courier_name")

        # 🧠 DEBUG LOG
        frappe.log_error("WEBHOOK RAW DATA", str(data))

        # ❌ VALIDATION
        if not order_id and not shipment_id:
            frappe.log_error("Missing Order ID & Shipment ID", str(data))
            return "Missing Data"

        # 🔧 CLEAN ORDER ID (REMOVE -C, -R, etc.)
        cleaned_order_id = None
        if order_id:
            parts = order_id.split("-")
            if parts[-1] in ["C", "R"] or len(parts[-1]) <= 2:
                cleaned_order_id = "-".join(parts[:-1])
            else:
                cleaned_order_id = order_id

        # 🔎 FIND SALES ORDER
        sales_order = None

        # 1️⃣ Exact match
        if order_id and frappe.db.exists("Sales Order", order_id):
            sales_order = frappe.get_doc("Sales Order", order_id)

        # 2️⃣ Cleaned order_id match
        elif cleaned_order_id and frappe.db.exists("Sales Order", cleaned_order_id):
            sales_order = frappe.get_doc("Sales Order", cleaned_order_id)

        # 3️⃣ Fallback using shipment_id
        elif shipment_id:
            so_name = frappe.db.get_value(
                "Sales Order",
                {"custom_shiprocket_shipment_id": shipment_id},
                "name"
            )
            if so_name:
                sales_order = frappe.get_doc("Sales Order", so_name)

        if not sales_order:
            frappe.log_error("Sales Order Not Found", str(data))
            return "Order Not Found"

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

        status_lower = (status or "").lower().strip()
        mapped_status = "Pending"

        for key in status_map:
            if key in status_lower:
                mapped_status = status_map[key]
                break

        # ✅ UPDATE ORDER
        frappe.db.set_value("Sales Order", sales_order.name, {
            "custom_shipment_status": mapped_status,
            "custom_shiprocket_awb": awb,
            "custom_courier_name": courier,
            "custom_tracking_url": (
                f"https://shiprocket.co/tracking/{awb}" if awb else ""
            )
        })

        frappe.db.commit()

        frappe.log_error(
            "WEBHOOK SUCCESS",
            f"{sales_order.name} → {mapped_status}"
        )

        # 🚨 AUTO CANCEL ERP ORDER
        if mapped_status in ["Cancelled", "RTO"] and sales_order.docstatus == 1:
            try:
                sales_order.cancel()
                frappe.db.commit()
                frappe.log_error("ERP CANCELLED", sales_order.name)
            except Exception as e:
                frappe.log_error("Cancel Failed", str(e))

        return "OK"

    except Exception as e:
        frappe.log_error("Webhook Error", str(e))
        return "Error"