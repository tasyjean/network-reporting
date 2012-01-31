# -*- coding: utf-8 -*-
from django.conf.urls.defaults import *

urlpatterns = patterns('publisher.views',
  url(r'^adunit/create/$','adunit_create',name='publisher_adunit_create'),
  url(r'^adunit/(?P<adunit_key>[-\w\.]+)/delete/$','publisher_adunit_delete',name='publisher_adunit_delete'),
  url(r'^adunit/(?P<adunit_key>[-\w\.]+)/generate/$','generate',name='publisher_generate'),
  url(r'^adunit/update/ajax/$','adunit_update_ajax',name='publisher_adunit_update_ajax'),
  url(r'^adunit/(?P<adunit_key>[-\w\.]+)/$','adunit_show',name='publisher_adunit_show'),
  url(r'^app/create/$','app_create',name='publisher_app_create'),
  url(r'^app/(?P<app_key>[-\w\.]+)/delete/$','app_delete',name='publisher_app_delete'),
  url(r'^app/(?P<app_key>[-\w\.]+)/update/ajax/$','app_update_ajax',name='publisher_app_update_ajax'),
  url(r'^app/(?P<app_key>[-\w\.]+)/$','app_show',name='publisher_app_show'),
  url(r'^app/icon/(?P<app_key>[-\w\.]+)/$','app_icon',name='publisher_app_icon'),
  url(r'^geo$','index_geo',name='publisher_index_geo'),
  url(r'^$','index',name='publisher_index'),
  url( r'^export/(?P<f_type>xls|csv)/(?P<key_type>adunit|app|adgroup|account)/(?P<key>[-\w\.]+)/$', 'export_file', name='exporter' ),
  url(r'^app_export$', 'app_export', name='app_export'),
  url(r'^dashboard_export$', 'dashboard_export', name='dashboard_export'),
)

url(r'^show/(?P<campaign_key>[-\w\.]+)$','campaign_show',name='advertiser_campaign_show'),
