from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
from django.db.models import Q, Count
from django.utils import timezone
from django.conf import settings
from datetime import date, datetime, timedelta
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from PIL import Image, ImageDraw, ImageFont
import os
import io
import json
import base64
import qrcode
import glob

from .models import Student, Attendance, Event, College, Program
from .forms import StudentForm, StudentUploadForm
from .student_import import import_students_from_file
from .student_export import export_students_response
from .qr_codes import (
    generate_qr_with_label,
    serialize_qr_list,
    get_filtered_students,
    export_qr_response,
)


def build_calendar_data(today=None):
    """Shared payload for the live calendar widget."""
    from django.urls import reverse

    today = today or date.today()
    events = Event.objects.filter(is_active=True).order_by("event_date", "start_time", "title")
    calendar_events = [
        {
            "id": event.id,
            "title": event.title,
            "date": event.event_date.isoformat(),
            "start_time": event.start_time.strftime("%H:%M") if event.start_time else "",
            "end_time": event.end_time.strftime("%H:%M") if event.end_time else "",
            "location": event.location or "",
            "is_current": event.is_current,
            "display_window": event.display_window,
        }
        for event in events
    ]

    activity_start = today - timedelta(days=90)
    activity_end = today + timedelta(days=60)
    attendance_days = (
        Attendance.objects.filter(timestamp__date__range=[activity_start, activity_end])
        .values("timestamp__date")
        .annotate(count=Count("id"))
    )
    attendance_by_date = {
        row["timestamp__date"].isoformat(): row["count"]
        for row in attendance_days
        if row["timestamp__date"]
    }

    return {
        "today": today.isoformat(),
        "events": calendar_events,
        "attendance_by_date": attendance_by_date,
        "manage_events_url": reverse("manage_events"),
    }, Event.objects.filter(is_current=True, is_active=True).first()


def build_event_analytics(students_qs, scanned_records, report_rows=None):
    """
    Comprehensive analytics for event attendance.
    Prefer report_rows (per-student status) when available for accurate counts.
    """
    expected = students_qs.count() if hasattr(students_qs, "count") else len(students_qs)

    if report_rows is not None:
        attended = sum(1 for r in report_rows if r.get("status") != "ABSENT")
        completed = sum(1 for r in report_rows if r.get("status") == "COMPLETED")
        still_inside = sum(1 for r in report_rows if r.get("status") == "IN")
        absent = sum(1 for r in report_rows if r.get("status") == "ABSENT")
    else:
        in_ids = set(scanned_records.filter(status="IN").values_list("student_id", flat=True))
        out_ids = set(scanned_records.filter(status="OUT").values_list("student_id", flat=True))
        attended = len(in_ids)
        completed = len(in_ids & out_ids)
        still_inside = len(in_ids - out_ids)
        absent = max(expected - attended, 0)

    attendance_rate = round((attended / expected) * 100, 1) if expected else 0.0
    completion_rate = round((completed / attended) * 100, 1) if attended else 0.0

    total_scans = scanned_records.count()
    total_in_scans = scanned_records.filter(status="IN").count()
    total_out_scans = scanned_records.filter(status="OUT").count()

    first_scan = scanned_records.order_by("timestamp").first()
    last_scan = scanned_records.order_by("-timestamp").first()

    # Peak check-in hour
    peak_hour_label = "-"
    peak_hour_count = 0
    hour_counts = {}
    for ts in scanned_records.filter(status="IN").values_list("timestamp", flat=True):
        try:
            local_ts = timezone.localtime(ts)
        except Exception:
            local_ts = ts
        hour = local_ts.hour
        hour_counts[hour] = hour_counts.get(hour, 0) + 1
    if hour_counts:
        peak_hour = max(hour_counts, key=hour_counts.get)
        peak_hour_count = hour_counts[peak_hour]
        suffix = "AM" if peak_hour < 12 else "PM"
        display_hour = peak_hour % 12 or 12
        peak_hour_label = f"{display_hour}:00 {suffix}"

    # Breakdowns from attended students (those with IN)
    attended_student_ids = scanned_records.filter(status="IN").values_list("student_id", flat=True).distinct()
    attended_students = Student.objects.filter(id__in=attended_student_ids)

    college_rows = list(
        attended_students.values("college__code").annotate(count=Count("id")).order_by("-count")[:6]
    )
    year_rows = list(
        attended_students.values("year").annotate(count=Count("id")).order_by("year")
    )
    sex_rows = list(
        attended_students.values("sex").annotate(count=Count("id")).order_by("-count")
    )

    max_college = max((r["count"] for r in college_rows), default=0) or 1
    college_breakdown = [
        {
            "label": r["college__code"] or "Unknown",
            "count": r["count"],
            "percent": round((r["count"] / attended) * 100, 1) if attended else 0,
            "bar": round((r["count"] / max_college) * 100, 1),
        }
        for r in college_rows
    ]

    max_year = max((r["count"] for r in year_rows), default=0) or 1
    year_breakdown = [
        {
            "label": f"Year {r['year']}",
            "count": r["count"],
            "percent": round((r["count"] / attended) * 100, 1) if attended else 0,
            "bar": round((r["count"] / max_year) * 100, 1),
        }
        for r in year_rows
    ]

    sex_map = {"M": "Male", "F": "Female", "Male": "Male", "Female": "Female"}
    sex_breakdown = [
        {
            "label": sex_map.get(r["sex"], r["sex"] or "Other"),
            "count": r["count"],
            "percent": round((r["count"] / attended) * 100, 1) if attended else 0,
        }
        for r in sex_rows
    ]

    def fmt_time(rec):
        if not rec:
            return "-"
        try:
            return timezone.localtime(rec.timestamp).strftime("%I:%M %p")
        except Exception:
            return rec.timestamp.strftime("%I:%M %p")

    return {
        "expected": expected,
        "attended": attended,
        "absent": absent,
        "still_inside": still_inside,
        "completed": completed,
        "attendance_rate": attendance_rate,
        "completion_rate": completion_rate,
        "total_scans": total_scans,
        "total_in_scans": total_in_scans,
        "total_out_scans": total_out_scans,
        "first_checkin": fmt_time(first_scan),
        "last_activity": fmt_time(last_scan),
        "peak_hour": peak_hour_label,
        "peak_hour_count": peak_hour_count,
        "college_breakdown": college_breakdown,
        "year_breakdown": year_breakdown,
        "sex_breakdown": sex_breakdown,
        # backward-compatible keys for older JS
        "present_in": still_inside,
        "present_out": completed,
    }


@staff_member_required
def dashboard_home(request):
    """Clean dashboard with only analytics and shortcuts"""
    today = date.today()

    # Get all students
    students = Student.objects.all()

    # Get today's attendance
    scanned_records = Attendance.objects.filter(timestamp__date=today).order_by('-timestamp')

    # Count stats
    today_scanned_students = scanned_records.values_list("student__id", flat=True).distinct()
    not_scanned = students.exclude(id__in=today_scanned_students)
    present_in = scanned_records.filter(status="IN")
    present_out = scanned_records.filter(status="OUT")

    # Last 7 days attendance overview (real chart data)
    week_labels = []
    week_check_in = []
    week_check_out = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        week_labels.append(day.strftime("%a"))
        day_qs = Attendance.objects.filter(timestamp__date=day)
        week_check_in.append(day_qs.filter(status="IN").count())
        week_check_out.append(day_qs.filter(status="OUT").count())

    # College breakdown: unique students who attended today
    college_rows = list(
        scanned_records.values("student__college__code")
        .annotate(count=Count("student_id", distinct=True))
        .order_by("-count")
    )
    if not college_rows:
        # Fallback so chart still reflects roster composition
        college_rows = list(
            students.values("college__code")
            .annotate(count=Count("id"))
            .order_by("-count")[:8]
        )
        college_labels = [row["college__code"] or "Unknown" for row in college_rows]
        college_counts = [row["count"] for row in college_rows]
    else:
        college_labels = [row["student__college__code"] or "Unknown" for row in college_rows]
        college_counts = [row["count"] for row in college_rows]

    chart_data = {
        "week_labels": week_labels,
        "week_check_in": week_check_in,
        "week_check_out": week_check_out,
        "college_labels": college_labels,
        "college_counts": college_counts,
    }

    calendar_data, current_event = build_calendar_data(today)

    return render(request, "qrapp/dashboard_home.html", {
        "students": students,
        "scanned_records": scanned_records,
        "not_scanned": not_scanned,
        "present_in": present_in,
        "present_out": present_out,
        "chart_data_json": json.dumps(chart_data),
        "calendar_data_json": json.dumps(calendar_data),
        "current_event": current_event,
    })

@staff_member_required
def admin_dashboard(request):
    from .models import College
    
    # Date and Time Filters
    date_filter = request.GET.get("date")
    start_date_filter = request.GET.get("start_date")
    end_date_filter = request.GET.get("end_date")
    start_time_filter = request.GET.get("start_time")
    end_time_filter = request.GET.get("end_time")

    # Get the original filters that were missing
    year_filter = request.GET.get("year")
    program_filter = request.GET.get("program")
    college_filter = request.GET.get("college")
    search_query = request.GET.get("search")

    # Default to today if no date specified
    if date_filter:
        try:
            selected_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
        except ValueError:
            selected_date = date.today()
    else:
        selected_date = date.today()

    # Filter students
    students = Student.objects.all()
    if year_filter:
        students = students.filter(year=year_filter)
    if program_filter:
        students = students.filter(program__code=program_filter)
    if college_filter:
        students = students.filter(college__code=college_filter)
    if search_query:
        students = students.filter(
            Q(name__icontains=search_query) |
            Q(student_id__icontains=search_query) |
            Q(program__code__icontains=search_query) |
            Q(year__icontains=search_query)
        )

    # Attendance filtering with date range and time
    scanned_records = Attendance.objects.all()

    # Single date filter
    if date_filter:
        scanned_records = scanned_records.filter(timestamp__date=selected_date)

    # Date range filter
    if start_date_filter and end_date_filter:
        try:
            start_date = datetime.strptime(start_date_filter, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_filter, "%Y-%m-%d").date()
            scanned_records = scanned_records.filter(
                timestamp__date__range=[start_date, end_date]
            )
        except ValueError:
            pass

    # Default to selected day (today) for event view when no date filters set
    if not date_filter and not (start_date_filter and end_date_filter):
        scanned_records = scanned_records.filter(timestamp__date=selected_date)

    # Time filtering (applies on single-day event window)
    if start_time_filter and not (start_date_filter and end_date_filter):
        try:
            start_datetime = datetime.combine(
                selected_date, datetime.strptime(start_time_filter, "%H:%M").time()
            )
            scanned_records = scanned_records.filter(timestamp__gte=start_datetime)
        except ValueError:
            pass

    if end_time_filter and not (start_date_filter and end_date_filter):
        try:
            end_datetime = datetime.combine(
                selected_date, datetime.strptime(end_time_filter, "%H:%M").time()
            )
            scanned_records = scanned_records.filter(timestamp__lte=end_datetime)
        except ValueError:
            pass

    # Apply year and course filters to attendance records
    if year_filter:
        scanned_records = scanned_records.filter(student__year=year_filter)
    if program_filter:
        scanned_records = scanned_records.filter(student__program__code=program_filter)
    if college_filter:
        scanned_records = scanned_records.filter(student__college__code=college_filter)

    # IN and OUT
    present_in = scanned_records.filter(status="IN")
    present_out = scanned_records.filter(status="OUT")

    # Students who have NOT scanned for the selected event window
    event_scanned_students = scanned_records.values_list("student__id", flat=True).distinct()
    not_scanned = students.exclude(id__in=event_scanned_students)

    # Get unique courses and colleges from database and student records
    unique_programs = Student.objects.values_list("program__code", flat=True).distinct().order_by("program__code")
    
    # Get colleges from College model (active ones)
    active_colleges = College.objects.filter(is_active=True).order_by('code')
    unique_colleges = [college.code for college in active_colleges]
    
    # Also add any colleges from existing students that might not be in College table
    student_colleges = Student.objects.values_list("college__code", flat=True).distinct()
    for college in student_colleges:
        if college and college not in unique_colleges:
            unique_colleges.append(college)
    unique_colleges = sorted(unique_colleges)
    
    # Build college-program mapping from Program model
    from .models import Program
    college_programs = {}
    for college in active_colleges:
        programs = Program.objects.filter(college=college, is_active=True).order_by('code')
        college_programs[college.code] = [{'code': p.code, 'name': p.name} for p in programs]
    
    # Convert to JSON for JavaScript
    import json
    college_programs_json = json.dumps(college_programs)

    student_programs_by_college = {}
    for college_code, program_code in Student.objects.values_list("college__code", "program__code").distinct():
        if not college_code:
            continue
        student_programs_by_college.setdefault(college_code, [])
        if program_code and program_code not in student_programs_by_college[college_code]:
            student_programs_by_college[college_code].append(program_code)
    for college_code in student_programs_by_college:
        student_programs_by_college[college_code].sort()
    student_programs_by_college_json = json.dumps(student_programs_by_college)
    
    # Get pending users for approval tab
    from django.contrib.auth.models import User
    pending_users = User.objects.filter(is_active=False)
    all_users = User.objects.all().order_by('-date_joined')
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()

    # Helper: make datetime timezone-aware/local
    def to_local(dt):
        if not dt:
            return None
        try:
            return timezone.localtime(dt)
        except Exception:
            return dt

    # Build report data with filtered records
    student_report_data = []
    for student in students:
        student_attendance = scanned_records.filter(student=student).order_by("timestamp")

        time_in = None
        time_out = None
        status = "ABSENT"

        if student_attendance.exists():
            for record in student_attendance:
                if record.status == "IN" and time_in is None:
                    time_in = record.timestamp
                elif record.status == "OUT":
                    time_out = record.timestamp

            if time_in and time_out:
                status = "COMPLETED"
            elif time_in:
                status = "IN"

        # Localize times
        time_in_local = to_local(time_in)
        time_out_local = to_local(time_out)
        date_obj = time_out_local or time_in_local

        student_report_data.append({
            "student": student,
            "time_in": time_in_local,
            "time_out": time_out_local,
            "date": date_obj,
            "status": status
        })

    analytics = build_event_analytics(students, scanned_records, student_report_data)

    event_label = selected_date.strftime("%b %d, %Y")
    if start_date_filter and end_date_filter:
        event_label = f"{start_date_filter} → {end_date_filter}"
    elif date_filter:
        event_label = selected_date.strftime("%b %d, %Y")

    calendar_data, current_event = build_calendar_data(date.today())

    return render(request, "qrapp/admin_dashboard.html", {
        "today": date.today(),
        "selected_date": selected_date,
        "event_label": event_label,
        "start_date_filter": start_date_filter,
        "end_date_filter": end_date_filter,
        "start_time_filter": start_time_filter,
        "end_time_filter": end_time_filter,
        "year_filter": year_filter,
        "program_filter": program_filter,
        "college_filter": college_filter,
        "students": students,
        "scanned_records": scanned_records,
        "present_in": present_in,
        "search_query": search_query,
        "present_out": present_out,
        "not_scanned": not_scanned,
        "unique_programs": unique_programs,
        "unique_colleges": unique_colleges,
        "student_report_data": student_report_data,
        "college_programs_json": college_programs_json,
        "student_programs_by_college_json": student_programs_by_college_json,
        "pending_users": pending_users,
        "all_users": all_users,
        "total_users": total_users,
        "active_users": active_users,
        "analytics": analytics,
        "calendar_data_json": json.dumps(calendar_data),
        "current_event": current_event,
    })


# ---------------- SCANNER ----------------
@login_required
def scanner_view(request):
    events = Event.objects.filter(is_active=True).order_by("-is_current", "-event_date", "title")
    current_event = events.filter(is_current=True).first() or events.filter(event_date=date.today()).first()
    return render(request, "qrapp/scanner.html", {
        "events": events,
        "current_event": current_event,
    })

# ---------------- data security ----------------

@login_required
def get_students_data(request):
    user = request.user

    if user.is_staff or user.is_superuser:
        # staff sees full dataset
        students = Student.objects.all()
        student_data = [
            {
                "id": s.id,
                "student_id": s.student_id,
                "name": s.name,
                "program": s.program_code,
                "year": s.year,
                "section": s.section,
                # add other fields if needed
            }
            for s in students
        ]
        return JsonResponse({"success": True, "data": student_data})

    # Non-staff: only return their own record (if they have one)
    try:
        student = Student.objects.get(user_profile__user=user)  # adapt to your model relation
    except Student.DoesNotExist:
        return JsonResponse({"success": False, "error": "Not allowed or no student record"}, status=403)

    data = {
        "id": student.id,
        "student_id": student.student_id,
        "name": student.name,
        "program": student.program_code,
        "year": student.year,
        "section": student.section,
    }
    return JsonResponse({"success": True, "data": data})



@login_required
def save_scan(request):
    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "message": "Invalid request method.",
            "color": "warning"
        })

    from .qr_security import resolve_scanned_student_id

    student_id, token_error = resolve_scanned_student_id(
        decoded_text=request.POST.get("qr_payload", ""),
        student_id=request.POST.get("student_id", ""),
        qr_token=request.POST.get("qr_token", ""),
    )
    if token_error:
        return JsonResponse({
            "success": False,
            "message": token_error,
            "color": "warning"
        })

    device_time_str = request.POST.get("local_time")
    manual_status = request.POST.get("manual_status")
    event_label = (request.POST.get("event_label") or "").strip()[:200]
    event_id = (request.POST.get("event_id") or "").strip()
    source = (request.POST.get("source") or "").strip().lower()
    valid_sources = {
        Attendance.SOURCE_CAMERA,
        Attendance.SOURCE_DEVICE,
        Attendance.SOURCE_MANUAL,
    }
    if source not in valid_sources:
        source = Attendance.SOURCE_MANUAL if manual_status else Attendance.SOURCE_CAMERA

    event = None
    if not event_id:
        return JsonResponse({
            "success": False,
            "message": "Please select an event before scanning attendance.",
            "color": "warning",
        })

    event = Event.objects.filter(id=event_id, is_active=True).first()
    if not event:
        return JsonResponse({
            "success": False,
            "message": "Selected event was not found or is inactive.",
            "color": "warning",
        })
    if not event_label:
        event_label = event.title

    try:
        student = Student.objects.get(student_id=student_id)
    except Student.DoesNotExist:
        return JsonResponse({
            "success": False,
            "message": "Student not found.",
            "color": "danger"
        })

    now = datetime.now()
    if device_time_str:
        try:
            now = datetime.fromisoformat(device_time_str)
        except ValueError:
            now = datetime.now()

    today = now.date()
    if event:
        scope_records = Attendance.objects.filter(student=student, event=event).order_by("timestamp")
    else:
        scope_records = Attendance.objects.filter(
            student=student,
            timestamp__date=today
        ).order_by("timestamp")

    def create_attendance(status):
        return Attendance.objects.create(
            student=student,
            event=event,
            status=status,
            timestamp=now,
            event_label=event_label,
            scanned_by=request.user if request.user.is_authenticated else None,
            source=source,
        )

    event_note = f" ({event.title})" if event else ""

    if manual_status:
        create_attendance(manual_status)
        return JsonResponse({
            "success": True,
            "message": f"{student.name} manually marked {manual_status}{event_note} at {now.strftime('%I:%M:%S %p')}",
            "status": manual_status,
            "color": "success" if manual_status == "IN" else "info",
            "student_name": student.name,
            "time": now.strftime('%I:%M:%S %p')
        })

    if not scope_records.exists():
        create_attendance("IN")
        return JsonResponse({
            "success": True,
            "message": f"{student.name} marked IN{event_note} at {now.strftime('%I:%M:%S %p')}",
            "status": "IN",
            "color": "success",
            "student_name": student.name,
            "time": now.strftime('%I:%M:%S %p')
        })

    last_record = scope_records.last()

    if last_record.status == "IN":
        if now - last_record.timestamp < timedelta(hours=1):
            return JsonResponse({
                "success": False,
                "message": f"{student.name} cannot log OUT yet. Wait at least 1 hour.",
                "color": "warning",
                "student_name": student.name
            })
        create_attendance("OUT")
        return JsonResponse({
            "success": True,
            "message": f"{student.name} marked OUT{event_note} at {now.strftime('%I:%M:%S %p')}",
            "status": "OUT",
            "color": "info",
            "student_name": student.name,
            "time": now.strftime('%I:%M:%S %p')
        })

    create_attendance("IN")
    return JsonResponse({
        "success": True,
        "message": f"{student.name} marked IN again{event_note} at {now.strftime('%I:%M:%S %p')}",
        "status": "IN",
        "color": "success",
        "student_name": student.name,
        "time": now.strftime('%I:%M:%S %p')
    })


@staff_member_required
def edit_student(request, student_id):
    from .models import College
    from .college_program import resolve_college_and_program

    student = get_object_or_404(Student, id=student_id)
    if request.method == "POST":
        # Check if it's an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.POST.get('name'):
            try:
                college, program = resolve_college_and_program(
                    request.POST.get("college"),
                    request.POST.get("program"),
                )
                student.name = request.POST.get("name")
                student.sex = request.POST.get("sex")
                student.college = college
                student.program = program
                student.year = request.POST.get("year")
                student.section = request.POST.get("section")
                student.save()

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': True, 'message': 'Student updated successfully!'})
                return redirect("admin_dashboard")
            except Exception as e:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': str(e)}, status=400)
                messages.error(request, f'Error updating student: {str(e)}')
        else:
            return redirect("admin_dashboard")

    active_colleges = College.objects.filter(is_active=True).order_by('code')
    college_choices = [(college.code, f"{college.code} - {college.name}") for college in active_colleges]

    return render(request, "qrapp/edit_student.html", {
        "student": student,
        "college_choices": college_choices
    })


@staff_member_required
def delete_student(request, student_id):
    student = get_object_or_404(Student, id=student_id)

    if request.method == "POST":
        password = request.POST.get('adminPassword', '')

        # Confirm with the currently logged-in staff user's password
        if request.user.check_password(password):
            student.delete()
            messages.success(request, f'Student {student.name} has been deleted successfully.')
            return redirect("admin_dashboard")
        else:
            messages.error(request, 'Incorrect password. Please try again.')

    return render(request, "qrapp/delete_student.html", {"student": student})


@staff_member_required
def ajax_student_list(request):
    """AJAX view to return filtered student list"""
    try:
        if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})

        year_filter = request.GET.get("year")
        program_filter = request.GET.get("program")
        college_filter = request.GET.get("college")
        search_query = request.GET.get("search")
        status_filter = request.GET.get("status")
        sort_filter = request.GET.get("sort", "name")
        today = date.today()

        # Filter students
        students = Student.objects.all()
        if year_filter:
            students = students.filter(year=year_filter)
        if program_filter:
            students = students.filter(program__code=program_filter)
        if college_filter:
            students = students.filter(college__code=college_filter)
        if search_query:
            students = students.filter(
                Q(name__icontains=search_query) |
                Q(student_id__icontains=search_query) |
                Q(program__code__icontains=search_query) |
                Q(year__icontains=search_query)
            )

        # Apply sorting
        if sort_filter == "name":
            students = students.order_by("name")
        elif sort_filter == "id":
            students = students.order_by("student_id")
        elif sort_filter == "program":
            students = students.order_by("program__code")
        elif sort_filter == "year":
            students = students.order_by("year")

        # Get attendance data for today
        scanned_records = Attendance.objects.filter(timestamp__date=today)
        if year_filter:
            scanned_records = scanned_records.filter(student__year=year_filter)
        if program_filter:
            scanned_records = scanned_records.filter(student__program__code=program_filter)
        if college_filter:
            scanned_records = scanned_records.filter(student__college__code=college_filter)

        present_in = scanned_records.filter(status="IN")
        present_out = scanned_records.filter(status="OUT")

        # Get scanned student IDs
        scanned_students = scanned_records.values_list("student__id", flat=True)
        not_scanned = students.exclude(id__in=scanned_students)

        # Analytics against filtered roster (before status narrowing)
        roster_students = students
        stats = build_event_analytics(roster_students, scanned_records)

        # Apply status filter if specified
        if status_filter:
            if status_filter == "present":
                students = students.filter(id__in=scanned_students)
            elif status_filter == "absent":
                students = not_scanned
            elif status_filter == "in":
                students = students.filter(id__in=present_in.values_list('student__id', flat=True))
            elif status_filter == "out":
                students = students.filter(id__in=present_out.values_list('student__id', flat=True))

        # Prepare student data for JSON response
        student_data = []
        for student in students:
            # Get today's attendance for this student
            today_attendance = Attendance.objects.filter(
                student=student,
                timestamp__date=today
            ).order_by("timestamp")

            time_in = None
            time_out = None
            status = "ABSENT"

            if today_attendance.exists():
                for record in today_attendance:
                    if record.status == "IN" and time_in is None:
                        time_in = record.timestamp
                    elif record.status == "OUT":
                        time_out = record.timestamp

                if time_in and time_out:
                    status = "COMPLETED"
                elif time_in:
                    status = "IN"

            student_data.append({
                'id': student.id,
                'student_id': student.student_id,
                'name': student.name,
                'college': student.college_code,
                'program': student.program_code,
                'year': student.year,
                'section': student.section,
                'time_in': time_in.strftime("%I:%M:%S %p")if time_in else None,
                'time_out': time_out.strftime("%H:%M:%S") if time_out else None,
                'status': status
            })

        return JsonResponse({
            'success': True,
            'students': student_data,
            'stats': stats
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@staff_member_required
def ajax_dashboard_data(request):
    try:
        if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})

        year_filter = request.GET.get("year")
        program_filter = request.GET.get("program")
        college_filter = request.GET.get("college")
        search_query = request.GET.get("search")
        status_filter = request.GET.get("status")
        date_filter = request.GET.get("date")
        start_date_filter = request.GET.get("start_date")
        end_date_filter = request.GET.get("end_date")
        start_time_filter = request.GET.get("start_time")
        end_time_filter = request.GET.get("end_time")

        # Filter students first
        students = Student.objects.all()
        if year_filter:
            students = students.filter(year=year_filter)
        if program_filter:
            students = students.filter(program__code=program_filter)
        if college_filter:
            students = students.filter(college__code=college_filter)
        if search_query:
            students = students.filter(
                Q(name__icontains=search_query) |
                Q(student_id__icontains=search_query) |
                Q(program__code__icontains=search_query) |
                Q(year__icontains=search_query)
            )

        # Date filtering logic
        scanned_records = Attendance.objects.all()
        selected_date = date.today()

        if date_filter:
            try:
                selected_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
                scanned_records = scanned_records.filter(timestamp__date=selected_date)
            except ValueError:
                scanned_records = scanned_records.filter(timestamp__date=date.today())

        if start_date_filter and end_date_filter:
            try:
                start_date = datetime.strptime(start_date_filter, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_filter, "%Y-%m-%d").date()
                scanned_records = scanned_records.filter(
                    timestamp__date__range=[start_date, end_date]
                )
            except ValueError:
                pass
        elif not date_filter:
            scanned_records = scanned_records.filter(timestamp__date=selected_date)

        # Time filtering
        if start_time_filter and not (start_date_filter and end_date_filter):
            try:
                event_date = selected_date
                if date_filter:
                    event_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
                start_datetime = datetime.combine(
                    event_date,
                    datetime.strptime(start_time_filter, "%H:%M").time()
                )
                scanned_records = scanned_records.filter(timestamp__gte=start_datetime)
            except ValueError:
                pass

        if end_time_filter and not (start_date_filter and end_date_filter):
            try:
                event_date = selected_date
                if date_filter:
                    event_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
                end_datetime = datetime.combine(
                    event_date,
                    datetime.strptime(end_time_filter, "%H:%M").time()
                )
                scanned_records = scanned_records.filter(timestamp__lte=end_datetime)
            except ValueError:
                pass

        # Apply year and course filters to attendance records
        if year_filter:
            scanned_records = scanned_records.filter(student__year=year_filter)
        if program_filter:
            scanned_records = scanned_records.filter(student__program__code=program_filter)
        if college_filter:
            scanned_records = scanned_records.filter(student__college__code=college_filter)

        # Apply status filter if specified
        display_records = scanned_records
        if status_filter:
            if status_filter == "in":
                display_records = scanned_records.filter(status="IN")
            elif status_filter == "out":
                display_records = scanned_records.filter(status="OUT")

        # Prepare record data for JSON response
        record_data = []
        for record in display_records:
            record_data.append({
                'student_id': record.student.student_id,
                'name': record.student.name,
                'college': record.student.college_code,
                'program': record.student.program_code,
                'year': record.student.year,
                'section': record.student.section,
                'status': record.status,
                'date': record.timestamp.strftime("%Y-%m-%d"),
                'timestamp': record.timestamp.strftime("%I:%M:%S %p")
            })

        # Build report-style rows for accurate analytics
        report_rows = []
        for student in students:
            student_attendance = scanned_records.filter(student=student).order_by("timestamp")
            time_in = None
            time_out = None
            status = "ABSENT"
            if student_attendance.exists():
                for record in student_attendance:
                    if record.status == "IN" and time_in is None:
                        time_in = record.timestamp
                    elif record.status == "OUT":
                        time_out = record.timestamp
                if time_in and time_out:
                    status = "COMPLETED"
                elif time_in:
                    status = "IN"
            report_rows.append({"status": status})

        stats = build_event_analytics(students, scanned_records, report_rows)

        # Add date info for display
        date_info = ""
        if date_filter:
            date_info = f"Showing attendance for {date_filter}"
        elif start_date_filter and end_date_filter:
            date_info = f"Showing attendance from {start_date_filter} to {end_date_filter}"
        else:
            date_info = f"Showing today's attendance - {date.today()}"

        return JsonResponse({
            'success': True,
            'records': record_data,
            'stats': stats,
            'date_info': date_info
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@staff_member_required
def ajax_reports_data(request):
    """AJAX view to return filtered reports data"""
    try:
        if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})

        year_filter = request.GET.get("year")
        program_filter = request.GET.get("program")
        college_filter = request.GET.get("college")
        search_query = request.GET.get("search")
        status_filter = request.GET.get("status")
        sort_filter = request.GET.get("sort", "name")
        date_filter = request.GET.get("date")
        start_date_filter = request.GET.get("start_date")
        end_date_filter = request.GET.get("end_date")
        start_time_filter = request.GET.get("start_time")
        end_time_filter = request.GET.get("end_time")

        # Filter students
        students = Student.objects.all()
        if year_filter:
            students = students.filter(year=year_filter)
        if program_filter:
            students = students.filter(program__code=program_filter)
        if college_filter:
            students = students.filter(college__code=college_filter)
        if search_query:
            students = students.filter(
                Q(name__icontains=search_query) |
                Q(student_id__icontains=search_query) |
                Q(program__code__icontains=search_query) |
                Q(year__icontains=search_query)
            )

        # Apply sorting
        if sort_filter == "name":
            students = students.order_by("name")
        elif sort_filter == "id":
            students = students.order_by("student_id")
        elif sort_filter == "program":
            students = students.order_by("program__code")
        elif sort_filter == "year":
            students = students.order_by("year")

        # Get attendance records with date/time filtering
        attendance_records = Attendance.objects.all()
        selected_date = date.today()

        # Single date filter
        if date_filter:
            try:
                selected_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
                attendance_records = attendance_records.filter(timestamp__date=selected_date)
            except ValueError:
                attendance_records = attendance_records.filter(timestamp__date=date.today())

        # Date range filter
        if start_date_filter and end_date_filter:
            try:
                start_date = datetime.strptime(start_date_filter, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_filter, "%Y-%m-%d").date()
                attendance_records = attendance_records.filter(
                    timestamp__date__range=[start_date, end_date]
                )
            except ValueError:
                pass
        elif not date_filter:
            attendance_records = attendance_records.filter(timestamp__date=selected_date)

        # Time filtering
        if start_time_filter and date_filter:
            try:
                start_datetime = datetime.combine(
                    datetime.strptime(date_filter, "%Y-%m-%d").date(),
                    datetime.strptime(start_time_filter, "%H:%M").time()
                )
                attendance_records = attendance_records.filter(timestamp__gte=start_datetime)
            except ValueError:
                pass

        if end_time_filter and date_filter:
            try:
                end_datetime = datetime.combine(
                    datetime.strptime(date_filter, "%Y-%m-%d").date(),
                    datetime.strptime(end_time_filter, "%H:%M").time()
                )
                attendance_records = attendance_records.filter(timestamp__lte=end_datetime)
            except ValueError:
                pass

        # Apply year and course filters to attendance records
        if year_filter:
            attendance_records = attendance_records.filter(student__year=year_filter)
        if program_filter:
            attendance_records = attendance_records.filter(student__program__code=program_filter)
        if college_filter:
            attendance_records = attendance_records.filter(student__college__code=college_filter)

        # Prepare report data for JSON response
        report_data = []
        for student in students:
            # Get filtered attendance for this student
            student_attendance = attendance_records.filter(student=student).order_by("timestamp")

            time_in = None
            time_out = None
            status = "ABSENT"
            attendance_date = None

            if student_attendance.exists():
                for record in student_attendance:
                    if record.status == "IN" and time_in is None:
                        time_in = record.timestamp
                    elif record.status == "OUT":
                        time_out = record.timestamp

                if time_in and time_out:
                    status = "COMPLETED"
                    attendance_date = time_out.date()
                elif time_in:
                    status = "IN"
                    attendance_date = time_in.date()

            # Apply status filter if specified
            if status_filter:
                if status_filter == "present" and status == "ABSENT":
                    continue
                elif status_filter == "absent" and status != "ABSENT":
                    continue
                elif status_filter == "in" and status != "IN":
                    continue
                elif status_filter == "out" and status != "COMPLETED":
                    continue

            report_data.append({
                'student_id': student.student_id,
                'name': student.name,
                'college': student.college_code,
                'program': student.program_code,
                'year': student.year,
                'section': student.section,
                'time_in': time_in.strftime("%I:%M:%S %p") if time_in else None,
                'time_out': time_out.strftime("%I:%M:%S %p") if time_out else None,
                'date': attendance_date.strftime("%Y-%m-%d") if attendance_date else None,
                'status': status
            })

        # Calculate stats based on filtered data
        stats = build_event_analytics(students, attendance_records, report_data)

        # Add date info for display
        date_info = ""
        if date_filter:
            date_info = f"Showing report for {date_filter}"
        elif start_date_filter and end_date_filter:
            date_info = f"Showing report from {start_date_filter} to {end_date_filter}"
        else:
            date_info = f"Showing today's report - {date.today()}"

        return JsonResponse({
            'success': True,
            'reports': report_data,
            'stats': stats,
            'date_info': date_info
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

# ---------------- AUTH ----------------
def register_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        email = request.POST.get("email")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already taken")
        else:
            user = User.objects.create_user(
                username=username,
                password=password,
                email=email,
                is_active=False  # 🔒 must be approved by admin
            )
            messages.success(request, "Account created! Please wait for admin approval.")
            return redirect("login")

    return render(request, "qrapp/register.html")


@staff_member_required
def approve_users(request):
    pending_users = User.objects.filter(is_active=False)
    total_users = User.objects.count()

    if request.method == "POST":
        user_id = request.POST.get("user_id")
        try:
            user = User.objects.get(id=user_id)
            user.is_active = True
            user.save()
            messages.success(request, f"User {user.username} approved!")
            return redirect("approve_users")
        except User.DoesNotExist:
            messages.error(request, "User not found.")

    return render(request, "qrapp/approve_users.html", {
        "pending_users": pending_users,
        "total_users": total_users
    })



def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            # Redirect based on role
            if user.is_staff or user.is_superuser:
                return redirect('admin_dashboard')
            else:
                return redirect('scanner')
        else:
            messages.error(request, "Invalid username or password")
    return render(request, "qrapp/login.html")


def logout_view(request):
    logout(request)
    return redirect('login')


# ---------------- QR CODE GENERATION ----------------

@staff_member_required
def download_qr_pdf(request):
    response, error = export_qr_response({**request.GET, "format": "pdf"})
    if error:
        return HttpResponse(error, status=404)
    return response


@staff_member_required
def ajax_qr_codes(request):
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return JsonResponse({"success": False, "error": "Invalid request"}, status=400)

    students = get_filtered_students(request.GET)
    qr_list = serialize_qr_list(students)
    return JsonResponse(
        {
            "success": True,
            "count": len(qr_list),
            "qr_list": qr_list,
        }
    )


@staff_member_required
def export_qr_codes(request):
    response, error = export_qr_response(request.GET)
    if error:
        return HttpResponse(error, status=404)
    return response


def safe_strip(value, default="NA"):
    """Helper to safely strip values or return default if None"""
    if value is None:
        return default
    value_str = str(value).strip()
    return value_str if value_str else default


@staff_member_required
def upload_pdf(request):
    """Import students from PDF, CSV, or Excel upload."""
    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        upload_file = request.FILES.get('student_file') or request.FILES.get('pdf_file')

        if not upload_file:
            error_msg = "Please select a file to upload."
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_msg}, status=400)
            messages.error(request, error_msg)
            return render(request, 'qrapp/upload_pdf.html', {'form': StudentUploadForm()})

        from django.utils.datastructures import MultiValueDict
        files = MultiValueDict({'student_file': [upload_file]})
        form = StudentUploadForm(request.POST, files)
        if not form.is_valid():
            error_msg = form.errors.get('student_file', ['Invalid file upload'])[0]
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_msg}, status=400)
            messages.error(request, error_msg)
            return render(request, 'qrapp/upload_pdf.html', {'form': form})

        upload_file = form.cleaned_data['student_file']
        extension = os.path.splitext(upload_file.name)[1].lower() or '.pdf'
        temp_path = os.path.join(settings.MEDIA_ROOT, f"temp_upload{extension}")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)

        try:
            with open(temp_path, 'wb+') as destination:
                for chunk in upload_file.chunks():
                    destination.write(chunk)

            result = import_students_from_file(temp_path)
            success_message = result['message']

            if is_ajax:
                return JsonResponse({'success': True, 'message': success_message})
            messages.success(request, success_message)
            return redirect('generate_all_qr')

        except Exception as e:
            error_msg = f"Error processing file: {str(e)}"
            print(error_msg)
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_msg}, status=400)
            messages.error(request, error_msg)

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        return render(request, 'qrapp/upload_pdf.html', {'form': StudentUploadForm()})

    return render(request, 'qrapp/upload_pdf.html', {'form': StudentUploadForm()})


@staff_member_required
def export_students(request):
    """Export filtered student roster as CSV or Excel."""
    response, error = export_students_response(request.GET)
    if error:
        return HttpResponse(error, status=404)
    return response


# ---------------- OTHER ----------------
def home(request):
    return redirect('generate_all_qr')


@staff_member_required
def delete_all_qr(request):
    student_count = Student.objects.count()
    Student.objects.all().delete()

    # Remove QR code images
    qr_files = glob.glob(os.path.join(settings.MEDIA_ROOT, "*_label.png"))
    for f in qr_files:
        try:
            os.remove(f)
        except:
            pass

    messages.success(request, f"Deleted {student_count} students and their QR codes!")
    return redirect('generate_all_qr')


@staff_member_required
def add_student(request):
    if request.method == 'POST':
        # Check if it's an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.POST.get('student_id'):
            # Handle AJAX request
            try:
                from .college_program import resolve_college_and_program
                college, program = resolve_college_and_program(
                    request.POST.get('college'),
                    request.POST.get('program'),
                )
                student = Student(
                    student_id=request.POST.get('student_id'),
                    name=request.POST.get('name'),
                    sex=request.POST.get('sex'),
                    college=college,
                    program=program,
                    year=request.POST.get('year'),
                    section=request.POST.get('section')
                )
                student.save()
                return JsonResponse({'success': True, 'message': 'Student added successfully!'})
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)}, status=400)
        else:
            # Handle regular form submission
            form = StudentForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "Student added successfully!")
                return redirect('generate_all_qr')
            else:
                messages.error(request, "Please correct the errors below.")
    else:
        form = StudentForm()
    return render(request, 'qrapp/add_student.html', {'form': form})

@staff_member_required
def generate_all_qr(request):
    students = Student.objects.all()
    student_map = {student.student_id: student for student in students}
    qr_list = []
    for item in serialize_qr_list(students):
        student = student_map.get(item["student_id"])
        if student:
            qr_list.append({"student": student, "qr_img": item["qr_img"]})

    return render(request, "qrapp/all_qr.html", {
        "qr_list": qr_list,
        "student_count": len(qr_list),
    })




# ---------------- COLLEGE MANAGEMENT ----------------
@staff_member_required
def manage_colleges(request):
    """View to list and manage colleges"""
    from .models import College
    import json
    
    colleges = College.objects.all().order_by('code')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add':
            code = request.POST.get('code', '').strip().upper()
            name = request.POST.get('name', '').strip()
            
            if code and name:
                if not College.objects.filter(code=code).exists():
                    College.objects.create(code=code, name=name, is_active=True)
                    messages.success(request, f'College {code} added successfully!')
                else:
                    messages.error(request, f'College code {code} already exists!')
            else:
                messages.error(request, 'Both code and name are required!')
                
        elif action == 'edit':
            college_id = request.POST.get('college_id')
            code = request.POST.get('code', '').strip().upper()
            name = request.POST.get('name', '').strip()
            is_active = request.POST.get('is_active') == 'on'
            
            try:
                college = College.objects.get(id=college_id)
                # Check if code is being changed and if new code already exists
                if code != college.code and College.objects.filter(code=code).exists():
                    messages.error(request, f'College code {code} already exists!')
                else:
                    college.code = code
                    college.name = name
                    college.is_active = is_active
                    college.save()
                    messages.success(request, f'College {code} updated successfully!')
            except College.DoesNotExist:
                messages.error(request, 'College not found!')
                
        elif action == 'delete':
            college_id = request.POST.get('college_id')
            try:
                college = College.objects.get(id=college_id)
                # Check if any students are using this college
                student_count = Student.objects.filter(college=college).count()
                if student_count > 0:
                    messages.warning(request, f'Cannot delete {college.code}! {student_count} students are still enrolled in this college. Please reassign them first.')
                else:
                    college.delete()
                    messages.success(request, f'College {college.code} deleted successfully!')
            except College.DoesNotExist:
                messages.error(request, 'College not found!')
        
        return redirect('manage_colleges')
    
    # Get active colleges for the dropdown
    active_colleges = College.objects.filter(is_active=True).order_by('code')
    
    # Count students per college
    college_stats = {}
    for college in colleges:
        college_stats[college.code] = Student.objects.filter(college=college).count()
    
    # Convert to JSON for JavaScript
    college_stats_json = json.dumps(college_stats)
    
    return render(request, 'qrapp/manage_colleges.html', {
        'colleges': colleges,
        'active_colleges': active_colleges,
        'college_stats': college_stats_json
    })


@staff_member_required
def get_colleges_json(request):
    """AJAX endpoint to get colleges for dropdowns"""
    from .models import College
    
    active_only = request.GET.get('active_only', 'true').lower() == 'true'
    
    if active_only:
        colleges = College.objects.filter(is_active=True).order_by('code')
    else:
        colleges = College.objects.all().order_by('code')
    
    college_list = [
        {
            'id': college.id,
            'code': college.code,
            'name': college.name,
            'is_active': college.is_active
        }
        for college in colleges
    ]
    
    return JsonResponse({
        'success': True,
        'colleges': college_list
    })


@staff_member_required
def get_programs_json(request, college_code):
    """AJAX endpoint to get programs for a specific college"""
    from .models import College, Program
    
    try:
        college = College.objects.get(code=college_code)
        active_only = request.GET.get('active_only', 'true').lower() == 'true'
        
        if active_only:
            programs = Program.objects.filter(college=college, is_active=True).order_by('code')
        else:
            programs = Program.objects.filter(college=college).order_by('code')
        
        program_list = [
            {
                'id': program.id,
                'code': program.code,
                'name': program.name,
                'is_active': program.is_active
            }
            for program in programs
        ]
        
        return JsonResponse({
            'success': True,
            'programs': program_list
        })
    except College.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'College not found'
        }, status=404)


@staff_member_required
def manage_programs(request, college_id):
    """View to manage programs for a specific college"""
    from .models import College, Program
    
    college = get_object_or_404(College, id=college_id)
    programs = Program.objects.filter(college=college).order_by('code')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add':
            code = request.POST.get('code', '').strip()
            name = request.POST.get('name', '').strip()
            
            if code and name:
                if not Program.objects.filter(college=college, code=code).exists():
                    Program.objects.create(college=college, code=code, name=name, is_active=True)
                    messages.success(request, f'Program {code} added successfully to {college.code}!')
                else:
                    messages.error(request, f'Program code {code} already exists in {college.code}!')
            else:
                messages.error(request, 'Both code and name are required!')
                
        elif action == 'edit':
            program_id = request.POST.get('program_id')
            code = request.POST.get('code', '').strip()
            name = request.POST.get('name', '').strip()
            is_active = request.POST.get('is_active') == 'on'
            
            try:
                program = Program.objects.get(id=program_id, college=college)
                # Check if code is being changed and if new code already exists
                if code != program.code and Program.objects.filter(college=college, code=code).exists():
                    messages.error(request, f'Program code {code} already exists in {college.code}!')
                else:
                    program.code = code
                    program.name = name
                    program.is_active = is_active
                    program.save()
                    messages.success(request, f'Program {code} updated successfully!')
            except Program.DoesNotExist:
                messages.error(request, 'Program not found!')
                
        elif action == 'delete':
            program_id = request.POST.get('program_id')
            try:
                program = Program.objects.get(id=program_id, college=college)
                # Check if any students are using this program
                student_count = Student.objects.filter(program=program).count()
                if student_count > 0:
                    messages.warning(request, f'Cannot delete {program.code}! {student_count} students are enrolled in this program. Please reassign them first.')
                else:
                    program.delete()
                    messages.success(request, f'Program {program.code} deleted successfully!')
            except Program.DoesNotExist:
                messages.error(request, 'Program not found!')
        
        return redirect('manage_programs', college_id=college_id)
    
    # Count students per program
    program_stats = {}
    for program in programs:
        program_stats[program.code] = Student.objects.filter(program=program).count()
    
    # Convert to JSON for JavaScript
    program_stats_json = json.dumps(program_stats)
    
    return render(request, 'qrapp/manage_programs.html', {
        'college': college,
        'programs': programs,
        'program_stats': program_stats_json
    })


# ---------------- USER MANAGEMENT ----------------
@staff_member_required
def manage_users(request):
    """AJAX handler for user management operations"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})
    
    action = request.POST.get('action')
    
    if action == 'add':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        is_staff = request.POST.get('is_staff') == 'true'
        is_active = request.POST.get('is_active') == 'true'
        
        if not username or not password:
            return JsonResponse({'success': False, 'error': 'Username and password are required'})
        
        if User.objects.filter(username=username).exists():
            return JsonResponse({'success': False, 'error': f'Username {username} already exists'})
        
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                is_staff=is_staff,
                is_active=is_active
            )
            return JsonResponse({
                'success': True,
                'message': f'User {username} created successfully',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'is_staff': user.is_staff,
                    'is_active': user.is_active,
                    'date_joined': user.date_joined.strftime('%b %d, %Y %H:%M')
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    elif action == 'edit':
        user_id = request.POST.get('user_id')
        email = request.POST.get('email', '').strip()
        is_staff = request.POST.get('is_staff') == 'true'
        is_active = request.POST.get('is_active') == 'true'
        new_password = request.POST.get('new_password', '').strip()
        
        try:
            user = User.objects.get(id=user_id)
            
            # Don't allow editing superuser
            if user.is_superuser and not request.user.is_superuser:
                return JsonResponse({'success': False, 'error': 'Cannot edit superuser'})
            
            user.email = email
            user.is_staff = is_staff
            user.is_active = is_active
            
            if new_password:
                user.set_password(new_password)
            
            user.save()
            
            return JsonResponse({
                'success': True,
                'message': f'User {user.username} updated successfully',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'is_staff': user.is_staff,
                    'is_active': user.is_active,
                    'date_joined': user.date_joined.strftime('%b %d, %Y %H:%M')
                }
            })
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'User not found'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    elif action == 'delete':
        user_id = request.POST.get('user_id')
        
        try:
            user = User.objects.get(id=user_id)
            
            # Don't allow deleting superuser or self
            if user.is_superuser:
                return JsonResponse({'success': False, 'error': 'Cannot delete superuser'})
            if user.id == request.user.id:
                return JsonResponse({'success': False, 'error': 'Cannot delete yourself'})
            
            username = user.username
            user.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'User {username} deleted successfully'
            })
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'User not found'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    elif action == 'approve':
        user_id = request.POST.get('user_id')
        
        try:
            user = User.objects.get(id=user_id)
            user.is_active = True
            user.save()
            
            return JsonResponse({
                'success': True,
                'message': f'User {user.username} approved successfully',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'is_staff': user.is_staff,
                    'is_active': user.is_active,
                    'date_joined': user.date_joined.strftime('%b %d, %Y %H:%M')
                }
            })
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'User not found'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid action'})


# ---------------- EVENT MANAGEMENT ----------------
def _parse_optional_time(value):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


@staff_member_required
def manage_events(request):
    """Create and manage attendance events/sessions."""
    events = Event.objects.all().order_by("-is_current", "-event_date", "-start_time", "title")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add":
            title = (request.POST.get("title") or "").strip()
            description = (request.POST.get("description") or "").strip()
            location = (request.POST.get("location") or "").strip()
            event_date_raw = (request.POST.get("event_date") or "").strip()
            start_time = _parse_optional_time(request.POST.get("start_time"))
            end_time = _parse_optional_time(request.POST.get("end_time"))
            is_current = request.POST.get("is_current") == "on"

            if not title:
                messages.error(request, "Event title is required.")
            else:
                try:
                    event_date = datetime.strptime(event_date_raw, "%Y-%m-%d").date() if event_date_raw else date.today()
                except ValueError:
                    event_date = date.today()

                event = Event(
                    title=title,
                    description=description,
                    location=location,
                    event_date=event_date,
                    start_time=start_time,
                    end_time=end_time,
                    is_active=True,
                    is_current=is_current,
                    created_by=request.user,
                )
                picture = request.FILES.get("picture")
                if picture:
                    event.picture = picture
                event.save()
                messages.success(request, f'Event "{title}" created successfully!')

        elif action == "edit":
            event_id = request.POST.get("event_id")
            title = (request.POST.get("title") or "").strip()
            description = (request.POST.get("description") or "").strip()
            location = (request.POST.get("location") or "").strip()
            event_date_raw = (request.POST.get("event_date") or "").strip()
            start_time = _parse_optional_time(request.POST.get("start_time"))
            end_time = _parse_optional_time(request.POST.get("end_time"))
            is_active = request.POST.get("is_active") == "on"
            is_current = request.POST.get("is_current") == "on"

            try:
                event = Event.objects.get(id=event_id)
                if not title:
                    messages.error(request, "Event title is required.")
                else:
                    try:
                        event_date = datetime.strptime(event_date_raw, "%Y-%m-%d").date() if event_date_raw else event.event_date
                    except ValueError:
                        event_date = event.event_date

                    event.title = title
                    event.description = description
                    event.location = location
                    event.event_date = event_date
                    event.start_time = start_time
                    event.end_time = end_time
                    event.is_active = is_active
                    event.is_current = is_current
                    picture = request.FILES.get("picture")
                    if picture:
                        if event.picture:
                            event.picture.delete(save=False)
                        event.picture = picture
                    elif request.POST.get("clear_picture") == "on":
                        if event.picture:
                            event.picture.delete(save=False)
                        event.picture = None
                    event.save()
                    messages.success(request, f'Event "{title}" updated successfully!')
            except Event.DoesNotExist:
                messages.error(request, "Event not found!")

        elif action == "set_current":
            event_id = request.POST.get("event_id")
            try:
                event = Event.objects.get(id=event_id)
                event.is_active = True
                event.is_current = True
                event.save()
                messages.success(request, f'"{event.title}" is now the current scanning event.')
            except Event.DoesNotExist:
                messages.error(request, "Event not found!")

        elif action == "delete":
            event_id = request.POST.get("event_id")
            try:
                event = Event.objects.get(id=event_id)
                scan_count = event.attendance_records.count()
                title = event.title
                if event.picture:
                    event.picture.delete(save=False)
                event.delete()
                messages.success(
                    request,
                    f'Event "{title}" deleted.'
                    + (f" {scan_count} related scans were unlinked." if scan_count else ""),
                )
            except Event.DoesNotExist:
                messages.error(request, "Event not found!")

        return redirect("manage_events")

    event_stats = {
        str(event.id): event.attendance_records.count()
        for event in events
    }

    return render(request, "qrapp/manage_events.html", {
        "events": events,
        "today": date.today().isoformat(),
        "event_stats": json.dumps(event_stats),
    })


@staff_member_required
def get_events_json(request):
    """AJAX endpoint for active events (scanner / filters)."""
    active_only = request.GET.get("active_only", "true").lower() == "true"
    events = Event.objects.all().order_by("-is_current", "-event_date", "title")
    if active_only:
        events = events.filter(is_active=True)

    payload = [
        {
            "id": event.id,
            "title": event.title,
            "event_date": event.event_date.isoformat(),
            "location": event.location,
            "is_current": event.is_current,
            "is_active": event.is_active,
            "display_window": event.display_window,
            "picture_url": event.picture.url if event.picture else "",
        }
        for event in events
    ]
    return JsonResponse({"success": True, "events": payload})
