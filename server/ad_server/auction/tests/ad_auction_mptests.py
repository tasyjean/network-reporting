########## Set up Django ###########
import sys
import os
import datetime

sys.path.append(os.environ['PWD'])
import common.utils.test.setup

from account.models import Account

from publisher.models import App
from publisher.models import Site as AdUnit

from advertiser.models import ( Campaign,
                                AdGroup,
                                Creative,
                                )
from google.appengine.ext.webapp import ( Request,
                                          Response,
                                          )
                                          
from server.ad_server.main import  ( AdClickHandler,
                                     AppOpenHandler,
                                     TestHandler,
                                     )
from server.ad_server.handlers import adhandler
from server.ad_server.handlers.adhandler import AdHandler                                     
from server.ad_server.auction.ad_auction import AdAuction

from publisher.query_managers import AdUnitQueryManager, AdUnitContextQueryManager
############# Integration Tests #############
import unittest
from nose.tools import eq_
from nose.tools import with_setup
from budget import budget_service
from google.appengine.api import memcache
from budget import models as budgetmodels
from budget.models import (BudgetSlicer,
                           BudgetSliceLog,
                           BudgetDailyLog,
                           )

from google.appengine.ext import testbed
################# End to End #################

from common.utils.system_test_framework import run_auction, fake_request



""" This module is where all of our system and end-to-end tests can live. """


class TestAdAuction(unittest.TestCase):
    """
    Using the web UI, we have created an ad_unit with the only two 
    competitors being a cheap campaign ($10/ad) and an expensive
    campaign ($100/ad)
    """

    def setUp(self):
        
    
        # First, create an instance of the Testbed class.
        self.testbed = testbed.Testbed()
        # Then activate the testbed, which prepares the service stubs for use.
        self.testbed.activate()
        # Next, declare which service stubs you want to use.
        self.testbed.init_datastore_v3_stub()
        self.testbed.init_memcache_stub()


        # We simplify the budgetmanger for testing purposes
        budgetmodels.DEFAULT_TIMESLICES = 10 # this means each campaign has 100 dollars per slice
        budgetmodels.DEFAULT_FUDGE_FACTOR = 0.0

        # Set up default models
        self.account = Account()
        self.account.put()

        self.app = App(account=self.account, name="Test App")
        self.app.put()

        self.adunit = AdUnit(account=self.account, 
                                     app_key=self.app, 
                                     name="Test AdUnit",
                                     format=u'320x50')
        self.adunit.put()

        # Make Expensive Campaign
        self.expensive_c = Campaign(name="expensive",
                                    budget=1000.0,
                                    budget_strategy="evenly")
        self.expensive_c.put()

        self.expensive_adgroup = AdGroup(account=self.account, 
                                          name="expensive",
                                          campaign=self.expensive_c, 
                                          site_keys=[self.adunit.key()],
                                          bid_strategy="cpm",
                                          bid=100000.0) # 100 per click
        self.expensive_adgroup.put()



        self.expensive_creative = Creative(account=self.account,
                                ad_group=self.expensive_adgroup,
                                tracking_url="test-tracking-url", 
                                cpc=.03,
                                ad_type="clear")
        self.expensive_creative.put()

        # Make cheap campaign
        self.cheap_c = Campaign(name="cheap",
                                budget=1000.0,
                                budget_strategy="evenly")
        self.cheap_c.put()

        self.cheap_adgroup = AdGroup(account=self.account, 
                              name="cheap",
                              campaign=self.cheap_c, 
                              site_keys=[self.adunit.key()],
                              bid_strategy="cpm",
                              bid=10000.0)
        self.cheap_adgroup.put()


        self.cheap_creative = Creative(account=self.account,
                                ad_group=self.cheap_adgroup,
                                tracking_url="test-tracking-url", 
                                cpc=.03,
                                ad_type="clear")
        self.cheap_creative.put()
    
        
        self.request = fake_request(self.adunit.key())
        adunit_id = str(self.adunit.key())

        self.adunit_context = AdUnitContextQueryManager.cache_get_or_insert(adunit_id)
   
    def tearDown(self):
        self.testbed.deactivate()

    def mptest_basic(self):
        auction_results = AdAuction.run(request = self.request,
                                       adunit=self.adunit,
                                       keywords=None,
                                       country_tuple=[],
                                       excluded_adgroups=[],
                                       udid="FakeUDID",
                                       ll=None,
                                       request_id=None,
                                       now=datetime.datetime.now(),
                                       user_agent='FakeAndroidOS',
                                       adunit_context=self.adunit_context,
                                       experimental=False)
        # Unpack results
        creative, on_fail_exclude_adgroups = auction_results                   

        eq_obj(creative, self.expensive_creative)
        
    def mptest_basic_country_tuple(self):
        auction_results = AdAuction.run(request = self.request,
                                       adunit=self.adunit,
                                       keywords=None,
                                       country_tuple=["US"],
                                       excluded_adgroups=[],
                                       udid="FakeUDID",
                                       ll=None,
                                       request_id=None,
                                       now=datetime.datetime.now(),
                                       user_agent='FakeAndroidOS',
                                       adunit_context=self.adunit_context,
                                       experimental=False)
        # Unpack results
        creative, on_fail_exclude_adgroups = auction_results                   

        eq_obj(creative, self.expensive_creative)
        
    def mptest_basic_exclusion(self):
        auction_results = AdAuction.run(request = self.request,
                                       adunit=self.adunit,
                                       keywords=None,
                                       country_tuple=[],
                                       excluded_adgroups=[],
                                       udid="FakeUDID",
                                       ll=None,
                                       request_id=None,
                                       now=datetime.datetime.now(),
                                       user_agent='FakeAndroidOS',
                                       adunit_context=self.adunit_context,
                                       experimental=False)
        # Unpack results
        creative, on_fail_exclude_adgroups = auction_results                   

        eq_obj(creative, self.expensive_creative)
        
        expensive_ag_key = str(self.expensive_adgroup.key())
        assert expensive_ag_key in on_fail_exclude_adgroups

    def mptest_inbound_exclusion(self):
        expensive_ag_key = str(self.expensive_adgroup.key())
        auction_results = AdAuction.run(request = self.request,
                                       adunit=self.adunit,
                                       keywords=None,
                                       country_tuple=[],
                                       excluded_adgroups=[expensive_ag_key],
                                       udid="FakeUDID",
                                       ll=None,
                                       request_id=None,
                                       now=datetime.datetime.now(),
                                       user_agent='FakeAndroidOS',
                                       adunit_context=self.adunit_context,
                                       experimental=False)
        # Unpack results
        creative, on_fail_exclude_adgroups = auction_results                   

        eq_obj(creative, self.cheap_creative)

        expensive_ag_key = str(self.expensive_adgroup.key())
        cheap_ag_key = str(self.cheap_adgroup.key())
        
        assert expensive_ag_key in on_fail_exclude_adgroups
        assert cheap_ag_key in on_fail_exclude_adgroups

    def mptest_native_network_failure_cascade(self):
        """ Native adnetwork failures should properly cascade """
        """ This belongs in ad_auction_mptests """
        auction_results = AdAuction.run(request = self.request,
                                       adunit=self.adunit,
                                       keywords=None,
                                       country_tuple=[],
                                       excluded_adgroups=[],
                                       udid="FakeUDID",
                                       ll=None,
                                       request_id=None,
                                       now=datetime.datetime.now(),
                                       user_agent='FakeAndroidOS',
                                       adunit_context=self.adunit_context,
                                       experimental=False)
        # Unpack results
        creative, on_fail_exclude_adgroups = auction_results                   
                                       
        eq_obj(creative, self.expensive_creative)
        
        
def eq_obj(obj1, obj2):
    eq_(obj1.key(), obj2.key())