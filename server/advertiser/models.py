from google.appengine.ext import db
from google.appengine.ext.db import polymodel

#
# A campaign.  Campaigns have budgetary and time based restrictions.  
#	
class Campaign(db.Model):
	name = db.StringProperty()
	description = db.TextProperty()

  # daily budget in USD
	budget = db.FloatProperty()	
	
	# start and end dates	
	start_date = db.DateProperty()
	end_date = db.DateProperty()
	
	active = db.BooleanProperty(default=True)
	deleted = db.BooleanProperty(default=False)
	
	# who owns this
	u = db.UserProperty()	
	t = db.DateTimeProperty(auto_now_add=True)
	
#
# An ad group, which specifies targeting and relevant behavior
#
class AdGroup(db.Model):
	campaign = db.ReferenceProperty(Campaign)
	name = db.StringProperty()
	
	# the priority level at which this ad group should be auctioned
	priority_level = db.IntegerProperty(default=1)

	bid = db.FloatProperty()
	bid_strategy = db.StringProperty(choices=["cpc", "cpm", "cpa"], default="cpc")

  # state of this ad group
	active = db.BooleanProperty(default=True)
	deleted = db.BooleanProperty(default=False)
	
	# Geographic preferences are expressed as string tuples that can match
	# the city, region or country that is resolved via reverse geocode at 
	# request time.  If the list is blank, any value will match. If the list
	# is not empty, the value must match one of the elements of the list.
	# 
	# Valid predicates are:
	# city_name=X,region_name=X,country_name=X
	# region_name=X,country_name=X
	# country_name=X
	# zipcode=X
	#
	# Each incoming request will be matched against all of these combinations
	geo_predicates = db.StringListProperty(default=["country_name=*"])
	
	# Device and platform preferences are listed similarly:
	#
	# model_name=X,brand_name=X
	# brand_name=X,platform_name=X
	# platform_name=X
	device_predicates = db.StringListProperty(default=["platform_name=*"])
	
	# all keyword and category bids are tracked here
	# categories use the category:games convention
	# if any of the input keywords match the n-grams here then we 
	# trigger a match
	keywords = db.StringListProperty()

	# all placements that are considered for this ad group
	# this is a list of keys corresponding to Site objects
	site_keys = db.ListProperty(db.Key)

	def __repr__(self):
		return "AdGroup:'%s'" % self.name

class Creative(polymodel.PolyModel):
  ad_group = db.ReferenceProperty(AdGroup)

  active = db.BooleanProperty(default=True)
  deleted = db.BooleanProperty(default=False)

  # the creative type helps the ad server render the right thing if the creative wins the auction
  ad_type = db.StringProperty(choices=["text", "image", "iAd", "adsense", "admob", "clear"], default="text")

  # destination URLs
  url = db.StringProperty()
  display_url = db.StringProperty()

  # format predicates - the set of formats that this creative can match
  # e.g. format=320x50
  # e.g. format=*
  format_predicates = db.StringListProperty(default=["format=*"])	

  # time of creation
  t = db.DateTimeProperty(auto_now_add=True)

  # calculates the eCPM for this creative, based on 
  # the CPM bid for the ad group or the CPC bid for the ad group and the predicted CTR for this
  # creative
  def e_cpm(self):
    if self.ad_group.bid_strategy == 'cpc':
      return self.p_ctr() * self.ad_group.bid * 1000
    elif self.ad_group.bid_strategy == 'cpm':
      return self.ad_group.bid

  # predicts a CTR for this ad.  We use 1% for now.
  # TODO: implement this in a better way
  def p_ctr(self):
    return 0.01

  def __repr__(self):
    return "Creative{ad_type=%s, eCPM=%.02f}" % (self.ad_type, self.e_cpm())

class TextCreative(Creative):
  # text ad properties
  headline = db.StringProperty()
  line1 = db.StringProperty()
  line2 = db.StringProperty()
  
  def __repr__(self):
    return "'%s'" % (self.headline,)

class ImageCreative(Creative):
  # image properties
  image = db.BlobProperty()
  image_width = db.IntegerProperty()
  image_height = db.IntegerProperty()

  @classmethod
  def get_format_predicates_for_image(c, img):
    IMAGE_PREDICATES = {"300x250": "format=300x250", 
    	"320x50": "format=320x50", 
    	"300x50": "format=320x50", 
    	"728x90": "format=728x90",
    	"468x60": "format=468x60"}
    fp = IMAGE_PREDICATES.get("%dx%d" % (img.width, img.height))
    return [fp] if fp else None

class iAdCreative(Creative):
  def __init__(self):
    super(ad_type="iAd", format_predicates=["format=320x50"])
    
class AdSenseCreative(Creative):
  def __init__(self):
    super(ad_type="adsense", format_predicates=["format=*"])

class AdMobCreative(Creative):
  def __init__(self):
    super(ad_type="admob", format_predicates=["format=320x50"])
    
class NullCreative(Creative):
  def __init__(self):
    super(ad_type="clear", format_predicates=["format=*"])
  