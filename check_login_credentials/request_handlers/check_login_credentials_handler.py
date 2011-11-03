import copy
import json
import logging
import sys
sys.path.append('/home/ubuntu/mopub_experimental/server')

import tornado.web

from account.query_managers import AccountQueryManager
from ad_network_reports.ad_networks import AD_NETWORKS, AdNetwork
from ad_network_reports.forms import LoginInfoForm
from ad_network_reports.query_managers import AdNetworkReportQueryManager

class AdNetworkLoginCredentials(object):
    pass

def setup_remote_api():
    from google.appengine.ext.remote_api import remote_api_stub
    app_id = 'mopub-experimental'
    host = '38.latest.mopub-experimental.appspot.com'
    #app_id = 'mopub-inc'
    #host = '38.latest.mopub-inc.appspot.com'
    remote_api_stub.ConfigureRemoteDatastore(app_id, '/remote_api', auth_func,
            host)

class CheckLoginCredentialsHandler(tornado.web.RequestHandler):
    def get(self, *args, **kwargs):
        callback = self.get_argument('callback')
        logging.warning("Arguments")
        logging.warning(self.request.arguments)

        ad_network = self.get_argument('ad_network_name')
        initial = {}
        for network in AD_NETWORKS.keys():
            initial[network + '-ad_network_name'] = network

        args = {}
        for key, value in self.request.arguments.iteritems():
            args[key] = value[0]
        args.update(initial)

        logging.warning(args)
        # Can't have the same name as the model. Fixes unicode bug.
        args[ad_network + '-password2'] = args[ad_network + '-password']
        form = LoginInfoForm(args, prefix=ad_network)

        if form.is_valid():
            login_credentials = AdNetworkLoginCredentials()
            login_credentials.ad_network_name = form.cleaned_data[
                    'ad_network_name']
            login_credentials.username = form.cleaned_data['username']
            logging.warning('cleaned data')
            logging.warning(form.cleaned_data)
            login_credentials.password = form.cleaned_data['password2']
            login_credentials.client_key = form.cleaned_data['client_key']
            logging.warning(login_credentials.__dict__)

            try:
                logging.warning("Creating the scraper object")
                scraper = AdNetwork(login_credentials).create_scraper()
                logging.warning("Testing the login info")
                scraper.test_login_info()
                logging.warning("Returning true")
                self.write(callback + '(true)')
                return
            except Exception as e:
                # We don't want Tornado to stop running if something breaks
                # somewhere.
                logging.error(e)
            else:
                setup_remote_api()
                account_key = self.get_argument('account_key')
                manager = AdNetworkReportQueryManager(AccountQueryManager.
                        get_account_by_key(account_key))
                wants_email = self.get_argument('email', False) and True
                manager.create_login_credentials_and_mappers(ad_network_name=
                        login_credentials.ad_network_name,
                        username=login_credentials.username
                        password=login_credentials.password
                        client_key=login_credentials.client_key
                        send_email=wants_email)

        logging.warning("Returning false")
        self.write(callback + '(false)')

