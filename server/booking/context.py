from status.models import CafeSettings


def cafe(request):
    """The café's settings (name, contact, rates) in every template."""
    return {"cafe": CafeSettings.load()}
