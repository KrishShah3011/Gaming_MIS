from django import template

register = template.Library()


@register.filter
def rupees(paise):
    """12500 → "₹125", 2475 → "₹24.75", -15000 → "−₹150"."""
    sign = "−" if paise < 0 else ""
    whole, fraction = divmod(abs(int(paise)), 100)
    # ponytail: western digit grouping (1,00,000 shows as 100,000); wallets stay far below a lakh.
    return f"{sign}₹{whole:,}" + (f".{fraction:02}" if fraction else "")


@register.filter
def duration(minutes):
    """90 → "1 hr 30 min", 120 → "2 hrs", 30 → "30 min"."""
    hours, mins = divmod(int(minutes), 60)
    parts = [f"{hours} hr" + ("s" if hours > 1 and not mins else "")] if hours else []
    return " ".join(parts + ([f"{mins} min"] if mins else []))
