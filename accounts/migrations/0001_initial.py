import accounts.models
import accounts.validators
import django.core.validators
import django.db.models.deletion
import django.db.models.functions.text
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='User',
            fields=[
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('email_verified_at', models.DateTimeField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('is_staff', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
            ],
            options={
                'ordering': ('email',),
            },
            managers=[
                ('objects', accounts.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name='Profile',
            fields=[
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name='profile', serialize=False, to=settings.AUTH_USER_MODEL)),
                ('display_name', models.CharField(max_length=80, validators=[django.core.validators.MinLengthValidator(2)])),
                ('course_code', models.CharField(blank=True, max_length=20)),
                ('time_zone', models.CharField(default='Australia/Sydney', max_length=64, validators=[accounts.validators.validate_iana_timezone])),
                ('biography', models.CharField(blank=True, max_length=500)),
                ('avatar_url', models.URLField(blank=True, max_length=2048)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ('display_name', 'user_id'),
            },
        ),
        migrations.CreateModel(
            name='EmailOTPChallenge',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('purpose', models.CharField(choices=[('registration', 'Verify registration'), ('login', 'Verify sign-in')], max_length=16)),
                ('code_hash', models.CharField(max_length=64)),
                ('expires_at', models.DateTimeField()),
                ('attempt_count', models.PositiveSmallIntegerField(default=0)),
                ('max_attempts', models.PositiveSmallIntegerField()),
                ('send_count', models.PositiveSmallIntegerField(default=1)),
                ('last_sent_at', models.DateTimeField()),
                ('consumed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='otp_challenges', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-created_at',),
            },
        ),
        migrations.CreateModel(
            name='LoginThrottle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('account', 'Account'), ('ip', 'IP address')], max_length=16)),
                ('key_digest', models.CharField(max_length=64)),
                ('failure_count', models.PositiveIntegerField(default=0)),
                ('window_started_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('last_failed_at', models.DateTimeField(blank=True, null=True)),
                ('locked_until', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'indexes': [models.Index(fields=['kind', 'key_digest'], name='accounts_throttle_lookup')],
                'constraints': [models.UniqueConstraint(fields=('kind', 'key_digest'), name='accounts_unique_throttle_key')],
            },
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(condition=models.Q(('email', django.db.models.functions.text.Lower('email'))), name='accounts_user_email_lowercase'),
        ),
        migrations.AddIndex(
            model_name='emailotpchallenge',
            index=models.Index(fields=['user', 'purpose', 'created_at'], name='accounts_otp_user_purpose'),
        ),
        migrations.AddConstraint(
            model_name='emailotpchallenge',
            constraint=models.CheckConstraint(condition=models.Q(('max_attempts__gte', 1)), name='accounts_otp_positive_max_attempts'),
        ),
        migrations.AddConstraint(
            model_name='emailotpchallenge',
            constraint=models.CheckConstraint(condition=models.Q(('send_count__gte', 1)), name='accounts_otp_positive_send_count'),
        ),
        migrations.AddConstraint(
            model_name='emailotpchallenge',
            constraint=models.CheckConstraint(condition=models.Q(('attempt_count__lte', models.F('max_attempts'))), name='accounts_otp_attempt_limit'),
        ),
    ]
