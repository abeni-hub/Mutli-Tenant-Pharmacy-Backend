from django.db import migrations, models
import django.db.models.deletion


def generate_uuid(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("catalog", "0001_initial"),
        ("inventory", "0002_stockbatch_batch_status_stockbatch_branch_and_more"),
        ("tenants", "0002_auth_phase3_user_login_history_password_reset"),
    ]

    operations = [
        migrations.CreateModel(
            name="Supplier",
            fields=[
                ("id", models.UUIDField(default=None, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("code", models.CharField(max_length=50, unique=True)),
                ("company_name", models.CharField(max_length=200)),
                ("contact_person", models.CharField(max_length=200, blank=True)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=50)),
                ("address", models.TextField(blank=True)),
                ("country", models.CharField(blank=True, max_length=100)),
                ("tax_number", models.CharField(blank=True, max_length=100)),
                ("license_number", models.CharField(blank=True, max_length=100)),
                ("payment_terms", models.CharField(blank=True, max_length=100)),
                ("status", models.CharField(choices=[("active", "Active"), ("inactive", "Inactive"), ("archived", "Archived")], default="active", max_length=20)),
                ("preferred_supplier", models.BooleanField(default=False)),
                ("notes", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="supplier_records", to="tenants.tenant")),
            ],
            options={"ordering": ("company_name",)},
        ),
        migrations.CreateModel(
            name="PurchaseOrder",
            fields=[
                ("id", models.UUIDField(default=None, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("po_number", models.CharField(max_length=100)),
                ("branch", models.CharField(blank=True, max_length=200)),
                ("warehouse", models.CharField(blank=True, max_length=200)),
                ("expected_delivery", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("approved", "Approved"), ("sent", "Sent"), ("received", "Received"), ("cancelled", "Cancelled")], default="draft", max_length=20)),
                ("total", models.DecimalField(decimal_places=2, default="0.00", max_digits=12)),
                ("tax", models.DecimalField(decimal_places=2, default="0.00", max_digits=12)),
                ("discount", models.DecimalField(decimal_places=2, default="0.00", max_digits=12)),
                ("is_active", models.BooleanField(default=True)),
                ("supplier", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_orders", to="purchases.supplier")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchaseorder_records", to="tenants.tenant")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="PurchaseOrderItem",
            fields=[
                ("id", models.UUIDField(default=None, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("ordered_quantity", models.PositiveIntegerField(default=0)),
                ("received_quantity", models.PositiveIntegerField(default=0)),
                ("unit_cost", models.DecimalField(decimal_places=2, default="0.00", max_digits=12)),
                ("discount", models.DecimalField(decimal_places=2, default="0.00", max_digits=12)),
                ("tax", models.DecimalField(decimal_places=2, default="0.00", max_digits=12)),
                ("total", models.DecimalField(decimal_places=2, default="0.00", max_digits=12)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_order_items", to="catalog.product")),
                ("purchase_order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="items", to="purchases.purchaseorder")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchaseorderitem_records", to="tenants.tenant")),
            ],
            options={"ordering": ("created_at",)},
        ),
        migrations.CreateModel(
            name="GoodsReceipt",
            fields=[
                ("id", models.UUIDField(default=None, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("receipt_number", models.CharField(max_length=100)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("notes", models.TextField(blank=True)),
                ("complete", models.BooleanField(default=False)),
                ("batch", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="goods_receipts", to="inventory.stockbatch")),
                ("purchase_order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="goods_receipts", to="purchases.purchaseorder")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="goodsreceipt_records", to="tenants.tenant")),
            ],
            options={"ordering": ("-received_at",)},
        ),
        migrations.AddConstraint(
            model_name="supplier",
            constraint=models.UniqueConstraint(fields=("tenant", "code"), name="unique_supplier_code_per_tenant"),
        ),
        migrations.AddConstraint(
            model_name="purchaseorder",
            constraint=models.UniqueConstraint(fields=("tenant", "po_number"), name="unique_po_number_per_tenant"),
        ),
    ]
