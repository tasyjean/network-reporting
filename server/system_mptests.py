########## Set up Django ###########
import sys
import os
import datetime

sys.path.append("/Applications/GoogleAppEngineLauncher.app/Contents/Resources/GoogleAppEngine-default.bundle/Contents/Resources/google_appengine")
sys.path.append("/Applications/GoogleAppEngineLauncher.app/Contents/Resources/GoogleAppEngine-default.bundle/Contents/Resources/google_appengine/lib/yaml/lib")
sys.path.append("/Applications/GoogleAppEngineLauncher.app/Contents/Resources/GoogleAppEngine-default.bundle/Contents/Resources/google_appengine/lib/fancy_urllib")
sys.path.append(os.environ['PWD'])

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
                                          
from server.ad_server.main import  ( AdHandler,
                                     AdAuction,
                                     AdClickHandler,
                                     AppOpenHandler,
                                     TestHandler,
                                     )
                                     
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
from ad_server_tests import run_auction


""" This module is where all of our system and end-to-end tests can live. """


class TestBudgetEndToEnd(unittest.TestCase):
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

        self.budget_ad_unit = AdUnit(account=self.account, 
                                     app_key=self.app, 
                                     name="Test AdUnit",
                                     format=u'320x50')
        self.budget_ad_unit.put()

        # Make Expensive Campaign
        self.expensive_c = Campaign(name="expensive",
                                    budget=1000.0,
                                    budget_strategy="evenly")
        self.expensive_c.put()

        self.expensive_adgroup = AdGroup(account=self.account, 
                                          name="expensive",
                                          campaign=self.expensive_c, 
                                          site_keys=[self.budget_ad_unit.key()],
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
                              site_keys=[self.budget_ad_unit.key()],
                              bid_strategy="cpm",
                              bid=10000.0)
        self.cheap_adgroup.put()


        self.cheap_creative = Creative(account=self.account,
                                ad_group=self.cheap_adgroup,
                                tracking_url="test-tracking-url", 
                                cpc=.03,
                                ad_type="clear")
        self.cheap_creative.put()
    
        self.switch_adgroups_to_cpm()
        
        
   
    def tearDown(self):
        self.testbed.deactivate()

    def update_adgroups(self):
        group_query = AdGroup.all().filter('name =', 'expensive') 

        e_g = group_query.get()
        e_g.bid = 100000.0
        e_g.put()
        
        group_query = AdGroup.all().filter('name =', 'cheap')
        c_g = group_query.get()
        c_g.bid = 10000.0
        c_g.put()

    def switch_adgroups_to_cpc(self):
        group_query = AdGroup.all().filter('name =', 'expensive') 

        e_g = group_query.get()
        e_g.bid = 100000.0
        e_g.bid_strategy = "cpc"
        e_g.put()
        
        group_query = AdGroup.all().filter('name =', 'cheap')
        c_g = group_query.get()
        c_g.bid = 10000.0
        c_g.bid_strategy = "cpc"
        c_g.put()

    def switch_adgroups_to_cpm(self):
        group_query = AdGroup.all().filter('name =', 'expensive') 

        e_g = group_query.get()
        e_g.bid = 100000.0
        e_g.bid_strategy = "cpm"
        e_g.put()

        group_query = AdGroup.all().filter('name =', 'cheap')
        c_g = group_query.get()
        c_g.bid = 10000.0
        c_g.bid_strategy = "cpm"
        c_g.put()


    def update_adgroups(self):
        group_query = AdGroup.all().filter('name =', 'expensive') 

        e_g = group_query.get()
        e_g.bid = 100000.0
        e_g.put()

        group_query = AdGroup.all().filter('name =', 'cheap')
        c_g = group_query.get()
        c_g.bid = 10000.0
        c_g.put()
    
    def mptest_simple_request(self):
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative.ad_group.campaign.name, "expensive")
        
    def mptest_two_requests(self):
        # We have enough budget for one expensive ad
    
        eq_(budget_service.remaining_daily_budget(self.expensive_c), 1000)
        eq_(budget_service.remaining_ts_budget(self.expensive_c), 100)
    
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative.ad_group.bid, 100000.0)
        eq_(creative.ad_group.campaign.name, "expensive")
    
        eq_(budget_service.remaining_daily_budget(self.expensive_c), 900)
        eq_(budget_service.remaining_ts_budget(self.expensive_c), 0)
    
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative.ad_group.campaign.name, "cheap")
    
      
      
    def mptest_multiple_requests(self):
        # We have enough budget for one expensive ad
        
        eq_(budget_service.remaining_daily_budget(self.expensive_c), 1000)
        eq_(budget_service.remaining_ts_budget(self.expensive_c), 100)
        
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative.ad_group.bid, 100000.0)
        eq_(creative.ad_group.campaign.name, "expensive")
    
        eq_(budget_service.remaining_daily_budget(self.expensive_c), 900)
        eq_(budget_service.remaining_ts_budget(self.expensive_c), 0)
    
        # We have enough budget for 10 cheap ads
        for i in xrange(10):
            creative = run_auction(self.budget_ad_unit.key())
            eq_(creative.ad_group.campaign.name, "cheap")
    
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative, None)
       
    def mptest_multiple_requests_timeslice_advance(self):
        # We have enough budget for one expensive ad
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative.ad_group.campaign.name, "expensive")
    
        # We use half our cheap campaign budget
        for i in xrange(5):
            creative = run_auction(self.budget_ad_unit.key())
            eq_(creative.ad_group.campaign.name, "cheap")
    
        # Advance all of our campaigns
        budget_service._advance_all()
    
    
        # We again have enough budget for one expensive ad
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative.ad_group.campaign.name, "expensive")
    
        # We now have a cheap campaign budget for 15 ads
        for i in xrange(15):
            creative = run_auction(self.budget_ad_unit.key())
            eq_(creative.ad_group.campaign.name, "cheap")
    
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative, None)
    
    def mptest_multiple_requests_timeslice_advance_twice(self):
        # We have enough budget for one expensive ad
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative.ad_group.campaign.name, "expensive")
    
        # We use half our cheap campaign budget
        for i in xrange(5):
            creative = run_auction(self.budget_ad_unit.key())
            eq_(creative.ad_group.campaign.name, "cheap")
    
        # Advance all of our campaigns
        budget_service._advance_all()
        budget_service._advance_all()
    
    
        # We again have enough budget for two expensive ads
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative.ad_group.campaign.name, "expensive")
    
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative.ad_group.campaign.name, "expensive")
    
        # We now have a cheap campaign budget for 25 ads
        for i in xrange(25):
            creative = run_auction(self.budget_ad_unit.key())
            eq_(creative.ad_group.campaign.name, "cheap")
    
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative, None)
    
    def mptest_multiple_requests_cpc(self):
        self.switch_adgroups_to_cpc()
    
        # We have enough budget for one expensive ad
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative.ad_group.campaign.name, "expensive")
    
        # We have enough budget for 10 cheap ads
        for i in xrange(10):
            creative = run_auction(self.budget_ad_unit.key())
            eq_(creative.ad_group.campaign.name, "cheap")
    
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative, None)
    
    def mptest_multiple_requests_timeslice_advance_logging(self):
        # We have enough budget for one expensive ad
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative.ad_group.campaign.name, "expensive")
    
        # We use half our cheap campaign budget
        for i in xrange(5):
            creative = run_auction(self.budget_ad_unit.key())
            eq_(creative.ad_group.campaign.name, "cheap")
    
        # Advance all of our campaigns
        budget_service._advance_all()
    
    
        # We spent 50.0 on cheap_c last timeslice
        last_log = budget_service.last_log(self.cheap_c)
        eq_(last_log.spending, 50)
    
        # We again have enough budget for one expensive ad
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative.ad_group.campaign.name, "expensive")
    
        # We now have a cheap campaign budget for 15 ads
        for i in xrange(15):
            creative = run_auction(self.budget_ad_unit.key())
            eq_(creative.ad_group.campaign.name, "cheap")
    
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative, None)
    
        # Advance all of our campaigns
        budget_service._advance_all()
    
    
        # We spent 150.0 on cheap_c last timeslice
        last_log = budget_service.last_log(self.cheap_c)
        eq_(last_log.spending, 150)
    
        # Test the generator function:
        log_generator = budget_service.log_generator(self.cheap_c)
    
        eq_(log_generator[0].spending,150)
        eq_(log_generator[1].spending,50)
    
    def mptest_allatonce(self):
        self.expensive_c.budget_strategy = "allatonce"
        self.expensive_c.put()
    
        self.cheap_c.budget_strategy = "allatonce"
        self.cheap_c.put()
    
        eq_(self.expensive_c.budget, 1000)
        eq_(budget_service.remaining_daily_budget(self.cheap_c),1000)     
    
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative.ad_group.campaign.name, "expensive")
    
    
    
        eq_(budget_service.remaining_daily_budget(self.expensive_c),900)
    
        # We have enough budget for 10 expensive ads
        for i in xrange(9):
            creative = run_auction(self.budget_ad_unit.key())
            eq_(creative.ad_group.campaign.name, "expensive")
    
        # We now use our cheap campaign budget
        creative = run_auction(self.budget_ad_unit.key())
        eq_(creative.ad_group.campaign.name, "cheap")