import logging, os, re, datetime, hashlib

from urllib import urlencode

import base64, binascii
from google.appengine.api import users, memcache, images
from google.appengine.api.urlfetch import fetch
from google.appengine.ext import db
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.core.urlresolvers import reverse
from common.ragendja.template import render_to_response, JSONResponse

# from common.ragendja.auth.decorators import google_login_required as login_required
from common.utils.decorators import whitelist_login_required

from advertiser.models import *
from advertiser.forms import CampaignForm, AdGroupForm

from publisher.models import Site, Account, App
from reporting.models import SiteStats

from common.utils.cachedquerymanager import CachedQueryManager

from account.query_managers import AccountQueryManager
from advertiser.query_managers import CampaignQueryManager, AdGroupQueryManager, \
                                      CreativeQueryManager
from publisher.query_managers import AdUnitQueryManager, AppQueryManager
from reporting.query_managers import SiteStatsQueryManager

class RequestHandler(object):
    def __call__(self,request,*args,**kwargs):
        self.params = request.POST or request.GET
        self.request = request
        self.account = None
        user = users.get_current_user()
        if user:
          if users.is_current_user_admin():
            account_key_name = request.COOKIES.get("account_impersonation",None)
            if account_key_name:
              self.account = AccountQueryManager().get_by_key_name(account_key_name)
        if not self.account:  
          self.account = Account.current_account()
          
        if request.method == "GET":
            return self.get(*args,**kwargs)
        elif request.method == "POST":
            return self.post(*args,**kwargs)    
    def get(self):
        pass
    def put(self):
        pass  

class IndexHandler(RequestHandler):
  def get(self):
    days = SiteStats.lastdays(14)

    campaigns = CampaignQueryManager().get_campaigns(account=self.account)
    today = SiteStats()
    for c in campaigns:
      c.all_stats = SiteStatsQueryManager.get_sitestats_for_days(owner=c, days=days)      
      c.stats = reduce(lambda x, y: x+y, c.all_stats, SiteStats())
      today += c.all_stats[-1]
            
    # compute rollups to display at the top
    totals = [reduce(lambda x, y: x+y, stats, SiteStats()) for stats in zip(*[c.all_stats for c in campaigns])]
    
    promo_campaigns = filter(lambda x: x.campaign_type in ['promo'], campaigns)
    garauntee_campaigns = filter(lambda x: x.campaign_type in ['gtee'], campaigns)
    network_campaigns = filter(lambda x: x.campaign_type in ['network'], campaigns)

    help_text = None
    if network_campaigns:
      if not (self.account.adsense_pub_id or self.account.admob_pub_id):
        help_text = 'Provide your ad network publisher IDs on the <a href="%s">account page</a>'%reverse('account_index')

    return render_to_response(self.request, 
      'advertiser/index.html', 
      {'campaigns':campaigns, 
       'today': today,
       'gtee': garauntee_campaigns,
       'promo': promo_campaigns,
       'network': network_campaigns,
       'helptext':help_text })
      
@whitelist_login_required     
def index(request,*args,**kwargs):
    return IndexHandler()(request,*args,**kwargs)     

class AdGroupIndexHandler(RequestHandler):
  def get(self):
    days = SiteStats.lastdays(14)

    app = AppQueryManager().get_apps(account=self.account)
    all_apps = None
    site = None
    all_sites = None
    campaigns = CampaignQueryManager().get_campaigns(account=self.account)
    if campaigns:
      adgroups = AdGroupQueryManager().get_adgroups(campaigns=campaigns)
    else:
      # TODO: Convert to QueryManager, why is this here anyway?
      campaigns = Campaign.gql("where u = :1 and deleted = :2", self.account.user, False).fetch(100)
      adgroups = AdGroup.gql("where campaign in :1 and deleted = :2", [x.key() for x in campaigns], False).fetch(100)
    adgroups = sorted(adgroups, lambda x,y: cmp(y.bid, x.bid))
    
    today = SiteStats()
    for c in adgroups:
      c.all_stats = SiteStatsQueryManager().get_sitestats_for_days(owner=c, days=days)      
      c.stats = reduce(lambda x, y: x+y, c.all_stats, SiteStats())
      today += c.all_stats[-1]

    # compute rollups to display at the top
    daily_totals = [reduce(lambda x, y: x+y, stats, SiteStats()) for stats in zip(*[c.all_stats for c in adgroups])]
    totals = reduce(lambda x,y: x+y, daily_totals, SiteStats())

    promo_campaigns = filter(lambda x: x.campaign.campaign_type in ['promo'], adgroups)
    guarantee_campaigns = filter(lambda x: x.campaign.campaign_type in ['gtee'], adgroups)
    network_campaigns = filter(lambda x: x.campaign.campaign_type in ['network'], adgroups)
    
    help_text = None
    if network_campaigns:
      if not (self.account.adsense_pub_id or self.account.admob_pub_id):
        help_text = 'Provide your ad network publisher IDs on the <a href="%s">account page</a>'%reverse('account_index')

    return render_to_response(self.request, 
      'advertiser/adgroups.html', 
      {'adgroups':adgroups,
       'start_date': days[0],
       'app' : app,
       'all_apps' : all_apps,
       'site' : site,
       'all_sites' : all_sites,
       'today': today,
       'totals':totals,
       'gtee': guarantee_campaigns,
       'promo': promo_campaigns,
       'network': network_campaigns,
       'account': self.account,
       'helptext':help_text })

@whitelist_login_required     
def adgroups(request,*args,**kwargs):
    return AdGroupIndexHandler()(request,*args,**kwargs)

class CreateHandler(RequestHandler):
  def get(self,campaign_form=None, adgroup_form=None):
    campaign_form = campaign_form or CampaignForm()
    adgroup_form = adgroup_form or AdGroupForm()
    networks = [["adsense","Google AdSense",False],["iAd","Apple iAd",False],["admob","AdMob",False],["millennial","Millennial Media",False],["inmobi","InMobi",False],["greystripe","GreyStripe",False],["appnexus","App Nexus",False],["brightroll","BrightRoll",False],["custom","Custom",False]]
    all_adunits = AdUnitQueryManager().get_adunits(account=self.account)
    adgroup_form['site_keys'].queryset = all_adunits

    adunit_keys = adgroup_form['site_keys'].value or []
    for adunit in all_adunits:
      adunit.checked = unicode(adunit.key()) in adunit_keys
      adunit.app = App.get(adunit.app_key.key())
    logging.warning("bid: %s"%adgroup_form['bid'].value)
    campaign_form.add_context(dict(networks=networks))
    adgroup_form.add_context(dict(all_adunits=all_adunits))

    return render_to_response(self.request,'advertiser/new.html', {"campaign_form": campaign_form, 
                                                                   "adgroup_form": adgroup_form,
                                                                   "networks": networks,
                                                                   "all_adunits": all_adunits})

  def post(self):
    campaign_form = CampaignForm(data=self.request.POST)
    adgroup_form = AdGroupForm(data=self.request.POST)
    if campaign_form.is_valid():
      campaign = campaign_form.save(commit=False)
      campaign.u = self.account.user
      CampaignQueryManager().put_campaigns(campaign)
      
      if adgroup_form.is_valid():
        adgroup = adgroup_form.save(commit=False)
        adgroup.campaign = campaign
        AdGroupQueryManager().put_adgroups(adgroup)        
        return HttpResponseRedirect(reverse('advertiser_adgroup_new', kwargs={'campaign_key':campaign.key()}))

    return self.get(campaign_form,adgroup_form)

@whitelist_login_required     
def campaign_adgroup_create(request,*args,**kwargs):
  return CreateHandler()(request,*args,**kwargs)      

class CreateAdGroupHandler(RequestHandler):
  def get(self, campaign_key=None, adgroup_key=None, edit=False, title="Create an Ad Group"):
    if campaign_key:
      c = CampaignQueryManager().get_by_key(campaign_key)
      adgroup = AdGroup(name="%s Ad Group" % c.name, campaign=c, bid_strategy="cpm", bid=10.0, percent_users=100.0)
    if adgroup_key:
      adgroup = AdGroupQueryManager().get_by_key(adgroup_key)
      c = adgroup.campaign
      if not adgroup:
        raise Http404("AdGroup does not exist")  
    adgroup.budget = adgroup.budget or c.budget # take budget from campaign for the time being
    f = AdGroupForm(instance=adgroup)
    adunits = AdUnitQueryManager().get_adunits(account=self.account)
    
    # allow the correct sites to be checked
    for adunit in adunits:
      adunit.checked = adunit.key() in adgroup.site_keys
      adunit.app = App.get(adunit.app_key.key())
			
		# TODO: Clean up this hacked shit	
    networks = [["adsense","Google AdSense",False],["iAd","Apple iAd",False],["admob","AdMob",False],["millennial","Millennial Media",False],["inmobi","InMobi",False],["greystripe","GreyStripe",False],["appnexus","App Nexus",False],["brightroll","BrightRoll",False],["custom","Custom",False]]
    for n in networks:
      if adgroup.network_type == n[0]:
        n[2] = True

    return render_to_response(self.request,'advertiser/new_adgroup.html', {"f": f, "c": c, "sites": adunits, "title": title, "networks":networks})

  def post(self, campaign_key=None,adgroup_key=None, edit=False, title="Create an Ad Group"):
    if adgroup_key:
      adgroup = AdGroupQueryManager().get_by_key(adgroup_key)
    else:
      adgroup = None  
    orig_site_keys = set(adgroup.site_keys) if adgroup else set()
    f = AdGroupForm(data=self.request.POST,instance=adgroup)
    if f.is_valid():
      adgroup = f.save(commit=False)
      adgroup.campaign = CampaignQueryManager().get_by_key(self.request.POST.get("id"))
      adgroup.keywords = filter(lambda k: len(k) > 0, self.request.POST.get('keywords').lower().replace('\r','\n').split('\n'))
      adgroup.site_keys = map(lambda x: db.Key(x), self.request.POST.getlist('sites'))
      AdGroupQueryManager().put_adgroups(adgroup)
    
      updated_site_keys = orig_site_keys.union(set(adgroup.site_keys))
    
      # update cache
      if updated_site_keys:
        adunits = AdUnitQueryManager().get_by_key(list(updated_site_keys))
        CachedQueryManager().cache_delete(adunits)
     
      # if the campaign is a network type, automatically populate the right creative and go back to
      # campaign page
      if adgroup.campaign.campaign_type == "network":
        if not edit:
          creative = adgroup.default_creative()
          CreativeQueryManager().put_creatives(creative)
        else:
          creatives = CreativeQueryManager().get_creatives(adgroup=adgroup)
          creative = creatives[0]
          if adgroup.network_type in ['millenial','inmobi','appnexus']:
            creative.ad_type = 'html'
          elif adgroup.network_type in ['brightroll']:
            creative.ad_type = "html_full"
          else:
            creative.ad_type = adgroup.network_type
          CreativeQueryManager().put_creatives(creative)
    else:
      logging.info("errors: %s"%f.errors)
      asdf1234    
    return HttpResponseRedirect(reverse('advertiser_adgroup_show',kwargs={'adgroup_key':str(adgroup.key())}))
       
@whitelist_login_required     
def campaign_adgroup_new(request,*args,**kwargs):
  return CreateAdGroupHandler()(request,*args,**kwargs)      

@whitelist_login_required
def campaign_adgroup_edit(request,*args,**kwargs):
  kwargs.update(title="Edit Ad Group",edit=True)
  return CreateAdGroupHandler()(request,*args,**kwargs)  
  

class ShowHandler(RequestHandler):          
  def get(self, campaign_key):
    days = SiteStats.lastdays(14)

    # load the campaign
    campaign = CampaignQueryManager.get_by_key(campaign_key)
    
    # load the adgroups
    bids = AdGroupQueryManager().get_campaigns(campaign=campaign)
    bids.sort(lambda x,y:cmp(x.priority_level, y.priority_level))
    for b in bids:
      b.all_stats = SiteStatsQueryManager.get_sitestats_for_days(owner=b, days=days)      
      b.stats = reduce(lambda x, y: x+y, b.all_stats, SiteStats())

    # no ad groups?
    if len(bids) == 0:
      return HttpResponseRedirect(reverse('advertiser_adgroup_new', kwargs={'campaign_key': campaign.key()}))
    else:
      # compute rollups to display at the top
      today = SiteStats.rollup_for_day(bids, SiteStats.today())
      totals = [reduce(lambda x, y: x+y, stats, SiteStats()) for stats in zip(*[b.all_stats for b in bids])]
      
      help_text = None
      if campaign.campaign_type == 'network':
        if not (self.account.adsense_pub_id or self.account.admob_pub_id):
          help_text = 'Provide your ad network publisher IDs on the <a href="%s">account page</a>'%reverse('account_index')

      
      # write response
      return render_to_response(self.request,'advertiser/show.html', 
                                            {'campaign':campaign, 
                                            'bids': bids,
                                            'today': today,
                                            'user':self.account,
                                            'helptext':help_text})

@whitelist_login_required     
def campaign_show(request,*args,**kwargs):
 return ShowHandler()(request,*args,**kwargs) 

class EditHandler(RequestHandler):
  def get(self,campaign_key):
    c = CampaignQueryManager().get_by_key(campaign_key)
    f = CampaignForm(instance=c)
    return render_to_response(self.request,'advertiser/edit.html', {"f": f, "campaign": c})

  def post(self):
    c = CampaignQueryManager().get_by_key(self.request.POST.get('id'))
    f = CampaignForm(data=self.request.POST, instance=c)
    if c.u == self.account.user:
      f.save(commit=False)
      CampaignQueryManager().put_campaigns(c)
      return HttpResponseRedirect(reverse('advertiser_campaign_show',kwargs={'campaign_key':c.key()}))

@whitelist_login_required  
def campaign_edit(request,*args,**kwargs):
  return EditHandler()(request,*args,**kwargs)

class PauseHandler(RequestHandler):
  def post(self):
    action = self.request.POST.get("action", "pause")
    updated_campaigns = []
    for id_ in self.request.POST.getlist('id') or []:
      c = CampaignQueryManager().get_by_key(id_)
      updated_campaigns.append(c)
      update_objs = []
      if c != None and c.u == self.account.user:
        if action == "pause":
          c.active = False
          c.deleted = False
          update_objs.append(c)
        elif action == "resume":
          c.active = True
          c.deleted = False
          update_objs.append(c)
        elif action == "delete":
          # 'deletes' adgroups and creatives
          c.active = False
          c.deleted = True
          update_objs.append(c)
          for adgroup in c.adgroups:
            adgroup.deleted = True
            update_objs.append(adgroup)
            for creative in adgroup.creatives:
              creative.deleted = True
              update_objs.append(creative)
      if update_objs: 
        db.put(update_objs)   
        adgroups = AdGroupQueryManager().get_adgroups(campaigns=updated_campaigns)
        adunits = []
        for adgroup in adgroups:
          adunits.extend(adgroups.site_keys)
        adunits = AdUnitQueryManager().get_by_key(adunits)  
        CachedQueryManager().put(adunits)
    return HttpResponseRedirect(reverse('advertiser_campaign',kwargs={}))
  
@whitelist_login_required
def campaign_pause(request,*args,**kwargs):
  return PauseHandler()(request,*args,**kwargs)
  
class ShowAdGroupHandler(RequestHandler):
  def get(self, adgroup_key):
    days = SiteStats.lastdays(14)

    adgroup = AdGroupQueryManager().get_by_key(adgroup_key)
    
    logging.info("adgroup: %s"%adgroup.priority_level)
    
    # creatives = Creative.gql('where ad_group = :1 and deleted = :2 and ad_type in :3', adgroup, False, ["text", "image", "html"]).fetch(50)
    creatives = CreativeQueryManager().get_creatives(adgroup=adgroup)
    creatives = list(creatives)
    for c in creatives:
      c.all_stats = SiteStatsQueryManager().get_sitestats_for_days(owner=c, days=days)
      c.stats = reduce(lambda x, y: x+y, c.all_stats, SiteStats())
    
    apps = App.gql("where account = :1 and deleted = :2", self.account, False).fetch(50)
    for a in apps:
      if a.icon:
        a.icon_url = "data:image/png;base64,%s" % binascii.b2a_base64(a.icon)

    sites = map(lambda x: Site.get(x), adgroup.site_keys)
    for s in sites:
      s.all_stats = SiteStatsQueryManager().get_sitestats_for_days(site=s,owner=adgroup, days=days)
      s.stats = reduce(lambda x, y: x+y, s.all_stats, SiteStats())
      s.app = App.get(s.app_key.key())

    # compute rollups to display at the top
    today = SiteStatsQueryManager().get_sitestats_for_days(owner=adgroup, days=[SiteStats.today()])[0]
    if len(sites) > 0:
      all_totals = [reduce(lambda x, y: x+y, stats, SiteStats()) for stats in zip(*[s.all_stats for s in sites])]
    else:
      all_totals = [SiteStats() for d in days]

    totals = reduce(lambda x,y: x+y, all_totals, SiteStats())

    # In order to make the edit page
    f = AdGroupForm(instance=adgroup)
    all_adunits = AdUnitQueryManager().get_adunits(account=self.account)
    
    # allow the correct sites to be checked
    for adunit in all_adunits:
      adunit.checked = adunit.key() in adgroup.site_keys
      adunit.app = App.get(adunit.app_key.key())
    
    return render_to_response(self.request,'advertiser/adgroup.html', 
                              {'campaign': adgroup.campaign,
                              'apps': apps,
                              'adgroup': adgroup, 
                              'creatives': creatives,
                              'today': today,
                              'totals': totals,
                              'sites': sites, 
                              'adunits' : sites, # TODO: migrate over to adunit instead of site
                              'all_adunits' : all_adunits,
                              'start_date': days[0],
                              'f':f})
    
@whitelist_login_required   
def campaign_adgroup_show(request,*args,**kwargs):    
  return ShowAdGroupHandler()(request,*args,**kwargs)


class PauseAdGroupHandler(RequestHandler):
  def post(self):
    action = self.request.POST.get("action", "pause")
    adgroups = []
    for id_ in self.request.POST.getlist('id') or []:
      a = AdGroupQueryManager().get_by_key(id_)
      adgroups.append(a)
      update_objs = []
      if a != None and a.campaign.u == self.account.user:
        if action == "pause":
          a.active = False
          a.deleted = False
          update_objs.append(a)
        elif action == "resume":
          a.active = True
          a.deleted = False
          update_objs.append(a)
        elif action == "delete":
          a.active = False
          a.deleted = True
          update_objs.append(a)
          for creative in a.creatives:
            creative.deleted = True
            update_objs.append(creative)
      if update_objs:
        # db.put(update_objs)     
        AdGroupQueryManager().put_adgroups(update_objs)
        adunits = []
        for adgroup in adgroups:
          adunits.extend(adgroup.site_keys)
        adunits = Site.get(adunits)  
        CachedQueryManager().cache_delete(adunits)
         
    return HttpResponseRedirect(reverse('advertiser_campaign', kwargs={}))

@whitelist_login_required
def bid_pause(request,*args,**kwargs):
  return PauseAdGroupHandler()(request,*args,**kwargs)
  
# Creative management
#
class AddCreativeHandler(RequestHandler):
  def post(self):
    ad_group = AdGroupQueryManager().get_by_key(self.request.POST.get('id'))
    creative = None
    if self.request.POST.get("headline"):
      creative = TextCreative(ad_group=ad_group,
      headline=self.request.POST.get('headline'),
      line1=self.request.POST.get('line1'),
      line2=self.request.POST.get('line2'),
      url=self.request.POST.get('url'),
      display_url=self.request.POST.get('display_url'),
      tracking_url=self.request.POST.get('tracking_url'))
      creative.put()
    elif self.request.POST.get("line1"):
      creative = TextAndTileCreative()
      creative.ad_group=ad_group
      creative.ad_type="text_icon"
      creative.line1=self.request.POST.get('line1')
      creative.line2=self.request.POST.get('line2')
      creative.url=self.request.POST.get('url')
      if self.request.FILES.get('image'):
        img=images.resize(self.request.FILES.get("image").read(), 40, 40)
        creative.image=db.Blob(img)
      elif self.request.POST.get('app_img'):
        a=App.get(self.request.POST.get('app_img'))
        creative.image=a.icon
      creative.action_icon=self.request.POST.get('action_icon')
      creative.color=self.request.POST.get('color')
      creative.font_color=self.request.POST.get('font_color')
      if self.request.POST.get('gradient'):
        creative.gradient=True
      creative.put()
    elif self.request.FILES.get("image"):
      img = images.Image(self.request.FILES.get("image").read())
      fp = ImageCreative.get_format_predicates_for_image(img)
      if fp is not None:
        img.im_feeling_lucky()
        creative = ImageCreative(ad_group=ad_group,
                                  ad_type="image",
                                  format_predicates=fp,
                                  url=self.request.POST.get('url'),
                                  image=db.Blob(img.execute_transforms()),
                                  image_width=img.width,
                                  image_height=img.height,
                                  tracking_url=self.request.POST.get('tracking_url'))
    elif self.request.POST.get("html_name"):
      creative = HtmlCreative(ad_group=ad_group,
        ad_type="html",
        html_name=self.request.POST.get('html_name'),
        html_data=self.request.POST.get('html_data'),
        tracking_url=self.request.POST.get('tracking_url'))
    if creative:  
        CreativeQueryManager().put_creatives(creative)
    # update cache
    adunits = AdUnitQueryManager().get_by_key(ad_group.site_keys)
    CachedQueryManager().cache_delete(adunits)
      
    return HttpResponseRedirect(reverse('advertiser_adgroup_show',kwargs={'adgroup_key':ad_group.key()}))
  
@whitelist_login_required
def creative_create(request,*args,**kwargs):
  return AddCreativeHandler()(request,*args,**kwargs)  

class DisplayCreativeHandler(RequestHandler):
  def get(self, creative_key):
    c = CreativeQueryManager().get_by_key(creative_key)
    if c and c.ad_type == "image" and c.image:
      return HttpResponse(c.image,content_type='image/png')
    if c and c.ad_type == "text_icon" and c.image:
      return HttpResponse(c.image,content_type='image/png')
    if c and c.ad_type == "html":
      return HttpResponse("<html><body>"+c.html_data+"</body></html");
    return HttpResponse('NOOOOOOOOOOOO IMAGE')

def creative_image(request,*args,**kwargs):
  return DisplayCreativeHandler()(request,*args,**kwargs)

def creative_html(request,*args,**kwargs):
  return DisplayCreativeHandler()(request,*args,**kwargs)

class RemoveCreativeHandler(RequestHandler):
  def post(self):
    ids = self.request.POST.getlist('id')
    update_objs = []
    for creative_key in ids:
      c = CreativeQueryManager().get_by_key(creative_key)
      if c != None and c.ad_group.campaign.u == self.account.user:
        c.deleted = True
        update_objs.append(c)
        
        
    if update_objs:
      # db.put(update_objs)
      CreativeQueryManager().put_creatives(update_objs)
      
      # update cache
      adunits = AdUnitQueryManager().get_by_key(c.ad_group.site_keys)
      CachedQueryManager().cache_delete(adunits)
        
    return HttpResponseRedirect(reverse('advertiser_adgroup_show',kwargs={'adgroup_key':c.ad_group.key()}))

@whitelist_login_required  
def creative_delete(request,*args,**kwargs):
  return RemoveCreativeHandler()(request,*args,**kwargs)
