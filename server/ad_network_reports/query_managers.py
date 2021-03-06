import logging
import os
import sys
import urllib

# Are we on EC2 (Note can't use django.settings_module since it's not defined)
# TODO: Add this stuff to my path on EC2
if os.path.exists('/home/ubuntu/'):
    sys.path.append('/home/ubuntu/mopub/server')
    sys.path.append('/home/ubuntu/google_appengine')
    sys.path.append('/home/ubuntu/google_appengine/lib/antlr3')
    sys.path.append('/home/ubuntu/google_appengine/lib/django_1_2')
    sys.path.append('/home/ubuntu/google_appengine/lib/fancy_urllib')
    sys.path.append('/home/ubuntu/google_appengine/lib/ipaddr')
    sys.path.append('/home/ubuntu/google_appengine/lib/webob')
    sys.path.append('/home/ubuntu/google_appengine/lib/yaml/lib')

    import common.utils.test.setup

from datetime import datetime, timedelta

from account.query_managers import AccountQueryManager
from ad_network_reports.models import AdNetworkLoginCredentials, \
     AdNetworkAppMapper, \
     AdNetworkStats, \
     AdNetworkScrapeStats, \
     AdNetworkNetworkStats, \
     AdNetworkAppStats, \
     AdNetworkManagementStats, \
     STAT_NAMES, \
     MANAGEMENT_STAT_NAMES, \
     FAILED_LOGINS
from common.utils.query_managers import CachedQueryManager
from common.constants import REPORTING_NETWORKS
from google.appengine.ext import db
from publisher.query_managers import AppQueryManager

from reporting.models import StatsModel

ADMOB = 'admob'
IAD = 'iad'
INMOBI = 'inmobi'
MOBFOX = 'mobfox'
MOBFOX_PRETTY = 'MobFox'

# TODO: Refactor the shit out of this, OMG can't believe I wrote some of this

class AdNetworkLoginManager(CachedQueryManager):
    # TODO: use get_by_key
    @classmethod
    def get_logins(cls,
                   account=None,
                   network='',
                   order_by_account=False):
        """
        Return AdNetworkLoginCredentials entities with the given parameters.
        """
        query = AdNetworkLoginCredentials.all()
        if account:
            query.filter('account =', account)
        if network:
            query.filter('ad_network_name =', network)
        if order_by_account:
            query.order('account')
        return query

    @classmethod
    def get_number_of_accounts(cls):
        """
        Return the total number of accounts using ad network revenue
        reporting.
        """
        accounts = set()
        for login in list(AdNetworkLoginCredentials.all().run(batch_size=300)):
            accounts.add(str(login.account.key()))
        return len(accounts)

class AdNetworkMapperManager(CachedQueryManager):
    @classmethod
    def create(cls,
               network,
               pub_id,
               login,
               app):
        """
        Create an AdNetworkAppMapper for the given input data
        """
        mapper = AdNetworkAppMapper(ad_network_name=network,
                           publisher_id=pub_id,
                           ad_network_login=login,
                           application=app)
        mapper.put()
        return mapper

    @classmethod
    # get_mappers_by_login
    def get_mappers(cls,
                    login=None,
                    app=None):
        """
        Return a generator of the AdNetworkAppMappers with this login.
        """
        query = AdNetworkAppMapper.all()
        if login:
            query.filter('ad_network_login =', login)
        if app:
            query.filter('application =', app)
        return query

    @classmethod
    # get_mappers
    def get_mappers_for_account(cls,
                    account,
                    network_name=''):
        """
        Inner join AdNetworkLoginCredentials with AdNetworkAppMapper.

        Return a generator of the AdNetworkAppMappers with this account.
        """
        for login in AdNetworkLoginManager. \
                get_logins(account):
            query = AdNetworkAppMapper.all().filter('ad_network_login =',
                    login)
            if network_name:
                query.filter('ad_network_name =', network_name)
            for mapper in query:
                yield mapper

    @classmethod
    def get_mapper(cls,
                   pub_id,
                   network):
        return AdNetworkAppMapper.get_by_publisher_id(pub_id, network)

    @classmethod
    def get(cls,
            mapper_key):
        return AdNetworkAppMapper.get(mapper_key)

class AdNetworkStatsManager(CachedQueryManager):
    @classmethod
    def roll_up_unique_stats(cls,
                             aggregate_stats_list,
                             networks=True):
        """
        Generate the stats roll ups required for the index page.

        Put the apps into an intuitive data structure
        Apps are mapped to their stats, as well as to a list of
        their individual network stats. E.g. :

        Network level roll up: (kwarg networks=True)
        {
            'network1' : {
                'sub_data': [ {app1_stats ... appN_stats],
                'revenue': 0,
                'attempts': 0,
                'impressions': 0,
                'fill_rate': 0,
                'clicks': 0,
                'ctr': 0,
                ...
            }
            ...
        }

        App level roll up (kwarg networks=False):
        {
            'app1' : {
                'sub_data': [ {network1_stats ... networkN_stats],
                'revenue': 0,
                'attempts': 0,
                'impressions': 0,
                'fill_rate': 0,
                'clicks': 0,
                'ctr': 0,
                ...
            }
            ...
        }

        Return the sorted list of lists which contain the rolled up stats for
        the account.
        """
        data_dict = {}
        for mapper, stats, sync_date in aggregate_stats_list:
            app = mapper.application
            if networks:
                attr = REPORTING_NETWORKS[mapper.ad_network_name]
                name = app.full_name
            else:
                attr = app.full_name
                name = REPORTING_NETWORKS[mapper.ad_network_name]
            sub_data = {
                'name': name,
                'revenue': stats.revenue,
                'attempts': stats.attempts,
                'impressions': stats.impressions,
                'cpm': stats.cpm,
                'fill_rate': stats.fill_rate,
                'clicks': stats.clicks,
                'ctr': stats.ctr,
                'cpc': stats.cpc,
            }
            if attr not in data_dict:
                data_dict[attr] = {
                    'sub_data_list': [],
                    'revenue': 0.0,
                    'attempts': 0,
                    'fill_rate_impressions': 0,
                    'impressions': 0,
                    'cpm': 0.0,
                    'fill_rate': 0.0,
                    'clicks': 0,
                    'ctr': 0.0,
                    'cpc': 0.0,
                }
            data_dict[attr]['sub_data_list'].append(sub_data)
            data_dict[attr]['revenue'] += sub_data['revenue']
            data_dict[attr]['attempts'] += sub_data['attempts']
            # Only include impressions in fill rate calculations when attempts
            # is != 0 (MobFox doesn't report attempts)
            if sub_data['attempts']:
                data_dict[attr]['fill_rate_impressions'] += \
                        sub_data['impressions']
            data_dict[attr]['impressions'] += sub_data['impressions']
            data_dict[attr]['clicks'] += sub_data['clicks']

        # Calculate stats for highest level roll up for networks or apps.
        for data in data_dict.values():
            # Sort sub_data list by app name or network name.
            data['sub_data_list'] = sorted(data['sub_data_list'], key=lambda \
                    sub_data: sub_data['name'].lower())
            if data['attempts']:
                data['fill_rate'] = data['fill_rate_impressions'] / float(
                        data['attempts'])
            if data['clicks']:
                data['cpc'] = data['revenue'] / data['clicks']
            if data['impressions']:
                data['cpm'] = data['revenue'] / data['impressions'] * 1000
                data['ctr'] = (data['clicks'] /
                        float(data['impressions']))

        # Sort alphabetically
        data_list = sorted(data_dict.items(), key=lambda data_tuple:
                data_tuple[0].lower())

        return data_list

    @classmethod
    def get_stats_for_mapper_and_days(cls,
                                      ad_network_app_mapper,
                                      days):
        """Calculate aggregate stats for an ad network and app
        for the given days.

        Return the aggregate stats.
        """
        stats_list, last_day = AdNetworkScrapeStats.get_by_app_mapper_and_days(
                ad_network_app_mapper.key(), days, include_last_day=True)
        if stats_list:
            return (cls.roll_up_stats(stats_list), last_day)

    @classmethod
    def roll_up_stats(cls,
                      stats_iterable):
        """Roll up (aggregate) stats in the stats iterable.

        Take a stats iterable (query or list).

        Return a stats object.
        """
        aggregate_stats = AdNetworkStats()

        aggregate_stats.fill_rate_impressions = 0
        for stats in stats_iterable:
            aggregate_stats += stats

            if stats.attempts:
                aggregate_stats.fill_rate_impressions += stats.impressions

        return aggregate_stats

    @classmethod
    def get_stats_for_days(cls,
                           mapper_key,
                           days):
        """Filter AdNetworkScrapeStats for a given ad_network_app_mapper. Sort
        chronologically by day, newest first (decending order.)

        Return a list of stats sorted by date.
        """
        stats_list = AdNetworkScrapeStats.get_by_app_mapper_and_days(mapper_key, days)
        return sorted(stats_list, key=lambda stats: stats.date, reverse=True)

    @classmethod
    def copy_stats(cls,
                   stats1,
                   stats2):
        for stat in STAT_NAMES:
            setattr(stats1, stat, getattr(stats2, stat))

    @classmethod
    def combined_stats(cls,
                       stats1,
                       stats2,
                       subtract=False):
        """
        stats1 = stats1 + stats2
        """
        for stat in STAT_NAMES:
            # example: stats1.revenue += stats2.revenue
            if subtract:
                setattr(stats1, stat, getattr(stats1, stat) - getattr(stats2,
                    stat))
            else:
                setattr(stats1, stat, getattr(stats1, stat) + getattr(stats2,
                    stat))


class AdNetworkAggregateManager(CachedQueryManager):
    @classmethod
    def create_stats(cls,
                     account,
                     day,
                     stats_list,
                     network=None,
                     app=None):
        if network:
            stats = AdNetworkNetworkStats(account=account,
                                          ad_network_name=network,
                                          date=day)
        elif app:
            stats = AdNetworkAppStats(account=account,
                                      application=app,
                                      date=day)
        else:
            raise LookupError("Method needs either an app or a network.")
        AdNetworkStatsManager.copy_stats(stats,
                AdNetworkStatsManager.roll_up_stats(stats_list))
        return stats

    @classmethod
    def update_stats(cls,
                     account,
                     mapper,
                     day,
                     stats,
                     network=None,
                     app=None):
        old_stats = AdNetworkScrapeStats.get_by_app_mapper_and_day(mapper,
                day)
        aggregate_stats = cls.find_or_create(account, day, network, app)
        # Do AdNetworkScrapeStats already exist for the app, network and
        # day?
        if old_stats:
            AdNetworkStatsManager.combined_stats(aggregate_stats, old_stats,
                    subtract=True)
        AdNetworkStatsManager.combined_stats(aggregate_stats, stats)
        aggregate_stats.put()

    @classmethod
    def find_or_create(cls,
                       account,
                       day,
                       network=None,
                       app=None,
                       create=True):
        if network:
            stats = AdNetworkNetworkStats.get_by_network_and_day(account,
                                                                network,
                                                                day)
            if create and not stats:
                return AdNetworkNetworkStats(account=account,
                                             ad_network_name=network,
                                             date=day)
            return stats
        elif app:
            stats = AdNetworkAppStats.get_by_app_and_day(account,
                                                        app,
                                                        day)
            if create and not stats:
                return AdNetworkAppStats(account=account,
                                         application=app,
                                         date=day)
            return stats
        raise LookupError("Method needs either an app or a network.")

    @classmethod
    def get_stats_for_day(cls,
                          account,
                          day):
        """Get rolled up stats for the given date (include all ad networks).

        Return rolled up stats.
        """
        stats_list = []
        for network in REPORTING_NETWORKS.keys():
            stats = AdNetworkNetworkStats.get_by_network_and_day(
                            account,
                            network,
                            day)
            if stats:
                stats_list.append(stats)
        return(AdNetworkStatsManager.roll_up_stats(stats_list))


# TODO: refactor model naming: make it less verbose so shit like this won't
# happen
class AdNetworkNetworkStatsManager(CachedQueryManager):
    @classmethod
    def get_stats_for_days(cls, account, network, days):
        return AdNetworkNetworkStats.get_by_network_and_days(account, network,
                days)

class AdNetworkAppStatsManager(CachedQueryManager):
    @classmethod
    def get_stats_for_days(cls, account, app, days):
        return AdNetworkAppStats.get_by_app_and_days(account, app, days)

# TODO: refactor model naming: make it less verbose so shit like this won't
# happen
class AdNetworkManagementStatsManager(CachedQueryManager):
    def __init__(self,
                 day,
                 assemble=False):
        self.day = day
        self.stats_dict = {}
        for network in REPORTING_NETWORKS.keys():
            if assemble:
                self.stats_dict[network] = AdNetworkManagementStats. \
                        get_by_day(network, day)
            else:
                self.stats_dict[network] = AdNetworkManagementStats(
                        ad_network_name=network,
                        date=day)

    @property
    def failed_logins(self):
        failed_logins = []
        for stats in self.stats_dict.itervalues():
            failed_logins += stats.failed_logins
        return failed_logins

    def clear_failed_logins(self):
        """
        Clear failed logins from management stats.
        """
        for stats in self.stats_dict.itervalues():
            stats.failed_logins = []
            stats.put()

    def append_failed_login(self,
                            login_credentials):
        if isinstance(login_credentials, unicode):
            login_key = login_credentials
            login_credentials = AdNetworkLoginManager.get(login_key)
        else:
            login_key = str(login_credentials.key())
        self.stats_dict[login_credentials.ad_network_name].failed_logins.append(
                login_key)

    def get_failed_logins(self):
        for stats in self.stats_dict.values():
            if stats.failed_logins:
                for login in stats.failed_logins:
                    yield login

    def increment(self,
                  ad_network_name,
                  field):
        setattr(self.stats_dict[ad_network_name], field,
                getattr(self.stats_dict[ad_network_name], field) + 1)

    def combined(self,
                 stats_manager):
        for network in REPORTING_NETWORKS.keys():
            for stat in (list(MANAGEMENT_STAT_NAMES) + [FAILED_LOGINS]):
                setattr(self.stats_dict[network], stat, getattr(
                    self.stats_dict[network], stat) + getattr(
                    stats_manager.stats_dict[network], stat))

    def put_stats(self):
        for stats in self.stats_dict.values():
            stats.put()

    @classmethod
    def get_stats(cls,
                  days):
        management_stats = {}
        for ad_network_name in REPORTING_NETWORKS.keys():
            management_stats[ad_network_name] = AdNetworkManagementStats. \
                    get_by_days(ad_network_name, days)
        return management_stats

