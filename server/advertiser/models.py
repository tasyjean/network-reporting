import datetime
import logging
import re

from google.appengine.api import images
from google.appengine.ext import blobstore, db
from google.appengine.ext.db import polymodel

from account.models import Account
from common.constants import (MIN_IOS_VERSION, MAX_IOS_VERSION,
                              MIN_ANDROID_VERSION, MAX_ANDROID_VERSION,
                              NETWORKS, NETWORK_ADGROUP_TRANSLATION)
from common.templatetags.filters import withsep
from common.utils.helpers import to_uni
from simple_models import (SimpleAdGroup,
                           SimpleCampaign,
                           SimpleCreative,
                           SimpleHtmlCreative,
                           SimpleImageCreative,
                           SimpleTextCreative,
                           SimpleTextAndTileCreative,
                           SimpleNullCreative,
                           SimpleDummyFailureCreative,
                           SimpleDummySuccessCreative)


class NetworkStates:
    """
    Network states
    """
    # STANDARD_CAMPAIGN is not a new network campaign
    STANDARD_CAMPAIGN = 0
    DEFAULT_NETWORK_CAMPAIGN = 1
    CUSTOM_NETWORK_CAMPAIGN = 2


class Campaign(db.Model):
    """
    Campaigns are essentially containers for adgroups.
    They have a name, advertiser, and description, some basic state,
    and an account. All other information should be added to AdGroup.
    """
    name = db.StringProperty(verbose_name='Name:',
                             default='Order Name',
                             required=True)
    advertiser = db.StringProperty(verbose_name='Advertiser:',
                                   default='None',
                                   required=True)
    description = db.TextProperty(verbose_name='Description:')

    # current state
    active = db.BooleanProperty(default=True)
    archived = db.BooleanProperty(default=False)
    deleted = db.BooleanProperty(default=False)

    # who owns this?
    account = db.ReferenceProperty(Account)

    # date of creation
    created = db.DateTimeProperty(auto_now_add=True)

    # is this a campaign for direct sold (an order), marketplace, or networks?
    campaign_type = db.StringProperty(choices=['order',
                                               'marketplace',
                                               'network',
                                               'backfill_marketplace'])

    # If the campaign is a new network campaign then the network field is
    # set otherwise it's left blank
    #
    # NETWORKS are used to instantiate the network field in campaigns
    #
    # Compared to an AdGroup (network_type):
    #       admob = admob_native
    #       millennial = millennial_native
    #       iad = iAd
    network_type = db.StringProperty(choices=NETWORKS.keys(), default='')
    network_state = db.IntegerProperty(default=NetworkStates.STANDARD_CAMPAIGN)
    # needed so old stats can be mapped to the new campaign on migration
    # since we can't keep the same campaign key for optimization purposes
    old_campaign = db.SelfReferenceProperty()
    transition_date = db.DateProperty()

    @property
    def is_order(self):
        return self.campaign_type == 'order'

    @property
    def is_marketplace(self):
        return self.campaign_type == 'marketplace'

    @property
    def is_network(self):
        return self.campaign_type == 'network'

    def simplify(self):
        return SimpleCampaign(
            key=str(self.key()),
            name=self.name,
            advertiser=self.advertiser,
            active=self.active,
            account=self.account
        )

    def __repr__(self):
        return "Campaign: %s, owned by %s, for %s" % (
            self.name,
            self.account,
            self.advertiser
        )

    @property
    def owner_key(self):
        return None

    @property
    def owner_name(self):
        return None

    def get_owner(self):
        return None

    def set_owner(self, value):
        pass

    def owner(self):
        return property(self.get_owner, self.set_owner)

    def to_dict(self):
        return {
            'name': self.name,
            'advertiser': self.advertiser,
            'description': self.description,
            'active': self.active,
            'deleted': self.deleted,
            'key': str(self.key())
        }

    # TODO: remove, as it returns a dict, not JSON
    # deprecated
    toJSON = to_dict

    @property
    def status_icon_url(self):
        if self.deleted:
            return "/images/deleted.gif"
        if self.active:
            return "/images/active.gif"
        if self.archived:
            return "/images/archived.gif"

        return "/images/paused.gif"

    @property
    def status(self):
        if self.deleted:
            return "deleted"
        elif self.archived:
            return "archived"
        elif self.active:
            return "running"
        return "paused"

Order = Campaign


class AdGroup(db.Model):
    account = db.ReferenceProperty(Account)

    campaign = db.ReferenceProperty(Campaign, collection_name='adgroups')

    created = db.DateTimeProperty(auto_now_add=True)

    # state of this ad group
    active = db.BooleanProperty(default=True)
    deleted = db.BooleanProperty(default=False)
    archived = db.BooleanProperty(default=False)

    NETWORK_TYPE_CHOICES = [NETWORK_ADGROUP_TRANSLATION.get(network_type,
        network_type) for network_type in NETWORKS]
    # TODO: this should be moved to Campaign
    network_type = db.StringProperty(choices=NETWORK_TYPE_CHOICES)

    # TODO: document
    optimizable = db.BooleanProperty(default=False)
    default_cpm = db.FloatProperty()  # TODO: default

    name = db.StringProperty(default='Line Item Name')

    adgroup_type = db.StringProperty(choices=['gtee_high', 'gtee', 'gtee_low',
                                              'network', 'promo',
                                              'backfill_promo', 'marketplace',
                                              'backfill_marketplace'])

    # TODO: one of these three fields is always unused, do something different.
    # budget per day
    daily_budget = db.FloatProperty()
    full_budget = db.FloatProperty()
    # Determines whether we redistribute if we underdeliver during a day
    budget_type = db.StringProperty(choices=['daily', 'full_campaign'],
                                    default='daily')
    # Determines whether we smooth during a day
    budget_strategy = db.StringProperty(choices=['evenly', 'allatonce'],
                                        default='allatonce')

    # Note that bid has different meaning depending on the bidding strategy.
    # if CPC: bid = cost per 1 click
    # if CPM: bid = cost per 1000 impressions
    # if CPA: bid = cost per 1000 conversions
    bid = db.FloatProperty(default=0.05, required=False)
    bid_strategy = db.StringProperty(choices=['cpc', 'cpm', 'cpa'], default='cpm')

    # New start and end date properties
    start_datetime = db.DateTimeProperty()
    end_datetime = db.DateTimeProperty()

    # Targeting: all placements that are considered for this ad group. This is a
    # list of keys corresponding to Site objects.
    site_keys = db.ListProperty(db.Key)

    # Device
    device_targeting = db.BooleanProperty(default=False)
    target_iphone = db.BooleanProperty(default=True)
    target_ipod = db.BooleanProperty(default=True)
    target_ipad = db.BooleanProperty(default=True)
    ios_version_min = db.StringProperty(default=MIN_IOS_VERSION)
    ios_version_max = db.StringProperty(default=MAX_IOS_VERSION)
    target_android = db.BooleanProperty(default=True)
    android_version_min = db.StringProperty(default=MIN_ANDROID_VERSION)
    android_version_max = db.StringProperty(default=MAX_ANDROID_VERSION)
    target_other = db.BooleanProperty(default=True)

    # Geography Targeting
    accept_targeted_locations = db.BooleanProperty(default=True)
    targeted_countries = db.ListProperty(basestring)
    targeted_regions = db.ListProperty(basestring)
    targeted_cities = db.ListProperty(basestring)
    targeted_zip_codes = db.StringListProperty()

    # Connectivity Targeting
    targeted_carriers = db.ListProperty(basestring)

    # User Targeting
    included_apps = db.ListProperty(db.Key)
    excluded_apps = db.ListProperty(db.Key)

    # Keywords: all keyword and category bids are tracked here. Categories use
    # the category:games convention. If any of the input keywords match the
    # n-grams here then we trigger a match.
    keywords = db.StringListProperty()

    # Frequency Caps
    daily_frequency_cap = db.IntegerProperty(default=0)
    hourly_frequency_cap = db.IntegerProperty(default=0)

    # Allocation
    allocation_percentage = db.FloatProperty(default=100.0)

    # Deprecated?
    mktplace_price_floor = db.FloatProperty(default=0.25, required=False)

    # Deprecated
    t = db.DateTimeProperty(auto_now_add=True)
    net_creative = db.ReferenceProperty(collection_name='creative_adgroups')
    minute_frequency_cap = db.IntegerProperty(default=0)
    weekly_frequency_cap = db.IntegerProperty(default=0)
    monthly_frequency_cap = db.IntegerProperty(default=0)
    lifetime_frequency_cap = db.IntegerProperty(default=0)
    allocation_type = db.StringProperty(choices=["users", "requests"])
    percent_users = db.FloatProperty(default=100.0)
    devices = db.StringListProperty(default=['any'])
    min_os = db.StringListProperty(default=['any'])
    geo_predicates = db.StringListProperty(default=["country_name=*"])
    cities = db.StringListProperty()
    country = db.StringProperty()
    region = db.StringProperty()
    state = db.StringProperty()
    city = db.StringProperty()
    active_user = db.StringListProperty(default=['any'])
    active_app = db.StringListProperty(default=['any'])

    @property
    def targeted_regions_tuples(self):
        targeted_region_tuples = []
        if self.targeted_regions:
            for region in self.targeted_regions:
                match = re.match("^\('(.*)','(.*)'\)$", region)
                if match:
                    targeted_region_tuples.append(match.groups())
                else:
                    logging.error("Malformed targeted region %s for adgroup %s" % (
                        region, self.key()))
        return targeted_region_tuples

    def targeted_regions_display(self):
        pass

    @property
    def targeted_cities_tuples(self):
        targeted_cities_tuples = []
        if self.targeted_cities:
            for city in self.targeted_cities:
                match = re.match("^\((.*),(.*),'(.*)','(.*)','(.*)'\)$", city)
                if match:
                    targeted_cities_tuples.append(match.groups())
                else:
                    logging.error("Malformed targeted city %s for adgroup %s" % (
                        city, self.key()))
        return targeted_cities_tuples

    @property
    def included_apps_global_ids(self):
        global_ids = []
        for app_key in self.included_apps or []:
            app = db.get(app_key)
            if app.global_id:
                global_ids.append(app.global_id)
        return global_ids

    @property
    def excluded_apps_global_ids(self):
        global_ids = []
        for app_key in self.excluded_apps or []:
            app = db.get(app_key)
            if app.global_id:
                global_ids.append(app.global_id)
        return global_ids

    @property
    def has_daily_budget(self):
        return self.daily_budget and self.budget_type == 'daily'

    @property
    def has_full_budget(self):
        return self.full_budget and self.budget_type == 'full_campaign'

    @property
    def calculated_cpm(self):
        """
        Calculate the ecpm for a cpc campaign.
        """
        if self.cpc and self.stats.impression_count:
            return (float(self.stats.click_count) * float(self.bid) * 1000.0 /
                    float(self.stats.impression_count))
        return self.bid

    @property
    def line_item_priority(self):
        ranks = {
            'gtee_high': 1,
            'gtee': 2,
            'gtee_low': 3,
            'promo': 4,
            'backfill_promo': 5
        }
        return ranks[self.adgroup_type]

    @property
    def status(self):
        if self.deleted:
            return "deleted"
        elif self.archived:
            return "archived"
        elif self.active and self.campaign.active:
            now = datetime.datetime.now()
            if (self.start_datetime <= now if self.start_datetime else True) and \
               (now <= self.end_datetime if self.end_datetime else True):
                return "running"
            elif self.end_datetime <= now:
                return "completed"
            else:
                return "scheduled"
        else:
            return "paused"
        return "running"

    @property
    def adgroup_type_display(self):
        kinds = {
            'gtee_high': "Guaranteed (High)",
            'gtee': "Guaranteed",
            'gtee_low': "Guaranteed (Low)",
            'promo': "Promotional",
            "backfill_promo": "Backfill Promotional",
            "network": "Network",
            "marketplace": "Marketplace"
        }

        if self.adgroup_type:
            return kinds[self.adgroup_type]
        return ''

    def simplify(self):
        # TODO: why are these necessary?
        if hasattr(self, 'full_budget'):
            full_budget = self.full_budget
        else:
            full_budget = 0

        if hasattr(self, 'daily_budget'):
            daily_budget = self.daily_budget
        else:
            daily_budget = 0

        if hasattr(self, 'budget_type'):
            budget_type = self.budget_type
        else:
            budget_type = None

        # NOTE: When we originally designed the networks page refactor we
        # didn't anticipate a need for s2s, server to server campaigns.
        # However, after launching the networks page refactor we realized it
        # was a requirement which conflicted with the new naming conventions we
        # put in place. ie. [campaign.network_type: admob] ->
        # [adgroup.network_type: admob_native] (same for millennial) which is
        # weird because the adgroup.network_type must be just admob or just
        # millennial for s2s. Hence this hack to make the adserver work and
        # maintain decent naming conventions for the FE models.
        #
        # Author: Tiago Bandeira (9/6/2012)
        NETWORK_TYPE_TRANSLATION = {'admob_s2s': 'admob',
                                    'millennial_s2s': 'millennial'}
        network_type = NETWORK_TYPE_TRANSLATION.get(self.network_type,
                self.network_type)

        return SimpleAdGroup(
            key=str(self.key()),  # modified
            account=self.account,
            campaign=self.campaign,
            # created=self.created,
            active=self.active,
            deleted=self.deleted,
            # archived=self.archived,
            network_type=network_type,
            optimizable=self.optimizable,
            default_cpm=self.default_cpm,
            # name=self.name,
            adgroup_type=self.adgroup_type,
            daily_budget=daily_budget,
            full_budget=full_budget,
            budget_type=budget_type,
            # budget_strategy=self.budget_strategy,
            bid=self.bid,
            bid_strategy=self.bid_strategy,
            start_datetime=self.start_datetime,
            end_datetime=self.end_datetime,
            site_keys=[str(key) for key in self.site_keys],  # modified
            device_targeting=self.device_targeting,
            target_iphone=self.target_iphone,
            target_ipod=self.target_ipod,
            target_ipad=self.target_ipad,
            ios_version_min=self.ios_version_min,
            ios_version_max=self.ios_version_max,
            target_android=self.target_android,
            android_version_min=self.android_version_min,
            android_version_max=self.android_version_max,
            target_other=self.target_other,
            accept_targeted_locations=self.accept_targeted_locations,
            targeted_countries=self.targeted_countries,
            targeted_regions=self.targeted_regions_tuples,  # modified
            targeted_cities=self.targeted_cities_tuples,  # modified
            targeted_zip_codes=self.targeted_zip_codes,
            targeted_carriers=self.targeted_carriers,
            included_apps=self.included_apps_global_ids,  # modified
            excluded_apps=self.excluded_apps_global_ids,  # modified
            keywords=self.keywords,
            daily_frequency_cap=self.daily_frequency_cap,
            hourly_frequency_cap=self.hourly_frequency_cap,
            allocation_percentage=self.allocation_percentage,
            mktplace_price_floor=self.mktplace_price_floor,  # deprecated?
        )

    def default_creative(self, custom_html=None, key_name=None):
        # TODO: These should be moved to ad_server/networks or some such
        c = None
        if self.network_type == 'adsense':
            c = AdSenseCreative(key_name=key_name,
                                name="adsense dummy",
                                ad_type="adsense",
                                format="320x50",
                                format_predicates=["format=*"])
        elif self.network_type == 'iAd':
            c = iAdCreative(key_name=key_name,
                            name="iAd dummy",
                            ad_type="iAd",
                            format="320x50",
                            format_predicates=["format=320x50"])
        elif self.network_type == 'admob_s2s':
            c = AdMobCreative(key_name=key_name,
                              name="admob s2s dummy",
                              ad_type="admob",
                              format="320x50",
                              format_predicates=["format=320x50"])
        elif self.network_type == 'brightroll':
            c = BrightRollCreative(key_name=key_name,
                                   name="brightroll dummy",
                                   ad_type="html_full",
                                   format="full",
                                   format_predicates=["format=*"])
        elif self.network_type == 'chartboost':
            c = ChartBoostCreative(key_name=key_name,
                                   name="chartboost dummy",
                                   ad_type="html",
                                   format="320x50",
                                   format_predicates=["format=320x50"])
        elif self.network_type == 'ejam':
            c = EjamCreative(key_name=key_name,
                             name="ejam dummy",
                             ad_type="html",
                             format="320x50",
                             format_predicates=["format=320x50"])
        elif self.network_type == 'jumptap':
            c = JumptapCreative(key_name=key_name,
                                name="jumptap dummy",
                                ad_type="html",
                                format="320x50",
                                format_predicates=["format=320x50"])
        elif self.network_type == 'millennial_s2s':
            c = MillennialCreative(key_name=key_name,
                                   name="millennial s2s dummy",
                                   ad_type="html",
                                   format="320x50",
                                   format_predicates=["format=320x50"])  # TODO: make sure formats are right
        elif self.network_type == 'inmobi':
            c = InMobiCreative(key_name=key_name,
                               name="inmobi dummy",
                               ad_type="html",
                               format="320x50",
                               format_predicates=["format=320x50"])  # TODO: make sure formats are right
        elif self.network_type == 'greystripe':
            c = GreyStripeCreative(key_name=key_name,
                                   name="greystripe dummy",
                                   ad_type="greystripe",
                                   format="320x50",
                                   format_predicates=["format=*"])  # TODO: only formats 320x320, 320x48, 300x250
        elif self.network_type == 'appnexus':
            c = AppNexusCreative(key_name=key_name,
                                 name="appnexus dummy",
                                 ad_type="html",
                                 format="320x50",
                                 format_predicates=["format=300x250"])
        elif self.network_type == 'mobfox':
            c = MobFoxCreative(key_name=key_name,
                               name="mobfox dummy",
                               ad_type="html",
                               format="320x50",
                               format_predicates=["format=320x50"])
        elif self.network_type == 'custom':
            c = CustomCreative(key_name=key_name,
                               name='custom',
                               ad_type='html',
                               format='',
                               format_predicates=['format=*'],
                               html_data=custom_html)
        elif self.network_type == 'custom_native':
            c = CustomNativeCreative(key_name=key_name,
                                     name='custom native dummy',
                                     ad_type='custom_native',
                                     format='320x50',
                                     format_predicates=['format=*'],
                                     html_data=custom_html)
        elif self.network_type == 'admob_native':
            c = AdMobNativeCreative(key_name=key_name,
                                    name="admob native dummy",
                                    ad_type="admob_native",
                                    format="320x50",
                                    format_predicates=["format=320x50"])
        elif self.network_type == 'millennial_native':
            c = MillennialNativeCreative(key_name=key_name,
                                         name="millennial native dummy",
                                         ad_type="millennial_native",
                                         format="320x50",
                                         format_predicates=["format=320x50"])
        elif self.adgroup_type in ['marketplace', 'backfill_marketplace']:
            c = MarketplaceCreative(key_name=key_name,
                                    name='marketplace dummy',
                                    ad_type='html')

        if c:
            c.ad_group = self
            c.account = self._account

        return c

    def __repr__(self):
        return u"AdGroup:%s" % to_uni(self.name)

    @property
    def uses_default_device_targeting(self):

        if self.target_iphone == False or \
        self.target_ipod == False or \
        self.target_ipad == False or \
        self.ios_version_min != MIN_IOS_VERSION or \
        self.ios_version_max != MAX_IOS_VERSION or \
        self.target_android == False or \
        self.android_version_min != MIN_ANDROID_VERSION or \
        self.android_version_max != MAX_ANDROID_VERSION or \
        self.target_other == False:
            return False
        else:
            return True

    def get_owner(self):
        return self.campaign

    def set_owner(self, value):
        self.campaign = value

    def owner(self, value):
        return property(self.get_owner, self.set_owner)

    @property
    def owner_key(self):
        return self._campaign

    @property
    def owner_name(self):
        return 'campaign'

    @property
    def cpc(self):
        if self.bid_strategy == 'cpc':
            return self.bid
        return None

    @property
    def cpm(self):
        if self.bid_strategy == 'cpm':
            return self.bid
        return None

    @property
    def budget_goal(self):
        try:
            if self.bid_strategy == 'cpm':
                if self.budget_type == 'daily':
                    return int((self.daily_budget / self.bid) * 1000)
                else:
                    return int((self.full_budget / self.bid) * 1000)
            else:
                if self.budget_type == 'daily':
                    return int(self.daily_budget)
                else:
                    return int(self.full_budget)
        except TypeError:
            # We'll get a NoneType exception if no budget is set
            return None

    @property
    def budget_goal_display(self):
        goal = self.budget_goal

        if goal:
            goal = withsep(goal) # add commas
            if self.bid_strategy == 'cpm':
                if self.budget_type == 'daily':
                    return str(goal) + ' Impressions Daily'
                else:
                    return str(goal) + ' Impressions Total'
            else:
                if self.budget_type == 'daily':
                    return str(goal) + ' USD Daily'
                else:
                    return str(goal) + ' USD Total'
        else:
            if self.bid_strategy == 'cpm':
                return "Unlimited Impressions"
            else:
                return "Unlimited Clicks"

    @property
    def rate_display(self):
        rate_display = "$%.2f" % self.bid
        if self.bid_strategy in ['cpm', 'cpc']:
            rate_display += " %s" % self.bid_strategy.upper()
        return rate_display

    @property
    def individual_cost(self):
        """ The smallest atomic bid. """
        if self.bid_strategy == 'cpc':
            return self.bid
        elif self.bid_strategy == 'cpm':
            return self.bid / 1000

    @property
    def running(self):
        """ Must be active and have proper start and end dates"""
        campaign = self.campaign
        pac_today = datetime.datetime.now().date()
        if ((not campaign.start_date or campaign.start_date < pac_today) and
            (not campaign.end_date or campaign.end_date > pac_today)):
            if self.active and campaign.active:
                return True

        return False

    @property
    def created_date(self):
        return self.created.date()

    @property
    def frequency_cap_display(self):

        display = []

        if self.minute_frequency_cap:
            display.append(str(self.minute_frequency_cap) + "/minute")
        if self.hourly_frequency_cap:
            display.append(str(self.hourly_frequency_cap) + "/hour")
        if self.daily_frequency_cap:
            display.append(str(self.daily_frequency_cap) + "/day")
        if self.weekly_frequency_cap:
            display.append(str(self.weekly_frequency_cap) + "/week")
        if self.monthly_frequency_cap:
            display.append(str(self.monthly_frequency_cap) + "/month")
        if self.lifetime_frequency_cap:
            display.append(str(self.lifetime_frequency_cap) + " total")

        if not display:
            return "No frequency caps"
        else:
            return ", ".join(display)

    @property
    def device_targeting_display(self):

        if self.device_targeting and not self.uses_default_device_targeting:

            display = []

            # iOS Targeting
            ios_display = []
            if self.target_iphone:
                ios_display.append("iPhone")
            if self.target_ipad:
                ios_display.append("iPad")
            if self.target_ipod:
                ios_display.append("iPod")

            if ios_display:
                ios_display_all = ", ".join(ios_display) + \
                                  " (iOS version " + self.ios_version_min + \
                                  " to " + self.ios_version_max + ")"
                ios_display_all = ios_display_all.replace("to 999", "and up")
                display.append(ios_display_all)

            # Android Targeting
            if self.target_android:
                android_display_all = "Android Devices (version " + \
                                      self.android_version_min + " to " + \
                                      self.android_version_max + ")"
                android_display_all = android_display_all.replace("to 999", "and up")
                display.append(android_display_all)

            if self.target_other:
                display.append("Other Devices")

            if display:
                return display

        return ["All devices"]

    def to_dict(self):
        return {
            'key': str(self.key()),
            'campaign_key': str(self.campaign.key()),
            'name': self.name,
            'created': self.created,
            'network_type': self.network_type,
            'bid': self.bid,
            'bid_strategy': self.bid_strategy,
            'budget_type': self.budget_type,
            'budget_strategy': self.budget_strategy,
            'adgroup_type': self.adgroup_type,
            'start_datetime': self.start_datetime,
            'end_datetime': self.end_datetime,
            'device_targeting': self.device_targeting_display,
            # 'country_targeting': self.country_targeting_display,
            'frequency_caps': self.frequency_cap_display,
            'allocation': self.allocation_percentage,
        }

    # TODO: remove, as it returns a dict, not JSON
    # deprecated
    toJSON = to_dict

    #############################
    # moved from campaign class #
    #############################

    @property
    def finite(self):
        if (self.start_datetime and self.end_datetime):
            return True
        else:
            return False

    def delivery(self):
        if self.stats:
            return self.stats.revenue / self.budget
        else:
            return 1

    def gtee(self):
        return self.adgroup_type in ['gtee', 'gtee_high', 'gtee_low']

    def promo(self):
        return self.adgroup_type in ['promo', 'backfill_promo']

    def network(self):
        return self.adgroup_type in ['network']

    def marketplace(self):
        return self.adgroup_type in ['marketplace']

    def is_active_for_date(self, date):
        """ Start and end dates are inclusive """
        if (self.start_date <= date if self.start_date else True) and \
           (date <= self.end_date if self.end_date else True):
            return True
        else:
            return False

    ##################################
    # /end moved from campaign class #
    ##################################

    @property
    def status_icon_url(self):
        if self.deleted:
            return "/images/deleted.gif"
        if self.active and self.campaign.active:
            return "/images/active.gif"
        if self.archived or self.campaign.archived:
            return "/images/archived.gif"

        return "/images/paused.gif"

LineItem = AdGroup


class Creative(polymodel.PolyModel):
    name = db.StringProperty(verbose_name='Creative Name',
                             default='Creative')
    custom_width = db.IntegerProperty()
    custom_height = db.IntegerProperty()
    landscape = db.BooleanProperty(default=False)  # TODO: make this more flexible later

    ad_group = db.ReferenceProperty(AdGroup, collection_name="creatives")

    active = db.BooleanProperty(default=True)
    was_active = db.BooleanProperty(default=True)
    deleted = db.BooleanProperty(default=False)

    # the creative type helps the ad server render the right thing if the creative wins the auction
    ad_type = db.StringProperty(choices=["text", "text_icon", "image", "html",
                                         "iAd", "adsense", "admob",
                                         "greystripe", "html_full", "clear",
                                         "custom_native", "admob_native",
                                         "millennial_native"],
                                default="image")

    # tracking pixel
    tracking_url = db.StringProperty(verbose_name='Impression Tracking URL')

    # destination URLs
    url = db.StringProperty(verbose_name='Click URL')
    display_url = db.StringProperty()

    # conversion goals
    conv_appid = db.StringProperty(verbose_name='Conversion Tracking ID')

    # format predicates - the set of formats that this creative can match
    # e.g. format=320x50
    # e.g. format=*
    format_predicates = db.StringListProperty(default=["format=*"])
    # We should switch to using this field instead of
    # format_predicates: one creative per size
    format = db.StringProperty(default="320x50")

    launchpage = db.StringProperty(verbose_name='Intercept URL')

    # time of creation
    account = db.ReferenceProperty(Account)
    t = db.DateTimeProperty(auto_now_add=True)

    # DEPRECATED: metrics such as e_cpm and CTR only make sense within the context of matching a creative with an adunit
    # Use /ad_server/optimizer/optimizer.py instead to calculate these metrics.
    #
    # def e_cpm(self):
    #     if self.ad_group.bid_strategy == 'cpc':
    #         return float(self.p_ctr() * self.ad_group.bid * 1000)
    #     elif self.ad_group.bid_strategy == 'cpm':
    #         return float(self.ad_group.bid)

    network_name = None
    SIMPLE = SimpleCreative

    @property
    def intercept_url(self):
        """ A URL prefix for which navigation should be intercepted and
            forwarded to a full-screen browser.

            For some ad networks, a click event actually results in navigation
            via "window.location = [TARGET_URL]". Since this kind of navigation is
            not limited exclusively to clicks, only a subset of all observed
            [TARGET_URL]s should be intercepted. This header is used as part of
            prefix-matching to distinguish true click events.
        """
        return self.launchpage

    # Set up the basic Renderers and ServerSides for the creative
    #Renderer = BaseCreativeRenderer
    #ServerSide = None  # Non-server-bound creatives don't need a serverside

    @property
    def multi_format(self):
            return None

    def _get_adgroup(self):
            return self.ad_group

    def _set_adgroup(self, value):
            self.ad_group = value

    #whoever did this you rule
    adgroup = property(_get_adgroup, _set_adgroup)

    def get_owner(self):
        return self.ad_group

    def set_owner(self, value):
        self.ad_group = value

    def _get_width(self):
        if self.custom_width:
            return self.custom_width
        if hasattr(self, '_width'):
            return self._width
        width = 0
        if self.format:
            parts = self.format.split('x')
            if len(parts) == 2:
                width = parts[0]
        return width

    def _set_width(self, value):
        self._width = value
    width = property(_get_width, _set_width)

    def _get_height(self):
        if self.custom_height:
            return self.custom_height
        if hasattr(self, '_height'):
            return self._height

        height = 0
        if self.format:
            parts = self.format.split('x')
            if len(parts) == 2:
                height = parts[1]
        return height

    def _set_height(self, value):
        self._height = value

    height = property(_get_height, _set_height)

    def owner(self):
        return property(self.get_owner, self.set_owner)

    @property
    def owner_key(self):
        return self._ad_group

    @property
    def owner_name(self):
        return 'ad_group'

    def __repr__(self):
        return "Creative{ad_type=%s, key_name=%s}" % (self.ad_type, self.key().id_or_name())

    def build_simplify_dict(self):
        return dict(key=str(self.key()),
                    name=self.name,
                    custom_width=self.custom_width,
                    custom_height=self.custom_height,
                    landscape=self.landscape,
                    ad_group=self.ad_group,
                    active=self.active,
                    ad_type=self.ad_type,
                    tracking_url=self.tracking_url,
                    url=self.url,
                    display_url=self.display_url,
                    conv_appid=self.conv_appid,
                    format=self.format,
                    launchpage=self.launchpage,
                    account=self.account,
                    multi_format=self.multi_format,
                    network_name=self.network_name)

    def simplify(self):
        simplify_dict = self.build_simplify_dict()
        return self.SIMPLE(**simplify_dict)

    def to_dict(self):
        return {
            'key': str(self.key()),
            'name': self.name
        }

    # TODO: remove, as it returns a dict, not JSON
    # deprecated
    toJSON = to_dict


class TextCreative(Creative):
    SIMPLE = SimpleTextCreative
    # text ad properties
    headline = db.StringProperty()
    line1 = db.StringProperty()
    line2 = db.StringProperty()

    #@property
    #def Renderer(self):
    #    return None

    def __repr__(self):
        return "'%s'" % (self.headline,)

    def build_simplify_dict(self):
        spec_dict = dict(headline=self.headline,
                         line1=self.line1,
                         line2=self.line2)
        spec_dict.update(super(TextCreative, self).build_simplify_dict())
        return spec_dict


class TextAndTileCreative(Creative):
    SIMPLE = SimpleTextAndTileCreative

    line1 = db.StringProperty(verbose_name='Line 1')
    line2 = db.StringProperty(verbose_name='Line 2')
    # image = db.BlobProperty()
    image_blob = blobstore.BlobReferenceProperty()
    image_serve_url = db.StringProperty()
    action_icon = db.StringProperty(choices=["download_arrow4", "access_arrow", "none"], default="download_arrow4")
    color = db.StringProperty(verbose_name='Background Color',
                              default="000000")
    font_color = db.StringProperty(verbose_name='Font Color',
                                   default="FFFFFF")
    gradient = db.BooleanProperty(verbose_name='Gradient',
                                  default=True)

    def build_simplify_dict(self):
        try:
            img_url = images.get_serving_url(self.image_blob)
        except:
            img_url = "http://curezone.com/upload/Members/new03/white.jpg"
        spec_dict = dict(line1=self.line1,
                         line2=self.line2,
                         image_url=img_url,
                         action_icon=self.action_icon,
                         color=self.color,
                         font_color=self.font_color,
                         gradient=self.gradient)

        spec_dict.update(super(TextAndTileCreative, self).build_simplify_dict())
        return spec_dict


class HtmlCreative(Creative):
    """ This creative has pure html that has been added by the user.
        This should not be confused with ad_type=html, which means that the
        payload is html as opposed to a native request. """

    SIMPLE = SimpleHtmlCreative
    html_data = db.TextProperty()
    ormma_html = db.BooleanProperty(verbose_name='MRAID Ad',
                                    default=False)

    def build_simplify_dict(self):
        spec_dict = dict(html_data=self.html_data,
                         ormma_html=self.ormma_html)

        spec_dict.update(super(HtmlCreative, self).build_simplify_dict())
        return spec_dict


    #@property
    #def Renderer(self):
    #    return HtmlDataRenderer


class ImageCreative(Creative):
    SIMPLE = SimpleImageCreative
    # image properties
    # image = db.BlobProperty()
    image_blob = blobstore.BlobReferenceProperty()
    image_serve_url = db.StringProperty()
    image_width = db.IntegerProperty(default=320)
    image_height = db.IntegerProperty(default=480)

    @classmethod
    def get_format_predicates_for_image(c, img):
        IMAGE_PREDICATES = {"300x250": "format=300x250",
            "320x50": "format=320x50",
            "300x50": "format=320x50",
            "728x90": "format=728x90",
            "468x60": "format=468x60"}
        fp = IMAGE_PREDICATES.get("%dx%d" % (img.width, img.height))
        return [fp] if fp else None

    def build_simplify_dict(self):
        spec_dict = dict(image_url=self.image_serve_url,
                         image_width=self.image_width,
                         image_height=self.image_height,
                         )

        spec_dict.update(super(ImageCreative, self).build_simplify_dict())
        return spec_dict

    #@property
    #def Renderer(self):
    #    return ImageRenderer


class MarketplaceCreative(HtmlCreative):
    """ If this is targetted to an adunit, lets the ad_auction know to
        run the marketplace battle. """

    @property
    def multi_format(self):
        return ('728x90', '320x50', '300x250', '160x600', 'full', 'full_tablet')


class CustomCreative(HtmlCreative):
    # TODO: For now this is redundant with HtmlCreative
    # If we don't want to add any properties to it, remove it
    network_name = "custom"


class CustomNativeCreative(HtmlCreative):
    network_name = "custom_native"
    #Renderer = CustomNativeRenderer

    @property
    def multi_format(self):
        return ('728x90', '320x50', '300x250', 'full')


class iAdCreative(Creative):
    network_name = "iAd"

    #Renderer = iAdRenderer

    @property
    def multi_format(self):
        return ('728x90', '320x50', 'full_tablet')


class AdSenseCreative(Creative):
    network_name = "adsense"

    #Renderer = AdSenseRenderer

    @property
    def multi_format(self):
        return ('320x50', '300x250')


class AdMobCreative(Creative):
    network_name = "admob"


    #Renderer = AdMobRenderer


class AdMobNativeCreative(AdMobCreative):
    network_name = "admob_native"

    #Renderer = AdMobNativeRenderer

    @property
    def multi_format(self):
        return ('728x90', '320x50', '300x250', 'full')


class MillennialCreative(Creative):

    network_name = "millennial"

    #Renderer = MillennialRenderer

    #ServerSide = MillennialServerSide

    @property
    def multi_format(self):
        return ('728x90', '320x50', '300x250',)


class MillennialNativeCreative(MillennialCreative):
    network_name = "millennial_native"

    #Renderer = MillennialNativeRenderer

    #ServerSide = None

    @property
    def multi_format(self):
        return ('728x90', '320x50', '300x250', 'full', 'full_tablet')


class ChartBoostCreative(Creative):

    network_name = "chartboost"

    #Renderer = ChartBoostRenderer

    #ServerSide = ChartBoostServerSide

    @property
    def multi_format(self):
        return ('320x50', 'full',)


class EjamCreative(Creative):
    network_name = "ejam"

    #Renderer = ChartBoostRenderer

    #ServerSide = EjamServerSide
    @property
    def multi_format(self):
        return ('320x50', 'full', '300x250', '728x90', '320x480')


class InMobiCreative(Creative):

    network_name = "inmobi"

    #Renderer = InmobiRenderer

    #ServerSide = InMobiServerSide

    @property
    def multi_format(self):
        return ('728x90', '320x50', '300x250', '468x60', '120x600',)


class AppNexusCreative(Creative):
    network_name = "appnexus"

    #Renderer = AppNexusRenderer

    #ServerSide = AppNexusServerSide


class BrightRollCreative(Creative):
    network_name = "brightroll"

    #Renderer = BrightRollRenderer

    #ServerSide = BrightRollServerSide

    @property
    def multi_format(self):
        return ('full', 'full_tablet')


class JumptapCreative(Creative):
    network_name = "jumptap"

    #Renderer = JumptapRenderer

    #ServerSide = JumptapServerSide

    @property
    def multi_format(self):
        return ('728x90', '320x50', '300x250')


class GreyStripeCreative(Creative):
    network_name = "greystripe"

    #Renderer = GreyStripeRenderer

    #ServerSide = GreyStripeServerSide

    @property
    def multi_format(self):
        return ('320x320', '320x50', '300x250',)


class MobFoxCreative(Creative):
    network_name = "mobfox"
    #Renderer = MobFoxRenderer

    #ServerSide = MobFoxServerSide

    @property
    def multi_format(self):
        return ('728x90', '320x50')


class NullCreative(Creative):
    SIMPLE = SimpleNullCreative


class DummyServerSideFailureCreative(Creative):
    SIMPLE = SimpleDummyFailureCreative
    #ServerSide = DummyServerSideFailure


class DummyServerSideSuccessCreative(Creative):
    SIMPLE = SimpleDummySuccessCreative
    #ServerSide = DummyServerSideSuccess
