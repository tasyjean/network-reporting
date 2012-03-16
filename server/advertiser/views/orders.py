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

from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.utils import simplejson

from common.utils.request_handler import RequestHandler
from common.ragendja.template import JSONResponse, render_to_response

from advertiser.forms import OrderForm, LineItemForm
from advertiser.query_managers import CampaignQueryManager, AdGroupQueryManager
from publisher.query_managers import AppQueryManager
from reporting.query_managers import StatsModelQueryManager
from reporting.models import StatsModel

import logging

ctr = lambda clicks, impressions: \
      (clicks/float(impressions) if impressions else 0)

class OrderIndexHandler(RequestHandler):
    """
    @responsible: pena
    Shows a list of orders and line items.
    Orders show:
      - name, status, advertiser, and a top-level stats rollup.
    Line Items show:
      - name, dates, budgeting information, top-level stats.
    """
    def get(self):


        orders = CampaignQueryManager.get_order_campaigns(account=self.account)

        # Stats for stats breakdown and graph.

        return {
            'orders': orders,
        }


@login_required
def order_index(request, *args, **kwargs):
    t = "advertiser/order_index.html"
    return OrderIndexHandler(template=t)(request, use_cache=False, *args, **kwargs)


class OrderDetailHandler(RequestHandler):
    """
    Top level stats rollup for all of the line items within the order.
    Lists each line item within the order with links to line item details.
    """
    def get(self, order_key):
        order = CampaignQueryManager.get(order_key)
        order_form = OrderForm(instance=order)
        
        stats_q = StatsModelQueryManager(self.account, self.offline)
        all_stats = stats_q.get_stats_for_days(advertiser=order,
                                                     days = self.days)
        return {
            'order': order,
            'order_form': order_form,
            'stats': format_stats(all_stats),
        }


@login_required
def order_detail(request, *args, **kwargs):
    t = "advertiser/order_detail.html"
    return OrderDetailHandler(template=t, id="order_key")(request, use_cache=False, *args, **kwargs)


class LineItemDetailHandler(RequestHandler):
    """
    Almost identical to current campaigns detail page.
    """
    def get(self, order_key, line_item_key):
        
        order = CampaignQueryManager.get(order_key)
        line_item = AdGroupQueryManager.get(line_item_key)
        stats_q = StatsModelQueryManager(self.account, self.offline)

        all_stats = stats_q.get_stats_for_days(advertiser=line_item,
                                                     days = self.days)
        
        line_item.stats = reduce(lambda x, y: x + y, all_stats, StatsModel())
        
        return {
            'order': order,
            'line_item': line_item,
            'stats': format_stats(all_stats),
        }


@login_required
def line_item_detail(request, *args, **kwargs):
    t = "advertiser/lineitem_detail.html"
    return LineItemDetailHandler(template=t)(request, use_cache=False, *args, **kwargs)


class OrderFormHandler(RequestHandler):
    """
    Edit order form handler which gets submitted from the order detail page.
    """
    def post(self, order_key):
        instance = CampaignQueryManager.get(order_key)
        order_form = OrderForm(self.request.POST, instance=instance)

        if order_form.is_valid():
            order = order_form.save()
            order.save()
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
    return OrderFormHandler()(request, use_cache=False, *args, **kwargs)


class OrderAndLineItemFormHandler(RequestHandler):
    """
    New/Edit form page for Orders and LineItems.
    """
    def get(self, order_key=None, line_item_key=None):
        if order_key:
            # TODO: make sure order belongs to account
            order = CampaignQueryManager.get(order_key)
            if line_item_key:
                # TODO: make sure line item belongs to account
                # TODO: make sure line item belongs to order
                line_item = AdGroupQueryManager.get(line_item_key)
            else:
                line_item = None
        else:
            order = None
            # TODO: make sure line_item_key is None
            line_item = None

        order_form = OrderForm(instance=order)
        line_item_form = LineItemForm(instance=line_item)

        apps = AppQueryManager.get_apps(account=self.account, alphabetize=True)

        return {
            'apps': apps,
            'order': order,
            'order_form': order_form,
            'line_item': line_item,
            'line_item_form': line_item_form,
        }

    def post(self, order_key=None, line_item_key=None):
        if order_key:
            # TODO: make sure order belongs to account
            order = CampaignQueryManager.get(order_key)
            if line_item_key:
                # TODO: make sure line item belongs to account
                # TODO: make sure line item belongs to order
                line_item = AdGroupQueryManager.get(line_item_key)
            else:
                line_item = None
        else:
            order = None
            # TODO: make sure line_item_key is None
            line_item = None

        if not order:
            order_form = OrderForm(self.request.POST, instance=order)

            if order_form.is_valid():
                order = order_form.save()
                order.account = self.account
                order.save()
                CampaignQueryManager.put(order)

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

        line_item_form = LineItemForm(self.request.POST, instance=line_item)

        if line_item_form.is_valid():
            line_item = line_item_form.save()
            line_item.account = self.account
            line_item.campaign = order
            line_item.save()
            AdGroupQueryManager.put(line_item)

            # TODO: go to order or line item detail page?
            return JSONResponse({
                'success': True,
                'redirect': reverse('advertiser_order_detail', args=(order.key(),)),
            })

        else:
            errors = {}
            for key, value in line_item_form.errors.items():
                errors[key] = ' '.join([error for error in value])

            return JSONResponse({
                'errors': errors,
                'success': False,
            })


@login_required
def order_and_line_item_form(request, *args, **kwargs):
    t = "advertiser/forms/order_and_line_item_form.html",
    return OrderAndLineItemFormHandler(template=t)(request, use_cache=False, *args, **kwargs)


###########
# Helpers #
###########

def format_stats(all_stats):
    summed = reduce(lambda x, y: x + y, all_stats, StatsModel())
    stats = {
        'requests': {
            'today': all_stats[0].request_count,
            'yesterday': all_stats[1].request_count,
            'total': summed.request_count,
            'series': [int(s.request_count) for s in all_stats]
        },
        'impressions': {
            'today': all_stats[0].impression_count,
            'yesterday': all_stats[1].impression_count,
            'total': summed.impression_count,
            'series': [int(s.impression_count) for s in all_stats]
        },
        'users': {
            'today': all_stats[0].user_count,
            'yesterday': all_stats[1].user_count,
            'total': summed.user_count,
            'series': [int(s.user_count) for s in all_stats]
        },
        'ctr': {
            'today': ctr(all_stats[0].click_count,
                         all_stats[0].impression_count),
            'yesterday': ctr(all_stats[1].click_count,
                             all_stats[1].impression_count),
            'total': ctr(summed.click_count, summed.impression_count),
        },
        'clicks': {
            'today': all_stats[0].click_count,
            'yesterday': all_stats[1].click_count,
            'total': summed.click_count,
            'series': [int(s.click_count) for s in all_stats]
        },
    }
    return stats