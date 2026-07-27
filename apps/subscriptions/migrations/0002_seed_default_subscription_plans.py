from django.db import migrations


def seed_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    plans = [
        {
            "name": "Starter",
            "code": "starter",
            "description": "Essential pharmacy management for small independent single-branch pharmacies.",
            "price_monthly": 29.00,
            "price_yearly": 290.00,
            "max_users": 3,
            "max_medicines": 500,
            "max_branches": 1,
            "has_reports": False,
            "has_sms": False,
            "has_backups": False,
            "is_active": True,
        },
        {
            "name": "Professional",
            "code": "professional",
            "description": "Advanced features, SMS alerts, and comprehensive reporting for growing multi-staff pharmacies.",
            "price_monthly": 79.00,
            "price_yearly": 790.00,
            "max_users": 10,
            "max_medicines": 5000,
            "max_branches": 3,
            "has_reports": True,
            "has_sms": True,
            "has_backups": False,
            "is_active": True,
        },
        {
            "name": "Enterprise",
            "code": "enterprise",
            "description": "Unlimited scale, automated backups, custom integrations, and dedicated enterprise support.",
            "price_monthly": 199.00,
            "price_yearly": 1990.00,
            "max_users": -1,
            "max_medicines": -1,
            "max_branches": -1,
            "has_reports": True,
            "has_sms": True,
            "has_backups": True,
            "is_active": True,
        },
    ]

    for plan_data in plans:
        SubscriptionPlan.objects.get_or_create(code=plan_data["code"], defaults=plan_data)


def unseed_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    SubscriptionPlan.objects.filter(code__in=["starter", "professional", "enterprise"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0001_initial_subscription_models"),
    ]

    operations = [
        migrations.RunPython(seed_plans, reverse_code=unseed_plans),
    ]
