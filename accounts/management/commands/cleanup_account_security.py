"""Remove expired recoveries/devices and old throttle keys; keep audit evidence."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import AccountDeviceSession, AccountSecurityThrottle, AccountSecurityToken


class Command(BaseCommand):
    help = "Delete expired account security links, device registrations and old fixed-window counters."

    def handle(self, *args, **options):
        now = timezone.now()
        tokens, _ = AccountSecurityToken.objects.filter(expires_at__lt=now - timedelta(days=1)).delete()
        devices, _ = AccountDeviceSession.objects.filter(expires_at__lt=now).delete()
        throttles, _ = AccountSecurityThrottle.objects.filter(window_started_at__lt=now - timedelta(days=7)).delete()
        self.stdout.write(self.style.SUCCESS(f"Removed {tokens} expired security links, {devices} device registrations and {throttles} old throttle counters."))
