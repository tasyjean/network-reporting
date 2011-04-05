from google.appengine.ext import db
from advertiser.models import Campaign
import logging

DEFAULT_TIMESLICES = 1440.0 # Timeslices per day
DEFAULT_FUDGE_FACTOR = 0.1

class BudgetSlicer(db.Model):
    
    campaign = db.ReferenceProperty(Campaign)
    timeslice_snapshot = db.FloatProperty()
    daily_snapshot = db.FloatProperty()
  

    @property
    def timeslice_budget(self):
        return self.campaign.budget / DEFAULT_TIMESLICES * (1.0 + DEFAULT_FUDGE_FACTOR)

    def __init__(self, parent=None, key_name=None, **kwargs):
        if not key_name and not kwargs.get('key', None):
            # We are not coming from database
            campaign = kwargs.get('campaign',None)
            if campaign:
                key_name = self.get_key_name(campaign)
                if campaign.budget:
                    timeslice_snapshot = (campaign.budget / 
                                                DEFAULT_TIMESLICES * 
                                                (1.0 + DEFAULT_FUDGE_FACTOR))
                                            
                    kwargs.update(daily_snapshot = campaign.budget)
                    kwargs.update(timeslice_snapshot = timeslice_snapshot)
                
        super(BudgetSlicer, self).__init__(parent=parent,
                                           key_name=key_name,
                                            **kwargs)

    @classmethod
    def get_key_name(cls, campaign):
        if isinstance(campaign,db.Model):
            campaign = campaign.key()
        return "k:"+str(campaign)
        
    @classmethod
    def get_by_campaign(cls, campaign):
        return cls.get_by_key_name(cls.get_key_name(campaign))
        

    @classmethod
    def get_db_key(cls, campaign):
        return Key.from_path(cls.kind(), cls.get_key_name(campaign))
        
    @classmethod
    def get_or_insert_for_campaign(cls,campaign,**kwargs):
        key_name = cls.get_key_name(campaign)
        kwargs.update(campaign=campaign)
        
        def _txn(campaign):
            obj = cls.get_by_campaign(campaign)
            if not obj:
                obj = BudgetSlicer(**kwargs)
                obj.put()
            return obj
        return db.run_in_transaction(_txn,campaign)        

class BudgetSliceLog(db.Model):
      budget_slicer = db.ReferenceProperty(BudgetSlicer,collection_name="timeslice_logs")
      initial_memcache_budget = db.FloatProperty()
      final_memcache_budget = db.FloatProperty()
      remaining_daily_budget = db.FloatProperty()
      end_date = db.DateTimeProperty()
      
      @property
      def spending(self):
          return self.initial_memcache_budget - self.final_memcache_budget

class BudgetDailyLog(db.Model):
    budget_slicer = db.ReferenceProperty(BudgetSlicer,collection_name="daily_logs")
    remaining_daily_budget = db.FloatProperty()
    end_datetime = db.DateTimeProperty()
    date = db.DateProperty

    @property
    def spending(self):
        return self.budget_slicer.campaign.budget - self.remaining_daily_budget