import frappe

def remove_custom_fields():
    fields = [
        "custom_shiprocket_details",
        "custom_shiprocket_shipment_id",
        "custom_shiprocket_awb",
        "custom_shipment_status",
        "custom_courier_name",
        "custom_tracking_url"
    ]

    for field in fields:
        frappe.db.delete("Custom Field", {
            "dt": "Sales Order",
            "fieldname": field
        })

    frappe.db.commit()