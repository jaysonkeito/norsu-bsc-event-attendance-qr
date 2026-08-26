import base64
import io
import os
import zipfile
from datetime import date

import qrcode
from django.conf import settings
from django.http import HttpResponse
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .student_export import filter_students_queryset


def build_qr_data(student):
    from .qr_security import make_qr_token

    college = getattr(student, "college_code", None) or (
        student.college.code if getattr(student, "college_id", None) else str(getattr(student, "college", "") or "")
    )
    program = getattr(student, "program_code", None) or (
        student.program.code if getattr(student, "program_id", None) else str(getattr(student, "program", "") or "")
    )
    token = make_qr_token(student.student_id)

    qr_data = (
        f"ID: {student.student_id}\n"
        f"TOKEN: {token}\n"
        f"Name: {student.name}\n"
        f"Sex: {student.sex}\n"
        f"College: {college}\n"
        f"Program: {program}\n"
        f"Year: {student.year}\n"
    )
    if getattr(student, "section", None) and student.section != "NA":
        qr_data += f"Section: {student.section}"
    return qr_data


def _load_font(size=14):
    font_paths = [
        "arial.ttf",
        "Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
        "/System/Library/Fonts/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for font_path in font_paths:
        try:
            return ImageFont.truetype(font_path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_qr_labeled_image(student):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(build_qr_data(student))
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    width, height = qr_img.size
    label_height = 60
    new_img = Image.new("RGB", (width, height + label_height), "white")
    new_img.paste(qr_img, (0, 0))

    draw = ImageDraw.Draw(new_img)
    font = _load_font()

    short_name = student.name.split(",")[0]
    if len(short_name) > 20:
        short_name = short_name[:17] + "..."
    text = f"{student.student_id} - {short_name}"

    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
    except Exception:
        text_w = len(text) * 8

    text_x = (width - text_w) / 2
    draw.text((text_x, height + 10), text, fill="black", font=font)
    return new_img


def build_qr_preview_base64(student):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=5,
        border=2,
    )
    qr.add_data(build_qr_data(student))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def generate_qr_with_label(student):
    """Generate QR code + text label and save PNG in media folder."""
    try:
        new_img = build_qr_labeled_image(student)
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        img_path = os.path.join(settings.MEDIA_ROOT, f"{student.student_id}_label.png")
        new_img.save(img_path)
        return img_path
    except Exception as exc:
        print(f"Error generating QR for {student.student_id}: {exc}")
        return None


def build_qr_filename(params, extension):
    parts = ["qrcodes"]
    for key in ("college", "program", "year", "section"):
        value = (params.get(key) or "").strip()
        if value:
            safe = "".join(ch if ch.isalnum() else "_" for ch in str(value))
            parts.append(safe.lower())
    parts.append(date.today().isoformat())
    return f"{'_'.join(parts)}.{extension}"


def serialize_qr_list(students):
    qr_list = []
    for student in students:
        try:
            qr_list.append(
                {
                    "student_id": student.student_id,
                    "name": student.name,
                    "college": student.college_code,
                    "program": student.program_code,
                    "year": student.year,
                    "section": student.section,
                    "sex": student.sex,
                    "qr_img": build_qr_preview_base64(student),
                }
            )
        except Exception as exc:
            print(f"Error building QR preview for {student.student_id}: {exc}")
    return qr_list


def export_qr_pdf(students, filename):
    if not students.exists():
        return None, "No students match the selected filters."

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    pdf = canvas.Canvas(response, pagesize=A4)
    width, height = A4

    qr_width = 45 * mm
    qr_height = 45 * mm
    label_height = 15 * mm
    total_height = qr_height + label_height

    margin_x = 10 * mm
    margin_y = 15 * mm
    gap_x = 5 * mm
    gap_y = 5 * mm

    cols = 4
    rows = 5

    x_positions = [margin_x + (qr_width + gap_x) * c for c in range(cols)]
    y_positions = [height - margin_y - (total_height + gap_y) * r for r in range(rows)]

    added = 0
    for student in students:
        img_path = generate_qr_with_label(student)
        if not img_path or not os.path.exists(img_path):
            continue

        if added > 0 and added % (cols * rows) == 0:
            pdf.showPage()

        row = added // cols
        col = added % cols
        x = x_positions[col]
        y = y_positions[row % rows] - (row // rows) * (rows * (total_height + gap_y))
        pdf.drawImage(img_path, x, y, width=qr_width, height=total_height)
        added += 1

    if added == 0:
        return None, "Could not generate QR codes for the selected students."

    pdf.save()
    return response, None


def export_qr_zip(students, filename):
    if not students.exists():
        return None, "No students match the selected filters."

    buffer = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for student in students:
            try:
                img = build_qr_labeled_image(student)
                png_buffer = io.BytesIO()
                img.save(png_buffer, format="PNG")
                archive.writestr(f"{student.student_id}_qr.png", png_buffer.getvalue())
                added += 1
            except Exception as exc:
                print(f"Error adding QR to zip for {student.student_id}: {exc}")

    if added == 0:
        return None, "Could not generate QR codes for the selected students."

    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response, None


def get_filtered_students(params):
    return filter_students_queryset(params)


def export_qr_response(params):
    export_format = (params.get("format") or "pdf").lower()
    students = get_filtered_students(params)

    if export_format == "zip":
        filename = build_qr_filename(params, "zip")
        return export_qr_zip(students, filename)

    filename = build_qr_filename(params, "pdf")
    return export_qr_pdf(students, filename)
