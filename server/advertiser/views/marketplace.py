import logging
from urllib2 import urlopen

from django.utils import simplejson
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse

from account.models import NetworkConfig
from account.query_managers import AccountQueryManager
from advertiser.query_managers import CampaignQueryManager, AdGroupQueryManager
from common.ragendja.template import render_to_response, JSONResponse
from common.utils.request_handler import RequestHandler
from publisher.query_managers import PublisherQueryManager
from reporting.query_managers import StatsModelQueryManager

from common.utils import tablib
from common.utils.string_utils import sanitize
from common.constants import (
    IAB_CATEGORIES, IAB_ATTRIBUTES,
    IAB_CATEGORY_VALUES, IAB_ATTRIBUTE_VALUES,
)


class MarketplaceIndexHandler(RequestHandler):
    """
    Rendering of the Marketplace page. At this point, this is the only
    Marketplace page, and everything is rendered here.
    """
    def get(self):

        # Marketplace settings are kept as a single campaign.  Only
        # one should exist per account.
        marketplace_campaign = CampaignQueryManager.get_marketplace(
            self.account, from_db=True)

        apps_dict = PublisherQueryManager.get_objects_dict_for_account(
            self.account)
        alphabetically_sorted_apps = sorted(apps_dict.values(), lambda x, y:
                                            cmp(x.name, y.name))
        app_keys_json = simplejson.dumps(apps_dict.keys())

        adunit_keys = []
        for app_key, app in apps_dict.iteritems():
            if app.adunits is not None:
                adunit_keys += [adunit.key() for adunit in app.adunits]

        # Set up the blocklist
        blocklist = []
        category_blocklist = set()
        attribute_blocklist = set()
        network_config = self.account.network_config
        if network_config:
            blocklist = [str(sanitize(domain)) for domain in network_config.blocklist \
                         if not str(sanitize(domain)) in ("", "#")]
            category_blocklist = set(network_config.category_blocklist)
            attribute_blocklist = set(network_config.attribute_blocklist)

        try:
            blind = self.account.network_config.blind
        except AttributeError:
            blind = False

        return {
            'marketplace': marketplace_campaign,
            'apps': alphabetically_sorted_apps,
            'app_keys': app_keys_json,
            'adunit_keys': adunit_keys,
            'pub_key': self.account.key(),
            'blocklist': blocklist,
            'blind': blind,
            'network_config': network_config,
            'category_blocklist': category_blocklist,
            'IAB_CATEGORIES': IAB_CATEGORIES,
            'attribute_blocklist': attribute_blocklist,
            'IAB_ATTRIBUTES': IAB_ATTRIBUTES,
        }


@login_required
def marketplace_index(request, *args, **kwargs):
    t = "advertiser/marketplace_index.html"
    return MarketplaceIndexHandler(template=t)(request, use_cache=False,
                                               *args, **kwargs)


class BlocklistHandler(RequestHandler):
    """
    Ajax handler for adding/removing marketplace blocklist items.
    Required data parameters:
    - blocklist: a comma/whitespace separated list of urls to add/remove
    - action: 'add' or 'remove', the action to take
    """
    def post(self):
        try:
            # Get the blocklist urls and the action
            blocklist_urls = self.request.POST.get('blocklist')
            # Split on whitespace and commas
            blocklist = blocklist_urls.replace(',', ' ').split()
            blocklist_action = self.request.POST.get('action')

            # Set the network config
            network_config = self.account.network_config

            # Process add's (sometimes they're in bulk)
            if blocklist_action == "add" and blocklist:
                new = [d for d in blocklist if not d in
                        network_config.blocklist]
                network_config.blocklist.extend(blocklist)
                # Removes duplicates and sorts
                network_config.blocklist = sorted(set(network_config.blocklist))
                AccountQueryManager.update_config_and_put(account=
                        self.account, network_config=network_config)

                return JSONResponse({'success': 'blocklist item(s) added',
                                     'new': new})

            # Process removes (there should only be one at a time, but we could
            # change functionality on the client side to remove multiple urls
            # at once
            elif blocklist_action == "remove" and blocklist:
                for url in blocklist:
                    if network_config.blocklist.count(url):
                        network_config.blocklist.remove(url)
                AccountQueryManager.update_config_and_put(account=
                        self.account, network_config=network_config)
                return JSONResponse({'success': 'blocklist item(s) removed'})

            # If they didn't pass the action, it's an error.
            else:
                return JSONResponse({'error': 'you must provide an action ' \
                        '(add|remove) and a blockist'})

        except Exception, e:
            logging.warn(e)
            return JSONResponse({'error': 'server error'})


@login_required
def marketplace_blocklist_change(request, *args, **kwargs):
    return BlocklistHandler()(request, *args, **kwargs)


class ContentFilterHandler(RequestHandler):
    """
    Ajax handler for changing the marketplace content filter settings.
    """
    def post(self):
        network_config = self.account.network_config
        filter_level = self.request.POST.get('filter_level', None)

        # If the account doesn't have a network config, make one
        if not network_config:
            network_config = NetworkConfig(account=self.account)
            AccountQueryManager.update_config_and_put(self.account, network_config)

        # Set the filter level if it was passed
        if filter_level:
            if filter_level == "none":
                network_config.set_no_filter()
            elif filter_level == "low":
                network_config.set_low_filter()
            elif filter_level == "moderate":
                network_config.set_moderate_filter()
            elif filter_level == "strict":
                network_config.set_strict_filter()
            elif filter_level == "custom":
                categories = self.request.POST.getlist('categories[]')
                attributes = self.request.POST.getlist('attributes[]')
                attributes = [int(attribute) for attribute in attributes]

                for category in categories:
                    if category not in IAB_CATEGORY_VALUES:
                        return JSONResponse({
                            'error': 'Invalid category selected'
                        })
                                
                for attribute in attributes:
                    if attribute not in IAB_ATTRIBUTE_VALUES:
                        return JSONResponse({
                            'error': 'Invalid creative attribute selected'
                        })

                network_config.set_custom_filter(categories, attributes)
                
            else:
                return JSONResponse({'error': 'Invalid filter level'})
        else:
            return JSONResponse({'error': 'No filter level specified (choose ' \
                    'one of [none, low, moderate, strict]'})

        return JSONResponse({'success': 'success'})


@login_required
def marketplace_content_filter(request, *args, **kwargs):
    return ContentFilterHandler()(request, *args, **kwargs)


class MarketplaceOnOffHandler(RequestHandler):
    """
    Ajax handler for activating/deactivating the marketplace.
    Required data parameters:
    - activate: 'true' or 'false', to set the marketplace on or off.
    """
    def post(self):
        try:
            activate = self.request.POST.get('activate', 'true')
            mpx = CampaignQueryManager.get_marketplace(self.account,
                                                       from_db=True)
            if activate == 'true':
                mpx.active = True
            elif activate == 'false':
                mpx.active = False

            CampaignQueryManager.put(mpx)
            return JSONResponse({'success': 'success'})
        except Exception, e:
            raise
            logging.error(e)
            return JSONResponse({'error': e})


@login_required
def marketplace_on_off(request, *args, **kwargs):
    return MarketplaceOnOffHandler()(request, *args, **kwargs)


class MarketplaceBlindnessChangeHandler(RequestHandler):
    """
    Ajax handler for activating/deactivating blindness
    """
    def post(self):
        try:
            network_config = self.account.network_config

            # Some accounts won't have a network config yet
            # REFACTOR: override getattr for Account to create a network
            # config if one doesn't exist?
            if network_config == None:
                n = NetworkConfig(account=self.account).put()
                self.account.network_config = n
                self.account.put()
                network_config = n

            activate = self.request.POST.get('activate', None)
            if activate == 'true':
                network_config.blind = True
                network_config.put()
                return JSONResponse({'success': 'activated'})
            elif activate == 'false':
                network_config.blind = False
                network_config.put()
                return JSONResponse({'success': 'deactivated'})
            else:
                return JSONResponse({'error': 'Invalid activation value'})
            return JSONResponse({'success': str(self.request.POST)})
        except Exception, e:
            return JSONResponse({'error': e})


@login_required
def marketplace_blindness_change(request, *args, **kwargs):
    return MarketplaceBlindnessChangeHandler()(request, *args, **kwargs)


class MarketplaceCreativeProxyHandler(RequestHandler):
    """
    Ajax hander that proxies requests for creative data from mongo.
    This is done so that we can use SSL (users will get https errors
    when we hit mongo directly over http).
    """
    def get(self):
        url = "http://mpx.mopub.com/stats/creatives"
        query = "?" + "&".join([key + '=' + value for key, value in
            self.request.GET.items()])
        url += query
        response = urlopen(url).read()

        return HttpResponse(response)


@login_required
def marketplace_creative_proxy(request, *args, **kwargs):
    return MarketplaceCreativeProxyHandler()(request, *args, **kwargs)


class MarketplaceExportHandler(RequestHandler):
    def get(self):

        marketplace_campaign = CampaignQueryManager.get_marketplace(
            self.account, from_db=True)
        apps_dict = PublisherQueryManager.get_objects_dict_for_account(self.account)
        export_type = self.request.GET.get('type', 'html')
        stats = StatsModelQueryManager(self.account)
        export_data = []

        for app in apps_dict.values():
            app_stats = stats.get_stats_sum(publisher=app,
                                            advertiser=marketplace_campaign,
                                            num_days=self.date_range)
            app_row = (
                app.name,
                str(app.key()),
                app_stats.rev,
                app_stats.imp,
                app_stats.cpm,
                "N/A",
                "N/A",
            )
            export_data.append(app_row)

            for adunit in app.adunits:
                marketplace_adgroup = AdGroupQueryManager.get_marketplace_adgroup(str(adunit.key()),
                                                                                  str(self.account.key()),
                                                                                  get_from_db=True)
                logging.warn(marketplace_adgroup)
                adunit_stats = stats.get_stats_sum(publisher=adunit,
                                                   advertiser=marketplace_campaign,
                                                   num_days=self.date_range)
                adunit_row = (
                    adunit.name,
                    str(adunit.key()),
                    adunit_stats.rev,
                    adunit_stats.imp,
                    adunit_stats.cpm,
                    marketplace_adgroup.mktplace_price_floor if marketplace_adgroup else 'Not activated',
                    'Activated' if marketplace_adgroup and marketplace_adgroup.active else 'Not activated',
                )
                export_data.append(adunit_row)


        # Put together the header list
        headers = (
            'Name',
            'Pub ID',
            'Revenue',
            'Impressions',
            'eCPM',
            'Minimum Acceptable CPM',
            'RTB Enabled'
        )

        # Create the data to export from all of the rows
        data_to_export = tablib.Dataset(headers=headers)
        data_to_export.extend(export_data)

        response = HttpResponse(getattr(data_to_export, export_type),
                                mimetype="application/octet-stream")
        response['Content-Disposition'] = 'attachment; filename=%s.%s' %\
                   ("MoPub marketplace", export_type)

        return response


@login_required
def marketplace_export(request, *args, **kwargs):
    return MarketplaceExportHandler()(request, *args, **kwargs)


# REFACTOR: Do we still need this?
class MPXInfoHandler(RequestHandler):
    def get(self):
        return render_to_response(self.request,
                                  "advertiser/mpx_splash.html",
                                  {})


@login_required
def mpx_info(request, *args, **kwargs):
    return MPXInfoHandler()(request, *args, **kwargs)
