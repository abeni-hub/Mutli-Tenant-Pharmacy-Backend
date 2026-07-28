# Multi-Tenant Pharmacy SaaS — API Request & Payload Reference

This document provides exact JSON request payload structures, headers, query parameters, and expected response payloads for key core operations across the Multi-Tenant Pharmacy API (`/api/v1/`).

---

## 1. Catalog Management

### Create Product
- **Endpoint**: `POST /api/v1/products/`
- **Headers**: 
  - `Authorization: Bearer <access_token>`
  - `X-Tenant-ID: <tenant_uuid>`
  - `Content-Type: application/json`

#### Request Payload
```json
{
  "name": "Amoxicillin 500mg Capsule",
  "sku": "AMX-500-CAP",
  "category": "Antibiotics",
  "description": "Broad-spectrum penicillin antibiotic",
  "unit_of_measure": "Box",
  "reorder_level": 20,
  "is_active": true
}
```

#### Response (201 Created)
```json
{
  "id": "e8d47b1a-29cf-4a4b-9876-123456789abc",
  "tenant": "018f3a5e-7c1b-7890-a123-456789abcdef",
  "name": "Amoxicillin 500mg Capsule",
  "sku": "AMX-500-CAP",
  "category": "Antibiotics",
  "description": "Broad-spectrum penicillin antibiotic",
  "unit_of_measure": "Box",
  "reorder_level": 20,
  "total_stock": 0,
  "is_active": true,
  "created_at": "2026-07-28T02:30:00Z",
  "updated_at": "2026-07-28T02:30:00Z"
}
```

---

## 2. Inventory Management

### Stock In (Add Batch)
- **Endpoint**: `POST /api/v1/inventory/batches/stock_in/`
- **Headers**: `Authorization: Bearer <token>`, `X-Tenant-ID: <tenant_uuid>`

#### Request Payload
```json
{
  "product_id": "e8d47b1a-29cf-4a4b-9876-123456789abc",
  "batch_number": "B-AMX-2026-001",
  "quantity": 100,
  "expiry_date": "2027-12-31",
  "unit_price": "3.50",
  "selling_price": "8.00",
  "supplier_name": "MedPharma Distributors",
  "notes": "Initial stock batch import"
}
```

#### Response (201 Created)
```json
{
  "id": "7b2c9d1e-84a1-43e5-bf12-9876543210fe",
  "batch_number": "B-AMX-2026-001",
  "product": "e8d47b1a-29cf-4a4b-9876-123456789abc",
  "product_name": "Amoxicillin 500mg Capsule",
  "quantity": 100,
  "expiry_date": "2027-12-31",
  "unit_price": "3.50",
  "selling_price": "8.00",
  "supplier_name": "MedPharma Distributors",
  "is_active": true
}
```

---

### FIFO Stock Out (Manual Inventory Reduction)
- **Endpoint**: `POST /api/v1/inventory/batches/stock_out_fifo/`
- **Headers**: `Authorization: Bearer <token>`, `X-Tenant-ID: <tenant_uuid>`

#### Request Payload
```json
{
  "product_id": "e8d47b1a-29cf-4a4b-9876-123456789abc",
  "quantity": 5,
  "reason": "Damaged items disposed"
}
```

#### Response (200 OK)
```json
{
  "detail": "Successfully deducted 5 units using FIFO logic.",
  "deducted_quantity": 5,
  "remaining_stock": 95
}
```

---

### Stock Adjustment (Audit / Correction)
- **Endpoint**: `POST /api/v1/inventory/batches/adjust_stock/`
- **Headers**: `Authorization: Bearer <token>`, `X-Tenant-ID: <tenant_uuid>`

#### Request Payload
```json
{
  "batch_id": "7b2c9d1e-84a1-43e5-bf12-9876543210fe",
  "new_quantity": 90,
  "reason": "Inventory physical count adjustment"
}
```

#### Response (200 OK)
```json
{
  "detail": "Batch stock adjusted successfully.",
  "batch_id": "7b2c9d1e-84a1-43e5-bf12-9876543210fe",
  "old_quantity": 95,
  "new_quantity": 90,
  "difference": -5
}
```

---

## 3. Sales & Point of Sale (POS)

### Sales Checkout
- **Endpoint**: `POST /api/v1/sales/`
- **Headers**: `Authorization: Bearer <token>`, `X-Tenant-ID: <tenant_uuid>`

#### Request Payload
```json
{
  "items_data": [
    {
      "product_id": "e8d47b1a-29cf-4a4b-9876-123456789abc",
      "quantity": 10,
      "discount_percent": "5.00"
    }
  ],
  "discount_amount": "0.00",
  "tax_percent": "15.00",
  "payment_method": "cash",
  "notes": "Walk-in customer sale"
}
```

#### Response (201 Created)
```json
{
  "id": "c1a2b3c4-d5e6-7f8a-9b0c-1d2e3f4a5b6c",
  "receipt_number": "REC-20260728-0001",
  "cashier": "9f8e7d6c-5b4a-3f2e-1d0c-9b8a7f6e5d4c",
  "cashier_name": "Betelehem Cashier",
  "subtotal": "76.00",
  "discount_amount": "4.00",
  "tax_amount": "10.80",
  "total_amount": "82.80",
  "total_cost": "35.00",
  "total_profit": "47.80",
  "payment_method": "cash",
  "status": "COMPLETED",
  "created_at": "2026-07-28T02:35:00Z",
  "items": [
    {
      "id": "item-uuid-1",
      "product": "e8d47b1a-29cf-4a4b-9876-123456789abc",
      "product_name": "Amoxicillin 500mg Capsule",
      "quantity": 10,
      "unit_price": "8.00",
      "discount_percent": "5.00",
      "unit_cost": "3.50",
      "total_price": "76.00",
      "profit": "41.00"
    }
  ]
}
```

---

### Sale Cancellation
- **Endpoint**: `POST /api/v1/sales/{sale_id}/cancel/`
- **Headers**: `Authorization: Bearer <token>`, `X-Tenant-ID: <tenant_uuid>`

#### Request Payload
```json
{
  "reason": "Customer changed mind before processing payment"
}
```

#### Response (200 OK)
```json
{
  "detail": "Sale REC-20260728-0001 cancelled successfully. Stock restored.",
  "sale_id": "c1a2b3c4-d5e6-7f8a-9b0c-1d2e3f4a5b6c",
  "status": "CANCELLED"
}
```

---

### Item Refund
- **Endpoint**: `POST /api/v1/sales/{sale_id}/refund_item/`
- **Headers**: `Authorization: Bearer <token>`, `X-Tenant-ID: <tenant_uuid>`

#### Request Payload
```json
{
  "sale_item_id": "item-uuid-1",
  "quantity": 2,
  "reason": "Defective packaging returned by customer"
}
```

#### Response (200 OK)
```json
{
  "detail": "Refunded 2 units of Amoxicillin 500mg Capsule.",
  "refunded_quantity": 2,
  "refund_amount": "15.20",
  "sale_status": "PARTIALLY_REFUNDED"
}
```

---

## 4. Reports & Analytics (Phase 7)

### KPI Dashboard Statistics
- **Endpoint**: `GET /api/v1/reports/dashboard/`
- **Headers**: `Authorization: Bearer <token>`, `X-Tenant-ID: <tenant_uuid>`

#### Response (200 OK)
```json
{
  "today": {
    "revenue": "1250.00",
    "cost": "550.00",
    "profit": "700.00",
    "net_profit": "700.00",
    "sales_count": 18
  },
  "this_month": {
    "revenue": "38500.00",
    "cost": "16200.00",
    "profit": "22300.00",
    "net_profit": "22300.00",
    "sales_count": 482
  },
  "inventory_summary": {
    "active_products": 145,
    "active_products_count": 145,
    "total_stock_balance": 4820,
    "total_stock_balance_count": 4820,
    "low_stock_products": 4,
    "low_stock_products_count": 4,
    "expired_batches": 1,
    "expired_batches_count": 1,
    "near_expiry_batches": 3,
    "near_expiry_batches_count": 3
  }
}
```

---

### Period-Based Financial Report
- **Endpoint**: `GET /api/v1/reports/financial/?period=monthly&start_date=2026-01-01&end_date=2026-12-31`
- **Headers**: `Authorization: Bearer <token>`, `X-Tenant-ID: <tenant_uuid>`

#### Response (200 OK)
```json
{
  "period_type": "monthly",
  "totals": {
    "total_sales_count": 482,
    "total_revenue": "38500.00",
    "total_cogs": "16200.00",
    "total_profit": "22300.00",
    "total_tax_collected": "4950.00",
    "total_discounts_given": "1200.00"
  },
  "breakdown": [
    {
      "date_period": "2026-07-01",
      "sales_count": 482,
      "revenue": "38500.00",
      "cogs": "16200.00",
      "profit": "22300.00",
      "tax_collected": "4950.00",
      "discounts_given": "1200.00"
    }
  ]
}
```

---

### Cashier Performance Ranking
- **Endpoint**: `GET /api/v1/reports/cashier-performance/`
- **Headers**: `Authorization: Bearer <token>`, `X-Tenant-ID: <tenant_uuid>`

#### Response (200 OK)
```json
[
  {
    "cashier_id": "9f8e7d6c-5b4a-3f2e-1d0c-9b8a7f6e5d4c",
    "name": "Betelehem Cashier",
    "cashier_name": "Betelehem Cashier",
    "email": "cashier@abeni.test",
    "cashier_email": "cashier@abeni.test",
    "sales_count": 142,
    "total_revenue": "14200.00",
    "total_profit": "8520.00",
    "average_sale_value": "100.00"
  }
]
```

---

### Product Performance (Top & Slow Medicines)
- **Endpoint**: `GET /api/v1/reports/product-performance/`
- **Headers**: `Authorization: Bearer <token>`, `X-Tenant-ID: <tenant_uuid>`

#### Response (200 OK)
```json
{
  "top_medicines": [
    {
      "product_id": "e8d47b1a-29cf-4a4b-9876-123456789abc",
      "product_name": "Amoxicillin 500mg Capsule",
      "sku": "AMX-500-CAP",
      "quantity_sold": 450,
      "total_revenue": "3600.00",
      "total_profit": "2025.00"
    }
  ],
  "slow_medicines": [
    {
      "product_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
      "product_name": "Rare Ointment 20g",
      "sku": "RO-20G",
      "total_stock": 15,
      "quantity_sold": 0,
      "status": "Zero Sales / Slow Moving"
    }
  ]
}
```

---

### Inventory Valuation & Asset Breakdown
- **Endpoint**: `GET /api/v1/reports/inventory-valuation/`
- **Headers**: `Authorization: Bearer <token>`, `X-Tenant-ID: <tenant_uuid>`

#### Response (200 OK)
```json
{
  "total_active_batches": 28,
  "total_items_in_stock": 4820,
  "cost_valuation": "16200.00",
  "retail_valuation": "38500.00",
  "potential_profit": "22300.00",
  "potential_profit_margin": "57.92%"
}
```

---

### Time-Series Charts API
- **Endpoint**: `GET /api/v1/reports/charts/?period=monthly&year=2026`
- **Headers**: `Authorization: Bearer <token>`, `X-Tenant-ID: <tenant_uuid>`

#### Response (200 OK)
```json
{
  "period": "monthly",
  "year": 2026,
  "labels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
  "datasets": {
    "revenue": ["0.00", "0.00", "0.00", "0.00", "0.00", "0.00", "38500.00", "0.00", "0.00", "0.00", "0.00", "0.00"],
    "profit": ["0.00", "0.00", "0.00", "0.00", "0.00", "0.00", "22300.00", "0.00", "0.00", "0.00", "0.00", "0.00"],
    "sales_count": [0, 0, 0, 0, 0, 0, 482, 0, 0, 0, 0, 0]
  }
}
```
