from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0006_interaction_presentation")]
    operations = [
        migrations.AddField(
            model_name="message", name="presentation", field=models.JSONField(null=True, blank=True)
        ),
        migrations.AddField(
            model_name="message", name="continuity", field=models.JSONField(null=True, blank=True)
        ),
    ]
