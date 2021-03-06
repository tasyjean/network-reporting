__doc__ = """
Views for orders and line items.

'Order' is an alias for 'Campaign', and 'LineItem' is an alias for
'AdGroup'.  We decided to make this change because many other
advertisers use this language.  The code hasn't adopted this naming
convention, and instead still uses "Campaign" and "AdGroup" for
compatibility with the ad server.

Whenever you see "Campaign", think "Order", and wherever you see
"AdGroup", think "LineItem".
"""

import datetime
import simplejson

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.http import HttpResponse, Http404
from google.appengine.ext import db

from common.ragendja.template import render_to_response, JSONResponse
from common.utils import helpers, tablib, stats_helpers, date_magic
from common.utils.request_handler import RequestHandler
from common.utils.string_utils import sanitize_string_for_export
from common.utils.timezones import Pacific_tzinfo
from common.utils.tzinfo import utc

from account.query_managers import AccountQueryManager

from advertiser.forms import (
    OrderForm, LineItemForm, NewCreativeForm,
    ImageCreativeForm, TextAndTileCreativeForm,
    HtmlCreativeForm
)
from advertiser.query_managers import (
    CampaignQueryManager,
    AdGroupQueryManager,
    CreativeQueryManager
)
from common.constants import (
    US_STATES, CA_PROVINCES, US_METROS, US_CARRIERS,
    GB_CARRIERS, CA_CARRIERS
)
from publisher.query_managers import (
    PublisherQueryManager, AppQueryManager,
    AdUnitQueryManager
)
from reporting.query_managers import StatsModelQueryManager
from budget.query_managers import BudgetQueryManager
import logging
from operator import attrgetter

flatten = lambda l: [item for sublist in l for item in sublist]


class OrderIndexHandler(RequestHandler):
    """
    Shows a list of orders and line items.
    Orders show:
      - name, status, advertiser, and a top-level stats rollup.
    Line Items show:
      - name, dates, budgeting information, top-level stats.
    """
    def get(self):
        orders = CampaignQueryManager.get_order_campaigns(account=self.account)
        line_items = AdGroupQueryManager.get_line_items(account=self.account,
                                                        orders=orders)

        # Filter out archived and deleted orders and line items
        orders = [order for order in orders if not (order.archived or order.deleted)]
        line_items = [line_item for line_item in line_items \
                      if not (line_item.archived or line_item.deleted) and
                      not (line_item.campaign.archived or line_item.campaign.deleted)]

        # Sort by multiple keys - case sensitive
        line_items = sorted(line_items, key=attrgetter('line_item_priority', 'name'))

        return {
            'orders': orders,
            'line_items': line_items
        }


@login_required
def order_index(request, *args, **kwargs):
    t = "advertiser/order_index.html"
    return OrderIndexHandler(template=t)(request,
                                         use_cache=False,
                                         *args, **kwargs)


class OrderArchiveHandler(RequestHandler):
    """
    Shows a list of archived orders and line items.
    """
    def get(self):

        orders = CampaignQueryManager.get_order_campaigns(account=self.account)
        line_items = AdGroupQueryManager.get_line_items(
            account=self.account,
            orders=orders,
            archived=True
        )

        archived_orders = [order for order in orders if order.archived]
        archived_line_items = [line_item for line_item in line_items \
                               if line_item.archived or line_item.campaign.archived]

        return {
            'orders': archived_orders,
            'line_items': archived_line_items
        }


@login_required
def order_archive(request, *args, **kwargs):
    t = "advertiser/order_archive.html"
    return OrderArchiveHandler(template=t)(request,
                                           use_cache=False,
                                           *args, **kwargs)


class OrderDetailHandler(RequestHandler):
    """
    Top level stats rollup for all of the line items within the order.
    Lists each line item within the order with links to line item details.
    """
    def get(self, order_key):

        # Grab the campaign info
        order = CampaignQueryManager.get(order_key)

        line_items = AdGroupQueryManager.get_line_items(
            account=self.account,
            order=order,
            archived=False
        )
        archived_line_items = AdGroupQueryManager.get_line_items(
            account=self.account,
            order=order,
            archived=True
        )
        line_items.extend(archived_line_items)

        if line_items:
            self.start_date = None
            self.end_date = None

            for line_item in line_items:
                if not self.start_date or (line_item.start_datetime if line_item.start_datetime else line_item.created).date() < self.start_date:
                    self.start_date = (line_item.start_datetime if line_item.start_datetime else line_item.created).date()

                if not line_item.end_datetime:
                    self.end_date = datetime.datetime.now(Pacific_tzinfo()).date()
                elif not self.end_date or line_item.end_datetime.date() > self.end_date:
                    self.end_date = line_item.end_datetime.date()

            self.date_range = (self.end_date - self.start_date).days + 1

        # Get the targeted adunits and group them by their app.
        targeted_adunits = set(flatten([AdUnitQueryManager.get(line_item.site_keys) \
                                    for line_item in order.adgroups]))
        targeted_apps = get_targeted_apps(targeted_adunits)

        # Set up the form
        order_form = OrderForm(instance=order)

        return {
            'order': order,
            'order_form': order_form,
            'line_items': line_items,
            'targeted_apps': targeted_apps.values(),
            'targeted_app_keys': targeted_apps.keys(),
            'targeted_adunits': targeted_adunits
        }


@login_required
def order_detail(request, *args, **kwargs):
    template = 'advertiser/order_detail.html'
    handler = OrderDetailHandler(template=template, id="order_key")
    return handler(request, use_cache=False, *args, **kwargs)


class LineItemDetailHandler(RequestHandler):
    """
    Almost identical to current campaigns detail page.
    """
    def get(self, line_item_key):

        line_item = AdGroupQueryManager.get(line_item_key)

        self.start_date = line_item.start_datetime.replace(tzinfo=utc).astimezone(Pacific_tzinfo()).date()
        if line_item.end_datetime:
            self.end_date = line_item.end_datetime.replace(tzinfo=utc).astimezone(Pacific_tzinfo()).date()
        else:
            self.end_date = datetime.datetime.now(Pacific_tzinfo()).date()

        self.date_range = (self.end_date - self.start_date).days + 1

        # Create creative forms
        creative_form = NewCreativeForm()

        # Get the targeted adunits and apps
        targeted_adunits = AdUnitQueryManager.get(line_item.site_keys)
        targeted_apps = get_targeted_apps(targeted_adunits)
        apps_without_global_id = get_targeted_apps_without_global_id(line_item)

        # We need all the other orders for the copy line item functionality
        orders = CampaignQueryManager.get_order_campaigns(account=self.account)

        return {
            'order': line_item.campaign,
            'orders': orders,
            'line_item': line_item,
            'creative_form': creative_form,
            'targeted_apps': targeted_apps.values(),
            'targeted_app_keys': targeted_apps.keys(),
            'targeted_adunits': targeted_adunits,
            'apps_without_global_id': apps_without_global_id,
        }


@login_required
def line_item_detail(request, *args, **kwargs):
    template = 'advertiser/line_item_detail.html'
    handler = LineItemDetailHandler(template=template, id='line_item_key')
    return handler(request, use_cache=False, *args, **kwargs)


class AdSourceStatusChangeHandler(RequestHandler):
    """
    Changes the status of a line item or list of line items.
    Author: John Pena
    """
    def post(self):
        # Pull out the params. `ad_sources` is a list of orders and/or
        # line items and/or creatives that we want to change the
        # status of. `status` is the status we want to change it to
        # (one of 'run', 'pause', 'archive', 'delete).
        ad_sources = self.request.POST.getlist('ad_sources[]')
        status = self.request.POST.get('status', None)

        # Both params are required.
        if ad_sources and status:
            for ad_source_key in ad_sources:
                # Get the ad source and keep track of which query manager we
                # used to fetch it. Keeping things DRY.
                try:
                    ad_source = CreativeQueryManager.get(ad_source_key)
                    manager_used = CreativeQueryManager
                except:
                    try:
                        ad_source = AdGroupQueryManager.get(ad_source_key)
                        manager_used = AdGroupQueryManager
                    except:
                        ad_source = CampaignQueryManager.get(ad_source_key)
                        manager_used = CampaignQueryManager

                # Update the status of the ad source. We make sure the
                # request user owns each source. Creatives don't get archived,
                # so we have to check for that in each case.
                updated = False
                if ad_source.account.key() == self.account.key():
                    if status == 'run' or status == 'play':
                        ad_source.active = True
                        ad_source.deleted = False
                        if manager_used != CreativeQueryManager:
                            ad_source.archived = False
                        updated = True
                    elif status == 'pause':
                        ad_source.active = False
                        ad_source.deleted = False
                        if manager_used != CreativeQueryManager:
                            ad_source.archived = False
                        updated = True
                    elif status == 'archive':
                        # NOTE: archiving a creative can't happen (because
                        # creatives don't archive), so if someone tries to archive
                        # a creative, it gets paused instead. Maybe this isn't
                        # the right thing to do.
                        ad_source.active = False
                        ad_source.deleted = False
                        if manager_used != CreativeQueryManager:
                            ad_source.archived = True
                        updated = True
                    elif status == 'delete':
                        ad_source.deleted = True
                        ad_source.archived = False
                        ad_source.active = False
                        updated = True

                    if updated:
                        manager_used.put(ad_source)

            return JSONResponse({
                'success': True,
            })

        else:
            return JSONResponse({
                'success': False,
                'errors': 'Bad Parameters'
            })


@login_required
def ad_source_status_change(request, *args, **kwargs):
    return AdSourceStatusChangeHandler()(request, use_cache=False,
                                         *args, **kwargs)


class OrderFormHandler(RequestHandler):
    """
    Edit order form handler which gets submitted from the order detail page.
    """
    def post(self, order_key):

        if not self.request.is_ajax():
            raise Http404

        instance = CampaignQueryManager.get(order_key)
        if not instance.is_order:
            raise Http404
        order_form = OrderForm(self.request.POST, instance=instance)

        if order_form.is_valid():
            order = order_form.save()
            order.save()
            CampaignQueryManager.put(order)
            # TODO: in js reload instead of looking for redirect
            return JSONResponse({
                'success': True,
            })

        else:
            # TODO: dict comprehension?
            errors = {}
            for key, value in order_form.errors.items():
                # TODO: just join value?
                errors[key] = ' '.join([error for error in value])

            return JSONResponse({
                'errors': errors,
                'success': False,
            })


@login_required
def order_form(request, *args, **kwargs):
    return OrderFormHandler(id="order_key")(request, use_cache=False, *args, **kwargs)


class OrderAndLineItemFormHandler(RequestHandler):
    """
    New/Edit form page for Orders and LineItems.
    """
    def get(self, order_key=None, line_item_key=None):

        if line_item_key:
            line_item = AdGroupQueryManager.get(line_item_key)
            order = line_item.campaign
        elif order_key:
            order = CampaignQueryManager.get(order_key)
            line_item = None
        else:
            order = None
            line_item = None

        if order and not order.is_order:
            raise Http404

        order_form = OrderForm(instance=order, prefix='order')
        line_item_form = LineItemForm(instance=line_item, apps_choices=get_apps_choices(self.account))

        apps = AppQueryManager.get_apps(account=self.account, alphabetize=True)
        apps_without_global_id = get_targeted_apps_without_global_id(line_item) if line_item else []

        return {
            'apps': apps,
            'order': order,
            'order_form': order_form,
            'line_item': line_item,
            'line_item_form': line_item_form,
            'apps_without_global_id': apps_without_global_id,
            'US_STATES': US_STATES,
            'CA_PROVINCES': CA_PROVINCES,
            'US_METROS': US_METROS,
            'US_CARRIERS': US_CARRIERS,
            'GB_CARRIERS': GB_CARRIERS,
            'CA_CARRIERS': CA_CARRIERS,
        }

    def post(self, order_key=None, line_item_key=None):
        if not self.request.is_ajax():
            raise Http404

        # If there's no POST body, then it's an erroneous request.
        if len(self.request.POST.keys()) == 0:
            raise Http404

        # Fetch the objects we're going to edit from their keys.
        # If both keys are None, we're making new objects.
        if line_item_key:
            line_item = AdGroupQueryManager.get(line_item_key)
            order = line_item.campaign
        elif order_key:
            order = CampaignQueryManager.get(order_key)
            line_item = None
        else:
            order = None
            line_item = None

        # Sanity checks. Make sure the order and line item are valid
        # and owned by the requester.
        if order:
            if (not order.is_order) or order.account.key() != self.account.key():
                raise Http404

        if line_item:
            if not line_item.account.key() == self.account.key():
                raise Http404

        order_form = OrderForm(self.request.POST, instance=order, prefix='order')

        # We grab the adunits available for targeting here, but we could probably
        # pass in the account and do it in the form.
        adunits = AdUnitQueryManager.get_adunits(account=self.account)
        site_keys = [(unicode(adunit.key()), '') for adunit in adunits]
        line_item_form = LineItemForm(self.request.POST,
                                      instance=line_item,
                                      site_keys=site_keys,
                                      apps_choices=get_apps_choices(self.account))

        # Shouldn't this be order_form.is_valid() if order else True ? why the 'not'?
        order_form_is_valid = order_form.is_valid() if not order else True
        line_item_form_is_valid = line_item_form.is_valid()

        if order_form_is_valid and line_item_form_is_valid:
            if not order:
                order = order_form.save()
                order.account = self.account
                order.campaign_type = 'order'
                order.save()
                CampaignQueryManager.put(order)

            line_item = line_item_form.save()
            line_item.account = self.account
            line_item.campaign = order
            line_item.save()
            AdGroupQueryManager.put(line_item)

            # Onboarding: user is done after they set up their first campaign
            if self.account.status == "step4":
                self.account.status = ""
                AccountQueryManager.put_accounts(self.account)

            return JSONResponse({
                'success': True,
                'redirect': reverse('advertiser_line_item_detail',
                                    kwargs={'line_item_key': line_item.key()}),
            })


        errors = {}
        if not line_item_form_is_valid:
            logging.warn('line')
            for key, value in line_item_form.errors.items():
                # TODO: find a less hacky way to get jQuery validator's
                # showErrors function to work with the SplitDateTimeWidget
                if key == 'start_datetime':
                    key = 'start_datetime_1'
                elif key == 'end_datetime':
                    key = 'end_datetime_1'
                # TODO: just join value?
                errors[key] = ' '.join([error for error in value])

        if not order_form_is_valid:
            # TODO: dict comprehension?
            for key, value in order_form.errors.items():
                # TODO: just join value?
                logging.warn(key)
                errors['order-' + key] = ' '.join([error for error in value])

        return JSONResponse({
            'errors': errors,
            'success': False,
        })


@login_required
def order_and_line_item_form_new_order(request, *args, **kwargs):
    handler = OrderAndLineItemFormHandler(template="advertiser/forms/order_and_line_item_form.html")
    return handler(request, use_cache=False, *args, **kwargs)


@login_required
def order_and_line_item_form_new_line_item(request, *args, **kwargs):
    handler = OrderAndLineItemFormHandler(id="order_key",
                                          template="advertiser/forms/order_and_line_item_form.html")
    return handler(request, use_cache=False, *args, **kwargs)


@login_required
def order_and_line_item_form_edit(request, *args, **kwargs):
    handler = OrderAndLineItemFormHandler(id="line_item_key",
                                          template="advertiser/forms/order_and_line_item_form.html")
    return handler(request, use_cache=False, *args, **kwargs)


class CreativeFormHandler(RequestHandler):
    """
    New/Edit form page for Creatives.
    """
    def post(self, line_item_key=None, creative_key=None):
        if creative_key:
            creative = CreativeQueryManager.get(creative_key)
            line_item = creative.ad_group
        else:
            creative = None
            line_item = AdGroupQueryManager.get(line_item_key)

        ad_type = creative.ad_type if creative else self.request.POST['ad_type']
        if ad_type == 'image':
            creative_form = ImageCreativeForm(self.request.POST,
                                              files=self.request.FILES,
                                              instance=creative)
        elif ad_type == 'text_icon':
            creative_form = TextAndTileCreativeForm(self.request.POST,
                                                    files=self.request.FILES,
                                                    instance=creative)
        elif ad_type == 'html':
            creative_form = HtmlCreativeForm(self.request.POST,
                                             instance=creative)
        else:
            raise Exception("Unsupported creative type %s." % ad_type)  # TODO: real exception type

        if creative_form.is_valid():
            creative = creative_form.save()
            creative.account = self.account
            creative.ad_group = line_item
            creative.save()
            CreativeQueryManager.put(creative)

            return JSONResponse({
                'success': True,
                'redirect': reverse('advertiser_line_item_detail',
                                    kwargs={'line_item_key': line_item.key()}),
            })

        else:
            errors = {}
            for key, value in creative_form.errors.items():
                # TODO: just join value?
                errors[key] = ' '.join([error for error in value])
            return JSONResponse({
                'errors': errors,
                'success': False,
            })


@login_required
def creative_form_new(request, *args, **kwargs):
    handler = CreativeFormHandler(id="line_item_key")
    return handler(request, use_cache=False, *args, **kwargs)


@login_required
def creative_form_edit(request, *args, **kwargs):
    handler = CreativeFormHandler(id="creative_key")
    return handler(request, use_cache=False, *args, **kwargs)


class DisplayCreativeHandler(RequestHandler):
    #asdf
    def get(self, creative_key):

        # Corner casing requests that are made for mraid.js.
        # This happens for MRAID creatives and can't be changed
        # because of the MRAID spec
        if creative_key == 'mraid.js':
            return HttpResponse("")

        try:
            creative = CreativeQueryManager.get(creative_key)
        except db.BadKeyError:
            raise Http404

        if creative and creative.account.key() == self.account.key():
            if creative.ad_type == "image":
                template = """<html><head>
                <style type="text/css">body{margin:0;padding:0;}</style>
                </head><body><img src="%s"/></body></html>"""
                url_for_blob = helpers.get_url_for_blob(creative.image_blob,
                                                        ssl=(not settings.DEBUG))
                return HttpResponse(template % url_for_blob)

            if creative.ad_type == "text_icon":
                creative.icon_url = helpers.get_url_for_blob(creative.image_blob,
                                                             ssl=(not settings.DEBUG))
                return render_to_response(self.request,
                                          'advertiser/text_tile.html',
                                          {'c': creative})

            if creative.ad_type == "html":
                html_data = creative.html_data or ''
                return HttpResponse("<html><body style='margin:0px;'>" + \
                                    html_data + "</body></html>")
        else:
            raise Http404


class CreativeImageHandler(RequestHandler):
    def get(self, creative_key):
        c = CreativeQueryManager.get(creative_key)
        if c and c.image:
            return HttpResponse(c.image, content_type='image/png')
        raise Http404


def creative_image(request, *args, **kwargs):
    return DisplayCreativeHandler()(request, *args, **kwargs)


def creative_html(request, *args, **kwargs):
    return DisplayCreativeHandler()(request, *args, **kwargs)


class CopyLineItemHandler(RequestHandler):

    def post(self):

        line_item_key = self.request.POST.get('line_item', None)
        order_key = self.request.POST.get('order', None)
        copy_creatives = self.request.POST.get('copy_creatives', None)

        if copy_creatives == 'true':
            copy_creatives = True

        if copy_creatives == 'false':
            copy_creatives = False

        if line_item_key:

            # Get the line item and copy it
            try:
                line_item = AdGroupQueryManager.get(line_item_key)
            except Exception, error:
                logging.warn(error)
                return JSONResponse({'error': 'Could not fetch line item.'})

            # If they've supplied an order key, we copy the line item
            # to that order. If not, we just copy it to the same order.
            if order_key:
                try:
                    order = CampaignQueryManager.get(order_key)
                except Exception, error:
                    logging.warn(error)
                    return JSONResponse({'error': 'Could not fetch order.'})
            else:
                order = line_item.campaign

            # Copy, rename and save the new line item
            copied_line_item = helpers.clone_entity(line_item,
                                                    name=line_item.name + " (Copy)",
                                                    campaign=order)
            AdGroupQueryManager.put(copied_line_item)

            # Copy all of the creatives if this was asked for
            if copy_creatives:
                for creative in line_item.creatives:
                    copied_creative = helpers.clone_entity(creative)
                    copied_creative.adgroup = copied_line_item
                    CreativeQueryManager.put(copied_creative)

            return JSONResponse({
                'success': 'Line item copied',
                'new_key': str(copied_line_item.key()),
                'url': reverse('advertiser_line_item_detail',
                               kwargs={'line_item_key':copied_line_item.key()})
            })
        else:
            raise Http404

def copy_line_item(request, *args, **kwargs):
    return CopyLineItemHandler()(request, *args, **kwargs)


#############
# Exporters #
#############

ctr = lambda clk, imp: float(clk)/float(imp)*100.0 if imp > 0 else 0

class MultipleOrderExporter(RequestHandler):

    def get(self):
        """
        Exports an account-level report on all orders.
        Used by the "Export" button in the order section
        of the index page.
        """

        # Get the export type, set up the headers for the export
        # document, and create the export document.
        export_type = self.request.GET.get('type', 'csv')
        headers = (
            'Order Name',
            'Advertiser',
            'Number of Line Items',
            'Impressions',
            'Clicks',
            'Conversions',
            'Revenue',
            'CTR',
            'Conv. Rate',
        )
        data_to_export = tablib.Dataset(headers=headers)

        # For each order, add a new row to the document
        stats_q = stats_helpers.DirectSoldStatsFetcher(self.account.key())
        orders = CampaignQueryManager.get_order_campaigns(account=self.account)
        for order in orders:
            stats = stats_q.get_campaign_stats(order,
                                               self.start_date,
                                               self.end_date,
                                               daily=False)['sum']

            order_data = (
                order.name,
                order.advertiser,
                len(AdGroupQueryManager.get_line_items(order=order, keys_only=True)),
                stats['imp'],
                stats['clk'],
                stats['conv'],
                stats['rev'],
                ctr(stats['clk'], stats['imp']),
                stats['conv_rate'],
            )
            data_to_export.extend([order_data])

        response = HttpResponse(getattr(data_to_export, export_type),
                                mimetype="application/octet-stream")
        response['Content-Disposition'] = 'attachment; filename=%s.%s' % (
            "MoPubOrders", export_type
        )

        return response

@login_required
def export_multiple_orders(request, *args, **kwargs):
    handler = MultipleOrderExporter()
    return handler(request, *args, **kwargs)


class MultipleLineItemExporter(RequestHandler):

    def get(self):
        """
        Exports an account-level report on all line items.
        Used by the "Export" button in the line item section
        of the index page.
        """
        export_type = self.request.GET.get('type', 'csv')
        headers = (
            'Order name',
            'Line Item name',
            'Advertiser',
            'Type',
            'Start Time',
            'Stop Time',
            'Rate (CPM/CPC)',
            'Budget',
            'Impressions',
            'Clicks',
            'Conversions',
            'Revenue',
            'CTR',
            'Conv. Rate',
            'Allocation',
            'Frequency Caps',
            'Country Target',
            'Device Target',
            'Keywords',
        )
        data_to_export = tablib.Dataset(headers=headers)


        stats_q = stats_helpers.DirectSoldStatsFetcher(self.account.key())
        orders = CampaignQueryManager.get_order_campaigns(account=self.account)
        for order in orders:
            line_items = AdGroupQueryManager.get_line_items(order=order)
            for line_item in line_items:
                stats = stats_q.get_adgroup_stats(
                    line_item,
                    self.start_date,
                    self.end_date,
                    daily=False
                )
                stats = stats['sum']
                
                order_data = (
                    order.name,
                    line_item.name,
                    order.advertiser,
                    line_item.adgroup_type_display,
                    str(line_item.start_datetime),
                    str(line_item.end_datetime),
                    line_item.bid,
                    str(line_item.budget_goal), #cast to string in case its None
                    stats['imp'],
                    stats['clk'],
                    stats['conv'],
                    stats['rev'],
                    ctr(stats['clk'],stats['imp']),
                    stats['conv_rate'],
                    str(line_item.allocation_percentage),
                    str(line_item.frequency_cap_display),
                    str([c for c in line_item.targeted_countries]),
                    str(line_item.device_targeting_display),
                    str(line_item.keywords),
                )
                data_to_export.extend([order_data])

        response = HttpResponse(
            getattr(data_to_export, export_type),
            mimetype="application/octet-stream"
        )
        response['Content-Disposition'] = 'attachment; filename=%s.%s' % (
            "MoPubLineItems", export_type
        )

        return response


@login_required
def export_multiple_line_items(request, *args, **kwargs):
    handler = MultipleLineItemExporter()
    return handler(request, *args, **kwargs)


class SingleOrderExporter(RequestHandler):

    def get(self, order_key):

        order = CampaignQueryManager.get(order_key)
        if not order.account.key() == self.account.key():
            raise Http404

        export_type = self.request.GET.get('type', 'csv')
        stats_q = StatsModelQueryManager(self.account)
        export_rows = []

        for line_item in order.adgroups:
            for creative in line_item.creatives:
                active_dates = date_magic.gen_days(
                    line_item.start_datetime,
                    line_item.end_datetime
                )
                stats_per_day = stats_q.get_stats_for_days(
                    advertiser=creative,
                    days=active_dates
                )

                for day in stats_per_day:
                    row = (
                        order.name,
                        line_item.name,
                        order.advertiser,
                        line_item.adgroup_type_display,
                        str(line_item.start_datetime),
                        str(line_item.end_datetime),
                        str(day.date),
                        creative.name,
                        creative.format,
                        creative.ad_type,
                        line_item.bid_strategy,
                        line_item.bid,
                        day.imp,
                        day.clk,
                        day.conv,
                        day.rev,
                        day.ctr,
                        day.conv_rate,
                        str(line_item.frequency_cap_display),
                        str([c for c in line_item.targeted_countries]),
                        str(line_item.device_targeting_display),
                        str(line_item.keywords)
                    )
                    export_rows.append(row)

        headers = (
            'Order name',
            'Line Item name',
            'Advertiser',
            'Type',
            'Start Time',
            'Stop Time',
            'Date',
            'Creative Name',
            'Creative Format',
            'Creative Type',
            'Rate',
            'Budget',
            'Impressions',
            'Clicks',
            'Conversions',
            'Revenue',
            'CTR',
            'Conv. Rate',
            'Frequency Caps',
            'Country Target',
            'Device Target',
            'Keywords',
        )

        data_to_export = tablib.Dataset(headers=headers)
        data_to_export.extend(export_rows)

        response = HttpResponse(
            getattr(data_to_export, export_type),
            mimetype="application/octet-stream"
        )
        response['Content-Disposition'] = 'attachment; filename=%s.%s' % (
            sanitize_string_for_export(order.name), export_type
        )

        return response


@login_required
def export_single_order(request, *args, **kwargs):
    handler = SingleOrderExporter()
    return handler(request, *args, **kwargs)


class SingleLineItemExporter(RequestHandler):

    def get(self, line_item_key):

        line_item = AdGroupQueryManager.get(line_item_key)
        if not line_item.account.key() == self.account.key():
            raise Http404

        order = line_item.campaign

        export_type = self.request.GET.get('type', 'csv')
        stats_q = StatsModelQueryManager(self.account)
        export_rows = []

        for creative in line_item.creatives:
            active_dates = date_magic.gen_days(
                line_item.start_datetime,
                line_item.end_datetime
            )
            stats_per_day = stats_q.get_stats_for_days(
                advertiser=creative,
                days=active_dates
            )

            for day in stats_per_day:
                row = (
                    order.name,
                    line_item.name,
                    order.advertiser,
                    line_item.adgroup_type_display,
                    str(line_item.start_datetime),
                    str(line_item.end_datetime),
                    str(day.date),
                    creative.name,
                    creative.format,
                    creative.ad_type,
                    line_item.bid_strategy,
                    line_item.bid,
                    day.imp,
                    day.clk,
                    day.conv,
                    day.rev,
                    day.ctr,
                    day.conv_rate,
                    str(line_item.frequency_cap_display),
                    str([c for c in line_item.targeted_countries]),
                    str(line_item.device_targeting_display),
                    str(line_item.keywords)
                )
                export_rows.append(row)

        headers = (
            'Order name',
            'Line Item name',
            'Advertiser',
            'Type',
            'Start Time',
            'Stop Time',
            'Date',
            'Creative Name',
            'Creative Format',
            'Creative Type',
            'Rate',
            'Budget',
            'Impressions',
            'Clicks',
            'Conversions',
            'Revenue',
            'CTR',
            'Conv. Rate',
            'Frequency Caps',
            'Country Target',
            'Device Target',
            'Keywords',
        )

        data_to_export = tablib.Dataset(headers=headers)
        data_to_export.extend(export_rows)

        response = HttpResponse(getattr(data_to_export, export_type),
                                mimetype="application/octet-stream")
        response['Content-Disposition'] = 'attachment; filename=%s.%s' % (
            sanitize_string_for_export(line_item.name), export_type
        )
        return response

@login_required
def export_single_line_item(request, *args, **kwargs):
    handler = SingleLineItemExporter()
    return handler(request, *args, **kwargs)


class AdServerTestHandler(RequestHandler):
    def get(self):
        devices = [('iphone', 'iPhone'),
                   ('ipad', 'iPad'),
                   ('nexus_s', 'Nexus S')]
        device_to_user_agent = {
            'iphone': 'Mozilla/5.0 (iPhone; U; CPU iPhone OS 4_0 like Mac OS X; %s) AppleWebKit/532.9 (KHTML, like Gecko) Version/4.0.5 Mobile/8A293 Safari/6531.22.7',
            'ipad': 'Mozilla/5.0 (iPad; U; CPU OS 3_2 like Mac OS X; %s) AppleWebKit/531.21.10 (KHTML, like Gecko) Version/4.0.4 Mobile/7B334b Safari/531.21.10',
            'nexus_s': 'Mozilla/5.0 (Linux; U; Android 2.1; %s) AppleWebKit/522+ (KHTML, like Gecko) Safari/419.3',
            'chrome': 'Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US) AppleWebKit/525.13 (KHTML, like Gecko) Chrome/0.A.B.C Safari/525.13',
        }

        country_to_locale_ip = {
            'US': ('en-US', '204.28.127.10'),
            'FR': ('fr-FR', '96.20.81.147'),
            'HR': ('hr-HR', '93.138.74.115'),
            'DE': ('de-DE', '212.183.113.32'),
            'DA': ('dk-DA', '62.107.177.124'),
            'FI': ('fi-FI', '91.152.79.118'),
            'JA': ('jp-JA', '110.163.227.87'),
            'HD': ('us-HD', '59.181.77.74'),
            'HE': ('il-HE', '99.8.113.207'),
            'RU': ('ru-RU', '83.149.3.32'),
            'NL': ('nl-NL', '77.251.143.68'),
            'PT': ('br-PT', '189.104.89.115'),
            'NB': ('no-NB', '88.89.244.197'),
            'TR': ('tr-TR', '78.180.93.4'),
            'NE': ('go-NE', '0.1.0.2'),
            'TH': ('th-TH', '24.52.71.42'),
            'RO': ('ro-RO', '85.186.180.111'),
            'IS': ('is-IS', '194.144.110.171'),
            'PL': ('pl-PL', '193.34.3.100'),
            'EL': ('gr-EL', '62.38.244.73'),
            'EN': ('us-EN', '174.255.120.125'),
            'ZH': ('tw-ZH', '124.190.51.251'),
            'MS': ('my-MS', '120.141.166.6'),
            'CA': ('es-CA', '95.17.76.100'),
            'IT': ('it-IT', '151.56.174.44'),
            'AR': ('sa-AR', '188.55.13.170'),
            'IN': ('id-IN', '114.57.226.18'),
            'CS': ('cz-CS', '90.180.148.68'),
            'HU': ('hu-HU', '85.66.221.12'),
            'ID': ('id-ID', '180.214.232.8'),
            'ES': ('ec-ES', '190.10.214.187'),
            'KO': ('kr-KO', '112.170.242.147'),
            'SV': ('se-SV', '90.225.96.11'),
            'SK': ('sk-SK', '213.151.218.130'),
            'UK': ('ua-UK', '92.244.103.199'),
            'SL': ('si-SL', '93.103.136.7'),
            'AU': ('en-AU', '114.30.96.10'),
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
def adserver_test(request, *args, **kwargs):
    return AdServerTestHandler()(request, *args, **kwargs)


class AdminPushBudget(RequestHandler):
    def get(self):

        adgroup_key = self.request.GET.get('adgroup_key', None)

        if not adgroup_key:
            logging.error("user " +
                          str(self.request.account.key()) +
                          "tried to access line item push budget for line item " +
                          adgroup_key)
            raise Http404

        logging.warn('pushing budget for ' + adgroup_key)

        testing = bool(self.request.GET.get('testing', False))
        staging = bool(int(self.request.GET.get('staging', 0)))
        total_spent = float(self.request.GET.get('total_spent', 0.0))



        adgroup = AdGroupQueryManager.get(adgroup_key)
        put_result = BudgetQueryManager.update_or_create_budget_for_adgroup(
            adgroup,
            total_spent = total_spent,
            testing = testing,
            staging = staging
        )

        if put_result:
            if staging:
                message = "Successfully updated budget on staging"
            else:
                message = "Successfully updated budget in production"
        else:
            message = "Unsuccessful in updating budget"

        return JSONResponse({
            'status': message
        })


@login_required
def push_budget(request, *args, **kwargs):
    if not request.user.is_staff:
        raise Http404

    return AdminPushBudget()(request, *args, **kwargs)



###########
# Helpers #
###########

def get_targeted_apps(adunits):
    # Database I/O could be made faster here by getting a list of
    # app keys and querying for the list, rather than querying
    # for each individual app. (au.app makes a query)
    targeted_apps = {}
    for adunit in adunits:
        app_key = str(adunit.app.key())
        app = targeted_apps.get(app_key)
        if not app:
            app = adunit.app
            app.adunits = []
            targeted_apps[app_key] = app
        targeted_apps[app_key].adunits += [adunit]
    return targeted_apps

def get_apps_choices(account):
    apps = PublisherQueryManager.get_apps_dict_for_account(account).values()
    apps = [app for app in apps if app.app_type != 'mweb']
    apps.sort(key=lambda app: app.name.lower())
    return [(str(app.key()), "%s (%s)" % (app.name, app.type)) for app in apps]


def get_targeted_apps_without_global_id(adgroup):
    app_keys = list(adgroup.included_apps) + list(adgroup.excluded_apps)
    apps_without_global_id = []
    for app_key in app_keys:
        app = AppQueryManager.get_app_by_key(app_key)
        if not app.global_id:
            apps_without_global_id.append(app)
    return apps_without_global_id
