import unicodedata
import uuid

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import MinValueValidator
from django.db import models

from datalayer.capture_catalog import KINDS


def normalize_zone(value):
    return "".join(
        c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c)
    ).strip()


def property_reference():
    return "MIA-" + uuid.uuid4().hex[:8].upper()


def default_visit_windows():
    return [
        {"day": day, "start": start, "end": end}
        for day in range(5)
        for start, end in [("10:00", "14:00"), ("16:00", "19:00")]
    ]


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Se requiere un email")
        user = self.model(email=self.normalize_email(email).casefold(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("El administrador debe tener permisos de staff y superusuario")
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=16, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()


class Advisor(models.Model):
    name = models.CharField(max_length=120)
    whatsapp = models.CharField(max_length=16, blank=True)
    telegram_chat_id = models.CharField(max_length=32, blank=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="one_default_advisor",
            )
        ]

    def __str__(self):
        return self.name


class Prospect(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Nuevo"
        ATTENDING = "attending", "En atención"
        NOT_INTERESTED = "not_interested", "Sin interés"
        SCHEDULED = "scheduled", "Cita agendada"

    phone = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=120, blank=True)
    advisor = models.ForeignKey(Advisor, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    criteria = models.JSONField(default=dict)
    criteria_source = models.ForeignKey(
        "Conversation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="criteria_prospects",
    )
    next_step = models.CharField(max_length=500, blank=True)
    automation_paused = models.BooleanField(default=False)
    contact_opted_out = models.BooleanField(default=False)
    properties = models.ManyToManyField("Property", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Property(models.Model):
    class Operation(models.TextChoices):
        RENT = "rent", "Renta"
        SALE = "sale", "Venta"

    class Kind(models.TextChoices):
        HOUSE = "house", "Casa"
        APARTMENT = "apartment", "Departamento"
        LAND = "land", "Terreno"

    reference = models.CharField(max_length=32, unique=True, default=property_reference)
    title = models.CharField(max_length=180)
    operation = models.CharField(max_length=8, choices=Operation.choices)
    kind = models.CharField(
        max_length=24, choices=[(key, value[0]) for key, value in KINDS.items()]
    )
    subtype = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    currency = models.CharField(
        max_length=3, choices=[("MXN", "MXN"), ("USD", "USD")], default="MXN"
    )
    is_presale = models.BooleanField(default=False)
    public_location = models.JSONField(default=dict, blank=True)
    details = models.JSONField(default=dict, blank=True)
    municipality = models.CharField(max_length=100)
    neighborhood = models.CharField(max_length=100)
    public_address = models.CharField(max_length=240, blank=True)
    normalized_zone = models.CharField(max_length=180, db_index=True, editable=False)
    price = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(1)])
    bedrooms = models.PositiveSmallIntegerField(null=True, blank=True)
    bathrooms = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    parking = models.PositiveSmallIntegerField(null=True, blank=True)
    area_m2 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(1)]
    )
    furnished = models.BooleanField(null=True, blank=True)
    accepts_pets = models.BooleanField(null=True, blank=True)
    near_schools = models.BooleanField(null=True, blank=True)
    description = models.TextField(blank=True, max_length=5000)
    photos = models.JSONField(default=list, blank=True)
    internal_notes = models.TextField(blank=True, max_length=5000)
    published = models.BooleanField(default=False, db_index=True)
    advisor = models.ForeignKey(Advisor, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    visit_duration = models.PositiveSmallIntegerField(default=60)
    visit_windows = models.JSONField(default=default_visit_windows)

    def save(self, *args, **kwargs):
        self.normalized_zone = normalize_zone(f"{self.municipality} {self.neighborhood}")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} · {self.title}"


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    browser_id = models.UUIDField(db_index=True, null=True)
    channel = models.CharField(max_length=12, default="website")
    whatsapp_sender = models.CharField(max_length=32, blank=True)
    last_whatsapp_at = models.DateTimeField(null=True)
    context_origin = models.ForeignKey("self", null=True, on_delete=models.SET_NULL)
    intent_started_at = models.DateTimeField(null=True)
    followup_permission = models.BooleanField(null=True)
    prospect = models.ForeignKey(
        Prospect, null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations"
    )
    advisor = models.ForeignKey(Advisor, null=True, blank=True, on_delete=models.SET_NULL)
    interests = models.ManyToManyField(Property, blank=True)
    contact_candidate = models.JSONField(default=dict)
    declared_phone = models.CharField(max_length=16, blank=True)
    contact_name = models.CharField(max_length=120, blank=True)
    name_requested = models.BooleanField(default=False)
    human_requested = models.BooleanField(default=False)
    interest_expressed = models.BooleanField(default=False)
    automation_paused = models.BooleanField(default=False)
    criteria = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=0)
    answered_revision = models.PositiveIntegerField(default=0)
    pending_since = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["whatsapp_sender"],
                condition=~models.Q(whatsapp_sender=""),
                name="unique_whatsapp_sender",
            )
        ]


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=12, choices=[("user", "Usuario"), ("assistant", "Maia")])
    text = models.TextField()
    kind = models.CharField(max_length=24, default="text")
    display_kind = models.CharField(max_length=12, default="message")
    client_message_id = models.UUIDField(null=True, blank=True)
    # Snapshots show exactly what was presented; current detail is read from inventory.
    properties = models.JSONField(default=list)
    presentation = models.JSONField(null=True, blank=True)
    continuity = models.JSONField(null=True, blank=True)
    is_error = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "client_message_id"], name="unique_client_message"
            )
        ]


class Execution(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="executions"
    )
    revision = models.PositiveIntegerField()
    purpose = models.CharField(max_length=20, default="conversation")
    model = models.CharField(max_length=100)
    status = models.CharField(max_length=20, default="running")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    elapsed_ms = models.PositiveIntegerField(default=0)
    tool_events = models.JSONField(default=list)
    error_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="notifications"
    )
    advisor = models.ForeignKey(Advisor, null=True, blank=True, on_delete=models.SET_NULL)
    event_key = models.CharField(max_length=180, unique=True)
    reason = models.CharField(max_length=30)
    summary = models.CharField(max_length=1000, blank=True)
    status = models.CharField(max_length=20, default="pending")
    payload = models.JSONField(default=dict)
    error_code = models.CharField(max_length=100, blank=True)
    telegram_message_id = models.CharField(max_length=40, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ProspectEvent(models.Model):
    prospect = models.ForeignKey(Prospect, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    description = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)


class BookingPolicy(models.Model):
    # One row, edited from the CRM. Defaults also work before the first edit.
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    notice_hours = models.PositiveSmallIntegerField(default=2)
    horizon_days = models.PositiveSmallIntegerField(default=14)


class CalendarConnection(models.Model):
    advisor = models.OneToOneField(Advisor, on_delete=models.PROTECT, related_name="calendar")
    email = models.EmailField()
    subject = models.CharField(max_length=255)
    credentials = models.TextField()  # Fernet encrypted, never serialized by an API.
    connected = models.BooleanField(default=True)
    generation = models.UUIDField(default=uuid.uuid4)
    initiated_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)


class CalendarAuthorization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    advisor = models.ForeignKey(Advisor, on_delete=models.CASCADE)
    actor = models.ForeignKey(User, on_delete=models.CASCADE)
    session_hash = models.CharField(max_length=64)
    state_hash = models.CharField(max_length=64)
    verifier = models.TextField()
    candidate = models.TextField(blank=True)
    email = models.EmailField(blank=True)
    subject = models.CharField(max_length=255, blank=True)
    consumed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class Appointment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name="appointments"
    )
    prospect = models.ForeignKey(Prospect, on_delete=models.PROTECT, related_name="appointments")
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="appointments")
    advisor = models.ForeignKey(Advisor, on_delete=models.PROTECT)
    connection = models.ForeignKey(CalendarConnection, on_delete=models.PROTECT)
    connection_generation = models.UUIDField()
    start = models.DateTimeField()
    end = models.DateTimeField()
    duration = models.PositiveSmallIntegerField(default=60)
    status = models.CharField(max_length=20, default="pending")
    google_id = models.CharField(max_length=64, unique=True, default=uuid.uuid4)
    etag = models.CharField(max_length=255, blank=True)
    # Only the projection of our own event; never other calendar events.
    observed = models.JSONField(default=dict)
    checked_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class AppointmentOperation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.ForeignKey(
        Appointment, on_delete=models.PROTECT, related_name="operations"
    )
    # Unique request key makes double clicks/retries the same business operation.
    request_id = models.UUIDField(unique=True)
    action = models.CharField(max_length=20)
    start = models.DateTimeField()
    end = models.DateTimeField()
    google_id = models.CharField(max_length=64)
    status = models.CharField(max_length=20, default="queued")
    error_code = models.CharField(max_length=100, blank=True)
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    attempts = models.PositiveSmallIntegerField(default=0)
    # Durable attempt marker, saved before any mutating request to Google.
    sent_at = models.DateTimeField(null=True)
    verify_after = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class AppointmentProposal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.OneToOneField(
        Conversation, on_delete=models.CASCADE, related_name="visit_proposal"
    )
    property = models.ForeignKey(Property, on_delete=models.CASCADE)
    appointment = models.ForeignKey(Appointment, null=True, on_delete=models.CASCADE)
    action = models.CharField(max_length=20, default="create")
    start = models.DateTimeField()
    end = models.DateTimeField()
    advisor = models.ForeignKey(Advisor, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now=True)


class FollowupPolicy(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    send_time = models.TimeField(default="11:00")


class FollowupCycle(models.Model):
    prospect = models.ForeignKey(Prospect, on_delete=models.PROTECT, related_name="followup_cycles")
    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT)
    started_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True)
    suspended = models.BooleanField(default=False)
    reason = models.CharField(max_length=100, blank=True)
    permission = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["prospect"],
                condition=models.Q(closed_at__isnull=True),
                name="one_open_followup_cycle",
            )
        ]


class WhatsAppTemplate(models.Model):
    name = models.CharField(max_length=512)
    language = models.CharField(max_length=20)
    body = models.TextField()
    status = models.CharField(max_length=30)
    fields = models.JSONField(default=list)
    synced_at = models.DateTimeField()
    enabled = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["name", "language"], name="unique_whatsapp_template")
        ]


class FollowupAttempt(models.Model):
    cycle = models.ForeignKey(FollowupCycle, on_delete=models.PROTECT, related_name="attempts")
    day = models.PositiveSmallIntegerField()
    due_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=20, default="queued")
    reason = models.CharField(max_length=100, blank=True)
    snapshot = models.CharField(max_length=64, blank=True)
    execution = models.ForeignKey(Execution, null=True, on_delete=models.SET_NULL)
    delivery = models.OneToOneField("WhatsAppDelivery", null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["cycle", "day"], name="unique_cycle_day")]


class WhatsAppDelivery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name="whatsapp_deliveries"
    )
    message = models.ForeignKey(Message, null=True, on_delete=models.PROTECT)
    event_key = models.CharField(max_length=180, unique=True)
    recipient = models.CharField(max_length=32)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default="queued")
    provider_id = models.CharField(max_length=256, blank=True, db_index=True)
    error_code = models.CharField(max_length=100, blank=True)
    revision = models.PositiveIntegerField(null=True)
    sent_at = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)


class WhatsAppEvent(models.Model):
    key = models.CharField(max_length=512, unique=True)
    conversation = models.ForeignKey(Conversation, null=True, on_delete=models.PROTECT)
    payload = models.JSONField(default=dict)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=20, default="queued")
    error_code = models.CharField(max_length=100, blank=True)


class Capture(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="captures")
    advisor = models.ForeignKey(Advisor, null=True, blank=True, on_delete=models.SET_NULL)
    property = models.OneToOneField(
        Property, null=True, blank=True, on_delete=models.PROTECT, related_name="capture"
    )
    data = models.JSONField(default=dict)
    status = models.CharField(max_length=24, default="draft")
    revision = models.PositiveIntegerField(default=0)
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.PROTECT, related_name="reviewed_captures"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    exact_location_approved = models.BooleanField(default=False)
    outside_area_approved = models.BooleanField(default=False)
    review_notes = models.TextField(blank=True)
    valuation = models.CharField(max_length=40, blank=True)
    valuation_notes = models.TextField(blank=True)
    valuation_communicated_at = models.DateTimeField(null=True, blank=True)
    pending_request = models.JSONField(default=dict, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class CaptureAsset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    capture = models.ForeignKey(Capture, on_delete=models.CASCADE, related_name="assets")
    request_id = models.UUIDField()
    kind = models.CharField(max_length=8, choices=[("photo", "Foto"), ("plan", "Plano")])
    file = models.FileField(upload_to="capture")
    content_type = models.CharField(max_length=40)
    position = models.PositiveSmallIntegerField(default=0)
    size = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["capture", "request_id"], name="unique_capture_asset_request"
            )
        ]
        ordering = ["position", "created_at"]


class CaptureAgreement(models.Model):
    capture = models.ForeignKey(Capture, on_delete=models.PROTECT, related_name="agreements")
    version = models.CharField(max_length=40)
    text = models.TextField()
    snapshot = models.JSONField(default=dict)
    accepted_by = models.ForeignKey(User, on_delete=models.PROTECT)
    accepted_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True)


class CaptureEvent(models.Model):
    capture = models.ForeignKey(Capture, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40)
    summary = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class CaptureDelivery(models.Model):
    channel = models.CharField(max_length=12)
    event_key = models.CharField(max_length=180, unique=True)
    capture = models.ForeignKey(
        Capture, null=True, on_delete=models.CASCADE, related_name="deliveries"
    )
    recipient = models.CharField(max_length=254, blank=True)
    subject = models.CharField(max_length=180)
    body = models.TextField()
    attachment = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, default="pending")
    error_code = models.CharField(max_length=80, blank=True)
    provider = models.CharField(max_length=16, blank=True)
    provider_id = models.CharField(max_length=128, blank=True, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class CaptureMailEvent(models.Model):
    event_id = models.CharField(max_length=200, unique=True)
    provider_id = models.CharField(max_length=128, db_index=True)
    event_type = models.CharField(max_length=40)
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)


class AccountThrottle(models.Model):
    key = models.CharField(max_length=64, unique=True)
    started_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)


class GoogleSearchSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    expires_at = models.DateTimeField()
    completed = models.BooleanField(default=False)


class GoogleLocation(models.Model):
    """Provider results live here, never in contract or conversation snapshots."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, null=True, on_delete=models.CASCADE)
    place_id = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=16, default="google")
    zone_key = models.CharField(max_length=64, blank=True, db_index=True)
    latitude = models.FloatField(null=True)
    longitude = models.FloatField(null=True)
    expires_at = models.DateTimeField(db_index=True)
    refreshed_at = models.DateTimeField(auto_now=True)


class GoogleLocationUsage(models.Model):
    month = models.CharField(max_length=7)
    sku = models.CharField(max_length=24)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["month", "sku"], name="google_usage_month_sku")
        ]
