from django.utils import timezone


def generate_number(empresa, prefix, model_class):
    """Generate sequential number per empresa per year: PREFIX-YYYY-NNNN"""
    year = timezone.now().year
    pattern = f"{prefix}-{year}-"
    last = (
        model_class.objects.filter(empresa=empresa, number__startswith=pattern)
        .order_by("-number")
        .values_list("number", flat=True)
        .first()
    )
    if last:
        seq = int(last.split("-")[-1]) + 1
    else:
        seq = 1
    return f"{pattern}{seq:04d}"
