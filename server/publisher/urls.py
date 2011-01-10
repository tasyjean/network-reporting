# -*- coding: utf-8 -*-
from django.conf.urls.defaults import *

urlpatterns = patterns('publisher.views',
  url(r'^adunit/create/$','adunit_create',name='publisher_adunit_create'),
  url(r'^adunit/delete/$','adunit_delete',name='publisher_delete'),
  url(r'^adunit/(?P<adunit_key>[-\w\.]+)/generate/$','generate',name='publisher_generate'),
  url(r'^adunit/(?P<adunit_key>[-\w\.]+)/update/$','adunit_update',name='publisher_adunit_update'),
  url(r'^adunit/(?P<adunit_key>[-\w\.]+)/$','adunit_show',name='publisher_adunit_show'),
  url(r'^app/create/$','app_create',name='publisher_app_create'),
  # url(r'^app/delete/$','app_create',name='publisher_app_create'),
  url(r'^app/(?P<app_key>[-\w\.]+)/update/$','app_update',name='publisher_app_update'),
  url(r'^app/(?P<app_key>[-\w\.]+)/$','app_show',name='publisher_app_show'),
  url(r'^getartwork/$','getartwork',name='publisher_getartwork'),
  url(r'^getstarted/$','getstarted',name='publisher_getstarted'),
  url(r'^geo$','index_geo',name='publisher_index_geo'),
  url(r'^$','index',name='publisher_index'),
)

url(r'^show/(?P<campaign_key>[-\w\.]+)$','campaign_show',name='advertiser_campaign_show'),
