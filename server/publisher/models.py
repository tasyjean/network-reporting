from google.appengine.ext import db
from google.appengine.api import users

from account.models import Account
from advertiser.models import Creative

# 
# A mobile app, which can have multiple Sites on which ads can be displayed
#
class App(db.Model):
  account = db.ReferenceProperty(Account)

  name = db.StringProperty(required=True)
  adsense_app_name = db.StringProperty()
  millennial_placement_id = db.StringProperty()
  
  app_type = db.StringProperty(required=True, default='iphone', choices=['iphone', 'android', 'ipad'])
  description = db.TextProperty()
  url = db.StringProperty()
  package = db.StringProperty()
  
  icon = db.BlobProperty()
  
  deleted = db.BooleanProperty(default=False)

  t = db.DateTimeProperty(auto_now_add=True)
  
  exchange_creative = db.ReferenceProperty(Creative)
  
  @property
  def owner(self):
      return None
  
  @property
  def owner_key(self):
      return None
  

class Site(db.Model):
  DEVICE_FORMAT_CHOICES = (
         u'phone',
         u'tablet',
     )
     
  FORMAT_CHOICES = (
        u'full',
        u'full_tablet',
        u'full_landscape',
        u'full_tablet_landscape',
        u'728x90',
        u'300x250',
        u'160x600',
        u'320x50',
    )
  app_key = db.ReferenceProperty(App)
  account = db.ReferenceProperty(Account)
  
  # TODO: figure out how to expose this
  adsense_channel_id = db.StringProperty()
  
  name = db.StringProperty(required=True,default='Banner Ad')
  url = db.StringProperty()
  description = db.TextProperty(required=True,default='General Purpose Banner Ad')
  width = db.FloatProperty()
  height = db.FloatProperty()

  
  device_format = db.StringProperty(default='phone', choices=DEVICE_FORMAT_CHOICES)
  format = db.StringProperty(choices=FORMAT_CHOICES) #TODO: we should use this w/o explicity using height, width

  deleted = db.BooleanProperty(default=False)
  
  # what kind of ad is preferred here
  ad_type = db.StringProperty(choices=['text', 'image'], default='image',required=False)
  
  # additional keywords that are passed to the auction
  keywords = db.TextProperty() # TODO: make sure this doesn't break shit
  # keywords = db.StringListProperty()                          
  
  refresh_interval = db.IntegerProperty(default=0)
  
  # color scheme
  color_border = db.StringProperty(required=True, default='336699')
  color_bg = db.StringProperty(required=True, default='FFFFFF')
  color_link = db.StringProperty(required=True, default='0000FF')
  color_text = db.StringProperty(required=True, default='000000')
  color_url = db.StringProperty(required=True, default='008000')
  
  # creation time
  t = db.DateTimeProperty(auto_now_add=True)
  
  # Allows the site to reject ads if their eCPM does not 
  # exceed a given threshold, on a per-priority level basis
  # TODO Make this actually do something 
  def threshold_cpm(self, priority_level):
    return 0
  
  def _get_app(self):
      return self.app_key
  def _set_app(self, value):
      self.app_key = value
  app = property(_get_app, _set_app)
    
    
  @classmethod
  def site_by_id(c, id):
    if id.startswith('ca'):
      account = Account.gql('where adsense_pub_id = :1', id).get()
      s = Site.gql('where account = :1', account).get()
    else:
      s = Site.get(id)      
    return s

  @property
  def owner(self):
      return self.app_key
  
  @property
  def owner_key(self):
      return self._app_key            
