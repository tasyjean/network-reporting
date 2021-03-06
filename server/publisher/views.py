"""
Views that handle pages for Apps and AdUnits.
"""

import logging
import urllib
import datetime
# hack to get urllib to work on snow leopard
urllib.getproxies_macosx_sysconf = lambda: {}

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, Http404
from django.core.urlresolvers import reverse
from django.utils import simplejson
from common.ragendja.template import (
    render_to_response,
    render_to_string,
    HttpResponse,
    JSONResponse
)

## Models
from advertiser.models import (
    Campaign,
    AdGroup,
    HtmlCreative
)

from publisher.forms import AppForm, AdUnitForm
from account.models import NetworkConfig

## Query Managers
from account.query_managers import AccountQueryManager
from ad_network_reports.query_managers import (
    AdNetworkMapperManager,
    AdNetworkLoginManager
)
from advertiser.query_managers import (
    AdvertiserQueryManager,
    CampaignQueryManager,
    AdGroupQueryManager,
    CreativeQueryManager
)
from publisher.query_managers import (
    PublisherQueryManager,
    AppQueryManager,
    AdUnitQueryManager
)
from reporting.query_managers import StatsModelQueryManager

from common.utils.request_handler import RequestHandler
from common.utils import tablib


class DashboardHandler(RequestHandler):
    def get(self):
        names = {
            'direct': 'Direct Sold',
            'mpx': 'Marketplace',
            'network': 'Ad Networks',
        }

        campaigns = AdvertiserQueryManager.get_campaigns_dict_for_account(
            account=self.account, include_deleted=True
        )
        for key, campaign in campaigns.items():
            names[key] = campaign.name

        apps = PublisherQueryManager.get_apps_dict_for_account(
            account=self.account, include_deleted=True
        )
        for key, app in apps.items():
            names[key] = app.name

        adunits = PublisherQueryManager.get_adunits_dict_for_account(
            account=self.account, include_deleted=True
        )
        for key, adunit in adunits.items():
            names[key] = adunit.name

        return {
            'page_width': 'wide',
            'names': names,
        }


@login_required
def dashboard(request, *args, **kwargs):
    handler = DashboardHandler(template="publisher/dashboard.html")
    return handler(request, use_cache=False, use_handshake=True, *args, **kwargs)


class AppIndexHandler(RequestHandler):
    """
    A list of apps and their real-time stats.
    """
    def get(self):

        # Get all of the account's apps.
        apps_dict = PublisherQueryManager.get_objects_dict_for_account(self.account)
        app_keys = simplejson.dumps([str(key) for key in apps_dict.keys()])
        sorted_apps = sorted(apps_dict.values(), lambda x, y: cmp(x.name, y.name))

        # If there are no apps, redirect to the app creation form.
        if len(apps_dict) == 0:
            return HttpResponseRedirect(reverse('publisher_create_app'))


        return {
            'apps': sorted_apps,
            'app_keys': app_keys,
        }


@login_required
def app_index(request, *args, **kwargs):
    handler = AppIndexHandler(template='publisher/app_index.html')
    return handler(request, use_cache=False, *args, **kwargs)


class CreateAppHandler(RequestHandler):

    def get(self, app_form=None, adunit_form=None, reg_complete=None):

        # create the forms
        app_form = app_form or AppForm()
        adunit_form = adunit_form or AdUnitForm(prefix="adunit")

        # REFACTOR
        # attach on registration related parameters to the account for template
        if reg_complete:
            self.account.reg_complete = 1

        return {
            "app_form": app_form,
            "adunit_form": adunit_form
        }

    def post(self):

        app_form = AppForm(data=self.request.POST, files=self.request.FILES)
        adunit_form = AdUnitForm(data=self.request.POST, prefix="adunit")

        # If there are validation errors in either the app_form or adunit_form,
        # fail by returning the page rendered with the invalid forms.
        if not app_form.is_valid() or not adunit_form.is_valid():
            return render_to_response(self.request, self.template, {
                'app_form': app_form,
                'adunit_form': adunit_form
            })

        account = self.account  # attach account info
        app = app_form.save(commit=False)
        app.account = account
        AppQueryManager.update_config_and_put(app, NetworkConfig())

        account = self.account
        adunit = adunit_form.save(commit=False)
        adunit.account = account
        AdUnitQueryManager.update_config_and_put(adunit, NetworkConfig())

        # update the database
        AppQueryManager.put(app)

        create_iad_mapper(self.account, app)

        adunit.app_key = app
        AdUnitQueryManager.put(adunit)

        # see if we need to enable the marketplace or network campaigns
        enable_marketplace(adunit, self.account)
        enable_networks(adunit, self.account)

        # Check if this is the first ad unit for this account
        if len(AdUnitQueryManager.get_adunits(account=self.account, limit=2)) == 1:
            add_demo_campaign(adunit)
        # Check if this is the first app for this account
        status = "success"
        if self.account.status == "new":
            self.account.status = "step4"
            # skip to step 4 (add campaigns), but show step 2 (integrate)
            # TODO (Tiago): add the itunes info here for iOS apps for iAd syncing
            network_config = self.account.network_config or NetworkConfig(account=self.account)
            AccountQueryManager.update_config_and_put(account, network_config)

            # create the marketplace account for the first time
            mpx = CampaignQueryManager.get_marketplace(self.account)
            mpx.active = False
            CampaignQueryManager.put(mpx)

            status = "welcome"

        # Redirect to the code snippet page
        publisher_integration_url = reverse('publisher_integration_help',
                                            kwargs = {
                                                'adunit_key': adunit.key()
                                            })
        publisher_integration_url = publisher_integration_url + '?status=' + status
        return HttpResponseRedirect(publisher_integration_url)


@login_required
def create_app(request, *args, **kwargs):
    handler = CreateAppHandler(template='publisher/create_app.html')
    return handler(request, *args, **kwargs)


class AppDetailHandler(RequestHandler):

    def get(self, app_key):

        app = AppQueryManager.get(app_key)
        app.adunits = AdUnitQueryManager.get_adunits(app=app)
        app.adunits = sorted(app.adunits,
                             key=lambda adunit: adunit.name,
                             reverse=True)

        help_text = 'Create an Ad Unit below' if len(app.adunits) == 0 else None

        app_form_fragment = AppUpdateAJAXHandler(self.request).get(app=app)
        adunit_form_fragment = AdUnitUpdateAJAXHandler(self.request).get(
            app=app)

        line_items = AdGroupQueryManager.get_sorted_line_items_for_app_and_date_range(
            app, self.start_date, self.end_date)

        marketplace_campaign = CampaignQueryManager.get_marketplace(app._account, from_db=True)

        network_campaigns = CampaignQueryManager.get_network_campaigns(app.account, is_new=True)
        for campaign in network_campaigns:
            if campaign.active:
                active = False
                for adunit in app.adunits:
                    adgroup = AdGroupQueryManager.get_network_adgroup(campaign, adunit.key(), app.account, get_from_db=True)
                    if adgroup.active:
                        active = True
                        break
                campaign.active = active
        network_campaigns = sorted(network_campaigns, key=lambda campaign: campaign.name.lower())

        return {
            'app': app,
            'app_form_fragment': app_form_fragment,
            'adunit_form_fragment': adunit_form_fragment,
            'helptext': help_text,
            'line_items': line_items,
            'marketplace_campaign': marketplace_campaign,
            'network_campaigns': network_campaigns,
        }


@login_required
def app_detail(request, *args, **kwargs):
    handler = AppDetailHandler(id='app_key', template='publisher/app.html')
    return handler(request, use_cache=False, *args, **kwargs)


class AdUnitDetailHandler(RequestHandler):

    def get(self, adunit_key):

        adunit = AdUnitQueryManager.get(adunit_key)

        # get the form to allow the adunit to be edited
        adunit_form_fragment = AdUnitUpdateAJAXHandler(self.request).get(
            adunit=adunit)

        line_items = AdGroupQueryManager.get_sorted_line_items_for_adunit_and_date_range(
            adunit, self.start_date, self.end_date)

        untargeted = True
        for line_item in line_items:
            if line_item.active:
                untargeted = False
                break

        marketplace_adgroup = AdGroupQueryManager.get_marketplace_adgroup(
            adunit.key(),
            adunit._account,
            get_from_db=True
        )
        if untargeted:
            untargeted = not (marketplace_adgroup.campaign.active \
                              and marketplace_adgroup.active)

        network_adgroups = AdGroupQueryManager.get_network_adgroups_for_adunit(adunit)
        network_adgroups = sorted(network_adgroups,
                                  key=lambda adgroup: adgroup.name.lower())
        if untargeted:
            for adgroup in network_adgroups:
                if adgroup.campaign.active and adgroup.active:
                    untargeted = False
                    break

        return {
            'site': adunit,
            'adunit': adunit,
            'adunit_form_fragment': adunit_form_fragment,
            'line_items': line_items,
            'marketplace_adgroup': marketplace_adgroup,
            'network_adgroups': network_adgroups,
            'untargeted': untargeted,
        }


@login_required
def adunit_detail(request, *args, **kwargs):
    handler = AdUnitDetailHandler(id='adunit_key', template='publisher/adunit.html')
    return handler(request, use_cache=False, *args, **kwargs)


class AppUpdateAJAXHandler(RequestHandler):

    TEMPLATE  = 'publisher/forms/app_form.html'
    def get(self,app_form=None,app=None):
        app_form = app_form or AppForm(instance=app, is_edit_form=True)
        app_form.is_edit_form = True
        return self.render(form=app_form)

    def render(self,template=None,**kwargs):
        template_name = template or self.TEMPLATE
        return render_to_string(self.request,
                                template_name = template_name,
                                data = kwargs)

    def json_response(self,json_dict):
        return JSONResponse(json_dict)

    def post(self,app_key=None):
        app_key = app_key or self.request.POST.get('app_key')
        if app_key:
            app = AppQueryManager.get(app_key)
            create = False
        else:
            app = None
            create = True

        app_form = AppForm(data = self.request.POST,
                           files = self.request.FILES,
                           instance = app,
                           is_edit_form = True)

        json_dict = {'success':False,'errors':[]}
        if app_form.is_valid():
            if not app_form.instance: #ensure form posts do not change ownership
                account = self.account
            else:
                account = app_form.instance.account

            app = app_form.save(commit=False)
            app.account = account

            if create:
                AppQueryManager.update_config_and_put(app, NetworkConfig())

            AppQueryManager.put(app)

            create_iad_mapper(self.account, app)

            json_dict.update(success=True)

            return self.json_response(json_dict)

        flatten_errors = lambda frm : [(k, unicode(v[0])) for k, v in frm.errors.items()]
        grouped_errors = flatten_errors(app_form)

        json_dict.update(success = False, errors = grouped_errors)
        return self.json_response(json_dict)


@login_required
def app_update_ajax(request, *args, **kwargs):
    handler = AppUpdateAJAXHandler(id='app_key')
    return handler(request, *args, **kwargs)


class AdUnitUpdateAJAXHandler(RequestHandler):
    """
    REFACTOR

                     %%%%%%
                   %%%% = =
                   %%C    >
                    _)' _( .' ,
                 __/ |_/\   " *. o
                /` \_\ \/     %`= '_  .
               /  )   \/|      .^',*. ,
              /' /-   o/       - " % '_
             /\_/     <       = , ^ ~ .
             )_o|----'|          .`  '
         ___// (_  - (\
        ///-(    \'   \\
    """

    TEMPLATE = 'publisher/forms/adunit_form.html'

    def get(self, adunit_form=None, adunit=None, app=None):
        initial = {}
        if app:
            initial.update(app_key=app.key())
        adunit_form = adunit_form or AdUnitForm(instance=adunit,
                                                initial=initial,
                                                prefix="adunit")
        return self.render(form=adunit_form)

    def render(self, template=None, **kwargs):
        template_name = template or self.TEMPLATE
        return render_to_string(self.request,
                                template_name=template_name,
                                data=kwargs)

    def json_response(self, json_dict):
        return JSONResponse(json_dict)

    def post(self, adunit_key=None):
        adunit_key = adunit_key or self.request.POST.get('adunit_key')
        if adunit_key:
            # Note this gets things from the cache ?
            adunit = AdUnitQueryManager.get(adunit_key)
            if adunit.account.key() != self.account.key():
                raise Http404
            create = False
        else:
            adunit = None
            create = True

        adunit_form = AdUnitForm(data=self.request.POST,
                                 instance=adunit,
                                 prefix="adunit")
        json_dict = {'success': False, 'errors': []}

        if adunit_form.is_valid():
            #ensure form posts do not change ownership
            if not adunit_form.instance:
                account = self.account
            else:
                account = adunit_form.instance.account

            adunit = adunit_form.save(commit=False)
            adunit.account = account

            if create:
                AdUnitQueryManager.update_config_and_put(adunit, NetworkConfig())

            AdUnitQueryManager.put(adunit)

            # If the adunit already exists we don't need to enable the
            # marketplace or networks
            if not adunit_key:
                enable_marketplace(adunit, self.account)
                enable_networks(adunit, self.account)

            json_dict.update(success=True)
            return self.json_response(json_dict)

        flatten_errors = lambda frm : [(k, unicode(v[0])) for k, v in
                frm.errors.items()]
        grouped_errors = flatten_errors(adunit_form)

        json_dict.update(success=False, errors=grouped_errors)
        return self.json_response(json_dict)


def adunit_update_ajax(request, *args, **kwargs):
    return AdUnitUpdateAJAXHandler()(request, *args, **kwargs)



class DeleteAppHandler(RequestHandler):
    """
    Deletes an app and redirects to the app index.
    """
    def post(self, app_key):
        app = AppQueryManager.get(app_key)

        if app is None or app.account.key() != self.account.key():
            raise Http404

        adunits = AdUnitQueryManager.get_adunits(app=app)

        app.deleted = True
        # also "delete" all the adunits associated with the app
        for adunit in adunits:
            adunit.deleted = True

        AppQueryManager.put(app)
        AdUnitQueryManager.put(adunits)

        return HttpResponseRedirect(reverse('app_index'))


@login_required
def delete_app(request, *args, **kwargs):
    return DeleteAppHandler()(request, *args, **kwargs)


class DeleteAdUnitHandler(RequestHandler):
    """
    Deletes an adunit and redirects to the adunit's app.
    """
    def post(self, adunit_key):
        adunit = AdUnitQueryManager.get(adunit_key)

        if adunit is None or adunit.account.key() != self.account.key():
            raise Http404

        adunit.deleted = True
        AdUnitQueryManager.put(adunit)

        return HttpResponseRedirect(reverse('publisher_app_show',
                                            kwargs = {
                                                'app_key': adunit.app.key()
                                            }))


@login_required
def delete_adunit(request, *args, **kwargs):
    return DeleteAdUnitHandler()(request, *args, **kwargs)


class IntegrationHelpHandler(RequestHandler):
    """
    This page displays some helpful information that helps pubs get
    their apps integrated. Pubs land on this page after they've
    created a new adunit.
    """
    def get(self, adunit_key):
        adunit = AdUnitQueryManager.get(adunit_key)
        status = self.params.get('status')
        return {
            'site': adunit,
            'status': status,
            'width': adunit.get_width(),
            'height': adunit.get_height(),
        }


@login_required
def integration_help(request, *args, **kwargs):
    t = 'publisher/integration_help.html'
    return IntegrationHelpHandler(template=t)(request, *args, **kwargs)


#############
# Exporting #
#############

class InventoryExporter(RequestHandler):

    def get(self):

        export_type = self.request.GET.get('type', 'html')

        apps_dict = PublisherQueryManager.get_objects_dict_for_account(self.account)
        app_data = []

        stats = StatsModelQueryManager(self.account)

        for app in apps_dict.values():

            # Make a row for each app with it's summed stats
            app_stats = stats.get_stats_sum(publisher=app, num_days=self.date_range)
            app_row = (
                app.name,
                'All',
                str(app.key()),
                app.global_id,
                app_stats.req,
                app_stats.imp,
                app_stats.imp,
                app_stats.clk,
                app_stats.clk,
                "N/A",
                app.app_type
            )
            app_data.append(app_row)

            # ... then make a row for each adunit with its summed stats
            for adunit in app.adunits:
                adunit_stats = stats.get_stats_sum(publisher=adunit,
                                                   num_days=self.date_range)

                row = (
                    app.name,
                    adunit.name,
                    str(adunit.key()),
                    app.global_id,
                    adunit_stats.req,
                    adunit_stats.imp,
                    adunit_stats.fill_rate,
                    adunit_stats.clk,
                    adunit_stats.ctr,
                    adunit.format,
                    app.app_type
                )
                app_data.append(row)

        # Put together the header list
        headers = (
            'App Name', 'Adunit Name', 'Pub ID', 'Resource ID',
            'Requests', 'Impressions', 'Fill Rate',
            'Clicks', 'CTR', 'Ad Size', 'Platform'
        )

        # Create the data to export from all of the rows
        data_to_export = tablib.Dataset(headers=headers)
        data_to_export.extend(app_data)

        response = HttpResponse(getattr(data_to_export, export_type),
                                mimetype="application/octet-stream")
        response['Content-Disposition'] = 'attachment; filename=%s.%s' %\
                   ("MoPub inventory", export_type)

        return response


@login_required
def inventory_exporter(request, *args, **kwargs):
    return InventoryExporter()(request, *args, **kwargs)


class AppExporter(RequestHandler):

    def get(self, app_key):

        app = AppQueryManager.get(app_key)
        if not app.account.key() == self.account.key():
            raise Http404

        export_type = self.request.GET.get('type', 'html')
        stats = StatsModelQueryManager(self.account)
        stats_per_day = stats.get_stats_for_days(publisher=app, num_days=self.date_range)
        app_data = []

        for day in stats_per_day:
            row = (
                str(day.date),
                day.req,
                day.imp,
                day.fill_rate,
                day.clk,
                day.ctr,
            )
            app_data.append(row)

        # Put together the header list
        headers = (
            'Date', 'Requests', 'Impressions',
            'Fill Rate', 'Clicks', 'CTR'
        )

        # Create the data to export from all of the rows
        data_to_export = tablib.Dataset(headers=headers)
        data_to_export.extend(app_data)

        response = HttpResponse(getattr(data_to_export, export_type),
                                mimetype="application/octet-stream")
        response['Content-Disposition'] = 'attachment; filename=%s.%s' %\
                   (app.name, export_type)

        return response



@login_required
def app_exporter(request, *args, **kwargs):
    return AppExporter()(request, *args, **kwargs)


class AdunitExporter(RequestHandler):

    def get(self, adunit_key):

        adunit = AdUnitQueryManager.get(adunit_key)
        if not adunit.account.key() == self.account.key():
            raise Http404

        export_type = self.request.GET.get('type', 'html')
        stats = StatsModelQueryManager(self.account)
        stats_per_day = stats.get_stats_for_days(publisher=adunit,
                                                 num_days=self.date_range)
        adunit_data = []

        for day in stats_per_day:
            row = (
                str(day.date),
                day.req,
                day.imp,
                day.fill_rate,
                day.clk,
                day.ctr,
            )
            adunit_data.append(row)

        # Put together the header list
        headers = (
            'Date', 'Requests', 'Impressions',
            'Fill Rate', 'Clicks', 'CTR'
        )

        # Create the data to export from all of the rows
        data_to_export = tablib.Dataset(headers=headers)
        data_to_export.extend(adunit_data)

        response = HttpResponse(getattr(data_to_export, export_type),
                                mimetype="application/octet-stream")
        response['Content-Disposition'] = 'attachment; filename=%s.%s' %\
                   (adunit.name, export_type)

        return response


@login_required
def adunit_exporter(request, *args, **kwargs):
    return AdunitExporter()(request, *args, **kwargs)


##################
# Helper methods #
##################

def enable_networks(adunit, account):
    """
    Create network adgroups for this adunit for all ad networks.
    """
    ntwk_adgroups = []
    creatives = []
    for campaign in CampaignQueryManager.get_network_campaigns(account,
            is_new=True):
        adgroup = AdGroupQueryManager.get_network_adgroup(campaign,
                adunit.key(), account.key())
        # New adunits are initialized as paused for the account's network
        # campaigns
        adgroup.active = False
        # Copy over global adgroup settings to new adgroup by copying them from
        # the pre-exitsting ones
        adgroups = AdGroupQueryManager.get_adgroups(campaign=campaign)
        # Accounts should have adunits prior to creating campaigns but just in
        # case don't break
        if adgroups:
            preexisting_adgroup = adgroups[0]
            # Copy over targeting for the NetworkDetails page

            adgroup.device_targeting = preexisting_adgroup.device_targeting
            adgroup.target_iphone = preexisting_adgroup.target_iphone
            adgroup.target_ipod = preexisting_adgroup.target_ipod
            adgroup.target_ipad = preexisting_adgroup.target_ipad
            adgroup.ios_version_min = preexisting_adgroup.ios_version_min
            adgroup.ios_version_max = preexisting_adgroup.ios_version_max
            adgroup.target_android = preexisting_adgroup.target_android
            adgroup.android_version_min = preexisting_adgroup.android_version_min
            adgroup.android_version_max = preexisting_adgroup.android_version_max
            adgroup.target_other = preexisting_adgroup.target_other

            adgroup.accept_targeted_locations = preexisting_adgroup.accept_targeted_locations
            adgroup.targeted_countries = preexisting_adgroup.targeted_countries
            adgroup.targeted_regions = preexisting_adgroup.targeted_regions
            adgroup.targeted_cities = preexisting_adgroup.targeted_cities
            adgroup.targeted_zip_codes = preexisting_adgroup.targeted_zip_codes

            adgroup.targeted_carriers = preexisting_adgroup.targeted_carriers

            adgroup.keywords = preexisting_adgroup.keywords

        creatives.append(adgroup.default_creative())
        ntwk_adgroups.append(adgroup)
    AdGroupQueryManager.put(ntwk_adgroups)
    CreativeQueryManager.put(creatives)


def enable_marketplace(adunit, account):
    """
    Gets/creates an adgroup and a default mpx creative for an adunit.
    Use this to enable marketplace on an adunit.
    """
    # create marketplace adgroup for this adunit
    mpx_adgroup = AdGroupQueryManager.get_marketplace_adgroup(adunit.key(), account.key())
    AdGroupQueryManager.put(mpx_adgroup)

    # create appropriate marketplace creative for this adunit / adgroup (same key_name)
    mpx_creative = mpx_adgroup.default_creative(key_name=mpx_adgroup.key().name())
    mpx_creative.adgroup = mpx_adgroup
    mpx_creative.account = account
    CreativeQueryManager.put(mpx_creative)


def add_demo_campaign(site):
    """
    Helper method that creates a demo campaign.
    Use this to create a default campaign when a user just signed up.
    """
    # Set up a test campaign that returns a demo ad
    demo_description = "Demo Order for checking that MoPub works for your application"
    c = Campaign(name="MoPub Demo Order",
                 u=site.account.user,
                 account=site.account,
                 campaign_type="order",
                 description=demo_description,
                 active=True)
    CampaignQueryManager.put(c)

    # Set up a test ad group for this campaign
    ag = AdGroup(name="MoPub Demo Line Item",
                 campaign=c,
                 adgroup_type="backfill_promo",
                 start_datetime=datetime.datetime.now(),
                 account=site.account,
                 priority_level=3,
                 bid=1.0,
                 bid_strategy="cpm",
                 site_keys=[site.key()])
    AdGroupQueryManager.put(ag)

    # And set up a default creative
    default_creative_html = """
    <style type="text/css">
    body {
      font-size: 12px;
      font-family: helvetica,arial,sans-serif;
      margin:0;
      padding:0;
      text-align:center;
      background:white
    }
    .creative_headline {
      font-size: 18px;
    }
    .creative_promo {
      color: green;
      text-decoration: none;
    }
    </style>
    <div class="creative_headline">
      Welcome to mopub!
    </div>
    <div class="creative_promo">
      <a href="http://www.mopub.com">
        Click here to test ad
      </a>
    </div>
    <div>
      You can now set up a new campaign to serve other ads.
    </div>
    """

    if site.format == "custom":
        h = HtmlCreative(ad_type="html",
                         ad_group=ag,
                         account=site.account,
                         custom_height = site.custom_height,
                         custom_width = site.custom_width,
                         format=site.format,
                         name="Demo HTML Creative",
                         html_data=default_creative_html)

    else:
        h = HtmlCreative(ad_type="html",
                         ad_group=ag,
                         account=site.account,
                         format=site.format,
                         name="Demo HTML Creative",
                         html_data=default_creative_html)
    CreativeQueryManager.put(h)


def create_iad_mapper(account, app):
    """
    Create AdNetworkAppMapper for iad if itunes url is input and iad
    AdNetworkLoginCredentials exist
    """
    if app.iad_pub_id:
        login = AdNetworkLoginManager.get_logins(account, network='iad').get()
        if login:
            mappers = AdNetworkMapperManager.get_mappers_for_app(login=login,
                    app=app)
            # Delete the existing mappers if there are no scrape stats for them.
            for mapper in mappers:
                if mapper:
                    stats = mapper.ad_network_stats
                    if not stats.count():
                        mapper.delete()
            AdNetworkMapperManager.create(network='iad',
                                          pub_id=app.iad_pub_id,
                                          login=login,
                                          app=app)


def calculate_ecpm(adgroup):
    """
    Calculate the ecpm for a cpc campaign.
    REFACTOR: move this to the app/adunit models
    """
    if adgroup.cpc and adgroup.stats.impression_count:
        return (float(adgroup.stats.click_count) * float(adgroup.bid) * 1000.0 /
                float(adgroup.stats.impression_count))
    return adgroup.bid


def filter_adgroups(adgroups, cfilter):
    filtered_adgroups = filter(lambda x: x.campaign.campaign_type in
            cfilter, adgroups)
    filtered_adgroups = sorted(filtered_adgroups, lambda x,y: cmp(y.bid, x.bid))
    return filtered_adgroups


def filter_campaigns(campaigns, cfilter):
    filtered_campaigns = filter(lambda x: x.campaign_type in
            cfilter, campaigns)
    filtered_campaigns = sorted(filtered_campaigns, lambda x,y: cmp(y.name,
        x.name))
    return filtered_campaigns
