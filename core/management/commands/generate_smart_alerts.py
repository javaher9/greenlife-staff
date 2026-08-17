from django.core.management.base import BaseCommand
from core.smart_alerts import generate_smart_alerts

class Command(BaseCommand):
    help = "Generate deduplicated operational alerts for Staff."

    def handle(self, *args, **options):
        count = generate_smart_alerts()
        self.stdout.write(self.style.SUCCESS(f"{count} smart alerts created"))
