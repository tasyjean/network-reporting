import logging

from google.appengine.api import taskqueue
from google.appengine.ext import db

from common.utils.query_managers import QueryManager, CachedQueryManager
from common.utils.decorators import wraps_first_arg
from common.utils.timezones import Pacific_tzinfo
from common.utils.tzinfo import utc

from common.constants import CAMPAIGN_LEVELS, \
        NETWORKS, \
        NETWORK_ADGROUP_TRANSLATION

from advertiser.models import Campaign, AdGroup, \
                              Creative, \
                              TextAndTileCreative, \
                              HtmlCreative,\
                              ImageCreative, \
                              NetworkStates

from publisher.query_managers import AdUnitQueryManager, AdUnitContextQueryManager

import copy

from common.constants import MAX_OBJECTS

NAMESPACE = None

MAX_ALLOWABLE_QUERIES = 30

def chunks(l, n):
    """ Yield successive n-sized chunks from l.
    """
    for i in xrange(0, len(l), n):
        yield l[i:i+n]

class AdvertiserQueryManager(CachedQueryManager):

    @classmethod
    def get_objects_dict_for_account(cls, account, include_deleted=False):
        """
        Returns a dictionary mapping Campaign keys to Campaign
        entities carrying Adgroup data.  Adgroups for each campaign
        can be retrieved as a list by using campaign._adgroups.
        Similarly, each Adgroup contains a list of its creatives,
        accessible as adgroup._creatives.
        """
        campaigns_dict = cls.get_campaigns_dict_for_account(account,
                include_deleted=include_deleted)
        adgroups_dict = cls.get_adgroups_dict_for_account(account,
                include_deleted=include_deleted, include_archived=True)
        creatives_dict = cls.get_creatives_dict_for_account(account,
                include_deleted=include_deleted)

        # Initialize the _creatives property for all of our adgroups.
        for adgroup in adgroups_dict.values():
            adgroup._creatives = []

        # Associate each creative with its adgroup.
        for creative in creatives_dict.values():
            # Looks weird, but we're just avoiding
            # creative.app_group.key() since it incurs a fetch.
            adgroup_key = str(Creative.ad_group.get_value_for_datastore(creative))
            try:
                adgroup_for_this_creative = adgroups_dict[adgroup_key]
                adgroup_for_this_creative._creatives.append(creative)
            except KeyError:

                # If we get here, it means that the creative belongs
                # to an adgroup that is not owned by this
                # account. This is clearly a sign of data corruption,
                # and these objects need to be fixed manually.
                logging.error("KeyError: Creative %s belongs to AdGroup %s which is not owned by %s" % (str(creative.key()), str(adgroup_key), account.mpuser.email))

        # Initialize the _adgroups property for all of our campaigns.
        for campaign in campaigns_dict.values():
            campaign._adgroups = []

        # Now we have a dictionary (adgroups_dict) mapping adgroup
        # keys to adgroup objects, where each adgroup object has a
        # list of its creatives. We can take this one step further to
        # work campaigns into this dict.
        for adgroup in adgroups_dict.values():
            # Again, getting around the fetch.
            campaign_key = str(AdGroup.campaign.get_value_for_datastore(adgroup))
            if campaign_key in campaigns_dict:
                campaign_for_this_adgroup = campaigns_dict[campaign_key]
                campaign_for_this_adgroup._adgroups.append(adgroup)
            net_creative_key = str(AdGroup.net_creative.get_value_for_datastore(adgroup))
            if net_creative_key in creatives_dict:
                adgroup.net_creative = creatives_dict[net_creative_key]

        return campaigns_dict

    @classmethod
    def get_campaigns_dict_for_account(cls, account, include_deleted=False):
        return cls.get_entities_for_account(account, Campaign, include_deleted)

    @classmethod
    def get_adgroups_dict_for_account(cls, account, include_deleted=False, include_archived=False):
        return cls.get_entities_for_account(account, AdGroup, include_deleted, include_archived)

    @classmethod
    def get_creatives_dict_for_account(cls, account, include_deleted=False):
        return cls.get_entities_for_account(account, Creative, include_deleted)


class CampaignQueryManager(QueryManager):
    Model = Campaign

    @classmethod
    def get_order_campaigns(cls, account):
        """
        Gets all campaigns for `account` that are orders (direct sold campaigns).
        """
        campaigns = cls.Model.all().filter('account =', account)\
                                   .filter('deleted =', False)\
                                   .filter('campaign_type =', 'order')\
                                   .order('name')\
                                   .fetch(1000)
        return campaigns

    @classmethod
    def get_campaigns_by_types(cls, account, types):
        campaigns = cls.Model.all().filter('account =', account)\
                                   .filter('campaign_type IN', types)\
                                   .filter('deleted =', False)
        return campaigns

    @classmethod
    def get_network_campaigns(cls, account, network_type=False, is_new=None):
        """
        is_new refers to models with the network_type attribute set,
        which means it's a new type of campaign (used by the networks django
        app).
        """
        # get campaigns for the account from memcache
        campaigns = AdvertiserQueryManager.get_campaigns_dict_for_account(account)

        def network_campaign_filter(campaign):
            if campaign.campaign_type == 'network':
                if network_type:
                    return campaign.network_type == network_type
                elif is_new:
                    return campaign.network_state != NetworkStates.STANDARD_CAMPAIGN
                elif is_new is False:
                    return campaign.network_state == NetworkStates.STANDARD_CAMPAIGN
                else:
                    return True

        return filter(network_campaign_filter, campaigns.values())

    @classmethod
    def get_default_network_campaign(cls, account, network, get_from_db=False):
        # Force to string
        account_key = str(account.key())

        cp_key_name = cls._get_network_key_name(account_key, network)

        if get_from_db:
            campaign = Campaign.get_by_key_name(cp_key_name)
            return campaign

        campaign = Campaign(key_name=cp_key_name, name=NETWORKS[network])

        # set the properties
        campaign.account = account
        campaign.campaign_type = 'network'
        campaign.network_type = network
        campaign.network_state = NetworkStates.DEFAULT_NETWORK_CAMPAIGN

        return campaign

    @classmethod
    def _get_network_key_name(cls, account_key, network):
        """
        Returns the key_name based on the account key and network
        """
        return 'ntwk:%s:%s' % (account_key, network)


    @classmethod
    def get_marketplace(cls, account, from_db=False):
        """
        Returns the only campaign that can belong to this account.
        The magic of key_names allows us to
        avoid getting the object from the db because
        all the information is a function of the account itself.

        Note: it is the API consumer's responsiblity to actually
        save this object with the put method of this class
        """
        # get the account_key from the model if necessary
        if isinstance(account, db.Model):
            account_key = account.key()
        elif isinstance(account, (str, unicode)):
            account_key = db.Key(account)
        else:
            account_key = account

        c_key_name = cls._get_marketplace_key_name(account_key)

        if from_db:
            return Campaign.get_by_key_name(c_key_name)
        return Campaign(key_name=c_key_name,
                        advertiser='marketplace',
                        campaign_type='marketplace',
                        name='MarketPlace',
                        account=account_key)

    @classmethod
    def _get_marketplace_key_name(cls, account_key):
        """
        Returns the key_name based on the account_key
        """
        return 'mkt:%s' % account_key

    # TODO: this is broken and not used anywhere.
    @classmethod
    def get_marketplace_campaign(cls, adunit=None):
        """ Returns a marketplace campaign for this adunit,
            Creatives a new campaign if one doesn't exist already
            """
        if adunit is None:
            return None
        camps = cls.get_campaigns(account=adunit.account)
        mkcamp = filter(lambda camp: camp.campaign_type == 'marketplace', camps)
        if mkcamp:
            ag = camp.adgroups
            if adunit.key() not in ag.site_keys:
                ag.site_keys.append(adunit.key())
                ag.put()
            mkcamp.put()
            return mkcamp
        else:
            return cls.add_marketplace_campaign(cls, adunit=adunit)

    # TODO: this is not used anywhere.
    @classmethod
    def add_marketplace_campaign(cls, adunit=None):
            """ Adds a marketplace campagin for this adunit
                """
            acct = adunit.account
            camp = Campaign(name = 'Marketplace Campaign',
                            campaign_type = 'marketplace',
                            account = acct)
            camp.put()

            ag = AdGroup(campaign = camp,
                         account = acct,
                         name = 'Marketplace adgroup',
                         site_keys = [adunit.key()],)
            ag.put()

            creative = ag.default_creative()
            creative.account = acct
            creative.put()

            return camp

    @classmethod
    def get_campaigns(cls, account=None, adunit=None,
                      deleted=False, limit=MAX_OBJECTS):
        campaigns = Campaign.all()
        if not (deleted == None):
            campaigns = campaigns.filter("deleted =",deleted)
        if account:
            campaigns = campaigns.filter("account =",account)
        return list(campaigns.run(limit=limit, batch_size=limit))

    @classmethod
    @wraps_first_arg
    def put(cls, campaigns):
        from budget.query_managers import BudgetQueryManager

        if not isinstance(campaigns, list):
            campaigns = [campaigns]

        # Put campaigns so if they're new they have a key
        put_response = db.put(campaigns)

        # Clear cache
        adunits = []
        affected_account_keys = set()

        for campaign in campaigns:
            affected_account_keys.add(Campaign.account.get_value_for_datastore(campaign))
            for adgroup in campaign.adgroups:
                adunits.extend(adgroup.site_keys)

        adunits = AdUnitQueryManager.get(adunits)
        AdUnitContextQueryManager.cache_delete_from_adunits(adunits)

        AdvertiserQueryManager.memcache_flush_entities_for_account_keys(affected_account_keys, Campaign)
        AdvertiserQueryManager.memcache_flush_entities_for_account_keys(affected_account_keys, AdGroup)
        AdvertiserQueryManager.memcache_flush_entities_for_account_keys(affected_account_keys, Creative)

        return put_response


    @classmethod
    def reports_get_campaigns(cls, account=None, publisher=None, advertiser=None, deleted=False, by_priority=False):
        if advertiser:
            # advertiser as list means priority level, return all these camps
            # because we want stuff for those campaigns individually
            if type(advertiser) == list:
                return advertiser
            else:
                return advertiser

        if publisher:
            # publisher is either an app or an adunit, assume it's an
            # adunit first and make it a list
            adunits = [publisher]
            if hasattr(publisher, 'all_adunits'):
                #if it's not an adunit, make it
                adunits = publisher.all_adunits
            adgroups = AdGroup.all().filter('site_keys IN', [a for a in adunits])
            if deleted is not None:
                adgroups = [a for a in adgroups if a.deleted == deleted]
            camps = [adgroup.campaign for adgroup in adgroups]
            if by_priority:
                temp = []
                for p in CAMPAIGN_LEVELS:
                    priority_camps = [c for c in camps if c.campaign_type == p]
                    if len(priority_camps) > 0:
                        temp.append(priority_camps)
                camps = temp
            return camps

        if deleted is not None:
            camps = Campaign.all().filter('deleted =', deleted)
        if account:
            camps = camps.filter('account = ', account)
        #turn a list of campaigns into a list of lists where each list is all
        #campaigns at a given priority level
        if by_priority:
            temp = []
            for p in CAMPAIGN_LEVELS:
                priority_camps = [c for c in camps if c.campaign_type == p]
                if len(priority_camps) > 0:
                    temp.append(priority_camps)
            camps = temp
        return camps


class AdGroupQueryManager(QueryManager):

    Model = AdGroup

    @classmethod
    def get_adgroups(cls, account=None, app=None, adunit=None, campaigns=None,
                     campaign=None, active=None, deleted=False, archived=False,
                     network_type=False, limit=MAX_OBJECTS):
        """
        archived=True means we only show archived adgroups.
        """

        adgroups = AdGroup.all()

        if account:
            adgroups = adgroups.filter("account =", account)

        if active is not None:
            adgroups = adgroups.filter("active =", active)

        if deleted is not None:
            adgroups = adgroups.filter("deleted =", deleted)

        if archived is not None:
            adgroups = adgroups.filter("archived =", archived)

        if network_type is not False:
            adgroups = adgroups.filter("network_type =", network_type)

        if campaigns:
            # if the number of campaigns is greater than 30 we must "chunk" the query
            if len(campaigns) > MAX_ALLOWABLE_QUERIES:
                total_adgroups = []
                for sub_campaigns in chunks(campaigns, MAX_ALLOWABLE_QUERIES):
                    adgroups_current = copy.deepcopy(adgroups)
                    total_adgroups += adgroups_current.filter("campaign IN",
                                                              sub_campaigns)\
                                                      .fetch(limit)
                return total_adgroups
            else:
                adgroups = adgroups.filter("campaign IN", campaigns)
        elif campaign:
            adgroups = adgroups.filter("campaign =", campaign)

        if adunit:
            if isinstance(adunit, db.Model):
                adunit_key = adunit.key()
            else:
                adunit_key = adunit
            adgroups = adgroups.filter("site_keys =", adunit_key)

        if app:
            adgroups_dict = {}
            adunits = AdUnitQueryManager.get_adunits(app=app)
            for adunit in adunits:
                adgroups_per_adunit = cls.get_adgroups(
                    adunit=adunit, active=active, deleted=deleted,
                    archived=archived, network_type=network_type, limit=limit)
                for adgroup in adgroups_per_adunit:
                    adgroups_dict[adgroup.key()] = adgroup
            return adgroups_dict.values()[:limit]

        return list(adgroups.run(limit=limit, batch_size=limit))

    @classmethod
    def get_line_items(cls, account=None, order=None,
                       orders=None, limit=1000, keys_only=False,
                       archived=False, deleted=False, **kwargs):
        """
        Return a list of line items for the specified account and/or order(s).
        """
        if order:
            adgroups = AdGroup.all(keys_only=keys_only)

            if account:
                adgroups = adgroups.filter("account =", account)

            adgroups = adgroups.filter("campaign =", order)

            if not (deleted == None):
                adgroups = adgroups.filter("deleted =", deleted)

            if not (archived == None):
                adgroups = adgroups.filter("archived =", archived)

            return list(adgroups.run(limit=limit, batch_size=limit))

        if not orders:
            orders = CampaignQueryManager.get_order_campaigns(account)

        # TODO: keys_only=True
        return cls.get_adgroups(account=account, campaigns=orders,
                                limit=limit, archived=archived, deleted=deleted,
                                **kwargs)

    @staticmethod
    def get_line_items_for_adunit(adunit):
        adgroup_query = AdGroup.all().filter('account =', adunit._account)
        adgroup_query = adgroup_query.filter('archived =', False)
        adgroup_query = adgroup_query.filter('deleted =', False)
        adgroup_query = adgroup_query.filter('adgroup_type IN', ['gtee_high', 'gtee', 'gtee_low', 'promo', 'backfill_promo'])
        adgroup_query = adgroup_query.filter('site_keys =', adunit.key())
        adgroups = filter(lambda adgroup: not adgroup.campaign.archived, adgroup_query.run())
        return adgroups

    @classmethod
    def get_sorted_line_items_for_app_and_date_range(cls, app, start_date, end_date):
        line_item_dict = {}
        for adunit in app.adunits:
            # TODO: move to a real database so this case is impossible...
            if not adunit._account == app._account:
                logging.error("App %s AdUnit %s account mismatch." % (app._account, adunit._account))
                continue
            for line_item in cls.get_line_items_for_adunit(adunit):
                line_item_dict[str(line_item.key())] = line_item
        line_items = line_item_dict.values()

        return cls._filter_and_sort_line_items(line_items, start_date, end_date)

    @classmethod
    def get_sorted_line_items_for_adunit_and_date_range(cls, adunit, start_date, end_date):
        line_items = cls.get_line_items_for_adunit(adunit)

        return cls._filter_and_sort_line_items(line_items, start_date, end_date)

    @staticmethod
    def _filter_and_sort_line_items(line_items, start_date, end_date):
        gtee_high_line_items = []
        gtee_line_items = []
        gtee_low_line_items = []
        promo_line_items = []
        backfill_promo_line_items = []

        for line_item in line_items:
            line_item_start_date = line_item.start_datetime.replace(tzinfo=utc).astimezone(Pacific_tzinfo()).date() if line_item.start_datetime else None
            line_item_end_date = line_item.end_datetime.replace(tzinfo=utc).astimezone(Pacific_tzinfo()).date() if line_item.end_datetime else None
            if (not line_item_start_date or line_item_start_date <= end_date) and (not line_item_end_date or line_item_end_date >= start_date):
                if line_item.adgroup_type == 'gtee_high':
                    gtee_high_line_items.append(line_item)
                elif line_item.adgroup_type == 'gtee':
                    gtee_line_items.append(line_item)
                elif line_item.adgroup_type == 'gtee_low':
                    gtee_low_line_items.append(line_item)
                elif line_item.adgroup_type == 'promo':
                    promo_line_items.append(line_item)
                elif line_item.adgroup_type == 'backfill_promo':
                    backfill_promo_line_items.append(line_item)
                else:
                    logging.error("AdGroup %s has adgroup_type %s but was in line_items list." % (
                        line_item.key(), line_item.adgroup_type))

        gtee_high_line_items = sorted(gtee_high_line_items, key=lambda line_item: line_item.name.lower())
        gtee_line_items = sorted(gtee_line_items, key=lambda line_item: line_item.name.lower())
        gtee_low_line_items = sorted(gtee_low_line_items, key=lambda line_item: line_item.name.lower())
        promo_line_items = sorted(promo_line_items, key=lambda line_item: line_item.name.lower())
        backfill_promo_line_items = sorted(backfill_promo_line_items, key=lambda line_item: line_item.name.lower())

        return (gtee_high_line_items + gtee_line_items + gtee_low_line_items +
                promo_line_items + backfill_promo_line_items)

    @classmethod
    def get_network_adgroups_for_adunit(cls, adunit):
        network_campaigns = CampaignQueryManager.get_network_campaigns(adunit.account, is_new=True)
        network_adgroups = []
        for network_campaign in network_campaigns:
            network_adgroup = cls.get_network_adgroup(network_campaign, adunit.key(), adunit.account.key(), get_from_db=True)
            network_adgroup.campaign = network_campaign
            network_adgroups.append(network_adgroup)
        return network_adgroups

    @classmethod
    def get_network_adgroup(cls, campaign,
                            adunit_key, account_key,
                            get_from_db=False):
        """
        Returns the only adgroup that can belong to this adunit
        and account. The magic of key_names allows us to
        avoid getting the object from the db because
        all the information is a function of the adunit itself.

        Note: it is the API consumer's responsiblity to actually
        save this object with the put method of this class
        """
        network_type = campaign.network_type

        # Force to string
        campaign_key = str(campaign.key())
        adunit_key = str(adunit_key)
        account_key = str(account_key)

        # By using a key_name that is one-to-one mapped with the
        # adunit, we can assure that there is only ever one
        # adgroup per adunit
        ag_key_name = cls._get_network_key_name(campaign_key, adunit_key)

        # if db = True, retrieve from the database vs creating a local copy
        if get_from_db:
            adgroup = AdGroup.get_by_key_name(ag_key_name)
            return adgroup

        adgroup = AdGroup(
            key_name=ag_key_name, name=campaign.name, adgroup_type='network')
        # set up the rest of the properties
        adgroup.account = db.Key(account_key)
        adgroup.campaign = db.Key(campaign_key)
        adgroup.network_type = NETWORK_ADGROUP_TRANSLATION.get(network_type,
                network_type)
        # only targetted at one adunit
        adgroup.site_keys = [db.Key(adunit_key)]
        # all network adgroups have cpm set as the bid strategy
        adgroup.bid_strategy = 'cpm'

        return adgroup

    @classmethod
    def _get_network_key_name(cls, campaign_key, adunit_key):
        """
        Returns the key_name based on the adunit_key
        """
        return 'ntwk:%s:%s' % (campaign_key, adunit_key)

    @classmethod
    def get_marketplace_adgroup(cls, adunit_key, account_key, get_from_db=False):
        """
        Returns the only adgroup that can belong to this adunit
        and account. The magic of key_names allows us to
        avoid getting the object from the db because
        all the information is a function of the adunit itself.

        Note: it is the API consumer's responsiblity to actually
        save this object with the put method of this class
        """

        # Force to string
        adunit_key = str(adunit_key)
        account_key = str(account_key)

        # gets the appropriate campaign so that the marketplace
        # adgroup can reference to the correct thing
        # since we only need this to create a reference property
        # and the object has a deterministic key_name
        # we don't need to bother saving.
        campaign = CampaignQueryManager.get_marketplace(account_key)

        # By using a key_name that is one-to-one mapped with the
        # adunit, we can assure that there is only ever one
        # adgroup per adunit
        ag_key_name = cls._get_marketplace_key_name(adunit_key)

        # if db = True, retrieve from the database vs creating a local copy
        if get_from_db:
            adgroup = AdGroup.get_by_key_name(ag_key_name)
            return adgroup

        adgroup = AdGroup(key_name=ag_key_name,
                          name='Marketplace',
                          bid_strategy='cpm',
                          adgroup_type='marketplace')
        # set up the rest of the properties
        adgroup.account = db.Key(account_key)
        adgroup.campaign = campaign
        # only targetted at one adunit
        adgroup.site_keys = [db.Key(adunit_key)]

        return adgroup

    @classmethod
    def _get_marketplace_key_name(cls, adunit_key):
        """
        Returns the key_name based on the adunit_key
        """
        return 'mkt:%s' % adunit_key

    @classmethod
    @wraps_first_arg
    def put(self, adgroups):
        put_response = db.put(adgroups)

        # Update campaign budgets asynchronously using a Task Queue.
        adgroup_keys = [adgroup.key() for adgroup in adgroups]
        queue = taskqueue.Queue()
        task = taskqueue.Task(params=dict(adgroup_keys=adgroup_keys),
                              method='POST',
                              url='/fetch_api/budget/update_or_create')
        queue.add(task)

        # Clear cache
        adunits = []
        affected_account_keys = set()
        for adgroup in adgroups:
            adunits.extend(adgroup.site_keys)
            affected_account_keys.add(AdGroup.account.get_value_for_datastore(adgroup))

        adunits = AdUnitQueryManager.get(adunits)
        AdUnitContextQueryManager.cache_delete_from_adunits(adunits)

        AdvertiserQueryManager.memcache_flush_entities_for_account_keys(affected_account_keys, AdGroup)
        AdvertiserQueryManager.memcache_flush_entities_for_account_keys(affected_account_keys, Creative)

        return put_response


class CreativeQueryManager(QueryManager):
    Model = Creative

    @classmethod
    def get_creatives(cls, adgroup=None, ad_type=None, ad_types=None, account=None, deleted=False, limit=MAX_OBJECTS):
        creatives = Creative.all()
        if not (deleted == None):
            creatives = creatives.filter("deleted =", deleted)
        if account:
            creatives = creatives.filter("account =", account)
        if adgroup:
            creatives = creatives.filter("ad_group =", adgroup)
        if ad_types:
            creatives = creatives.filter("ad_types IN", ad_types)
        if ad_type:
            creatives = creatives.filter("ad_type =", ad_type)
        return list(creatives.run(limit=limit, batch_size=limit))

    def put_creatives(self, creatives):
        return db.put(creatives)

    @classmethod
    def reports_get_creatives(cls, account=None, publisher=None, advertiser=None, deleted=False):
        adgroups = []
        #Advertiser will always be a campaign or a list of campaigns
        if advertiser:
            if not isinstance(advertiser, list):
                advertiser = [advertiser]
            for adv in advertiser:
                adgroups += adv.adgroups
        if publisher:
            adunits = [publisher]
            if hasattr(publisher, 'all_adunits'):
                adunits = [au for au in publisher.all_adunits]
            pub_ags = AdGroup.all().filter('site_keys IN', adunits)
            if deleted is not None:
                pub_ags = [a for a in pub_ags if a.deleted == deleted]
            #collect all the adgroups for the publisher and the advertiser
            #make sure to only take the intersection of the sets
            if adgroups:
                final = []
                for pub_ag in pub_ags:
                    for ag in adgroups:
                        if pub_ag.key() == ag.key():
                            final.append(pub_ag)
                adgroups = final
            else:
                adgroups = pub_ags
        if adgroups:
            return reduce(lambda x, y: x + y, [[c for c in ag.creatives] for ag in adgroups])
        crtvs = Creative.all().filter('account =', account)
        if deleted is not None:
            crtvs = crtvs.filter('deleted =', deleted)
        return crtvs

    @classmethod
    @wraps_first_arg
    def put(cls, creatives):
        put_response = db.put(creatives)

        affected_account_keys = set()
        for creative in creatives:
            # update cache
            adunits = AdUnitQueryManager.get(creative.ad_group.site_keys)
            affected_account_keys.add(Creative.account.get_value_for_datastore(creative))
            if adunits:
                AdUnitContextQueryManager.cache_delete_from_adunits(adunits)

        AdvertiserQueryManager.memcache_flush_entities_for_account_keys(affected_account_keys, Creative)

        return put_response


class TextAndTileCreativeQueryManager(CreativeQueryManager):
    Model = TextAndTileCreative


class HtmlCreativeQueryManager(CreativeQueryManager):
    Model = HtmlCreative


class ImageCreativeQueryManager(CreativeQueryManager):
    Model = ImageCreative
