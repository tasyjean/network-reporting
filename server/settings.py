# Copyright 2008 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Django settings for google-app-engine-django project.

import os
from common.ragendja.settings_pre import *


NEW_UI = True
DEFAULT_FROM_EMAIL = 'olp@mopub.com'
SERVER_EMAIL = 'olp@mopub.com'
REPLY_TO_EMAIL = 'support@mopub.com'

ADMINS = (
    ('Front End Team', 'fe-bugs@mopub.com'),
)

MANAGERS = ADMINS

DATABASE_ENGINE = 'appengine'  # 'postgresql_psycopg2', 'postgresql', 'mysql', 'sqlite3' or 'oracle'.
DATABASE_NAME = ''             # Or path to database file if using sqlite3.
DATABASE_USER = ''             # Not used with sqlite3.
DATABASE_PASSWORD = ''         # Not used with sqlite3.
DATABASE_HOST = ''             # Set to empty string for localhost. Not used with sqlite3.
DATABASE_PORT = ''             # Set to empty string for default. Not used with sqlite3.


# Report server endpoints
if DEBUG:
    REPORT_SERVER_HOST = 'localhost'
    REPORT_SERVER_PORT = 8888
else:
    REPORT_SERVER_HOST = 'reporting.mopub.com'
    REPORT_SERVER_PORT = 80

REPORT_SERVER_SECRET_API_KEY = 'rs7tvxW9ZKJ7WVJH3OwTe7CUG2ZNzoUmn9wv4y6Kpda2ns6iWqR5TrMDeFScImH'


# Whether to actually use report server as canonical source
WRITE_REPORT_SERVER_RESULTS = True

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# If running in a Windows environment this must be set to the same as your
# system time zone.
TIME_ZONE = 'UTC'

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-us'

SITE_ID = 1

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# Absolute path to the directory that holds media.
# Example: "/home/media/media.lawrence.com/"
MEDIA_ROOT = ''

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash if there is a path component (optional in other cases).
# Examples: "http://media.lawrence.com", "http://example.com/media/"
MEDIA_URL = ''

# URL prefix for admin media -- CSS, JavaScript and images. Make sure to use a
# trailing slash.
# Examples: "http://foo.com/media/", "/media/".
ADMIN_MEDIA_PREFIX = '/media/'

# Make this unique, and don't share it with anybody.
SECRET_KEY = 'hvhxfm5u=^*v&doo#oq8x*eg8+1&9sxbye@=umutgn^t_sg_nx'

# Ensure that email is not sent via SMTP by default to match the standard App
# Engine SDK behaviour. If you want to sent email via SMTP then add the name of
# your mailserver here.
EMAIL_HOST = ''

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.load_template_source',
    'common.ragendja.template.app_prefixed_loader',
    'django.template.loaders.app_directories.load_template_source',
)

MIDDLEWARE_CLASSES = (
'common.ragendja.middleware.ErrorMiddleware',
'django.contrib.sessions.middleware.SessionMiddleware',
# 'appengine_django.auth.middleware.AuthenticationMiddleware',
# Django authentication
# 'django.contrib.auth.middleware.AuthenticationMiddleware',
# Google authentication
# 'common.ragendja.auth.middleware.GoogleAuthenticationMiddleware',
# Hybrid Django/Google authentication
'common.ragendja.auth.middleware.HybridAuthenticationMiddleware',
'django.middleware.common.CommonMiddleware',
'django.middleware.locale.LocaleMiddleware',
# 'common.ragendja.middleware.LoginRequiredMiddleware',
# 'ragendja.sites.dynamicsite.DynamicSiteIDMiddleware',
# 'django.contrib.flatpages.middleware.FlatpageFallbackMiddleware',
# 'django.contrib.redirects.middleware.RedirectFallbackMiddleware',
'djangoflash.middleware.FlashMiddleware',
)

TEMPLATE_CONTEXT_PROCESSORS = (
    'django.core.context_processors.auth',
    'django.core.context_processors.debug',
    # 'django.core.context_processors.i18n',
    'common.ragendja.auth.context_processors.google_user',
#    'django.core.context_processors.media',  # 0.97 only.
   # 'django.core.context_processors.request',
    'djangoflash.context_processors.flash',
)

ROOT_URLCONF = 'urls'

INSTALLED_APPS = (
     'appengine_django',
     'django.contrib.auth',
     'django.contrib.sessions',
     # 'django.contrib.admin',
     'django.contrib.webdesign',
     'django.contrib.flatpages',
     'django.contrib.redirects',
     'django.contrib.sites',
     #'django_nose',
     'common.ragendja',
     'account',
     'api',
     'publisher',
     'advertiser',
     'website',
     'admin',
     'common',
     'budget',
     'registration',
     'reports',
     'ad_network_reports',
     'networks',
)

#TEST_RUNNER = 'django_nose.NoseTestSuitRunner'

IGNORE_APP_URLSAUTO = ('website')

AUTHENTICATION_BACKENDS = ('common.ragendja.auth.backends.MPModelBackend',)

AUTH_USER_MODULE = 'account.models'

LOGIN_URL = '/account/login/'
LOGOUT_URL = '/account/logout/'
LOGIN_REDIRECT_URL = '/inventory/'

LOGIN_REQUIRED_PREFIXES = (
    '/inventory/',
    '/campaigns/',
    '/networks/',
)

ACCOUNT_ACTIVATION_DAYS = 14

PWD = os.path.dirname(os.path.abspath(__file__))
VERSIONS_FILE = os.path.join(PWD, 'versions.yaml')

import yaml
config = yaml.load(open(VERSIONS_FILE, 'r'))

SCRIPTS_VERSION_NUMBER = config['scripts']
STYLES_VERSION_NUMBER = config['styles']
STATIC_VERSION_NUMBER = SCRIPTS_VERSION_NUMBER

from common.ragendja.settings_post import *

#add additional settings for local machine settings
try:
    from local_settings import *
except ImportError:
    pass

