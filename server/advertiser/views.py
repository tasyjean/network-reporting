import logging, os, re, datetime, hashlib

from django.conf import settings

from urllib import urlencode
from copy import deepcopy

import base64, binascii
from google.appengine.api import users, images, files
from google.appengine.api.urlfetch import fetch
from google.appengine.ext import db
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

from django.contrib.auth.decorators import login_required
from common.utils import date_magic
from common.utils import sswriter
from common.utils.decorators import cache_page_until_post
from common.utils.helpers import campaign_stats
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.core.urlresolvers import reverse
from django.utils import simplejson
from common.ragendja.template import render_to_response, render_to_string, JSONResponse
from common.utils.marketplace_helpers import MarketplaceStatsFetcher
# from common.ragendja.auth.decorators import google_login_required as login_required

from advertiser.models import *
from advertiser.forms import CampaignForm, AdGroupForm, \
                             BaseCreativeForm, TextCreativeForm, \
                             ImageCreativeForm, TextAndTileCreativeForm, \
                             HtmlCreativeForm

from publisher.models import Site, Account, App
from reporting.models import StatsModel

from common.utils.query_managers import CachedQueryManager
from common.utils.request_handler import RequestHandler

from account.query_managers import AccountQueryManager
from account.forms import NetworkConfigForm
from advertiser.query_managers import CampaignQueryManager, AdGroupQueryManager, \
                                      CreativeQueryManager, TextCreativeQueryManager, \
                                      ImageCreativeQueryManager, TextAndTileCreativeQueryManager, \
                                      HtmlCreativeQueryManager
from publisher.query_managers import AdUnitQueryManager, AppQueryManager, AdUnitContextQueryManager
from reporting.query_managers import StatsModelQueryManager
from budget import budget_service
from budget.models import BudgetSlicer

from common.constants import MPX_DSP_IDS

from django.views.decorators.cache import cache_page

from ad_server.optimizer.optimizer import DEFAULT_CTR

class AdGroupIndexHandler(RequestHandler):

    def get(self):
        # Set start date if passed in, otherwise get most recent days
        if self.start_date:
            days = StatsModel.get_days(self.start_date, self.date_range)
        else:
            days = StatsModel.lastdays(self.date_range)

        apps = AppQueryManager.get_apps(account=self.account, alphabetize=True)

        # memoize
        campaigns_dict = {}

        campaigns = CampaignQueryManager.get_campaigns(account=self.account)
        for campaign in campaigns:
            campaigns_dict[campaign.key()] = campaign


        if campaigns:
            adgroups = AdGroupQueryManager().get_adgroups(account=self.account)
        else:
            adgroups = []

        # Roll up and attach various stats to adgroups
        for adgroup in adgroups:
            try:
                adgroup.campaign = campaigns_dict[adgroup._campaign]
            except KeyError:
                pass


        # memoize
        adunits_dict = {}
        apps_dict = {}

        # gets account level stats

        stats_model = StatsModelQueryManager(self.account, offline=self.offline)
        stats = stats_model.get_stats_for_days(publisher=None, advertiser=None, days=days)


        key = "||"
        stats_dict = {}
        stats_dict[key] = {}
        stats_dict[key]['name'] = "||"
        stats_dict[key]['daily_stats'] = [s.to_dict() for s in stats]
        summed_stats = sum(stats, StatsModel())
        stats_dict[key]['sum'] = summed_stats.to_dict()

        response_dict = {}
        response_dict['status'] = 200
        response_dict['all_stats'] = stats_dict

        for adgroup in adgroups:
            adunits = []
            adunit_keys_to_fetch = []
            # get targeted apps
            adgroup.targeted_app_keys = []
            adunit_keys = [adunit_key for adunit_key in adgroup.site_keys]
            for adunit_key in adunit_keys:
                if adunit_key in adunits_dict:
                    adunits.append(adunits_dict[adunit_key])
                else:
                    adunit_keys_to_fetch.append(adunit_key)

            if adunit_keys_to_fetch:
                adunits += AdUnitQueryManager.get(adunit_keys_to_fetch)

            for adunit in adunits:
                adunits_dict[adunit.key()] = adunit
                if adunit:
                    adgroup.targeted_app_keys.append(adunit._app_key)
                # apps.append(adunit.app_key)

        # Due to weirdness, network_campaigns and backfill_promo_campaigns are actually lists of adgroups
        sorted_campaign_groups = _sort_campaigns(adgroups)
        promo_campaigns, guaranteed_campaigns, marketplace_campaigns, network_campaigns, backfill_promo_campaigns = sorted_campaign_groups

        guarantee_levels = _sort_guarantee_levels(guaranteed_campaigns)


        help_text = None


        return render_to_response(self.request,
                                 'advertiser/adgroups.html',
                                  {'adgroups':adgroups,
                                   # 'graph_adgroups': graph_adgroups,
                                   # 'graph_gtee_adgroups': graph_gtee_adgroups,
                                   # 'graph_totals': account_level_stats,
                                   'account_stats': simplejson.dumps(response_dict),
                                   'start_date': days[0],
                                   'end_date':days[-1],
                                   'date_range': self.date_range,
                                   'apps' : apps,
                                   'guarantee_levels': guarantee_levels,
                                   'guarantee_num': len(guaranteed_campaigns),
                                   'marketplace': marketplace_campaigns,
                                   'promo': promo_campaigns,
                                   'network': network_campaigns,
                                   'backfill_promo': backfill_promo_campaigns,
                                   'account': self.account,
                                   'helptext':help_text,
                               })

####### Helpers for campaign page #######

def _sort_guarantee_levels(guaranteed_campaigns):
    """ Sort guaranteed campaigns according to levels """
    levels = ('high', '', 'low')
    gtee_str = "gtee_%s"
    gtee_levels = []
    for level in levels:
        this_level = gtee_str % level if level else "gtee"
        name = level if level else 'normal'
        level_camps = filter(lambda x:x.campaign.campaign_type == this_level, guaranteed_campaigns)
        gtee_levels.append(dict(name = name, adgroups = level_camps))

    # Determine which gtee_levels to display
    for level in gtee_levels:
        if level['name'] == 'normal' and len(gtee_levels[0]['adgroups']) == 0 and len(gtee_levels[2]['adgroups']) == 0:
            level['display'] = True
        elif len(level['adgroups']) > 0:
            level['display'] = True
        else:
            level['display'] = False
    return gtee_levels


def _sort_campaigns(adgroups):
    promo_campaigns = filter(lambda x: x.campaign.campaign_type in ['promo'], adgroups)
    promo_campaigns = sorted(promo_campaigns, lambda x,y: cmp(y.bid, x.bid))

    guaranteed_campaigns = filter(lambda x: x.campaign.campaign_type in ['gtee_high', 'gtee_low', 'gtee'], adgroups)
    guaranteed_campaigns = sorted(guaranteed_campaigns, lambda x,y: cmp(y.bid, x.bid))

    marketplace_campaigns = filter(lambda x: x.campaign.campaign_type in ['marketplace'], adgroups)
    marketplace_campaigns = sorted(marketplace_campaigns, lambda x,y: cmp(x.bid, y.bid))

    network_campaigns = filter(lambda x: x.campaign.campaign_type in ['network'], adgroups)
    network_campaigns = sorted(network_campaigns, lambda x,y: cmp(y.bid, x.bid))

    backfill_promo_campaigns = filter(lambda x: x.campaign.campaign_type in ['backfill_promo'], adgroups)
    backfill_promo_campaigns = sorted(backfill_promo_campaigns, lambda x,y: cmp(y.bid, x.bid))


    return [
        promo_campaigns,
        guaranteed_campaigns,
        marketplace_campaigns,
        network_campaigns,
        backfill_promo_campaigns,
    ]

def _calc_app_level_stats(adgroups):
    # adgroup1.all_stats = [StatsModel(day=1), StatsModel(day=2), StatsModel(day=3)]
    # adgroup2.all_stats = [StatsModel(day=1), StatsModel(day=2), StatsModel(day=3)]
    # adgroup3.all_stats = [StatsModel(day=1), StatsModel(day=2), StatsModel(day=3)]
    # all_daily_stats = [(StatsModel(day=1),StatsModel(day=1),StatsModel(day=1)),
    #                    (StatsModel(day=2),StatsModel(day=2),StatsModel(day=2)),
    #                    (StatsModel(day=3),StatsModel(day=3),StatsModel(day=3))]
    # returns [StatsModel(day=1)+StatsModel(day=1)+StatsModel(day=1),
    #          StatsModel(day=2)+StatsModel(day=2)+StatsModel(day=2)),
    #          StatsModel(day=3)+StatsModel(day=3)+StatsModel(day=3)]
    all_daily_stats = zip(*[adgroup.all_stats for adgroup in adgroups])
    return [sum(daily_stats, StatsModel()) for daily_stats in all_daily_stats]


def _calc_and_attach_e_cpm(adgroups_with_stats, app_level_summed_stats):
    """ Requires that adgroups already have attached stats """
    for adgroup in adgroups_with_stats:

        if adgroup.cpc:
            app_level_ctr = app_level_summed_stats.ctr
            e_ctr = adgroup.summed_stats.ctr or app_level_ctr or DEFAULT_CTR

            adgroup.summed_stats.e_cpm = float(e_ctr) * float(adgroup.cpc) * 1000

        else:
            adgroup.summed_stats.e_cpm = adgroup.cpm

    return adgroups_with_stats

def _calc_and_attach_osi_success(adgroups):
    for adgroup in adgroups:
        if adgroup.running and adgroup.campaign.budget:
            adgroup.osi_success = budget_service.get_osi(adgroup.campaign)

    return adgroups


@login_required
def adgroups(request,*args,**kwargs):
    return AdGroupIndexHandler()(request,*args,**kwargs)


class AdGroupArchiveHandler(RequestHandler):

    def get(self):
        archived_adgroups = AdGroupQueryManager().get_adgroups(account=self.account, archived=True)

        for adgroup in archived_adgroups:
            adgroup.budget_slicer = BudgetSlicer.get_by_campaign(adgroup.campaign)

        return render_to_response(self.request,
                                   'advertiser/archived_adgroups.html',
                                    {'archived_adgroups':archived_adgroups,
                                     })


@login_required
def archive(request,*args,**kwargs):
    return AdGroupArchiveHandler()(request,*args,**kwargs)


class CreateCampaignAJAXHander(RequestHandler):
    TEMPLATE    = 'advertiser/forms/campaign_create_form.html'
    def get(self,campaign_form=None,adgroup_form=None,
                             campaign=None,adgroup=None):
        if adgroup:
            campaign = campaign or adgroup.campaign

        # TODO: HACKKKK get price floors done
        initial = {}
        if campaign and campaign.campaign_type in ['marketplace', 'backfill_marketplace']:
            initial.update(price_floor=self.account.network_config.price_floor)
        campaign_form = campaign_form or CampaignForm(instance=campaign, initial=initial)
        adgroup_form = adgroup_form or AdGroupForm(instance=adgroup)
        networks = [['admob_native', 'AdMob', False],["adsense","AdSense",False],["brightroll","BrightRoll",False],["chartboost","ChartBoost",False],["ejam","eJam",False],\
            ["iAd","iAd",False],["inmobi","InMobi",False],["jumptap","Jumptap",False],['millennial_native', 'Millennial Media', False],["mobfox","MobFox",False],\
            ['custom','Custom Network', False], ['custom_native','Custom Native Network', False]]

        all_adunits = AdUnitQueryManager.get_adunits(account=self.account)
        # sorts by app name, then adunit name
        def adunit_cmp(adunit_1, adunit_2):
            app_cmp = cmp(adunit_1.app.name, adunit_2.app.name)
            if not app_cmp:
                return cmp(adunit_1.name, adunit_2.name)
            else:
                return app_cmp

        all_adunits.sort(adunit_cmp)

        adgroup_form['site_keys'].choices = all_adunits # needed for validation TODO: doesn't actually work

        # TODO: Remove this hack to place the bidding info with the rest of campaign
        #Hackish part
        campaign_form.bid    = adgroup_form['bid']
        campaign_form.bid_strategy = adgroup_form['bid_strategy']
        campaign_form.custom_html = adgroup_form['custom_html']
        campaign_form.custom_method = adgroup_form['custom_method']
        campaign_form.network_type = adgroup_form['network_type']

        adunit_keys = adgroup_form['site_keys'].value or []
        adunit_str_keys = [unicode(k) for k in adunit_keys]
        for adunit in all_adunits:
            adunit.checked = unicode(adunit.key()) in adunit_str_keys

        if adgroup_form:
            # We hide deprecated networks by default.  Show them for pre-existing adgroups though
            if adgroup_form['network_type'].value == 'admob' or self.request.user.is_staff:
                networks.append(["admob","AdMob Javascript (deprecated)",False])
            # Allow admins to create Millennial s2s campaigns
            if adgroup_form['network_type'].value == 'millennial' or self.request.user.is_staff:
                networks.append(["millennial","Millennial Server-side (deprecated)",False])
            if adgroup_form['network_type'].value == 'greystripe':
                networks.append(["greystripe","GreyStripe (deprecated)",False])
            for n in networks:
                if adgroup_form['network_type'].value == n[0]:
                    n[2] = True
        elif adgroup:
            for n in networks:
                if adgroup.network_type == n[0]:
                    n[2] = True
        else:
            networks[0][2] = True # select the first by default

        campaign_form.add_context(dict(networks=networks))
        adgroup_form.add_context(dict(all_adunits=all_adunits))
        return self.render(campaign_form=campaign_form,adgroup_form=adgroup_form)

    def render(self,template=None,**kwargs):
        template_name = template or self.TEMPLATE
        return render_to_string(self.request,template_name=template_name,data=kwargs)

    def json_response(self,json_dict):
        return JSONResponse(json_dict)

    def post(self):
        """
        TODO: Refactor these incredibly long views into something less mindfucky.
        """
        adgroup_key = self.request.POST.get('adgroup_key')
        if adgroup_key:
            adgroup = AdGroupQueryManager.get(adgroup_key)
            campaign = adgroup.campaign
        else:
            adgroup = None
            campaign = None

        campaign_form = CampaignForm(data=self.request.POST,instance=campaign)
        adgroup_form = AdGroupForm(data=self.request.POST,instance=adgroup)

        # We pre-emptively clear the cache for site keys, as they may be updated
        adunits_to_update = set()
        if adgroup:
            adunits_to_update.update(adgroup.site_keys)

        all_adunits = AdUnitQueryManager.get_adunits(account=self.account)
        sk_field = adgroup_form.fields['site_keys']
        sk_field.choices = all_adunits # TODO: doesn't work needed for validation

        json_dict = {'success':False,'errors': None}

        if campaign_form.is_valid():
            if not campaign_form.instance: #ensure form posts do not change ownership
                account = self.account
            else:
                account = campaign_form.instance.account
            campaign = campaign_form.save(commit=False)
            campaign.account = account

            if campaign.marketplace():
                self.account.network_config.price_floor = float(campaign_form.cleaned_data['price_floor'])
                AccountQueryManager.update_config_and_put(self.account, self.account.network_config)

            if adgroup_form.is_valid():
                if not adgroup_form.instance: #ensure form posts do not change ownership
                    account = self.account
                    has_adgroup_instance = False
                else:
                    account = adgroup_form.instance.account
                    has_adgroup_instance = True
                adgroup = adgroup_form.save(commit=False)
                adgroup.account = account


                # TODO: clean this up in case the campaign succeeds and the adgroup fails
                CampaignQueryManager.put(campaign)

                # Update budget upon changes or set budget from full_budget. Have to put in datastore first.
                budget_service.update_budget(campaign, save_campaign = False)
                # And then put in datastore again.
                CampaignQueryManager.put(campaign)

                adgroup.campaign = campaign
                # TODO: put this in the adgroup form
                if not adgroup.campaign.campaign_type == 'network':
                    adgroup.network_type = None


             #put adgroup so creative can have a reference to it
                AdGroupQueryManager.put(adgroup)

             ##Check if creative exists for this network type, if yes
             #update, if no, delete old and create new
                if campaign.campaign_type in ['marketplace', 'backfill_marketplace']:
                    if not has_adgroup_instance: #ensure form posts do not change ownership
                        creative = adgroup.default_creative()
                        creative.account = self.account
                        CreativeQueryManager.put(creative)

                elif campaign.campaign_type == "network":
                    html_data = None
                    if adgroup.network_type == 'custom':
                        html_data = adgroup_form['custom_html'].value
                    elif adgroup.network_type == 'custom_native':
                        html_data = adgroup_form['custom_method'].value
                    #build default creative with custom_html data if custom or none if anything else
                    creative = adgroup.default_creative(html_data)
                    if adgroup.net_creative and creative.__class__ == adgroup.net_creative.__class__:
                        #if the adgroup has a creative AND the new creative and old creative are the same class,
                        #ignore the new creative and set the variable to point to the old one
                        creative = adgroup.net_creative
                        if adgroup.network_type == 'custom':
                            #if the network is a custom one, the creative might be the same, but the data might be new, set the old
                            #creative to have the (possibly) new data
                            creative.html_data = html_data
                        elif adgroup.network_type == 'custom_native':
                            creative.html_data = html_data
                    elif adgroup.net_creative:
                        #in this case adgroup.net_creative has evaluated to true BUT the class comparison did NOT.
                        #at this point we know that there was an old creative AND it's different from the new creative so
                        #and delete the old creative just marks as deleted!
                        CreativeQueryManager.delete(adgroup.net_creative)

                    #creative should now reference the appropriate creative (new if different, old if the same, updated old if same and custom)
                    if not has_adgroup_instance: #ensure form posts do not change ownership
                        creative.account = self.account
                    #put the creative so we can reference it
                    CreativeQueryManager.put(creative)
                    #set adgroup to reference the correct creative
                    adgroup.net_creative = creative.key()
                    #put the adgroup again with the new (or old) creative reference
                    AdGroupQueryManager.put(adgroup)

                # Update network config information if this is a network type adgroup
                if campaign.campaign_type == "network":
                    apps_for_account = AppQueryManager.get_apps(account=self.account)
                    # Build app level pub_ids
                    for app in apps_for_account:
                        app_network_config_data = {}
                        for (key, value) in self.request.POST.iteritems():
                            app_key_identifier = key.split('-__-')
                            if app_key_identifier[0] == str(app.key()):
                                app_network_config_data[app_key_identifier[1]] = value

                        # logging.warning("link" + unicode(app.name) + " " + str(app_network_config_data))
                        app_form = NetworkConfigForm(data=app_network_config_data, instance=app.network_config)
                        app_network_config = app_form.save(commit=False)
                        AppQueryManager.update_config_and_put(app, app_network_config)

                # Delete Cache. We leave this in views.py because we
                # must delete the adunits that the adgroup used to have as well
                adunits_to_update.update(adgroup.site_keys)
                if adunits_to_update:
                    adunits = AdUnitQueryManager.get(adunits_to_update)
                    AdUnitContextQueryManager.cache_delete_from_adunits(adunits)

                # Onboarding: user is done after they set up their first campaign
                if self.account.status == "step4":
                    self.account.status = ""
                    AccountQueryManager.put_accounts(self.account)

                json_dict.update(success=True,new_page=reverse('advertiser_adgroup_show',kwargs={'adgroup_key':str(adgroup.key())}))
                return self.json_response(json_dict)


        flatten_errors = lambda frm : [(k, unicode(v[0])) for k, v in frm.errors.items()]
        grouped_errors = flatten_errors(campaign_form) + flatten_errors(adgroup_form)

        json_dict.update(success=False, errors=grouped_errors)
        return self.json_response(json_dict)

@login_required
def campaign_adgroup_create_ajax(request,*args,**kwargs):
    return CreateCampaignAJAXHander()(request,*args,**kwargs)


# Wrapper for the AJAX handler
class CreateCampaignHandler(RequestHandler):
    def get(self,campaign_form=None, adgroup_form=None, adgroup_key=None):
        adgroup = None
        if adgroup_key:
            adgroup = AdGroupQueryManager.get(adgroup_key)
            if not adgroup:
                raise Http404("AdGroup does not exist")

        campaign_create_form_fragment = CreateCampaignAJAXHander(self.request).get(adgroup=adgroup)
        return render_to_response(self.request,'advertiser/new.html', {"adgroup_key": adgroup_key,
            "adgroup":adgroup,
            "account": self.account,
            "campaign_create_form_fragment": campaign_create_form_fragment})

@login_required
def campaign_adgroup_create(request,*args,**kwargs):
    return CreateCampaignHandler()(request,*args,**kwargs)

class CreateAdGroupHandler(RequestHandler):
    def get(self, campaign_key=None, adgroup_key=None, edit=False, title="Create an Ad Group"):
        if campaign_key:
            c = AdGroupQueryManager.get(campaign_key)
            adgroup = AdGroup(name="%s Ad Group" % c.name, campaign=c, bid_strategy="cpm", bid=10.0, percent_users=100.0)
        if adgroup_key:
            adgroup = AdGroupQueryManager.get(adgroup_key)
            c = adgroup.campaign
            if not adgroup:
                raise Http404("AdGroup does not exist")
        adgroup.budget = c.budget # take budget from campaign for the time being
        f = AdGroupForm(instance=adgroup)
        adunits = AdUnitQueryManager.get_adunits(account=self.account)

        # allow the correct sites to be checked
        for adunit in adunits:
            adunit.checked = adunit.key() in adgroup.site_keys

        # TODO: Clean up this hacked shit
        networks = [["admob","AdMob",False],["adsense","AdSense",False],["brightroll","BrightRoll",False],["chartboost","ChartBoost",False],["ejam","eJam",False],["jumptap","Jumptap",False],["greystripe","GreyStripe",False],["iAd","iAd",False],["inmobi","InMobi",False],["millennial","Millennial Media",False],["mobfox","MobFox",False]]
        for n in networks:
            if adgroup.network_type == n[0]:
                n[2] = True

        return render_to_response(self.request,'advertiser/new_adgroup.html', {"f": f, "c": c, "sites": adunits, "title": title, "networks":networks})

    def post(self, campaign_key=None,adgroup_key=None, edit=False, title="Create an Ad Group"):

        adgroup = AdGroupQueryManager.get(adgroup_key)
        campaign = adgroup.campaign

        campaign_form = CampaignForm(data=self.request.POST,instance=campaign)
        adgroup_form = AdGroupForm(data=self.request.POST,instance=adgroup)

        all_adunits = AdUnitQueryManager.get_adunits(account=self.account)

        if campaign_form.is_valid():
            if not campaign_form.instance: #ensure form posts do not change ownership
                account = self.account
            else:
                account = campaign_form.instance.account
            campaign = campaign_form.save(commit=False)
            campaign.account = account
            if adgroup_form.is_valid():
                adgroup = adgroup_form.save(commit=False)
                # TODO: clean this up in case the campaign succeeds and the adgroup fails
                CampaignQueryManager.put(campaign)
                adgroup.campaign = campaign
                AdGroupQueryManager.put(adgroup)
                return HttpResponseRedirect(reverse('advertiser_adgroup_show',kwargs={'adgroup_key':str(adgroup.key())}))

@login_required
def campaign_adgroup_new(request,*args,**kwargs):
    return CreateAdGroupHandler()(request,*args,**kwargs)

@login_required
def campaign_adgroup_edit(request,*args,**kwargs):
    kwargs.update(title="Edit Ad Group",edit=True)
    return CreateAdGroupHandler()(request,*args,**kwargs)

class ShowAdGroupHandler(RequestHandler):
    def post(self, adgroup_key):
        adgroup = AdGroupQueryManager.get(adgroup_key)
        opt = self.params.get('action')
        update = False
        campaign = adgroup.campaign
        if opt == 'play':
            adgroup.active = True
            adgroup.archived = False
            update = True
        elif opt == 'pause':
            adgroup.active = False
            adgroup.archived = False
            update = True
        elif opt == "archive":
            adgroup.active = False
            adgroup.archived = True
            update = True
        elif opt == "delete":
            adgroup.deleted = True
            campaign.deleted = True
            AdGroupQueryManager.put(adgroup)
            CampaignQueryManager.put(campaign)

            self.request.flash["message"] = "Campaign: %s has been deleted." % adgroup.name
            return HttpResponseRedirect(reverse('advertiser_campaign'))

        else:
            logging.error("Passed an impossible option")

        if update:
            campaign.active = adgroup.active
            campaign.deleted = adgroup.deleted
            CampaignQueryManager.put(campaign)
            AdGroupQueryManager.put(adgroup)
        return HttpResponseRedirect(reverse('advertiser_adgroup_show', kwargs={'adgroup_key': str(adgroup.key())}))

    def get(self, adgroup_key):
        # Set start date if passed in, otherwise get most recent days
        if self.start_date:
            days = StatsModel.get_days(self.start_date, self.date_range)
        else:
            days = StatsModel.lastdays(self.date_range)

        # show a flash message recommending using reports if selecting more than 30 days
        if self.date_range > 30:
            self.request.flash['message'] = "For showing more than 30 days we recommend using the <a href='%s'>Reports</a> page." % reverse('reports_index')
        else:
            del self.request.flash['message']

        # Load the ad group itself
        adgroup = AdGroupQueryManager.get(adgroup_key)
        adgroup.all_stats = StatsModelQueryManager(self.account,offline=self.offline).get_stats_for_days(advertiser=adgroup, days=days)
        adgroup.stats = reduce(lambda x, y: x+y, adgroup.all_stats, StatsModel())
        adgroup.percent_delivered = budget_service.percent_delivered(adgroup.campaign)

        # Load creatives and populate
        creatives = CreativeQueryManager.get_creatives(adgroup=adgroup)
        creatives = list(creatives)
        for c in creatives:
            c.all_stats = StatsModelQueryManager(self.account,offline=self.offline).get_stats_for_days(advertiser=c, days=days)
            c.stats = reduce(lambda x, y: x+y, c.all_stats, StatsModel())
            if not c.format:
                c.format = "320x50" # TODO: Should fix DB so that format is always there
            c.size = c.format.partition('x')

        # Load all adunits that this thing is targeting right now
        adunits = AdUnitQueryManager.get_adunits(keys=adgroup.site_keys)
        apps = {}
        for au in adunits:
            app = apps.get(au.app_key.key())
            if not app:
                app = AppQueryManager.get(au.app_key.key())
                app.adunits = [au]
                app.all_stats = StatsModelQueryManager(self.account,offline=self.offline).\
                                        get_stats_for_days(publisher=app,
                                                           advertiser=adgroup,
                                                           days=days)
                app.stats = reduce(lambda x, y: x+y, app.all_stats, StatsModel())
                # if app.icon:
                #     app.icon_url = "data:image/png;base64,%s" % binascii.b2a_base64(app.icon)
                apps[au.app_key.key()] = app
            else:
                app.adunits += [au]

            au.all_stats = StatsModelQueryManager(self.account,offline=self.offline).get_stats_for_days(publisher=au,advertiser=adgroup, days=days)
            au.stats = reduce(lambda x, y: x+y, au.all_stats, StatsModel())

        # Figure out the top 4 ad units for the graph
        adunits = sorted(adunits, key=lambda adunit: adunit.stats.impression_count, reverse=True)
        graph_adunits = adunits[0:4]

        if len(adunits) > 4:
              graph_adunits[3] = Site(name='Others')
              graph_adunits[3].all_stats = [reduce(lambda x, y: x+y, stats, StatsModel()) for stats in zip(*[au.all_stats for au in adunits[3:]])]

        # Load creatives if we are supposed to
        if not (adgroup.campaign.campaign_type in ['network', 'marketplace', 'backfill_marketplace']):
            # In order to have add creative
            creative_handler = AddCreativeHandler(self.request)
            creative_fragment = creative_handler.get() # return the creative fragment

            # In order to have each creative be editable
            for c in creatives:
                c.html_fragment = creative_handler.get(creative=c)
        else:
            creative_fragment = None

        # In order to make the edit page
        campaign_create_form_fragment = CreateCampaignAJAXHander(self.request).get(adgroup=adgroup)

        try:
            yesterday = reduce(lambda x, y: x+y, [a.all_stats[-2] for a in graph_adunits], StatsModel())
        except:
            yesterday = StatsModel()

        message = []
        if adgroup.network_type and not 'custom' in adgroup.network_type and adgroup.network_type!='iAd':
            # gets rid of _native_ in admob_native_pub_id to become admob_pub_id
            if '_native' in adgroup.network_type:
                adgroup_network_type = adgroup.network_type.replace('_native','')
            else:
                adgroup_network_type = adgroup.network_type

            if (self.account.network_config and not getattr(self.account.network_config,adgroup_network_type+'_pub_id')) or not self.account.network_config:
                for app in apps.values():
                    if (app.network_config and not getattr(app.network_config,adgroup_network_type+'_pub_id')) or not app.network_config:
                        message.append("The application "+app.name+" needs to have a <strong>"+adgroup_network_type.title()+" Network ID</strong> in order to serve. Specify a "+adgroup_network_type.title()+" Network ID on <a href=%s>your account's ad network settings</a> page."%reverse("ad_network_settings"))
        if message == []:
            message = None
        else:
            message = "<br/>".join(message)
        return render_to_response(self.request, 'advertiser/adgroup.html',
                                    {'campaign': adgroup.campaign,
                                    'apps': apps.values(),
                                    'adgroup': adgroup,
                                    'creatives': creatives,
                                    'totals': reduce(lambda x, y: x+y.stats, adunits, StatsModel()),
                                    'today': reduce(lambda x, y: x+y, [a.all_stats[-1] for a in graph_adunits], StatsModel()),
                                    'yesterday': yesterday,
                                    'graph_adunits': graph_adunits,
                                    'start_date': days[0],
                                    'end_date': days[-1],
                                    'date_range': self.date_range,
                                    'creative_fragment':creative_fragment,
                                    'campaign_create_form_fragment':campaign_create_form_fragment,
                                    'message': message})

@login_required
def campaign_adgroup_show(request,*args,**kwargs):
    return ShowAdGroupHandler()(request,*args,**kwargs)


class PauseAdGroupHandler(RequestHandler):
    def post(self):
        action = self.request.POST.get("action", "pause")
        adgroups = []
        update_objs = []
        update_creatives = []
        for id_ in self.request.POST.getlist('id') or []:
            a = AdGroupQueryManager.get(id_)
            adgroups.append(a)
            if a != None and a.campaign.account == self.account:
                if action == "pause":
                    a.active = False
                    a.campaign.active = False
                    a.deleted = False
                    a.campaign.deleted = False
                    a.archived = False
                    update_objs.append(a)
                elif action == "resume":
                    a.active = True
                    a.campaign.active = True
                    a.deleted = False
                    a.campaign.deleted = False
                    a.archived = False
                    update_objs.append(a)
                elif action == "activate":
                    a.active = True
                    a.campaign.active = True
                    a.deleted = False
                    a.campaign.deleted = False
                    a.archived = False
                    update_objs.append(a)
                    self.request.flash["message"] = "A campaign has been activated. View it within <a href='%s'>active campaigns</a>." % reverse('advertiser_campaign')
                elif action == "archive":
                    a.active = False
                    a.campaign.active = False
                    a.deleted = False
                    a.campaign.deleted = False
                    a.archived = True
                    update_objs.append(a)
                    self.request.flash["message"] = "A campaign has been archived. View it within <a href='%s'>archived campaigns</a>." % reverse('advertiser_archive')
                elif action == "delete":
                    a.active = False
                    a.campaign.active = False
                    a.deleted = True
                    a.campaign.deleted = True
                    a.archived = False
                    update_objs.append(a)
                    self.request.flash["message"] = "Your campaign has been successfully deleted"
                    for creative in a.creatives:
                        creative.deleted = True
                        update_creatives.append(creative)

        if update_objs:
            AdGroupQueryManager.put(update_objs)
            camp_objs = []
            for adgroup in update_objs:
                camp_objs.append(adgroup.campaign)

            CampaignQueryManager.put(camp_objs)

        if update_creatives:
            CreativeQueryManager.put(update_creatives)

        return HttpResponseRedirect(self.request.META["HTTP_REFERER"])

@login_required
def bid_pause(request,*args,**kwargs):
    return PauseAdGroupHandler()(request,*args,**kwargs)

# AJAX Creative Create/Edit
#
class AddCreativeHandler(RequestHandler):
    TEMPLATE    = 'advertiser/forms/creative_form.html'
    def get(self,
            base_creative_form=None,
            text_creative_form=None,
            image_creative_form=None,
            text_tile_creative_form=None,
            html_creative_form=None,
            creative=None,
            text_creative=None,
            image_creative=None,
            text_tile_creative=None,
            html_creative=None):

        # TODO: Shouldn't I be able to just cast???
        if creative:
            if creative.ad_type == "text":
                text_creative = TextCreativeQueryManager.get(creative.key())
            elif creative.ad_type == "text_icon":
                text_tile_creative = TextAndTileCreativeQueryManager.get(creative.key())
            elif creative.ad_type == 'image':
                image_creative = ImageCreativeQueryManager.get(creative.key())
            elif creative.ad_type == "html":
                html_creative = HtmlCreativeQueryManager.get(creative.key())

        # NOTE: creative is usually None so the default form is actually unbound
        base_creative_form = base_creative_form or BaseCreativeForm(instance=creative)
        text_creative_form = text_creative_form or TextCreativeForm(instance=text_creative)
        image_creative_form = image_creative_form or ImageCreativeForm(instance=image_creative)
        text_tile_creative_form = text_tile_creative_form or TextAndTileCreativeForm(instance=text_tile_creative)
        html_creative_form = html_creative_form or HtmlCreativeForm(instance=html_creative)

        return self.render(base_creative_form=base_creative_form,
                                    text_creative_form=text_creative_form,
                                    image_creative_form=image_creative_form,
                                    text_tile_creative_form=text_tile_creative_form,
                                    html_creative_form=html_creative_form)

    def render(self,template=None,**kwargs):
        template_name = template or self.TEMPLATE
        return render_to_string(self.request,template_name=template_name,data=kwargs)

    def json_response(self,json_dict):
        # if not self.request.FILES:
        return JSONResponse(json_dict)
        # else:
        #     logging.info("responding with: %s"%('<textarea>'+simplejson.dumps(json_dict)+'</textarea>'))
        #     return HttpResponse('<textarea>'+simplejson.dumps(json_dict)+'</textarea>',mimetype="text/plain")

    def post(self):
        ad_group = AdGroupQueryManager.get(self.request.POST.get('adgroup_key'))
        creative_key = self.request.POST.get('creative_key')
        if creative_key:
            creative = CreativeQueryManager.get(creative_key)
        else:
            creative = None

        creative_form = None
        text_creative = None
        image_creative = None
        text_tile_creative = None
        html_creative = None

        # TODO: Shouldn't I be able to just cast???
        if creative:
            if creative.ad_type == "text":
                text_creative = TextCreativeQueryManager.get(creative.key())
            elif creative.ad_type == "text_icon":
                text_tile_creative = TextAndTileCreativeQueryManager.get(creative.key())
            elif creative.ad_type == "image":
                image_creative = ImageCreativeQueryManager.get(creative.key())
            elif creative.ad_type == "html":
                html_creative = HtmlCreativeQueryManager.get(creative.key())


        base_creative_form = BaseCreativeForm(data=self.request.POST,instance=creative)
        text_creative_form = TextCreativeForm(data=self.request.POST,instance=text_creative)
        image_creative_form = ImageCreativeForm(data=self.request.POST,files=self.request.FILES,instance=image_creative)
        text_tile_creative_form = TextAndTileCreativeForm(data=self.request.POST,files=self.request.FILES,instance=text_tile_creative)
        html_creative_form = HtmlCreativeForm(data=self.request.POST,instance=html_creative)


        jsonDict = {'success':False,'errors':[]}
        if base_creative_form.is_valid():
            base_creative = base_creative_form.save(commit=False)
            ad_type = base_creative.ad_type
            if ad_type == "text":
                creative_form = text_creative_form
            elif ad_type == "text_icon":
                creative_form = text_tile_creative_form
            elif ad_type == "image":
                creative_form = image_creative_form
            elif ad_type == "html":
                creative_form = html_creative_form

            if creative_form.is_valid():

                if not creative_form.instance: #ensure form posts do not change ownership
                    account = self.account
                else:
                    account = creative_form.instance.account
                creative = creative_form.save(commit=False)
                creative.account = account
                creative.ad_group = ad_group
                CreativeQueryManager.put(creative)

                jsonDict.update(success=True)
                return self.json_response(jsonDict)

        flatten_errors = lambda frm : [(k, unicode(v[0])) for k, v in frm.errors.items()]
        grouped_errors = flatten_errors(base_creative_form)
        if creative_form:
            grouped_errors.extend(flatten_errors(creative_form))

        jsonDict.update(success=False, errors=grouped_errors)
        return self.json_response(jsonDict)


@login_required
def creative_create(request,*args,**kwargs):
    return AddCreativeHandler()(request,*args,**kwargs)

class DisplayCreativeHandler(RequestHandler):
    def get(self, creative_key):
        c = CreativeQueryManager.get(creative_key)
        if c and c.ad_type == "image":

            return HttpResponse('<html><head><style type="text/css">body{margin:0;padding:0;}</style></head><body><img src="%s"/></body></html>'%images.get_serving_url(c.image_blob))
            # return HttpResponse(c.image,content_type='image/png')
        if c and c.ad_type == "text_icon":
            c.icon_url = images.get_serving_url(c.image_blob)

            return render_to_response(self.request, 'advertiser/text_tile.html', {'c':c})
            #return HttpResponse(c.image,content_type='image/png')
        if c and c.ad_type == "html":
            return HttpResponse("<html><body style='margin:0px;'>"+c.html_data+"</body></html");

class CreativeImageHandler(RequestHandler):
    def get(self,creative_key):
        c = CreativeQueryManager.get(creative_key)
        if c and c.image:
            return HttpResponse(c.image,content_type='image/png')
        raise Http404

def creative_image(request,*args,**kwargs):
    return DisplayCreativeHandler()(request,*args,**kwargs)

def creative_html(request,*args,**kwargs):
    return DisplayCreativeHandler()(request,*args,**kwargs)

class CreativeManagementHandler(RequestHandler):
    def post(self):
        adgroup_key = self.request.POST.get('adgroup_key')
        keys = self.request.POST.getlist('key')
        action = self.request.POST.get('action','pause')
        update_objs = []
        # TODO: bulk get before for loop
        for creative_key in keys:
            c = CreativeQueryManager.get(creative_key)
            if c != None and c.ad_group.campaign.account == self.account: # TODO: clean up dereferences
                if action == "pause":
                    c.deleted = False
                    c.active = False
                    update_objs.append(c)
                elif action == "resume":
                    c.deleted = False
                    c.active = True
                    update_objs.append(c)
                elif action == "delete":
                    c.deleted = True
                    c.active = False
                    update_objs.append(c)

        if update_objs:
            # db.put(update_objs)
            CreativeQueryManager.put(update_objs)

        return HttpResponseRedirect(reverse('advertiser_adgroup_show',kwargs={'adgroup_key':adgroup_key}))

@login_required
def creative_manage(request,*args,**kwargs):
    return CreativeManagementHandler()(request,*args,**kwargs)


class AdServerTestHandler(RequestHandler):
    def get(self):
        devices = [('iphone','iPhone'),('ipad','iPad'),('nexus_s','Nexus S')]
        device_to_user_agent = {
            'iphone': 'Mozilla/5.0 (iPhone; U; CPU iPhone OS 4_0 like Mac OS X; %s) AppleWebKit/532.9 (KHTML, like Gecko) Version/4.0.5 Mobile/8A293 Safari/6531.22.7',
            'ipad': 'Mozilla/5.0 (iPad; U; CPU OS 3_2 like Mac OS X; %s) AppleWebKit/531.21.10 (KHTML, like Gecko) Version/4.0.4 Mobile/7B334b Safari/531.21.10',
            'nexus_s': 'Mozilla/5.0 (Linux; U; Android 2.1; %s) AppleWebKit/522+ (KHTML, like Gecko) Safari/419.3',
            'chrome': 'Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US) AppleWebKit/525.13 (KHTML, like Gecko) Chrome/0.A.B.C Safari/525.13',
        }
        country_to_locale_ip = {
            'US': ('en-US', '204.28.127.10')      ,
            'FR': ('fr-FR', '96.20.81.147')       ,
            'HR': ('hr-HR', '93.138.74.115')      ,
            'DE': ('de-DE', '212.183.113.32')     ,
            'DA': ('dk-DA', '62.107.177.124')     ,
            'FI': ('fi-FI', '91.152.79.118')      ,
            'JA': ('jp-JA', '110.163.227.87')     ,
            'HD': ('us-HD', '59.181.77.74')       ,
            'HE': ('il-HE', '99.8.113.207')       ,
            'RU': ('ru-RU', '83.149.3.32')        ,
            'NL': ('nl-NL', '77.251.143.68')      ,
            'PT': ('br-PT', '189.104.89.115')     ,
            'NB': ('no-NB', '88.89.244.197')      ,
            'TR': ('tr-TR', '78.180.93.4')        ,
            'NE': ('go-NE', '0.1.0.2')            ,
            'TH': ('th-TH', '24.52.71.42')        ,
            'RO': ('ro-RO', '85.186.180.111')     ,
            'IS': ('is-IS', '194.144.110.171')    ,
            'PL': ('pl-PL', '193.34.3.100')       ,
            'EL': ('gr-EL', '62.38.244.73')       ,
            'EN': ('us-EN', '174.255.120.125')    ,
            'ZH': ('tw-ZH', '124.190.51.251')     ,
            'MS': ('my-MS', '120.141.166.6')      ,
            'CA': ('es-CA', '95.17.76.100')       ,
            'IT': ('it-IT', '151.56.174.44')      ,
            'AR': ('sa-AR', '188.55.13.170')      ,
            'IN': ('id-IN', '114.57.226.18')      ,
            'CS': ('cz-CS', '90.180.148.68')      ,
            'HU': ('hu-HU', '85.66.221.12')       ,
            'ID': ('id-ID', '180.214.232.8')      ,
            'ES': ('ec-ES', '190.10.214.187')     ,
            'KO': ('kr-KO', '112.170.242.147')    ,
            'SV': ('se-SV', '90.225.96.11')       ,
            'SK': ('sk-SK', '213.151.218.130')    ,
            'UK': ('ua-UK', '92.244.103.199')     ,
            'SL': ('si-SL', '93.103.136.7')       ,
        }

        adunits = AdUnitQueryManager.get_adunits(account=self.account)

        return render_to_response(self.request,
                                  'advertiser/adserver_test.html',
                                  {'adunits': adunits,
                                   'devices': devices,
                                   'countries': sorted(country_to_locale_ip.keys()),
                                   'device_to_user_agent': simplejson.dumps(device_to_user_agent),
                                   'country_to_locale_ip': simplejson.dumps(country_to_locale_ip)})

@login_required
def adserver_test(request,*args,**kwargs):
    return AdServerTestHandler()(request,*args,**kwargs)

class AJAXStatsHandler(RequestHandler):
    def get(self, start_date=None, date_range=14):
        from common.utils.query_managers import QueryManager
        from common_templates.templatetags import filters

        if start_date:
            s = start_date.split('-')
            start_date = datetime.date(int(s[0]),int(s[1]),int(s[2]))
            days = StatsModel.get_days(start_date, int(date_range))
        else:
            days = StatsModel.lastdays(int(date_range))

        if self.start_date: # this is tarded. the start date is really the end of the date range.
            end_date = datetime.datetime.strptime(self.start_date, "%Y-%m-%d")
        else:
            end_date = datetime.date.today()

        if self.date_range:
            start_date = end_date - datetime.timedelta(int(self.date_range) - 1)
        else:
            start_date = end_date - datetime.timedelta(13)


        advs = self.params.getlist('adv')
        pubs = self.params.getlist('pub')

        if not advs:
            advs = [None]

        if not pubs:
            pubs = [None]

        stats_dict = {}
        for adv in advs:
            for pub in pubs:
                stats = StatsModelQueryManager(self.account,
                                               offline=self.offline).get_stats_for_days(publisher=pub,
                                                                                        advertiser=adv,
                                                                                        days=days)

                key = "%s||%s"%(pub or '',adv or '')
                stats_dict[key] = {}
                stats_dict[key]['daily_stats'] = [s.to_dict() for s in stats]
                summed_stats = sum(stats, StatsModel())

                # adds ECPM if the adgroup is a CPC adgroup
                if db.Key(adv).kind() == 'AdGroup':
                    adgroup = AdGroupQueryManager.get(adv)
                    if adgroup.cpc:
                        e_ctr = summed_stats.ctr or DEFAULT_CTR
                        summed_stats.cpm = float(e_ctr) * float(adgroup.cpc) * 1000
                    elif 'marketplace' in adgroup.campaign.campaign_type:
                        # Overwrite the revenue from MPX if its marketplace
                        # TODO: overwrite clicks as well
                        stats_fetcher = MarketplaceStatsFetcher(self.account.key())
                        mpx_stats = stats_fetcher.get_account_stats( start_date, end_date)
                        summed_stats.revenue = float(mpx_stats.get('revenue', '$0.00').replace('$','').replace(',',''))
                        summed_stats.impression_count = int(mpx_stats.get('impressions', 0))

                        summed_stats.cpm = summed_stats.cpm # no-op
                    else:
                        summed_stats.cpm = adgroup.cpm

                    percent_delivered = budget_service.percent_delivered(adgroup.campaign)
                    summed_stats.percent_delivered = percent_delivered
                    adgroup.percent_delivered = percent_delivered

                    summed_stats.status = filters.campaign_status(adgroup)


                    if adgroup.running and adgroup.campaign.budget:
                        summed_stats.on_schedule = str(budget_service.get_osi(adgroup.campaign) * 100)
                    else:
                        summed_stats.on_schedule = "none"
                stats_dict[key]['sum'] = summed_stats.to_dict()

                # make name
                if pub:
                    pub_name = QueryManager.get(pub).name
                else:
                    pub_name = ''

                if adv:
                    adv_name = QueryManager.get(adv).name
                else:
                    adv_name = ''

                stats_dict[key]['name'] = "%s||%s"%(pub_name, adv_name)



        response_dict = {}
        response_dict['status'] = 200
        response_dict['all_stats'] = stats_dict
        return JSONResponse(response_dict)

from django.views.decorators.cache import cache_control
from django.views.decorators.vary import vary_on_headers, vary_on_cookie

@login_required
@cache_control(max_age=60)
def stats_ajax(request, *args, **kwargs):
    return AJAXStatsHandler()(request, *args, **kwargs)

class CampaignExporter(RequestHandler):
    def post(self, adgroup_key, file_type, start, end, *args, **kwargs):
        start = datetime.datetime.strptime(start,'%m%d%y')
        end = datetime.datetime.strptime(end,'%m%d%y')
        days = date_magic.gen_days(start, end)
        adgroup = AdGroupQueryManager.get(adgroup_key)
        all_stats = StatsModelQueryManager(self.account, offline=self.offline).get_stats_for_days(advertiser=adgroup, days=days)
        f_name_dict = dict(adgroup_title = adgroup.campaign.name,
                           start = start.strftime('%b %d'),
                           end   = end.strftime('%b %d, %Y'),
                           )
        # Build
        f_name = "%(adgroup_title)s CampaignStats,  %(start)s - %(end)s" % f_name_dict
        f_name = f_name.encode('ascii', 'ignore')
        # Zip up days w/ corresponding stats object and other stuff
        data = map(lambda x: [x[0]] + x[1], zip([day.strftime('%a, %b %d, %Y') for day in days], [campaign_stats(stat, adgroup.campaign.campaign_type) for stat in all_stats]))
        # Row titles
        c_type = adgroup.campaign.campaign_type
        titles = ['Date']
        if c_type == 'network':
            titles += ['Attempts', 'Impressions', 'Fill Rate', 'Clicks', 'CTR']
        elif 'gtee' in c_type:
            titles += ['Impressions', 'Clicks', 'CTR', 'Revenue']
        elif 'promo' in c_type:
            titles += ['Impressions', 'Clicks', 'CTR', 'Conversions', 'Conversion Rate']
        return sswriter.export_writer(file_type, f_name, titles, data)



def campaign_export(request, *args, **kwargs):
    return CampaignExporter()(request, *args, **kwargs)


# Marketplace Views
# At some point in the future, these should be branched into their own django app


class MPXInfoHandler(RequestHandler):
    def get(self):
        return render_to_response(self.request,
                                  "advertiser/mpx_splash.html",
                                  {})

@login_required
def mpx_info(request, *args, **kwargs):
    return MPXInfoHandler()(request, *args, **kwargs)


class MarketplaceIndexHandler(RequestHandler):
    """
    Rendering of the Marketplace page. At this point, this is the only
    Marketplace page, and everything is rendered here.
    """
    def get(self):

        # Marketplace settings are kept as a single campaign.
        # Only one should exist per account.
        marketplace_campaign = CampaignQueryManager.get_marketplace(self.account, from_db=True)

        # We list the app traits in the table, and then load their stats over ajax using Backbone.
        # Fetch the apps for the template load, and then create a list of keys for ajax bootstrapping.
        adunits = AdUnitQueryManager.get_adunits(account=self.account)
        adunit_keys = simplejson.dumps([str(au.key()) for au in adunits])

        apps = {}
        for au in adunits:
            app = apps.get(au.app_key.key())
            if not app:
                app = AppQueryManager.get(au.app_key.key())
                logging.info(app.name)
                app.adunits = [au]
                apps[au.app_key.key()] = app
            else:
                app.adunits += [au]
        app_keys = simplejson.dumps([str(k) for k in apps.keys()])

        # Set up a MarketplaceStatsFetcher with this account
        stats_fetcher = MarketplaceStatsFetcher(self.account.key())
        #stats_fetcher = MarketplaceStatsFetcher("agltb3B1Yi1pbmNyEAsSB0FjY291bnQY8d77Aww")

        # Form the date range
        # this is tarded. the start date is really the end of the date range.
        if self.start_date:
            year, month, day = str(self.start_date).split('-')
            end_date = datetime.date(int(year), int(month), int(day))
        else:
            end_date = datetime.date.today()

        if self.date_range:
            start_date = end_date - datetime.timedelta(int(self.date_range) - 1)
        else:
            start_date = end_date - datetime.timedelta(13)

        # Get the top level marketplace stats for the account
        top_level_mpx_stats = stats_fetcher.get_account_stats(start_date, end_date)

        # Set up the blocklist
        blocklist = []
        network_config = self.account.network_config
        if network_config:
            blocklist = [str(domain) for domain in network_config.blocklist if not str(domain) in ("", "#")]

        dsp_keys =  simplejson.dumps([str(dsp_key) for dsp_key in MPX_DSP_IDS])

        return render_to_response(self.request,
                                  "advertiser/marketplace_index.html",
                                  {
                                      'marketplace': marketplace_campaign,
                                      'apps': apps.values(),
                                      'app_keys': app_keys,
                                      'adunit_keys': adunit_keys,
                                      'dsp_keys':dsp_keys,
                                      'pub_key': self.account.key(),
                                      'top_level_mpx_stats': top_level_mpx_stats,
                                      'blocklist': blocklist,
                                      'date_range': self.date_range
                                  })


@login_required
def marketplace_index(request, *args, **kwargs):
    return MarketplaceIndexHandler()(request, use_cache=False, *args, **kwargs)


class AddBlocklistHandler(RequestHandler):
    def post(self):
        add_blocklist_string = self.request.POST.get('blocklist')
        add_blocklist = add_blocklist_string.replace(',',' ').split()

        if add_blocklist:
            network_config = self.account.network_config
            network_config.blocklist.extend(add_blocklist)
            network_config.blocklist = sorted(set(network_config.blocklist))   # Removes duplicates and sorts
            AccountQueryManager().update_config_and_put(account=self.account,network_config=network_config)
        return HttpResponseRedirect(reverse('marketplace_index'))

@login_required
def add_blocklist_handler(request,*args,**kwargs):
    return AddBlocklistHandler()(request,*args,**kwargs)


class RemoveBlocklistHandler(RequestHandler):
    def get(self, url=None):
        #url = self.request.GET.get('url')
        network_config = self.account.network_config
        if network_config.blocklist.count(url):
            network_config.blocklist.remove(url)
            AccountQueryManager().update_config_and_put(account=self.account,network_config=network_config)

        return HttpResponseRedirect(reverse('marketplace_index'))


@login_required
def remove_blocklist_handler(request,*args,**kwargs):
    return RemoveBlocklistHandler()(request, use_cache=False, *args, **kwargs)


class MarketplaceOnOffHandler(RequestHandler):
    def post(self):
        try:
            activate = self.request.POST.get('activate', 'on')
            mpx = CampaignQueryManager.get_marketplace(self.account)
            if activate == 'on':
                mpx.active = True
            elif activate == 'off':
                mpx.active = False

            CampaignQueryManager.put(mpx)
            return JSONResponse({'success': 'success'})
        except Exception, e:
            return JSONResponse({'error': e})

@login_required
def marketplace_on_off(request, *args, **kwargs):
    return MarketplaceOnOffHandler()(request, *args, **kwargs)


class MarketplaceSettingsChangeHandler(RequestHandler):
    def post(self):
        try:
            return JSONResponse({'success': str(self.request.POST)})
        except Exception, e:
            return JSONResponse({'success': e})

@login_required
def marketplace_settings_change(request, *args, **kwargs):
    return MarketplaceSettingsChangeHandler()(request, *args, **kwargs)


def test_jsonp(request, *args, **kwargs):
    logging.warn(request.GET)
    from common_templates.templatetags.filters import currency, percentage, percentage_rounded
    data = {"4e45baaddadbc70de9000002": {"157:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 0.06710719999999998, "clk": 0.0, "bid": 1.6070199999999977, "chrg": 0.08284839506172802, "imp": 49.0, "bid_cnt": 784.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/0/320x50girl.png", "dsp": "4e45baaddadbc70de9000002", "_id": "157:4e45baaddadbc70de9000002", "crtv_id": "157"}}, "135:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 0.20621219999999996, "clk": 0.0, "bid": 0.5432000000000008, "chrg": 0.25458296296295985, "imp": 146.0, "bid_cnt": 258.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/1/tzf_320x50_trex_copy.png", "dsp": "4e45baaddadbc70de9000002", "_id": "135:4e45baaddadbc70de9000002", "crtv_id": "135"}}, "128:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 10.253166300000247, "clk": 0.0, "bid": 44.81724000000253, "chrg": 12.787477477654068, "imp": 6806.0, "bid_cnt": 21700.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/1/tp_320x50_bulldog_trees.png", "dsp": "4e45baaddadbc70de9000002", "_id": "128:4e45baaddadbc70de9000002", "crtv_id": "128"}}, "127:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 2.2066263000000026, "clk": 0.0, "bid": 10.368309999999996, "chrg": 2.7438060200000116, "imp": 1458.0, "bid_cnt": 5071.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/1/tp_320x50_kitten_blue.png", "dsp": "4e45baaddadbc70de9000002", "_id": "127:4e45baaddadbc70de9000002", "crtv_id": "127"}}, "139:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 6.414811200000116, "clk": 0.0, "bid": 17.40092000000083, "chrg": 7.978434230000027, "imp": 4272.0, "bid_cnt": 8353.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/1/tzf_320x50_fox_copy.png", "dsp": "4e45baaddadbc70de9000002", "_id": "139:4e45baaddadbc70de9000002", "crtv_id": "139"}}, "119:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 1.6569770999999904, "clk": 0.0, "bid": 77.55464999996597, "chrg": 2.050049480740752, "imp": 1166.0, "bid_cnt": 40282.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/0/iPhone_Pod_300x50_Groupon_13.jpg", "dsp": "4e45baaddadbc70de9000002", "_id": "119:4e45baaddadbc70de9000002", "crtv_id": "119"}}, "138:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 0.8074744000000014, "clk": 0.0, "bid": 71.82487000000586, "chrg": 1.0115733333332328, "imp": 1149.0, "bid_cnt": 35596.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/1/tzf_320x50_horse_copy.png", "dsp": "4e45baaddadbc70de9000002", "_id": "138:4e45baaddadbc70de9000002", "crtv_id": "138"}}, "154:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 0.08237700000000005, "clk": 0.0, "bid": 0.4737699999999998, "chrg": 0.10169999999999997, "imp": 56.0, "bid_cnt": 229.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/0/Zoo_retarget_300x50.png", "dsp": "4e45baaddadbc70de9000002", "_id": "154:4e45baaddadbc70de9000002", "crtv_id": "154"}}, "140:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 0.33895260000000005, "clk": 0.0, "bid": 1.1651400000000005, "chrg": 0.4184599999999994, "imp": 218.0, "bid_cnt": 570.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/1/tzf_320x50_horse_copy.png", "dsp": "4e45baaddadbc70de9000002", "_id": "140:4e45baaddadbc70de9000002", "crtv_id": "140"}}, "123:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 0.06781869999999998, "clk": 0.0, "bid": 0.5141300000000001, "chrg": 0.08372679012345602, "imp": 49.0, "bid_cnt": 248.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/1/tp_320x50_kitten_trees.png", "dsp": "4e45baaddadbc70de9000002", "_id": "123:4e45baaddadbc70de9000002", "crtv_id": "123"}}, "142:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 5.465296799999992, "clk": 0.0, "bid": 55.6291300000031, "chrg": 6.774577225185229, "imp": 3758.0, "bid_cnt": 26653.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/1/tzf_320x50_bronto_copy.png", "dsp": "4e45baaddadbc70de9000002", "_id": "142:4e45baaddadbc70de9000002", "crtv_id": "142"}}, "126:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 0.6383409000000004, "clk": 0.0, "bid": 56.610070000001095, "chrg": 0.7975813580245933, "imp": 907.0, "bid_cnt": 26974.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/1/tp_320x50_dog1_red.png", "dsp": "4e45baaddadbc70de9000002", "_id": "126:4e45baaddadbc70de9000002", "crtv_id": "126"}}, "125:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 2.5895072000000177, "clk": 0.0, "bid": 208.04931999997623, "chrg": 3.246181728394733, "imp": 3680.0, "bid_cnt": 100299.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/1/tp_320x50_bulldog_trees.png", "dsp": "4e45baaddadbc70de9000002", "_id": "125:4e45baaddadbc70de9000002", "crtv_id": "125"}}, "159:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 0.12455870000000002, "clk": 0.0, "bid": 3.4172599999999886, "chrg": 0.15464037037036804, "imp": 94.0, "bid_cnt": 1642.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/0/320x50nogirl.jpg", "dsp": "4e45baaddadbc70de9000002", "_id": "159:4e45baaddadbc70de9000002", "crtv_id": "159"}}, "141:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 4.546954300000034, "clk": 0.0, "bid": 7.373459999999929, "chrg": 5.6135238271605115, "imp": 3259.0, "bid_cnt": 3492.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/1/tzf_320x50_trex_nocopy.png", "dsp": "4e45baaddadbc70de9000002", "_id": "141:4e45baaddadbc70de9000002", "crtv_id": "141"}}, "155:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 0.14750860000000005, "clk": 0.0, "bid": 0.7712300000000003, "chrg": 0.18210938271604793, "imp": 105.0, "bid_cnt": 375.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/0/Zoo_retarget_300x50.png", "dsp": "4e45baaddadbc70de9000002", "_id": "155:4e45baaddadbc70de9000002", "crtv_id": "155"}}, "129:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 29.085825499999007, "clk": 0.0, "bid": 49.543050000003056, "chrg": 36.0579327160469, "imp": 21297.0, "bid_cnt": 24346.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/1/tp_320x50_kitten_green.png", "dsp": "4e45baaddadbc70de9000002", "_id": "129:4e45baaddadbc70de9000002", "crtv_id": "129"}}, "130:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 3.876862500000001, "clk": 0.0, "bid": 27.913090000000118, "chrg": 4.7990599850617555, "imp": 2651.0, "bid_cnt": 13345.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/1/tp_320x50_dog1_trees.png", "dsp": "4e45baaddadbc70de9000002", "_id": "130:4e45baaddadbc70de9000002", "crtv_id": "130"}}, "137:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 0.7056201000000022, "clk": 0.0, "bid": 67.10532000000602, "chrg": 0.8797779012344641, "imp": 996.0, "bid_cnt": 33529.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/1/tzf_320x50_horse_copy.png", "dsp": "4e45baaddadbc70de9000002", "_id": "137:4e45baaddadbc70de9000002", "crtv_id": "137"}}, "109:4e45baaddadbc70de9000002": {"stats": {"pub_rev": 0.011380499999999998, "clk": 0.0, "bid": 2.1614800000000174, "chrg": 0.01405, "imp": 8.0, "bid_cnt": 1031.0}, "creative": {"body": None, "ad_dmn": None, "url": "http://m.adsymptotic.com/i/0/vegas_320x50_2am.gif", "dsp": "4e45baaddadbc70de9000002", "_id": "109:4e45baaddadbc70de9000002", "crtv_id": "109"}}}}

    # creatives = []
    # for key, creative in data['4e45baaddadbc70de9000002'].iteritems():
    #     creatives.append([
    #         creative["creative"]["url"],
    #         creative["creative"]["ad_dmn"],
    #         creative["stats"]["pub_rev"],
    #         10.0,
    #         creative["stats"]["imp"],
    #         #creative["stats"]["clk"],
    #         #percentage_rounded(creative['stats']['ctr']),
    #     ])

    # response = {'aaData': creatives}
    s = simplejson.dumps(data)
    return HttpResponse("%s(%s);" % (request.GET.get('callback'), s))