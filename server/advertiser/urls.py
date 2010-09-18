# -*- coding: utf-8 -*-
from django.conf.urls.defaults import *

urlpatterns = patterns('advertiser.views',
  url(r'^create$','campaign_create',name='advertiser_campaign_create'),
  url(r'^edit$','campaign_edit',name='advertiser_campaign_edit'),
  url(r'^delete$','campaign_delete',name='advertiser_campaign_delete'),
  url(r'^pause$','campaign_pause',name='advertiser_campaign_pause'),
  url(r'^show/(?P<campaign_key>[-\w\.]+)$','campaign_show',name='advertiser_campaign_show'),
  url(r'^creative/create$','creative_create',name='advertiser_creative_create'),
  url(r'^creative/delete$','creative_delete',name='advertiser_creative_delete'),
  url(r'^creative/image/(?P<creative_key>[-\w\.]+)$','creative_image',name='advertiser_creative_image'),
  url(r'^bid/create$','bid_create',name='advertiser_bid_create'),
  url(r'^bid/delete$','bid_delete',name='advertiser_bid_delete'),
  url(r'^bid/pause$','bid_pause',name='advertiser_bid_pause'),
  url(r'^adgroup/edit$','campaign_adgroup_edit',name='advertiser_adgroup_edit'),  
  url(r'^adgroup/(?P<adgroup_key>[-\w\.]+)$','campaign_adgroup_show',name='advertiser_adgroup_show'),  
  url(r'^$','index',name='advertiser_campaign'),
)
