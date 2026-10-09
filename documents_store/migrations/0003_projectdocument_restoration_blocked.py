from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("documents_store", "0002_documenttag")]
    operations = [migrations.AddField(model_name="projectdocument", name="restoration_blocked",
        field=models.BooleanField(default=False))]
