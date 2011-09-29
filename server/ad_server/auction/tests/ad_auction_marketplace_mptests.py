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
                                             
from ad_server.auction.client_context import ClientContext
                                        
from server.ad_server.auction import ad_auction     
from google.appengine.ext import testbed
################# End to End #################
                                                            
from ad_server.auction.battles import (Battle, 
                                       GteeBattle, 
                                       GteeHighBattle,
                                       GteeLowBattle 
                                      )

class TestAdAuction(unittest.TestCase):


    def setUp(self):   
        """ We make three Campaigns:
                expensive_c - network with eCPM of 1.00, always fails      
                cheap_c - network with eCPM of 0.25, always succeeds  
                marketplace_c - always returns a bid with eCPM of 0.50  
                
            All three target the same adgroup.    
        """
        
    
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

        # Make Expensive Network Campaign that always fails
        self.expensive_c = Campaign(name="expensive",
                                    budget=1000.0,
                                    budget_strategy="evenly",
                                    campaign_type="gtee")
        self.expensive_c.put()

        self.expensive_adgroup = AdGroup(account=self.account, 
                                          name="expensive",
                                          campaign=self.expensive_c, 
                                          site_keys=[self.adunit.key()],
                                          bid_strategy="cpm",
                                          bid=100000.0) # 100 per click
        self.expensive_adgroup.put()



        self.expensive_creative = DummyServerSideFailureCreative(account=self.account,
                                ad_group=self.expensive_adgroup,
                                tracking_url="test-tracking-url", 
                                cpc=.03,
                                ad_type="clear")
        self.expensive_creative.put()

        # Make cheap campaign
        self.cheap_c = Campaign(name="cheap",
                                budget=1000.0,
                                budget_strategy="evenly",
                                campaign_type="gtee")
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
                                                         
        adunit_id = str(self.adunit.key())

        self.adunit_context = AdUnitContextQueryManager.cache_get_or_insert(adunit_id)
   
    def tearDown(self):
        self.testbed.deactivate()                                           
        
    def mptest_network_beating_marketplace(self):
        """ If a network with an ecpm higher than the best marketplace bid
            returns a valid creative, use it """   
            
        client_context = ClientContext(adunit=self.adunit,
                                       keywords=None,
                                       country_code=None,
                                       excluded_adgroup_keys=[],
                                       raw_udid="FakeUDID", 
                                       ll=None,
                                       request_id=None,
                                       now=datetime.datetime.now(),
                                       user_agent='FakeAndroidOS',
                                       experimental=False)
        # Unpack results
        creative, on_fail_exclude_adgroups = ad_auction.run(client_context, self.adunit_context)                    
                                       
        eq_obj(creative, self.expensive_creative)  
            
     
    def mptest_marketplace_is_not_excluded(self):
        """ The marketplace should never be added to the list of 
            excluded adgroups """   
                                           
            
            
    def mptest_marketplace_beating_failed_networks(self):
        """ If the best marketplace bid with .50, and there are two networks worth
            1.00 and .25, then if the 1.00 fails, go directly to the marketplace
            without pinging the crappier network. """   
                                           
            
         
    def mptest_marketplace_beating_failed_networks_with_exclusion(self):
        """ If the best marketplace bid with .50, and there are two networks worth
            1.00 and .25, then if the 1.00 is excluded, go directly to the 
            marketplace without pinging the crappier network. """   
                                        
                                                        
                                                    
        
def eq_obj(obj1, obj2):
    eq_(obj1.key(), obj2.key())