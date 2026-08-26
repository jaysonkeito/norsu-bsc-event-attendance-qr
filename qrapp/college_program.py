"""Helpers to resolve/create College and Program from string codes."""

from .models import College, Program


def normalize_code(value, fallback="NA", max_length=50):
    code = (str(value).strip() if value is not None else "") or fallback
    return code[:max_length]


def resolve_college(code_or_name, create=True):
    """
    Resolve a College from a code (preferred) or name.
    Creates an active college when missing if create=True.
    """
    raw = (str(code_or_name).strip() if code_or_name is not None else "") or "UNK"
    code = normalize_code(raw, fallback="UNK", max_length=20)

    college = College.objects.filter(code__iexact=code).first()
    if college:
        return college

    college = College.objects.filter(name__iexact=raw).first()
    if college:
        return college

    if not create:
        return None

    college, _ = College.objects.get_or_create(
        code=code,
        defaults={"name": raw, "is_active": True},
    )
    return college


def resolve_program(college, program_code_or_name, create=True):
    """Resolve a Program under a College; create when missing if create=True."""
    if college is None:
        return None

    raw = (str(program_code_or_name).strip() if program_code_or_name is not None else "") or "NA"
    code = normalize_code(raw, fallback="NA", max_length=50)

    program = Program.objects.filter(college=college, code__iexact=code).first()
    if program:
        return program

    program = Program.objects.filter(college=college, name__iexact=raw).first()
    if program:
        return program

    if not create:
        return None

    program, _ = Program.objects.get_or_create(
        college=college,
        code=code,
        defaults={"name": raw, "is_active": True},
    )
    return program


def resolve_college_and_program(college_value, program_value, create=True):
    college = resolve_college(college_value, create=create)
    program = resolve_program(college, program_value, create=create) if college else None
    return college, program
