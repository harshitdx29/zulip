from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.views import login as django_login_page
from django.http import HttpResponseRedirect
from django.shortcuts import render_to_response, redirect
from django.template import RequestContext, loader

from zerver.decorator import has_request_variables, REQ, json_to_dict
from zerver.lib.actions import internal_send_message
from zerver.lib.response import json_success, json_error, json_response, json_method_not_allowed
from zerver.lib.rest import rest_dispatch as _rest_dispatch
from zerver.models import get_realm, get_user_profile_by_email, resolve_email_to_domain, \
        UserProfile
from zilencer.forms import EnterpriseToSForm
from error_notify import notify_server_error, notify_browser_error
from django.core.mail import send_mail
from django.conf import settings

rest_dispatch = csrf_exempt((lambda request, *args, **kwargs: _rest_dispatch(request, globals(), *args, **kwargs)))


def get_ticket_number():
    fn = '/var/tmp/.feedback-bot-ticket-number'
    try:
        ticket_number = int(open(fn).read()) + 1
    except:
        ticket_number = 1
    open(fn, 'w').write('%d' % ticket_number)
    return ticket_number

@has_request_variables
def submit_feedback(request, deployment, message=REQ(converter=json_to_dict)):
    domainish = message["sender_domain"]
    if get_realm("zulip.com") not in deployment.realms.all():
        domainish += " via " + deployment.name
    subject = "%s" % (message["sender_email"],)

    if len(subject) > 60:
        subject = subject[:57].rstrip() + "..."


    ticket_number = get_ticket_number()
    content = '\n~~~'
    content += '\nticket Z%03d (@support please ack)' % (ticket_number,)
    content += '\nsender: %s' % (message['sender_full_name'],)
    content += '\nemail: %s' % (message['sender_email'],)
    if 'sender_domain' in message:
        content += '\nrealm: %s' % (message['sender_domain'],)
    content += '\n~~~'

    content += '\n\n'
    content += message['content']

    internal_send_message("feedback@zulip.com", "stream", "support", subject, content)

    return HttpResponse(message['sender_email'])

@has_request_variables
def report_error(request, deployment, type=REQ, report=REQ(converter=json_to_dict)):
    report['deployment'] = deployment.name
    if type == 'browser':
        notify_browser_error(report)
    elif type == 'server':
        notify_server_error(report)
    else:
        return json_error("Invalid type parameter")
    return json_response({})

def realm_for_email(email):
    try:
        user = get_user_profile_by_email(email)
        return user.realm
    except UserProfile.DoesNotExist:
        pass

    return get_realm(resolve_email_to_domain(email))

# Requests made to this endpoint are UNAUTHENTICATED
@csrf_exempt
@has_request_variables
def lookup_endpoints_for_user(request, email=REQ()):
    try:
        return json_response(realm_for_email(email).deployment.endpoints)
    except AttributeError:
        return json_error("Cannot determine endpoint for user.", status=404)

def account_deployment_dispatch(request, **kwargs):
    sso_unknown_email = False
    if request.method == 'POST':
        email = request.POST['username']
        realm = realm_for_email(email)
        try:
            return HttpResponseRedirect(realm.deployment.base_site_url)
        except AttributeError:
            # No deployment found for this user/email
            sso_unknown_email = True

    template_response = django_login_page(request, **kwargs)
    template_response.context_data['desktop_sso_dispatch'] = True
    template_response.context_data['desktop_sso_unknown_email'] = sso_unknown_email
    return template_response

def enterprise_registration(request):
    if request.method == "POST":
        form = EnterpriseToSForm(request.POST)
        if form.is_valid():
            company = form.cleaned_data["company"]
            name = form.cleaned_data["full_name"]
            subject = "Enterprise terms acceptance for " + company
            body = loader.render_to_string(
                "zilencer/enterprise_tos_accept_body.txt",
                {"name": name, "company": company})
            send_mail(subject, body, settings.EMAIL_HOST_USER,
                      ["support@zulip.com"])
            return redirect("https://zulip.com/enterprise/download")
    else:
        form = EnterpriseToSForm()
    return render_to_response(
        "zilencer/enterprise-registration.html", {"form": form},
        context_instance=RequestContext(request))
