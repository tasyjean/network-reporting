import logging
import sys
import urllib

EC2 = True

if EC2:
    sys.path.append('/home/ubuntu/mopub/server')
    sys.path.append('/home/ubuntu/google_appengine')
    sys.path.append('/home/ubuntu/google_appengine/lib/antlr3')
    sys.path.append('/home/ubuntu/google_appengine/lib/django_1_2')
    sys.path.append('/home/ubuntu/google_appengine/lib/fancy_urllib')
    sys.path.append('/home/ubuntu/google_appengine/lib/ipaddr')
    sys.path.append('/home/ubuntu/google_appengine/lib/webob')
    sys.path.append('/home/ubuntu/google_appengine/lib/yaml/lib')

    import common.utils.test.setup

from google.appengine.ext import db

from account.models import NetworkConfig
from common.utils import date_magic
from common.utils.query_managers import CachedQueryManager
from ad_network_reports.models import AdNetworkLoginInfo, AdNetworkAppMapper, \
        AdNetworkScrapeStats
from publisher.models import App

class Stats(object):
    pass

class AdNetworkReportQueryManager(CachedQueryManager):
    def __init__(self, account=None):
        self.account = account

    def get_ad_network_mappers(self):
        """Inner join AdNetworkLoginInfo with AdNetworkAppMapper.

        Return a generator of the AdNetworkAppMappers with this account.
        """
        for credential in AdNetworkLoginInfo.all().filter('account =',
                self.account):
            for mapper in AdNetworkAppMapper.all().filter('ad_network_login =',
                    credential):
                yield mapper

    def get_ad_network_aggregates(self, ad_network_app_mapper,
            start_date, end_date):
        """Calculate aggregate stats for an ad network and app
        between the given start date and end date.

        Return the aggregate stats.
        """
        query = AdNetworkScrapeStats.all()
        query.filter('ad_network_app_mapper =', ad_network_app_mapper)
        query.filter('date IN', date_magic.gen_days(start_date, end_date))

        return self.roll_up_stats(query)

    def roll_up_stats(self, stats_iterable):
        """Roll up (aggregate) stats in the stats iterable.

        Take a stats iterable (query or list).

        Return a stats object.
        """
        aggregate_stats = Stats()
        aggregate_stats.revenue = 0
        aggregate_stats.attempts = 0
        aggregate_stats.impressions = 0
        aggregate_stats.clicks = 0
        aggregate_stats.ecpm = 1

        aggregate_stats.fill_rate_impressions = 0
        for stats in stats_iterable:
            old_impressions_total = stats.impressions

            aggregate_stats.revenue += stats.revenue
            aggregate_stats.attempts += stats.attempts
            aggregate_stats.impressions += stats.impressions
            aggregate_stats.clicks += stats.clicks

            if stats.attempts != 0:
                aggregate_stats.fill_rate_impressions += stats.impressions

            if aggregate_stats.impressions != 0:
                aggregate_stats.ecpm += stats.ecpm * stats.impressions

        if aggregate_stats.attempts != 0:
            aggregate_stats.fill_rate = (aggregate_stats.fill_rate_impressions /
                    float(aggregate_stats.attempts)) * 100
        else:
            aggregate_stats.fill_rate = 0
        if aggregate_stats.impressions != 0:
            aggregate_stats.ctr = (aggregate_stats.clicks /
                    float(aggregate_stats.impressions)) * 100
            aggregate_stats.ecpm /= float(aggregate_stats.impressions)
        else:
            aggregate_stats.ctr = 0

        return aggregate_stats

    def get_ad_network_app_stats(self, ad_network_app_mapper):
        """Filter AdNetworkStats for a given ad_network_app_mapper. Sort
        chronologically by day, newest first (decending order.)

        Return the query (a generator.)
        """
        query = AdNetworkScrapeStats.all()
        query.filter('ad_network_app_mapper =', ad_network_app_mapper)
        query.order('-date')
        return query

    def get_ad_network_app_mapper(self, ad_network_app_mapper_key = None,
            publisher_id = None, login_info = None):
        """Keyword arguments: either an ad_network_app_mapper_key or a
        publisher_id and login_info.

        Return the corresponding AdNetworkAppMapper.
        """
        if ad_network_app_mapper_key:
            return db.get(ad_network_app_mapper_key)
        elif publisher_id and login_info:
            query = AdNetworkAppMapper.all()
            query.filter('publisher_id =', publisher_id)
            query.filter('ad_network_login =', login_info)
            return query.get()
        return None

    def get_apps_with_publisher_ids(self, ad_network_name):
        """Check apps to see if their pub_id for the given ad_network is
        defined

        Return generator of applications with publisher ids for the account on
        the ad_network.
        """
        for app in App.all().filter('account =',
                self.account).filter('network_config !=', None):
            pub_id = getattr(app.network_config, '%s_pub_id' % ad_network_name,
                    None)
            if pub_id != None:
                # example return (App, NetworkConfig.admob_pub_id)
                yield (app, pub_id)

    def create_login_info_and_mappers(self, ad_network_name, username, password,
            client_key, send_email):
        """Check login credentials by making a request to tornado on EC2. If
        they're valid create AdNetworkLoginInfo and AdNetworkAppMapper entities
        and store them in the db.

        Return None if the login credentials are correct otherwise return an
        error message.
        """
        login_info = AdNetworkLoginInfo(account=self.account,
                                        ad_network_name=ad_network_name,
                                        username=username,
                                        password=password,
                                        client_key=client_key)

        login_info.put()

        apps_with_publisher_ids = self.get_apps_with_publisher_ids(
                ad_network_name)
        # Create all the different AdNetworkAppMappers for all the
        # applications on the ad network for the user and add them to the db
        db.put([AdNetworkAppMapper(ad_network_name = ad_network_name,
            publisher_id = publisher_id, ad_network_login = login_info,
            application = app, send_email = send_email) for app,
            publisher_id in apps_with_publisher_ids])

    def find_app_for_stats(self, publisher_id, login_info):
        """Attempt to link the publisher id with an App stored in MoPub's db.

        Check if the publisher id is in MoPub. If it is create an
        AdNetworkAppMapper and update the AdNetworkLoginInfo.

        Return the mapper or None.
        """
        # Sanity check
        if publisher_id:
            ad_network_name = login_info.ad_network_name
            for app in App.all().filter('account =',
                    self.account).filter('network_config !=', None):
                # Is the app in Mopub?
                if getattr(app.network_config, ad_network_name + '_pub_id', None) \
                        == publisher_id:
                    mapper = AdNetworkAppMapper(ad_network_name=ad_network_name,
                                                publisher_id=publisher_id,
                                                ad_network_login=login_info,
                                                application=app)
                    mapper.put()
                    return mapper

    def get_app_publisher_ids(self, ad_network_name):
        """Check apps to see if their pub_id for the given ad_network is
        defined

        Return generator of publisher ids at the application level for the
        account on the ad_network.
        """
        for app in App.all().filter('account =',
                self.account).filter('network_config !=', None):
            pub_id = getattr(app.network_config, '%s_pub_id' % ad_network_name,
                    None)
            if pub_id != None:
                yield pub_id

    def get_adunit_publisher_ids(self, ad_network_name):
        """Get the ad unit publisher ids with the ad network from the generator
        of apps.

        Return a generator of ad unit publisher ids.
        """
        for app in App.all().filter('account =', self.account):
            for adunit in app.all_adunits:
                if hasattr(adunit, 'network_config') and getattr(adunit.
                        network_config, '%s_pub_id' % ad_network_name, None):
                    yield getattr(adunit.network_config, '%s_pub_id' %
                            ad_network_name)
#        return [getattr(adunit.network_config, '%s_pub_id' % ad_network_name)
#                for app in App.all().filter('account =', account) for adunit in
#                app.all_adunits if hasattr(adunit, 'network_config') and
#                getattr(adunit.network_config, '%s_pub_id' % ad_network_name,
#                    None)]

def get_all_login_credentials():
    """Return all AdNetworkLoginInfo entities ordered by account."""
    return AdNetworkLoginInfo.all().order('account')