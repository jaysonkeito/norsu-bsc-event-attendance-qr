from django.conf import settings
from django.db import models
from django.utils import timezone


class College(models.Model):
    """College model for managing college names dynamically"""
    code = models.CharField(max_length=20, unique=True, help_text="Short code (e.g., CCJE, CTED)")
    name = models.CharField(max_length=200, help_text="Full college name")
    is_active = models.BooleanField(default=True, help_text="Active colleges appear in dropdowns")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "College"
        verbose_name_plural = "Colleges"

    def __str__(self):
        return f"{self.code} - {self.name}"


class Program(models.Model):
    """Program model for managing programs within colleges"""
    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="programs")
    code = models.CharField(max_length=50, help_text="Program code (e.g., BSCS, BSIT)")
    name = models.CharField(max_length=200, help_text="Full program name")
    is_active = models.BooleanField(default=True, help_text="Active programs appear in dropdowns")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["college__code", "code"]
        unique_together = ["college", "code"]
        verbose_name = "Program"
        verbose_name_plural = "Programs"

    def __str__(self):
        return f"{self.college.code} - {self.code}: {self.name}"


class Student(models.Model):
    student_id = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    sex = models.CharField(max_length=10)
    college = models.ForeignKey(
        College,
        on_delete=models.PROTECT,
        related_name="students",
        null=True,
        blank=True,
    )
    program = models.ForeignKey(
        Program,
        on_delete=models.PROTECT,
        related_name="students",
        null=True,
        blank=True,
    )
    year = models.IntegerField()
    major = models.CharField(max_length=200)

    class Meta:
        ordering = ["name", "student_id"]

    def __str__(self):
        return f"{self.student_id} - {self.name}"

    @property
    def college_code(self):
        return self.college.code if self.college_id else ""

    @property
    def program_code(self):
        return self.program.code if self.program_id else ""


class Event(models.Model):
    """Campus/school event or session used for attendance scanning."""
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    event_date = models.DateField(default=timezone.localdate)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True, default="")
    picture = models.ImageField(
        upload_to="events/",
        blank=True,
        null=True,
        help_text="Optional image shown on the scanner for this event",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive events are hidden from scanner selection",
    )
    is_current = models.BooleanField(
        default=False,
        help_text="Marks the event currently used for live scanning",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-event_date", "-start_time", "title"]
        verbose_name = "Event"
        verbose_name_plural = "Events"

    def __str__(self):
        return f"{self.title} ({self.event_date})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_current:
            Event.objects.filter(is_current=True).exclude(pk=self.pk).update(is_current=False)

    @property
    def display_window(self):
        parts = [self.event_date.strftime("%b %d, %Y")]
        if self.start_time and self.end_time:
            parts.append(
                f"{self.start_time.strftime('%I:%M %p')} - {self.end_time.strftime('%I:%M %p')}"
            )
        elif self.start_time:
            parts.append(self.start_time.strftime("%I:%M %p"))
        if self.location:
            parts.append(self.location)
        return " · ".join(parts)


class Attendance(models.Model):
    SOURCE_CAMERA = "camera"
    SOURCE_DEVICE = "device"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [
        (SOURCE_CAMERA, "Camera"),
        (SOURCE_DEVICE, "Scanner Device"),
        (SOURCE_MANUAL, "Manual Entry"),
    ]

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_records",
    )
    status = models.CharField(max_length=10, choices=[("IN", "IN"), ("OUT", "OUT")])
    timestamp = models.DateTimeField(default=timezone.now)
    event_label = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Optional event/session label (e.g. Morning Assembly)",
    )
    scanned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scans_recorded",
    )
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_CAMERA,
    )

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.student.name} - {self.status} @ {self.timestamp.strftime('%Y-%m-%d %I:%M %p')}"
