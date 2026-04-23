import frappe
import requests
import re
from .auth import get_shiprocket_token


def create_shiprocket_order(doc, method=None):

    # جلوگیری duplicate
    if doc.get("custom_shiprocket_shipment_id"):
        return

    try:
        token = get_shiprocket_token()
        settings = frappe.get_single("Shiprocket Settings")

        # ✅ ADDRESS FETCH
        address_name = (
            doc.shipping_address_name
            or doc.customer_address
            or doc.billing_address_name
        )

        address = None

        if address_name:
            address = frappe.get_doc("Address", address_name)
        else:
            address_list = frappe.get_all(
                "Address",
                filters={
                    "link_doctype": "Customer",
                    "link_name": doc.customer
                },
                fields=["name"],
                limit=1
            )

            if address_list:
                address = frappe.get_doc("Address", address_list[0].name)

        if not address:
            frappe.throw("No Address found for Customer")

        # ✅ VALIDATION
        if not address.address_line1 or not address.city or not address.pincode:
            frappe.throw("Incomplete Address")

        # ✅ CUSTOMER NAME
        customer_name = (doc.customer_name or doc.customer or "Customer").strip()
        if len(customer_name) < 2:
            customer_name = "Customer"

        # ✅ EMAIL (FIXED)
        email = (
            address.email_id
            or doc.contact_email
            or "support@quantumberg.com"
        )

        # ✅ PHONE (FIXED)
        phone = (
            address.phone
            or address.mobile_no
            or doc.contact_mobile
            or doc.contact_phone
        )

        phone = re.sub(r"\D", "", str(phone or ""))

        if len(phone) > 10:
            phone = phone[-10:]

        if len(phone) != 10:
            frappe.throw(f"Invalid Phone: {phone}")

        # ✅ PINCODE
        pincode = str(address.pincode).strip()
        if not pincode.isdigit() or len(pincode) != 6:
            frappe.throw(f"Invalid Pincode: {pincode}")

        # ✅ STATE
        state = (address.state or "").strip().title()

        valid_states = [
            "Andhra Pradesh","Arunachal Pradesh","Assam","Bihar","Chhattisgarh",
            "Goa","Gujarat","Haryana","Himachal Pradesh","Jharkhand","Karnataka",
            "Kerala","Madhya Pradesh","Maharashtra","Manipur","Meghalaya",
            "Mizoram","Nagaland","Odisha","Punjab","Rajasthan","Sikkim",
            "Tamil Nadu","Telangana","Tripura","Uttar Pradesh","Uttarakhand",
            "West Bengal","Delhi"
        ]

        if state not in valid_states:
            frappe.throw(f"Invalid State: {state}")

        # ✅ ITEMS
        items = []
        for d in doc.items:
            items.append({
                "name": d.item_name,
                "sku": d.item_code,
                "units": int(d.qty),
                "selling_price": float(d.rate),
                "discount": 0,
                "tax": 0,
                "hsn": "1234"
            })

        # ✅ FINAL PAYLOAD
        payload = {
            "order_id": doc.name,
            "order_date": str(doc.transaction_date),
            "pickup_location": settings.pickup_location,

            "comment": "",
            "company_name": "Quantumberg",

            # ✅ IMPORTANT FIX
            "shipping_is_billing": True,

            "billing_isd_code": "91",
            "billing_alternate_phone": phone,
            "order_type": "ESSENTIALS",

            # BILLING
            "billing_customer_name": customer_name,
            "billing_last_name": ".",
            "billing_address": address.address_line1.strip(),
            "billing_address_2": address.address_line2 or "",
            "billing_city": address.city,
            "billing_pincode": pincode,
            "billing_state": state,
            "billing_country": "India",
            "billing_email": email,
            "billing_phone": phone,

            # SHIPPING
            "shipping_customer_name": customer_name,
            "shipping_last_name": ".",
            "shipping_address": address.address_line1.strip(),
            "shipping_address_2": address.address_line2 or "",
            "shipping_city": address.city,
            "shipping_pincode": pincode,
            "shipping_state": state,
            "shipping_country": "India",
            "shipping_email": email,
            "shipping_phone": phone,

            # ORDER
            "order_items": items,
            "payment_method": "Prepaid",
            "sub_total": float(doc.grand_total),

            "shipping_charges": 0,
            "giftwrap_charges": 0,
            "transaction_charges": 0,
            "total_discount": 0,

            # PACKAGE
            "length": 10,
            "breadth": 10,
            "height": 10,
            "weight": 0.5
        }

        # ✅ LOGGING
        frappe.log_error("Shiprocket Payload", frappe.as_json(payload))

        # ✅ API CALL
        url = "https://apiv2.shiprocket.in/v1/external/orders/create/adhoc"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        res = requests.post(url, json=payload, headers=headers)

        frappe.log_error("Shiprocket Response", res.text)

        if res.status_code != 200:
            frappe.throw(f"Shiprocket Order Failed: {res.text}")

        result = res.json()

        shipment_id = result.get("shipment_id")

        if not shipment_id:
            frappe.throw(f"Shipment ID missing: {res.text}")

        # ✅ SAVE
        doc.db_set("custom_shiprocket_shipment_id", shipment_id)
        doc.db_set("custom_shipment_status", "Order Created")

    except Exception as e:
        frappe.log_error("Shiprocket Exception", str(e))
        frappe.throw(str(e))