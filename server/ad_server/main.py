# !/usr/bin/env python

# TODO: PLEASE HAVE THIS FIX DJANGO PROBLEMS
from appengine_django import LoadDjango
LoadDjango()
import os
from django.conf import settings

os.environ['DJANGO_SETTINGS_MODULE'] = 'settings'
# Force Django to reload its settings.
settings._target = None
# END TODO: PLEASE HAVE THIS FIX DJANGO PROBLEMS

import wsgiref.handlers
import cgi
import logging
import os
import re
import datetime
import hashlib
import traceback
import random
import hashlib
import time
import base64, binascii
import urllib


urllib.getproxies_macosx_sysconf = lambda: {}


# moved from django to common utils
# from django.utils import simplejson
from common.utils import simplejson

from string import Template
from urllib import urlencode, unquote

from google.appengine.api import users, urlfetch, memcache
from google.appengine.api.labs import taskqueue
from google.appengine.ext import webapp, db
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

from publisher.models import *
from advertiser.models import *
from reporting.models import *

from ad_server.networks.appnexus import AppNexusServerSide
from ad_server.networks.brightroll import BrightRollServerSide
from ad_server.networks.greystripe import GreyStripeServerSide
from ad_server.networks.inmobi import InMobiServerSide
from ad_server.networks.jumptap import JumptapServerSide
from ad_server.networks.millennial import MillennialServerSide
from ad_server.networks.mobfox import MobFoxServerSide

from publisher.query_managers import AdServerAdUnitQueryManager, AdUnitQueryManager
from advertiser.query_managers import CampaignStatsCounter

from mopub_logging import mp_logging

test_mode = "3uoijg2349ic(test_mode)kdkdkg58gjslaf"
CRAWLERS = ["Mediapartners-Google,gzip(gfe)", "Mediapartners-Google,gzip(gfe),gzip(gfe)"]
MAPS_API_KEY = 'ABQIAAAAgYvfGn4UhlHdbdEB0ZyIFBTJQa0g3IQ9GZqIMmInSLzwtGDKaBRdEi7PnE6cH9_PX7OoeIIr5FjnTA'
DOMAIN = 'ads.mopub.com'
FREQ_ATTR = '%s_frequency_cap'
CAMPAIGN_LEVELS = ('gtee_high', 'gtee', 'gtee_low', 'promo', 'network')




# TODO: Logging is fucked up with unicode characters

# DOMAIN = 'localhost:8080'
#
# Ad auction logic
# The core of the whole damn thing
#

## Key functions
def memcache_key_for_date(udid,datetime,db_key):
  return '%s:%s:%s'%(udid,datetime.strftime('%y%m%d'),db_key)

def memcache_key_for_hour(udid,datetime,db_key):
  return '%s:%s:%s'%(udid,datetime.strftime('%y%m%d%H'),db_key)

###############################
# BASIC FILTERS
#
# --- Each filter function is a function which takes some arguments (or none) necessary 
#       for the filter to work its magic. log_mesg is the message that will be logged 
#       for the associated objects that eval'd to false.
# --- ALL FILTER GENERATOR FUNCTIONS MUST RETURN ( filter_function, log_mesg, [] )
# --- The empty list is the list that will contain all elt's for which the 
#       filter_function returned False
###############################

def budget_filter():
    log_mesg = "Removed due to being over budget: %s"
    def real_filter( a ):
        return not ( a.budget is None or a.campaign.delivery_counter.count < a.budget )
    return ( real_filter, log_mesg, [] )

def active_filter():
    log_mesg = "Removed due to inactivity: %s"
    def real_filter( a ):
        return not ( a.campaign.active and ( a.campaign.start_date  >= SiteStats.today() if a.campaign.start_date else True ) and ( SiteStats.today() <= a.campaign.end_date if a.campaign.end_date else True ) )
    return ( real_filter, log_mesg, [] )

def kw_filter( keywords ):
    log_mesg = "Removed due to keyword mismatch: %s"
    def real_filter( a ):
        return not ( not a.keywords or set( keywords ).intersection( a.keywords ) > set() )
    return ( real_filter, log_mesg, [] )

def geo_filter( geo_preds ):
    log_mesg = "Removed due to geo mismatch: %s"
    def real_filter( a ):
        return not ( set( geo_preds ).intersection( a.geographic_predicates ) > set() )
    return ( real_filter, log_mesg, [] )

def device_filter( dev_preds ):
    log_mesg = "Removed due to device mismatch: %s"
    def real_filter( a ):
        return  not ( set( dev_preds ).intersection( a.device_predicates ) > set() )
    return ( real_filter, log_mesg, [] )

def mega_filter( *filters ): 
    def actual_filter( a ):
        for ( f, msg, lst ) in filters:
            if f( a ):
                lst.append( a )
                return False
        return True
    return actual_filter

######################################
#
# Creative filters
#
######################################

def format_filter( format ):
    log_mesg = "Removed due to format mismatch, expected " + str( format ) + ": %s"
    def real_filter( a ):
        return not a.format == format
    return ( real_filter, log_mesg, [] )

def exclude_filter( excl_params ):
    log_mesg = "Removed due to exclusion parameters: %s"
    # NOTE: we are excluding on ad type not the creative id
    def real_filter( a ):
        return a.ad_type in excl_params 
    return ( real_filter, log_mesg, [] )

def ecpm_filter( winning_ecpm ):
    log_mesg = "Removed due to being a loser: %s"
    def real_filter( a ):
        return not a.e_cpm() >= winning_ecpm
    return ( real_filter, log_mesg, [] )

##############################################
#
#   FREQUENCY FILTERS
#
##############################################

# Function for constructing a frequency filter
# Super generic, made this way since all frequencies are just
#  -verify frequency cap, if yes make sure we're not over it, otherwise carry on
# so I just made a way to generate them
def freq_filter( type, key_func, udid, now, frq_dict ):
    log_mesg = "Removed due to " + type + " frequency cap: %s"
    def real_filter( a ):
        a_key = key_func( udid, now, a.key() )
        #This is why all frequency cap attributes must follow the same naming convention, otherwise this
        #trick doesn't work
        try:
            frq_cap = getattr( a, FREQ_ATTR % type ) 
        except:
            frq_cap = 0

        if frq_cap and ( a_key in frq_dict ):
            imp_cnt = int( frq_dict[ a_key ] )
        else:
            imp_cnt = 0
        #Log the current counts and cap
        logging.warning( "%s imps: %s, freq cap: %d" % ( type.title(), imp_cnt, frq_cap ) )
        return not ( not frq_cap or imp_cnt < frq_cap )
    return ( real_filter, log_mesg, [] )

#this is identical to mega_filter except it logs the adgroup 
def all_freq_filter( *filters ):
    def actual_filter( a ):
        #print the adgroup title so the counts/cap printing in the acutal filter don't confuse things
        logging.warning( "Adgroup: %s" % a )
        for f, msg, lst in filters:
            if f( a ):
                lst.append( a )
                return False
        return True
    return actual_filter


###############
# End filters
###############

class AdAuction(object):
  MAX_ADGROUPS = 30

  @classmethod
  def request_third_party_server(cls,request,adunit,adgroups):
    rpcs = []
    for adgroup in adgroups:
      server_side_dict = {"millennial":MillennialServerSide,
                          "appnexus":AppNexusServerSide,
                          "inmobi":InMobiServerSide,
                          "brightroll":BrightRollServerSide,
                          "jumptap":JumptapServerSide,
                          "greystripe":GreyStripeServerSide,
                          "mobfox":MobFoxServerSide,}
      if adgroup.network_type in server_side_dict:
        KlassServerSide = server_side_dict[adgroup.network_type]
        server_side = KlassServerSide(request, adunit) 
        logging.warning("%s url %s"%(KlassServerSide,server_side.url))

        rpc = urlfetch.create_rpc(2) # maximum delay we are willing to accept is 2000 ms
        payload = server_side.payload
        if payload == None:
          urlfetch.make_fetch_call(rpc, server_side.url, headers=server_side.headers)
        else:
          urlfetch.make_fetch_call(rpc, server_side.url, headers=server_side.headers, method=urlfetch.POST, payload=payload)
        # attaching the adgroup to the rpc
        rpc.adgroup = adgroup
        rpc.serverside = server_side
        rpcs.append(rpc)
    return rpcs    
      # 
      # # ... do other things ...
      # 
      # try:
      #     result = rpc.get_result()
      #     if result.status_code == 200:
      #         response = mmServerSide.html_for_response(result)
      #         self.response.out.write("%s<br/> %s"%(mmServerSide.url,response))
      # except urlfetch.DownloadError:
      #   self.response.out.write("%s<br/> %s"%(mmServerSide.url,"response not fast enough"))

  # Runs the auction itself.  Returns the winning creative, or None if no creative matched
  @classmethod
  def run(cls, **kw):
    now = kw["now"]
    site = kw["site"]
    manager = kw["manager"]
    request = kw["request"]
    
    udid = kw["udid"]

    keywords = kw["q"]
    geo_predicates = AdAuction.geo_predicates_for_rgeocode(kw["addr"])
    device_predicates = AdAuction.device_predicates_for_request(kw["request"])
    format_predicates = AdAuction.format_predicates_for_format(kw["format"])
    exclude_params = kw["excluded_creatives"]
    excluded_predicates = AdAuction.exclude_predicates_params(exclude_params)
    logging.warning("keywords=%s, geo_predicates=%s, device_predicates=%s, format_predicates=%s" % (keywords, geo_predicates, device_predicates, format_predicates))

    # Matching strategy: 
    # 1) match all ad groups that match the placement that is in question, sort by priority
    # 2) throw out ad groups owned by campaigns that have exceeded budget or are paused
    # 3) throw out ad groups that restrict by keywords and do not match the keywords
    # 4) throw out ad groups that do not match device and geo predicates
    all_ad_groups = manager.get_adgroups() #AdGroup.gql("where site_keys = :1 and active = :2 and deleted = :3", site.key(), True, False).fetch(AdAuction.MAX_ADGROUPS)
    
    #Start up those RPC calls
    rpcs = AdAuction.request_third_party_server(request,site,all_ad_groups)
    logging.warning("ad groups: %s" % all_ad_groups)
    # # campaign exclusions... budget + time
    for a in all_ad_groups:
      logging.info("%s of %s"%(a.campaign.delivery_counter.count,a.budget))
    
    ALL_FILTERS     = ( budget_filter(), 
                        active_filter(), 
                        kw_filter( keywords ), 
                        geo_filter( geo_predicates ), 
                        device_filter( device_predicates ) 
                        ) 

    all_ad_groups = filter( mega_filter( *ALL_FILTERS ), all_ad_groups )
    for ( func, warn, lst ) in ALL_FILTERS:
        logging.warning( warn % lst )

    # TODO: user based frequency caps (need to add other levels)
    # to add a frequency cap, add it here as follows:
    #         ( 'name',     key_function ),
    #   IMPORTANT: The corresponding frequency_cap property of adgroup must match the name as follows:
    #                   (adgroup).<name>_frequency_cap, eg daily_frequency_cap, hourly_frequency_cap
    #                   otherwise the filter will not fetch the appropriate cap
    FREQS = ( ( 'daily',    memcache_key_for_date ),
              ( 'hourly',   memcache_key_for_hour ),
              )

    #Pull ALL keys (Before prioritizing) and batch get. This is slightly (according to test timings) 
    # better than filtering based on priority 
    user_keys = []
    for adgroup in all_ad_groups:
        for type, key_func in FREQS:
            try:
                # This causes an exception if it fails, the variable is actually never used though.
                temp = getattr( adgroup, FREQ_ATTR % type ) 
                user_keys.append( key_func( udid, now, adgroup.key() ) )
            except:
                continue
    if user_keys:  
        frequency_cap_dict = memcache.get_multi(user_keys)    
    else:
        frequency_cap_dict = {}
    #build and apply list of frequency filter functions
    FREQ_FILTERS = [ freq_filter( type, key_func, udid, now, frequency_cap_dict ) for ( type, key_func ) in FREQS ] 
    all_ad_groups = filter( all_freq_filter( *FREQ_FILTERS ), all_ad_groups )
    for fil in FREQ_FILTERS: 
        func, warn, lst = fil
        logging.warning( warn % lst )
        
    # calculate the user experiment bucket
    user_bucket = hash(udid+','.join([str( ad_group.key() ) for ad_group in all_ad_groups])) % 100 # user gets assigned a number between 0-99 inclusive
    logging.warning("the user bucket is: #%d",user_bucket)

  # determine in which ad group the user falls into to
  # otherwise give creatives in the other adgroups a shot
  # TODO: fix the stagger method how do we get 3 ads all at 100%
  # currently we just mod by 100 such that there is wrapping
    start_bucket = 0
    winning_ad_groups = []
  
  # sort the ad groups by the percent of users desired, this allows us 
  # to do the appropriate wrapping of the number line if they are nicely behaved
  # TODO: finalize this so that we can do things like 90% and 15%. We need to decide
  # what happens in this case, unclear what the intent of this is.
    all_ad_groups.sort(lambda x,y: cmp(x.percent_users if x.percent_users else 100.0,y.percent_users if y.percent_users else 100.0))
    for ad_group in all_ad_groups:
        percent_users = ad_group.percent_users if not (ad_group.percent_users is None) else 100.0
        if start_bucket <= user_bucket and user_bucket < (start_bucket + percent_users):
            winning_ad_groups.append(ad_group)
        start_bucket += percent_users
        start_bucket = start_bucket % 100 

    all_ad_groups = winning_ad_groups
    # if any ad groups were returned, find the creatives that match the requested format in all candidates
    if len(all_ad_groups) > 0:
        logging.warning("ad_group: %s"%all_ad_groups)
        all_creatives = manager.get_creatives_for_adgroups(all_ad_groups)
        # all_creatives = Creative.gql("where ad_group in :1 and format_predicates in :2 and active = :3 and deleted = :4", 
        #   map(lambda x: x.key(), ad_groups), format_predicates, True, False).fetch(AdAuction.MAX_ADGROUPS)
        if len(all_creatives) > 0:
            # for each priority_level, perform an auction among the various creatives 
            for p in CAMPAIGN_LEVELS: 
                logging.warning("priority level: %s"%p)
                eligible_adgroups = [a for a in all_ad_groups if a.campaign.campaign_type == p]
                logging.warning("eligible_adgroups: %s"%eligible_adgroups)
                if not eligible_adgroups:
                    continue
                players = manager.get_creatives_for_adgroups(eligible_adgroups)
                players.sort(lambda x,y: cmp(y.e_cpm(), x.e_cpm()))

                while players:
                    logging.warning("players: %s"%players)
                    winning_ecpm = players[0].e_cpm()
                    logging.warning("auction at priority=%s: %s, max eCPM=%s" % (p, players, winning_ecpm))
                    if winning_ecpm >= site.threshold_cpm( p ):

                        # exclude according to the exclude parameter must do this after determining adgroups
                        # so that we maintain the correct order for user bucketing
                        # TODO: we should exclude based on creative id not ad type :)
                        CRTV_FILTERS = (    format_filter( site.format ), # remove wrong formats
                                            exclude_filter( exclude_params ), # remove exclude parameter
                                            ecpm_filter( winning_ecpm ), # remove creatives that don't meet site threshold
                                            )
                        winners = filter( mega_filter( *CRTV_FILTERS ), players )
                        for func, warn, lst in CRTV_FILTERS:
                            logging.warning( warn % lst )

                        # if there is a winning/eligible adgroup find the appropriate creative for it
                        winning_creative = None
                        logging.warning("winner ad_groups: %s"%winning_ad_groups)

                        if winners:
                            logging.warning('winners %s' % [w.ad_group for w in winners])
                            random.shuffle(winners)
                            logging.warning('random winners %s' % winners)
                            actual_winner = None
                            # find the actual winner among all the eligble ones
                            # loop through each of the randomized winners making sure that the data is ready to display
                            for winner in winners:
                                if not rpcs:
                                    winning_creative = winner
                                    return winning_creative
                                else:
                                    rpc = None                      
                                    if winner.ad_group.key() in [r.adgroup.key() for r in rpcs]:
                                        for rpc in rpcs:
                                            if rpc.adgroup.key() == winner.ad_group.key():
                                                logging.warning("rpc.adgroup %s"%rpc.adgroup)
                                                break # This pulls out the rpc that matters there should be one always

                            # if the winning creative relies on a rpc to get the actual data to display
                            # go out and get the data and paste in the data to the creative      
                                    if rpc:      
                                        try:
                                            result = rpc.get_result()
                                            if result.status_code == 200:
                                                bid,response = rpc.serverside.bid_and_html_for_response(result)
                                                winning_creative = winner
                                                winning_creative.html_data = response
                                                return winning_creative
                                        except Exception,e:
                                            import traceback, sys
                                            exception_traceback = ''.join(traceback.format_exception(*sys.exc_info()))
                                            logging.warning(exception_traceback)
                                    else:
                                        winning_creative = winner
                                        return winning_creative
                        else:
                            # remove players of the current winning e_cpm
                            logging.warning('current players: %s'%players)
                            players = [ p for p in players if p.e_cpm() != winning_ecpm ] 
                            logging.warning('remaining players %s'%players)
                        if not winning_creative:
                            #logging.warning('taking away some players not in %s'%ad_groups)
                            #logging.warning( 'current ad_groups %s' % [c.ad_group for c in players] )
                            logging.warning('current players: %s'%players)
                            #players = [c for c in players if not c.ad_group in ad_groups]  
                            players = [ p for p in players if p not in winners ] 
                            logging.warning('remaining players %s'%players)
             # try at a new priority level   

    # nothing... failed auction
    logging.warning("auction failed, returning None")
    return None
    
  @classmethod
  def geo_predicates_for_rgeocode(c, r):
    # r = [US, CA SF] or []
    # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # TODO: DEFAULT COUNTRY SHOULD NOT BE US!!!!!!!
    # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    if len(r) == 0:
      return ["country_name=US","country_name=*"] # ["country_name"=*] or ["country_name=US] ["country_name="CD"]
    elif len(r) == 1:
        return ["country_name=%s" % r[0], "country_name=*"]
    elif len(r) == 2:
      return ["region_name=%s,country_name=%s" % (r[0], r[1]),
              "country_name=%s" % r[1],
              "country_name=*"]
    elif len(r) == 3:
      return ["city_name=%s,region_name=%s,country_name=%s" % (r[0], r[1], r[2]),
              "region_name=%s,country_name=%s" % (r[1], r[2]),
              "country_name=%s" % r[2],
              "country_name=*"]

  @classmethod
  def device_predicates_for_request(c, req):
    ua = req.headers["User-Agent"]
    if "Android" in ua:
      return ["platform_name=android", "platform_name=*"]
    elif "iPhone" in ua:
      return ["platform_name=iphone", "platform_name=*"]
    else:
      return ["platform_name=*"]

  @classmethod
  def format_predicates_for_format(c, f):
    # TODO: does this always work for any format
    return ["format=%dx%d" % (f[0], f[1]), "format=*"]
  
  @classmethod
  def exclude_predicates_params(c,params):
    return ["exclude=%s"%param for param in params]    
#
# Primary ad auction handler 
# -- Handles ad request parameters and normalizes for the auction logic
# -- Handles rendering the winning creative into the right HTML
#
class AdHandler(webapp.RequestHandler):
  
  # AdSense: Format properties: width, height, adsense_format, num_creatives
  FORMAT_SIZES = {
    "300x250_as": (300, 250, "300x250_as", 3),
    "320x50_mb": (320, 50, "320x50_mb", 1),
    "728x90_as": (728, 90, "728x90_as", 2),
    "468x60_as": (468, 60, "468x60_as", 1),
    "300x250": (300, 250, "300x250_as", 3),
    "320x50": (320, 50, "320x50_mb", 1),
    "728x90": (728, 90, "728x90_as", 2),
    "468x60": (468, 60, "468x60_as", 1),
    "320x480": (300, 250, "300x250_as", 1),
  }
  
  def get(self):
    id = self.request.get("id")
    manager = AdUnitQueryManager(id)
    now = datetime.datetime.now()
    
    
    #Testing!
    if self.request.get( 'testing' ) == test_mode:
        manager = AdServerAdUnitQueryManager( id )
        testing = True
        now = datetime.datetime.fromtimestamp( float( self.request.get('dt') ) )
    else:
        testing = False
    
    if not testing:
        mp_logging.log(self.request,event=mp_logging.REQ_EVENT)  
    
    logging.warning(self.request.headers['User-Agent'] )
    locale = self.request.headers.get("Accept-Language")
    country_re = r'[A-Z][A-Z]'
    if locale:
        countries = re.findall(country_re, locale)
    else:
        countries = [] 
    addr = []
    if len(countries) == 1:
        addr = tuple(countries[0])



    # site = manager.get_by_key(key)#Site.site_by_id(id) if id else None
    adunit = manager.get_adunit()
    site = adunit
    
    # the user's site key was not set correctly...
    if site is None:
        self.error(404)
        self.response.out.write( "Publisher adunit key %s not valid" % id )
        return
    
    # get keywords 
    # q = [sz.strip() for sz in ("%s\n%s" % (self.request.get("q").lower() if self.request.get("q") else '', site.keywords if site.k)).split("\n") if sz.strip()]
    keywords = []
    if site.keywords and site.keywords != 'None':
        keywords += site.keywords.split(',')
    if self.request.get("q"):
        keywords += self.request.get("q").lower().split(',')
    q = keywords
    logging.warning("keywords are %s" % keywords)

    # get format
    f = self.request.get("f") or "320x50" # TODO: remove this default
    f = "%dx%d"%(int(site.width),int(site.height))
    format = self.FORMAT_SIZES.get(f)
    # logging.warning("format is %s (requested '%s')" % (format, f))
    
    # look up lat/lon
    addr = self.rgeocode(self.request.get("ll")) if self.request.get("ll") else ()      
    logging.warning("geo is %s (requested '%s')" % (addr, self.request.get("ll")))
    
    # get creative exclusions usually used to exclude iAd because it has already failed
    excluded_creatives = self.request.get_all("exclude")
    logging.info("excluded_creatives: %s"%excluded_creatives)
    
    # TODO: get udid we should hash it if its not already hashed
    udid = self.request.get("udid")
    
    # create a unique request id, but only log this line if the user agent is real
    request_id = hashlib.md5("%s:%s" % (self.request.query_string, time.time())).hexdigest()
    if str(self.request.headers['User-Agent']) not in CRAWLERS:
        logging.info('OLP ad-request {"request_id": "%s", "remote_addr": "%s", "q": "%s", "user_agent": "%s", "udid":"%s" }' % (request_id, self.request.remote_addr, self.request.query_string, self.request.headers["User-Agent"], udid))

    # get winning creative
    c = AdAuction.run(request=self.request, site=site, format=format, q=q, addr=addr, excluded_creatives=excluded_creatives, udid=udid, request_id=request_id, now=now,manager=manager)
    # output the request_id and the winning creative_id if an impression happened
    if c:
        user_adgroup_daily_key = memcache_key_for_date(udid,now,c.ad_group.key())
        user_adgroup_hourly_key = memcache_key_for_hour(udid,now,c.ad_group.key())
        logging.warning("user_adgroup_daily_key: %s"%user_adgroup_daily_key)
        logging.warning("user_adgroup_hourly_key: %s"%user_adgroup_hourly_key)
        memcache.offset_multi({user_adgroup_daily_key:1,user_adgroup_hourly_key:1}, key_prefix='', namespace=None, initial_value=0)
      
        if str(self.request.headers['User-Agent']) not in CRAWLERS:
            logging.info('OLP ad-auction {"id": "%s", "c": "%s", "request_id": "%s", "udid": "%s"}' % (id, c.key(), request_id, udid))

        self.response.headers.add_header("X-Creative",str(c.key()))    

        # add timer and animations for the ad 
        refresh = adunit.refresh_interval
        # only send to client if there should be a refresh
        if refresh:
            self.response.headers.add_header("X-Refreshtime",str(refresh))
        # animation_type = random.randint(0,6)
        # self.response.headers.add_header("X-Animation",str(animation_type))    

      # create an ad clickthrough URL
        ad_click_url = "http://%s/m/aclk?id=%s&c=%s&req=%s" % (DOMAIN,id, c.key(), request_id)
        self.response.headers.add_header("X-Clickthrough", str(ad_click_url))
      
      # ad an impression tracker URL
        self.response.headers.add_header("X-Imptracker", "http://%s/m/imp?id=%s&cid=%s"%(DOMAIN,id,c.key()))
      
      #add creative ID for testing (also prevents that one bad bug from happening)
        self.response.headers.add_header("X-Creativeid", "%s" % c.key())

      # add to the campaign counter
        logging.info("adding to delivery: %s"%c.ad_group.bid)
        c.ad_group.campaign.delivery_counter.increment(dollars=c.ad_group.bid)
      
      # render the creative 
        self.response.out.write( self.render_creative(  c, 
                                                        site                = site, 
                                                        format              = format, 
                                                        q                   = q, 
                                                        addr                = addr,
                                                        excluded_creatives  = excluded_creatives, 
                                                        request_id          = request_id, 
                                                        v                   = int(self.request.get('v') or 0),
                                                        ) )
    else:
        self.response.out.write( self.render_creative(  c, 
                                                        site                = site, 
                                                        format              = format, 
                                                        q                   = q, 
                                                        addr                = addr, 
                                                        excluded_creatives  = excluded_creatives, 
                                                        request_id          = request_id, 
                                                        v                   = int(self.request.get('v') or 0),
                                                        ) )

      
  #
  # Templates
  #
  TEMPLATES = {
    "adsense": Template("""<html>
                            <head>
                              <title>$title</title>
                              $finishLoad
                              <script>
                                function webviewDidClose(){} 
                                function webviewDidAppear(){} 
                              </script>
                            </head>
                            <body style="margin: 0;width:${w}px;height:${h}px;" >
                              <script type="text/javascript">window.googleAfmcRequest = {client: '$client',ad_type: 'text_image', output: 'html', channel: '$channel_id',format: '$adsense_format',oe: 'utf8',color_border: '336699',color_bg: 'FFFFFF',color_link: '0000FF',color_text: '000000',color_url: '008000',};</script> 
                              <script type="text/javascript" src="http://pagead2.googlesyndication.com/pagead/show_afmc_ads.js"></script>  
                              $trackingPixel
                            </body>
                          </html> """),
    "iAd": Template("iAd"),
    "clear": Template(""),
    "text": Template("""<html>
                        <head>
                          <style type="text/css">.creative {font-size: 12px;font-family: Arial, sans-serif;width: ${w}px;height: ${h}px;}.creative_headline {font-size: 14px;}.creative .creative_url a {color: green;text-decoration: none;}
                          </style>
                          $finishLoad
                          <script>
                            function webviewDidClose(){} 
                            function webviewDidAppear(){} 
                          </script>
                          <title>$title</title>
                        </head>
                        <body style="margin: 0;width:${w}px;height:${h}px;padding:0;">
                          <div class="creative"><div style="padding: 5px 10px;"><a href="$url" class="creative_headline">$headline</a><br/>$line1 $line2<br/><span class="creative_url"><a href="$url">$display_url</a></span></div></div>\
                          $trackingPixel
                        </body> </html> """),
    "text_icon": Template(
"""<html>
  <head>
    $finishLoad
    <script>
      function webviewDidClose(){}
      function webviewDidAppear(){}
    </script>
    <title></title>
  </head>
  <body style="top-margin:0;margin:0;width:320px;padding:0;background-color:#$color;font-size:12px;font-family:Arial,sans-serif;">
  <div id='highlight' style="position:relative;height:50px;background:-webkit-gradient(linear, left top, left bottom, from(rgba(255,255,255,0.35)),
    to(rgba(255,255,255,0.06))); -webkit-background-origin: padding-box; -webkit-background-clip: content-box;">
    <div style="margin:5px;width:40px;height:40px;float:left"><img id="thumb" src="$image_url" style="-webkit-border-radius:6px;-moz-border-radius:6px" width=40 height=40/></div>
    <div style="float:left;width:230">
      <div style="color:white;font-weight:bold;margin:0px 0 0 5px;padding-top:8;">$line1</div>
      <div style="color:white;margin-top:6px;margin:5px 0 0 5px;">$line2</div>
    </div>
    $action_icon_div
    $trackingPixel
  </div>
  </body>
</html>"""),
    "image":Template("""<html>
                        <head>
                          <style type="text/css">.creative {font-size: 12px;font-family: Arial, sans-serif;width: ${w}px;height: ${h}px;}.creative_headline {font-size: 20px;}.creative .creative_url a {color: green;text-decoration: none;}
                          </style>
                          $finishLoad
                          <script>
                            function webviewDidClose(){} 
                            function webviewDidAppear(){} 
                          </script>
                        </head>
                        <body style="margin: 0;width:${w}px;height:${h}px;padding:0;">\
                          <a href="$url" target="_blank"><img src="$image_url" width=$w height=$h/></a>
                          $trackingPixel
                        </body></html> """),
    "admob": Template("""<html><head>
                        <script type="text/javascript">
                          function webviewDidClose(){} 
                          function webviewDidAppear(){} 
                          window.innerWidth = $w;
                          window.innerHeight = $h;
                        </script>
                        <title>$title</title>
                        </head><body style="margin: 0;width:${w}px;height:${h}px;padding:0;background-color:transparent;">
                        <script type="text/javascript">
                        var admob_vars = {
                         pubid: '$client', // publisher id
                         bgcolor: '000000', // background color (hex)
                         text: 'FFFFFF', // font-color (hex)
                         ama: false, // set to true and retain comma for the AdMob Adaptive Ad Unit, a special ad type designed for PC sites accessed from the iPhone.  More info: http://developer.admob.com/wiki/IPhone#Web_Integration
                         test: false, // test mode, set to false to receive live ads
                         manual_mode: true // set to manual mode
                        };
                        </script>
                        <script type="text/javascript" src="http://mmv.admob.com/static/iphone/iadmob.js"></script>  
                        
                        <!-- DIV For admob ad -->
                        <div id="admob_ad">
                        </div>

                        <!-- Script to determine if admob loaded -->
                        <script>
                            var ad = _admob.fetchAd(document.getElementById('admob_ad'));                                                                         
                            var POLLING_FREQ = 500;
                            var MAX_POLL = 2000;
                            var polling_timeout = 0;                                                                                                              
                            var polling_func = function() {                                                                                                       
                             if(ad.adEl.height == 48) {                                                                                                           
                               // we have an ad                                                                                                                   
                               console.log('received ad');
                               $admob_finish_load
                             } 
                             else if(polling_timeout < MAX_POLL) {                                                                                                         
                               console.log('repoll');                                                                                                             
                               polling_timeout += POLLING_FREQ;                                                                                                           
                               window.setTimeout(polling_func, POLLING_FREQ);                                                                                             
                             }                                                                                                                                    
                             else {                                                                                                                               
                               console.log('no ad'); 
                               $admob_fail_load                                                                                                               
                               ad.adEl.style.display = 'none';                                                                                                    
                             }                                                                                                                                    
                            };                                                                                                                                    
                            window.setTimeout(polling_func, POLLING_FREQ);
                        </script>
                        $trackingPixel
                        </body></html>"""),
    "html":Template("""<html><head><title>$title</title>
                        $finishLoad
                        <script type="text/javascript">
                          function webviewDidClose(){}
                          function webviewDidAppear(){}
                          window.addEventListener("load", function() {
                            var links = document.getElementsByTagName('a');
                            for(var i=0; i < links.length; i++) {
                              links[i].setAttribute('target','_blank');
                            }
                          }, false);
                        </script></head>
                        <body style="margin:0;padding:0;width:${w}px;background:white;">${html_data}$trackingPixel</body></html>"""),
    "html_full":Template("$html_data")
  }
  def render_creative(self, c, **kwargs):
    if c:
      logging.warning("rendering: %s" % c.ad_type)
      format = kwargs["format"]
      site = kwargs["site"]

      template_name = c.ad_type
      
      params = kwargs
      params.update(c.__dict__.get("_entity"))
      if c.ad_type == "adsense":
        params.update({"title": ','.join(kwargs["q"]), "adsense_format": format[2], "w": format[0], "h": format[1], "client": kwargs["site"].account.adsense_pub_id})
        params.update(channel_id=kwargs["site"].adsense_channel_id or '')
        # self.response.headers.add_header("X-Launchpage","http://googleads.g.doubleclick.net")
      elif c.ad_type == "admob":
        params.update({"title": ','.join(kwargs["q"]), "w": format[0], "h": format[1], "client": kwargs["site"].account.admob_pub_id})
        self.response.headers.add_header("X-Launchpage","http://c.admob.com/")
      elif c.ad_type == "text_icon":
        if c.image:
          params["image_url"] = "data:image/png;base64,%s" % binascii.b2a_base64(c.image)
        if c.action_icon:
          params["action_icon_div"] = '<div style="padding-top:5px;position:absolute;top:0;right:0;"><a href="'+c.url+'" target="_blank"><img src="/images/'+c.action_icon+'.png" width=40 height=40/></a></div>'
        # self.response.headers.add_header("X-Adtype", str('html'))
      elif c.ad_type == "greystripe":
        params.update(html_data=c.html_data)
        # TODO: Why is html data here twice?
        params.update({"html_data": kwargs["html_data"], "w": format[0], "h": format[1]})
        self.response.headers.add_header("X-Launchpage","http://adsx.greystripe.com/openx/www/delivery/ck.php")
        template_name = "html"
      elif c.ad_type == "image":
        params["image_url"] = "data:image/png;base64,%s" % binascii.b2a_base64(c.image)
        params.update({"w": format[0], "h": format[1]})
      elif c.ad_type == "html":
        params.update(html_data=c.html_data)
        params.update({"html_data": kwargs["html_data"], "w": format[0], "h": format[1]})
        
        # HACK FOR RUSSEL's INTERSTITIAL
        # if str(c.key()) == "agltb3B1Yi1pbmNyEAsSCENyZWF0aXZlGPmNGAw":
        #   self.response.headers.add_header("X-Closebutton","None")
        
      elif c.ad_type == "html_full":
        params.update(html_data=c.html_data)
        params.update({"html_data": kwargs["html_data"]})
        self.response.headers.add_header("X-Scrollable","1")
        self.response.headers.add_header("X-Interceptlinks","0")
      elif c.ad_type == "text":  
        self.response.headers.add_header("X-Productid","pixel_001")
        
        
      if kwargs["q"] or kwargs["addr"]:
        params.update(title=','.join(kwargs["q"]+list(kwargs["addr"])))
      else:
        params.update(title='')
        
      if kwargs["v"] >= 2 and not "Android" in self.request.headers["User-Agent"]:  
        params.update(finishLoad='<script>function finishLoad(){window.location="mopub://finishLoad";} window.onload = function(){finishLoad();} </script>')
        # extra parameters used only by admob template
        params.update(admob_finish_load='window.location = "mopub://finishLoad";')
        params.update(admob_fail_load='window.location = "mopub://failLoad";')
      else:
        # don't use special url hooks because older clients don't understand    
        params.update(finishLoad='')
        # extra parameters used only by admob template
        params.update(admob_finish_load='')
        params.update(admob_fail_load='')
      
      if c.tracking_url:
        params.update(trackingPixel='<span style="display:none;"><img src="%s"/></span>'%c.tracking_url)
      else:
        params.update(trackingPixel='')  
      
      # indicate to the client the winning creative type, in case it is natively implemented (iad, clear)
      
      if str(c.ad_type) == "iAd":
        # self.response.headers.add_header("X-Adtype","custom")
        # self.response.headers.add_header("X-Backfill","alert")
        # self.response.headers.add_header("X-Nativeparams",'{"title":"MoPub Alert View","cancelButtonTitle":"No Thanks","message":"We\'ve noticed you\'ve enjoyed playing Angry Birds.","otherButtonTitle":"Rank","clickURL":"mopub://inapp?id=pixel_001"}')
        # self.response.headers.add_header("X-Customselector","customEventTest")
        
        self.response.headers.add_header("X-Adtype", str(c.ad_type))
        self.response.headers.add_header("X-Backfill", str(c.ad_type))        
        self.response.headers.add_header("X-Failurl",self.request.url+'&exclude='+str(c.ad_type))
        
      elif str(c.ad_type) == "adsense":
        self.response.headers.add_header("X-Adtype", str(c.ad_type))
        self.response.headers.add_header("X-Backfill", str(c.ad_type))
        
        logging.warning('pub id:%s'%kwargs["site"].account.adsense_pub_id)
        header_dict = {
          "Gclientid":str(kwargs["site"].account.adsense_pub_id),
          "Gcompanyname":str(kwargs["site"].account.adsense_company_name),
          "Gappname":str(kwargs["site"].app_key.adsense_app_name),
          "Gappid":"0",
          "Gkeywords":str(kwargs["site"].keywords or ''),
          "Gtestadrequest":"0",
          "Gchannelids":str(kwargs["site"].adsense_channel_id or ''),        
        # "Gappwebcontenturl":,
          "Gadtype":"GADAdSenseTextImageAdType", #GADAdSenseTextAdType,GADAdSenseImageAdType,GADAdSenseTextImageAdType
          "Gtestadrequest":"1" if site.account.adsense_test_mode else "0",
        # "Ghostid":,
        # "Gbackgroundcolor":"00FF00",
        # "Gadtopbackgroundcolor":"FF0000",
        # "Gadbordercolor":"0000FF",
        # "Gadlinkcolor":,
        # "Gadtextcolor":,
        # "Gadurlolor":,
        # "Gexpandirection":,
        # "Galternateadcolor":,
        # "Galternateadurl":, # This could be interesting we can know if Adsense 'fails' and is about to show a PSA.
        # "Gallowadsafemedium":,
        }
        json_string_pairs = []
        for key,value in header_dict.iteritems():
          json_string_pairs.append('"%s":"%s"'%(key,value))
        json_string = '{'+','.join(json_string_pairs)+'}'
        self.response.headers.add_header("X-Nativeparams",json_string)
        
        # add some extra  
        self.response.headers.add_header("X-Failurl",self.request.url+'&exclude='+str(c.ad_type))
        self.response.headers.add_header("X-Format",format[2])
        self.response.headers.add_header("X-Width",str(format[0]))
        self.response.headers.add_header("X-Height",str(format[1]))
      
        self.response.headers.add_header("X-Backgroundcolor","0000FF")
      elif str(c.ad_type) == 'admob':
          self.response.headers.add_header("X-Failurl",self.request.url+'&exclude='+str(c.ad_type))
          self.response.headers.add_header("X-Adtype", str('html'))
      else:  
        self.response.headers.add_header("X-Adtype", str('html'))
        
      if kwargs["q"] or kwargs["addr"]:
        params.update(title=','.join(kwargs["q"]+list(kwargs["addr"])))
      else:
        params.update(title='')
      
      if c.tracking_url:
        params.update(trackingPixel='<span style="display:none;"><img src="%s"/></span>'%c.tracking_url)
      else:
        params.update(trackingPixel='')

      self.response.headers.add_header("X-Backfill", str('html'))

      # render the HTML body
      self.response.out.write(self.TEMPLATES[template_name].safe_substitute(params))
    else:
      self.response.headers.add_header("X-Adtype", "clear")
      self.response.headers.add_header("X-Backfill", "clear")
    
    # make sure this response is not cached by the client  
    # self.response.headers.add_header('Cache-Control','no-cache')  
  
  def rgeocode(self, ll):
    url = "http://maps.google.com/maps/geo?%s" % urlencode({"q": ll, 
      "key": MAPS_API_KEY, 
      "sensor": "false", 
      "output": "json"})
    json = urlfetch.fetch(url).content
    try:
      geocode = simplejson.loads(json)

      if geocode.get("Placemark"):
        for placemark in geocode["Placemark"]:
          if placemark.get("AddressDetails").get("Accuracy") == 8:
            logging.warning("rgeocode Accuracy == 8")
          
            country = placemark.get("AddressDetails").get("Country")
            administrativeArea = country.get("AdministrativeArea") if country else None
            subAdministrativeArea = administrativeArea.get("SubAdministrativeArea") if administrativeArea else None
            locality = (subAdministrativeArea.get("Locality") if subAdministrativeArea else administrativeArea.get("Locality")) if administrativeArea else None
            logging.warning("country=%s, administrativeArea=%s, subAdminArea=%s, locality=%s" % (country, administrativeArea, subAdministrativeArea, locality))
          
            return (locality.get("LocalityName") if locality else "", 
                    administrativeArea.get("AdministrativeAreaName") if administrativeArea else "",
                    country.get("CountryNameCode") if country else "")
        return ()
      else:
        return ()
    except:
      logging.error("rgeocode failed to parse %s" % json)
      return ()

class AdImpressionHandler(webapp.RequestHandler):
  def get(self):
    mp_logging.log(self.request,event=mp_logging.IMP_EVENT)  
    self.response.out.write("OK")
        
class AdClickHandler(webapp.RequestHandler):
  # /m/aclk?v=1&udid=26a85bc239152e5fbc221fe5510e6841896dd9f8&q=Hotels:%20Hotel%20Utah%20Saloon%20&id=agltb3B1Yi1pbmNyDAsSBFNpdGUY6ckDDA&r=http://googleads.g.doubleclick.net/aclk?sa=l&ai=BN4FhRH6hTIPcK5TUjQT8o9DTA7qsucAB0vDF6hXAjbcB4KhlEAEYASDgr4IdOABQrJON3ARgyfb4hsijoBmgAbqxif8DsgERYWRzLm1vcHViLWluYy5jb226AQkzMjB4NTBfbWLIAQHaAbwBaHR0cDovL2Fkcy5tb3B1Yi1pbmMuY29tL20vYWQ_dj0xJmY9MzIweDUwJnVkaWQ9MjZhODViYzIzOTE1MmU1ZmJjMjIxZmU1NTEwZTY4NDE4OTZkZDlmOCZsbD0zNy43ODM1NjgsLTEyMi4zOTE3ODcmcT1Ib3RlbHM6JTIwSG90ZWwlMjBVdGFoJTIwU2Fsb29uJTIwJmlkPWFnbHRiM0IxWWkxcGJtTnlEQXNTQkZOcGRHVVk2Y2tEREGAAgGoAwHoA5Ep6AOzAfUDAAAAxA&num=1&sig=AGiWqtx2KR1yHomcTK3f4HJy5kk28bBsNA&client=ca-mb-pub-5592664190023354&adurl=http://www.sanfranciscoluxuryhotels.com/
  def get(self):
    mp_logging.log(self.request,event=mp_logging.CLK_EVENT)  
      
    id = self.request.get("id")
    q = self.request.get("q")    
    # BROKEN
    # url = self.request.get("r")
    sz = self.request.query_string
    r = sz.rfind("&r=")
    if r > 0:
      url = sz[(r + 3):]
      url = unquote(url)
      # forward on to the click URL
      self.redirect(url)
    else:
      self.response.out.write("OK")

# TODO: Process this on the logs processor 
class AppOpenHandler(webapp.RequestHandler):
  # /m/open?v=1&udid=26a85bc239152e5fbc221fe5510e6841896dd9f8&q=Hotels:%20Hotel%20Utah%20Saloon%20&id=agltb3B1Yi1pbmNyDAsSBFNpdGUY6ckDDA&r=http://googleads.g.doubleclick.net/aclk?sa=l&ai=BN4FhRH6hTIPcK5TUjQT8o9DTA7qsucAB0vDF6hXAjbcB4KhlEAEYASDgr4IdOABQrJON3ARgyfb4hsijoBmgAbqxif8DsgERYWRzLm1vcHViLWluYy5jb226AQkzMjB4NTBfbWLIAQHaAbwBaHR0cDovL2Fkcy5tb3B1Yi1pbmMuY29tL20vYWQ_dj0xJmY9MzIweDUwJnVkaWQ9MjZhODViYzIzOTE1MmU1ZmJjMjIxZmU1NTEwZTY4NDE4OTZkZDlmOCZsbD0zNy43ODM1NjgsLTEyMi4zOTE3ODcmcT1Ib3RlbHM6JTIwSG90ZWwlMjBVdGFoJTIwU2Fsb29uJTIwJmlkPWFnbHRiM0IxWWkxcGJtTnlEQXNTQkZOcGRHVVk2Y2tEREGAAgGoAwHoA5Ep6AOzAfUDAAAAxA&num=1&sig=AGiWqtx2KR1yHomcTK3f4HJy5kk28bBsNA&client=ca-mb-pub-5592664190023354&adurl=http://www.sanfranciscoluxuryhotels.com/
  def get(self):
    self.response.out.write("OK") 

class TestHandler(webapp.RequestHandler):
  # /m/open?v=1&udid=26a85bc239152e5fbc221fe5510e6841896dd9f8&q=Hotels:%20Hotel%20Utah%20Saloon%20&id=agltb3B1Yi1pbmNyDAsSBFNpdGUY6ckDDA&r=http://googleads.g.doubleclick.net/aclk?sa=l&ai=BN4FhRH6hTIPcK5TUjQT8o9DTA7qsucAB0vDF6hXAjbcB4KhlEAEYASDgr4IdOABQrJON3ARgyfb4hsijoBmgAbqxif8DsgERYWRzLm1vcHViLWluYy5jb226AQkzMjB4NTBfbWLIAQHaAbwBaHR0cDovL2Fkcy5tb3B1Yi1pbmMuY29tL20vYWQ_dj0xJmY9MzIweDUwJnVkaWQ9MjZhODViYzIzOTE1MmU1ZmJjMjIxZmU1NTEwZTY4NDE4OTZkZDlmOCZsbD0zNy43ODM1NjgsLTEyMi4zOTE3ODcmcT1Ib3RlbHM6JTIwSG90ZWwlMjBVdGFoJTIwU2Fsb29uJTIwJmlkPWFnbHRiM0IxWWkxcGJtTnlEQXNTQkZOcGRHVVk2Y2tEREGAAgGoAwHoA5Ep6AOzAfUDAAAAxA&num=1&sig=AGiWqtx2KR1yHomcTK3f4HJy5kk28bBsNA&client=ca-mb-pub-5592664190023354&adurl=http://www.sanfranciscoluxuryhotels.com/
  def get(self):
    from ad_server.networks.greystripe import GreyStripeServerSide
    from ad_server.networks.millennial import MillennialServerSide
    from ad_server.networks.brightroll import BrightRollServerSide
    from ad_server.networks.jumptap import JumptapServerSide
    from ad_server.networks.mobfox import MobFoxServerSide
    key = self.request.get('id') or 'agltb3B1Yi1pbmNyCgsSBFNpdGUYAgw'
    delay = self.request.get('delay') or '5'
    delay = int(delay)
    adunit = Site.get(key)
    server_side = MobFoxServerSide(self.request,adunit)
    logging.warning("%s\n%s"%(server_side.url,server_side.payload))
    
    rpc = urlfetch.create_rpc(delay) # maximum delay we are willing to accept is 1000 ms

    payload = server_side.payload
    if payload == None:
      urlfetch.make_fetch_call(rpc, server_side.url, headers=server_side.headers)
    else:
      urlfetch.make_fetch_call(rpc, server_side.url, headers=server_side.headers, method=urlfetch.POST, payload=payload)


    # ... do other things ...

    try:
        result = rpc.get_result()
        if result.status_code == 200:
            bid,response = server_side.bid_and_html_for_response(result)
            self.response.out.write("%s<br/> %s %s"%(server_side.url+'?'+payload if payload else '',bid,response))
    except urlfetch.DownloadError:
      self.response.out.write("%s<br/> %s"%(server_side.url,"response not fast enough"))
      
  def post(self):
    logging.info("%s"%self.request.headers["User-Agent"])  
    self.response.out.write("hello world")

# TODO: clears the cache USE WITH FEAR
class ClearHandler(webapp.RequestHandler):
  def get(self):
    self.response.out.write(memcache.flush_all())
    
class PurchaseHandler(webapp.RequestHandler):
  def post(self):
    logging.info(self.request.get("receipt"))
    logging.info(self.request.get("udid"))
    self.response.out.write("OK")    
    

def main():
  application = webapp.WSGIApplication([('/m/ad', AdHandler), 
                                        ('/m/imp', AdImpressionHandler),
                                        ('/m/aclk', AdClickHandler),
                                        ('/m/open', AppOpenHandler),
                                        ('/m/track', AppOpenHandler),
                                        ('/m/test', TestHandler),
                                        ('/m/clear', ClearHandler),
                                        ('/m/purchase', PurchaseHandler)], 
                                        debug=True)
  run_wsgi_app(application)
  # wsgiref.handlers.CGIHandler().run(application)

# webapp.template.register_template_library('filters')
if __name__ == '__main__':
  main()
