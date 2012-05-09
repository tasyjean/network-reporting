import os
import sys

sys.path.append(os.environ['PWD'])

import common.utils.test.setup

from django.core.urlresolvers import reverse

from admin.randomgen import generate_app, generate_adunit
from common.utils.test.views import BaseViewTestCase
from publisher.query_managers import PublisherQueryManager


class AppIndexViewTestCase(BaseViewTestCase):
    def test_http_response_code(self):
        url = reverse('app_index')
        response = self.client.get(url)
        self.assertTrue(response.status_code in [200, 302])


class CreateAppViewTestCase(BaseViewTestCase):
    def setUp(self):
        super(CreateAppViewTestCase, self).setUp()

        self.app1 = generate_app(self.account)
        self.app2 = generate_app(self.account)
        self.app3 = generate_app(self.account)
        self.adunit1 = generate_adunit(self.app1, self.account)

    def test_create_app(self):
        apps_dict = PublisherQueryManager.get_apps_dict_for_account(account=self.account)
        self.assertEqual(len(apps_dict), 3)

        url = reverse('publisher_create_app')
        data = {
            u'adunit-name': [u'Banner Ad'],
            u'adunit-description': [u'\r\n'],
            u'adunit-custom_height': [u''],
            u'app_type': [u'iphone'],
            u'name': [u'Angry Birds'],
            u'package': [u''],
            u'url': [u'', u''],
            u'img_file': [u''],
            u'secondary_category': [u''],
            u'adunit-custom_width': [u''],
            u'adunit-format': [u'320x50'],
            u'adunit-app_key': [u''],
            u'adunit-device_format': [u'phone'],
            u'img_url': [u''],
            u'primary_category': [u'books'],
            u'adunit-refresh_interval': [u'0'],
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        apps_dict = PublisherQueryManager.get_apps_dict_for_account(account=self.account)
        self.assertEqual(len(apps_dict), 4)
