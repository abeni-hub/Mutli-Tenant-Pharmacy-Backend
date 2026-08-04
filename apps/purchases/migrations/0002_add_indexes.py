from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("purchases", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="supplier",
            name="code",
            field=models.CharField(db_index=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="purchaseorder",
            name="po_number",
            field=models.CharField(db_index=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="purchaseorder",
            name="status",
            field=models.CharField(db_index=True, choices=[("draft", "Draft"), ("approved", "Approved"), ("sent", "Sent"), ("received", "Received"), ("cancelled", "Cancelled")], default="draft", max_length=20),
        ),
        migrations.AlterField(
            model_name="purchaseorderitem",
            name="product",
            field=models.ForeignKey(on_delete=models.deletion.PROTECT, related_name="purchase_order_items", to="catalog.product"),
        ),
    ]
