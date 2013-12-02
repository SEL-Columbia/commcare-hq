from corehq.apps.sms.api import incoming as incoming_sms
from corehq.apps.twilio.models import TwilioBackend
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt

EMPTY_RESPONSE = """<?xml version="1.0" encoding="UTF-8" ?>
<Response></Response>"""

@csrf_exempt
def sms_in(request):
    if request.method == "POST":
        message_sid = request.POST.get("MessageSid")
        account_sid = request.POST.get("AccountSid")
        from_ = request.POST.get("From")
        to = request.POST.get("To")
        body = request.POST.get("Body")
        incoming_sms(
            from_,
            body,
            TwilioBackend.get_api_id(),
            backend_message_id=message_sid
        )
        return HttpResponse(EMPTY_RESPONSE)
    else:
        return HttpResponseBadRequest("POST Expected")

