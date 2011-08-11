#
# COPIED FROM DJANGO 1.2 so that MOPUB can Modify
#

import re, logging
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
# Avoid shadowing the login() view below.
from django.contrib.auth import login as auth_login
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm, PasswordChangeForm
from django.contrib.auth.tokens import default_token_generator
from django.views.decorators.csrf import csrf_protect
from django.core.urlresolvers import reverse
from django.shortcuts import render_to_response, get_object_or_404
from django.contrib.sites.models import get_current_site
from django.http import HttpResponseRedirect, Http404
from django.template import RequestContext
from django.utils.http import urlquote, base36_to_int
from django.utils.translation import ugettext as _
from django.contrib.auth.models import User
from django.views.decorators.cache import never_cache

from account.query_managers import UserQueryManager
from registration.forms import MPAuthenticationForm

@csrf_protect
@never_cache
def login(request, template_name='registration/login.html',
          redirect_field_name=REDIRECT_FIELD_NAME,
          authentication_form=MPAuthenticationForm):
    """Displays the login form and handles the login action."""

    redirect_to = request.REQUEST.get(redirect_field_name, '')

    if request.method == "POST":
        form = authentication_form(data=request.POST)
        if form.is_valid():
            # Light security check -- make sure redirect_to isn't garbage.
            if not redirect_to or ' ' in redirect_to:
                redirect_to = settings.LOGIN_REDIRECT_URL

            # Heavier security check -- redirects to http://example.com should
            # not be allowed, but things like /view/?param=http://example.com
            # should be allowed. This regex checks if there is a '//' *before* a
            # question mark.
            elif '//' in redirect_to and re.match(r'[^\?]*//', redirect_to):
                    redirect_to = settings.LOGIN_REDIRECT_URL

            # Okay, security checks complete. Log the user in.
            auth_login(request, form.get_user())

            if request.session.test_cookie_worked():
                request.session.delete_test_cookie()

            return HttpResponseRedirect(redirect_to)

    else:
        form = authentication_form(request)

    request.session.set_test_cookie()

    current_site = get_current_site(request)

    return render_to_response(template_name, {
        'form': form,
        redirect_field_name: redirect_to,
        'site': current_site,
        'site_name': current_site.name,
    }, context_instance=RequestContext(request))

def logout(request, next_page=None, template_name='registration/logged_out.html', redirect_field_name=REDIRECT_FIELD_NAME):
    "Logs out the user and displays 'You are logged out' message."
    from django.contrib.auth import logout
    # catch errors when the user is logged in with google
    # account but never used the new mopub login
    # this is a temporal problem as users migrate
    try:
        logout(request)
    except TypeError:
        pass    
    if next_page is None:
        redirect_to = request.REQUEST.get(redirect_field_name, '')
        if redirect_to:
            return HttpResponseRedirect(redirect_to)
        else:
            current_site = get_current_site(request)
            return render_to_response(template_name, {
                'site': current_site,
                'site_name': current_site.name,
                'title': _('Logged out')
            }, context_instance=RequestContext(request))
    else:
        # Redirect to this page until the session has been cleared.
        return HttpResponseRedirect(next_page or request.path)

def logout_then_login(request, login_url=None):
    "Logs out the user if he is logged in. Then redirects to the log-in page."
    if not login_url:
        login_url = settings.LOGIN_URL
    return logout(request, login_url)

def redirect_to_login(next, login_url=None, redirect_field_name=REDIRECT_FIELD_NAME):
    "Redirects the user to the login page, passing the given 'next' page"
    if not login_url:
        login_url = settings.LOGIN_URL
    return HttpResponseRedirect('%s?%s=%s' % (login_url, urlquote(redirect_field_name), urlquote(next)))

# 4 views for password reset:
# - password_reset sends the mail
# - password_reset_done shows a success message for the above
# - password_reset_confirm checks the link the user clicked and
#   prompts for a new password
# - password_reset_complete shows a success message for the above

@csrf_protect
def password_reset(request, is_admin_site=False, template_name='registration/password_reset_form.html',
        email_template_name='registration/password_reset_email.html',
        password_reset_form=PasswordResetForm, token_generator=default_token_generator,
        post_reset_redirect=None):
        
    from google.appengine.api import users
        
    if post_reset_redirect is None:
        post_reset_redirect = reverse('auth_password_reset_done')
    if request.method == "POST":
        form = password_reset_form(request.POST)
        try:
            if form.is_valid():
                opts = {}
                opts['use_https'] = request.is_secure()
                opts['token_generator'] = token_generator
                opts['email_template_name'] = email_template_name
                opts['request'] = request
                if is_admin_site:
                    opts['domain_override'] = request.META['HTTP_HOST']
                try:    
                    form.save(**opts)
                    return HttpResponseRedirect(post_reset_redirect)
                except AttributeError:
                    form.mperrors = ["Your account requires you to use your Google Account to <a href='%s'>log in</a>. \
                                     <br/>If you want to unlink your account first log in then <a href='%s'>migrate</a> your account."%
                                     (users.create_login_url('/inventory/'),reverse('registration_migrate_user'))]
        except AttributeError:
             form.mperrors = ["Your account requires you to use your Google Account to <a href='%s'>log in</a>. \
                              <br/>If you want to unlink your account first log in then <a href='%s'>migrate</a> your account."%
                              (users.create_login_url('/inventory/'),reverse('registration_migrate_user'))]
                                         
    else:
        form = password_reset_form()
    return render_to_response(template_name, {
        'form': form,
    }, context_instance=RequestContext(request))        

def password_reset_done(request, template_name='registration/password_reset_done.html'):
    return render_to_response(template_name, context_instance=RequestContext(request))

@never_cache
def password_reset_confirm(request, uidb36=None, token=None, template_name='registration/password_reset_confirm.html',
                           token_generator=default_token_generator, set_password_form=SetPasswordForm,
                           post_reset_redirect=None):
    """
    View that checks the hash in a password reset link and presents a
    form for entering a new password.
    """
    assert uidb36 is not None and token is not None # checked by URLconf
    if post_reset_redirect is None:
        post_reset_redirect = reverse('auth_password_reset_complete')
    try:
        # uid_int = base36_to_int(uidb36)
        user = UserQueryManager.get(uidb36)
    except (ValueError, User.DoesNotExist):
        user = None

    context_instance = RequestContext(request)

    if user is not None and token_generator.check_token(user, token):
        context_instance['validlink'] = True
        if request.method == 'POST':
            form = set_password_form(user, request.POST)
            if form.is_valid():
                form.save()
                # logs the user in automatically, instead of forcing them to 
                # manually enter new login info
                login_user = authenticate(username=user.username, 
                                          password=form.cleaned_data['new_password1'])
                auth_login(request, login_user)
                return HttpResponseRedirect(post_reset_redirect)
        else:
            form = set_password_form(None)
    else:
        context_instance['validlink'] = False
        form = None
    context_instance['form'] = form
    return render_to_response(template_name, context_instance=context_instance)                           

def password_reset_complete(request, template_name='registration/password_reset_complete.html'):
    return render_to_response(template_name, context_instance=RequestContext(request,
                                                                             {'login_url': settings.LOGIN_URL}))
                                                                             
@login_required    
def migrate_user(request, template_name='registration/password_reset_confirm.html',
                            token_generator=default_token_generator, set_password_form=SetPasswordForm,
                            post_reset_redirect=None):
     """
     View that checks the hash in a password reset link and presents a
     form for entering a new password.
     """
     if post_reset_redirect is None:
        post_reset_redirect = reverse('registration_migrate_user_complete')

     user = request.user

     context_instance = RequestContext(request)

     if user is not None:
        context_instance['validlink'] = True
        if request.method == 'POST':
            form = set_password_form(user, request.POST)
            if form.is_valid():
                form.save()
                # logs the user in automatically, instead of forcing them to 
                # manually enter new login info
                login_user = authenticate(username=user.username, 
                                          password=form.cleaned_data['new_password1'])
                auth_login(request, login_user)
                return HttpResponseRedirect(post_reset_redirect)
        else:
            form = set_password_form(None)
     else:
        context_instance['validlink'] = False
        form = None
     context_instance['form'] = form
     context_instance['unlink'] = True
     return render_to_response(template_name, context_instance=context_instance)
     
@login_required
def migrate_user_complete(request, template_name='registration/migrate_user_complete.html'):
    return render_to_response(template_name, context_instance=RequestContext(request,
                                                                             {'login_url': settings.LOGIN_URL}))

@csrf_protect
@login_required
def password_change(request, template_name='registration/password_change_form.html',
                    post_change_redirect=None, password_change_form=PasswordChangeForm):
    if post_change_redirect is None:
        post_change_redirect = reverse('auth_password_change_done')
    if request.method == "POST":
        form = password_change_form(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(post_change_redirect)
    else:
        form = password_change_form(user=request.user)
    return render_to_response(template_name, {
        'form': form,
    }, context_instance=RequestContext(request))

def password_change_done(request, template_name='registration/password_reset_complete.html'):
    return render_to_response(template_name, context_instance=RequestContext(request))
