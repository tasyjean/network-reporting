# -*- coding: utf-8 -*-
import os
from google.appengine.api import apiproxy_stub_map

from google.appengine.api import apiproxy_stub_map
import os, sys

have_appserver = bool(apiproxy_stub_map.apiproxy.GetStub('datastore_v3'))

if have_appserver:
    appid = os.environ.get('APPLICATION_ID')
else:
    try:
        from google.appengine.tools import dev_appserver
        from aecmd import PROJECT_DIR
        appconfig, unused = dev_appserver.LoadAppConfig(PROJECT_DIR, {})
        appid = appconfig.application
    except ImportError:
        appid = None

on_production_server = have_appserver and \
    not os.environ.get('SERVER_SOFTWARE', '').lower().startswith('devel')

have_appserver = bool(apiproxy_stub_map.apiproxy.GetStub('datastore_v3'))

DEBUG = not on_production_server

# The MEDIA_VERSION will get integrated via %d
MEDIA_URL = '/media/%d/'
# The MEDIA_URL will get integrated via %s
ADMIN_MEDIA_PREFIX = '%sadmin_media/'

ADMINS = ()

DATABASE_ENGINE = 'appengine'
DATABASE_SUPPORTS_TRANSACTIONS = False

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

EMAIL_HOST = 'localhost'
EMAIL_PORT = 25
EMAIL_HOST_USER = 'user'
EMAIL_HOST_PASSWORD = 'password'
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = 'user@localhost'
SERVER_EMAIL = 'user@localhost'
EMAIL_BACKEND = 'appengine_django.mail.GoogleSMTPConnection'

LOGIN_REQUIRED_PREFIXES = ()
NO_LOGIN_REQUIRED_PREFIXES = ()

ROOT_URLCONF = 'urls'

TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.load_template_source',
    'common.ragendja.template.app_prefixed_loader',
    'django.template.loaders.app_directories.load_template_source',
)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(__file__))))
COMMON_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
MAIN_DIRS = (PROJECT_DIR, COMMON_DIR)

TEMPLATE_DIRS = tuple([os.path.join(dir, 'templates') for dir in MAIN_DIRS])

LOCALE_PATHS = (
    os.path.join(PROJECT_DIR, 'media', 'locale'),
) + tuple([os.path.join(dir, 'locale') for dir in TEMPLATE_DIRS])

FILE_UPLOAD_HANDLERS = (
    'django.core.files.uploadhandler.MemoryFileUploadHandler',
)

CACHE_BACKEND = 'memcached://?timeout=0'

COMBINE_MEDIA = {}

if not on_production_server:
    INTERNAL_IPS = ('127.0.0.1',)

IGNORE_APP_SETTINGS = ()
