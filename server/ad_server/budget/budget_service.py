from google.appengine.api import memcache
import datetime
from advertiser.models import ( Campaign,
                                AdGroup,
                                )
import logging
                        
"""
A service that determines if a campaign can be shown based upon the defined 
budget for that campaign. If the budget_type is "evenly", a minute by minute
timeslice-budget is kept as well. 
"""

TIMESLICES = 1440 #we use a default timeslice of one minute
TEST_MODE = False
SECONDS_PER_DAY = 86400
FUDGE_FACTOR = 0.1

test_timeslice = 0
test_daily_budget = 0


def has_budget(campaign, cost):
    """ Returns True if the cost is less than the budget in the current slice """
    campaign_daily_budget = campaign.budget
    
    key = _make_campaign_ts_budget_key(campaign)
    
    # If there is a cache miss, we fall back to the previous snapshot
    ts_init_budget = campaign.previous_budget_snapshot
    if ts_init_budget is None:
        ts_init_budget = _calculate_timeslice_initial_budget(campaign)
    # Add the budget every time, only is actually added the first
    memcache.add(key, _to_memcache_int(ts_init_budget),namespace="budget")
    
    if _get_memcache(campaign) >= cost:
        return True
    return False
    
  
def get_budget(campaign):
    key = _make_campaign_ts_budget_key(campaign)
    # logging.warning( "key: %s" % key )
    value = memcache.get(key, namespace="budget")
    if value is None:
        return None
    else:
        return _from_memcache_int(value)
    
def apply_expense(campaign, cost):
    """ Applies an expense to our memcache """
    key = _make_campaign_ts_budget_key(campaign)
    memcache.decr(key, _to_memcache_int(cost), namespace="budget")
    # TODO: Check for rollunder in devappserver
    

def advance_timeslice(campaign):
    """ Adds a new timeslice's worth of budget and pulls the budget
     expenditures into the database. Executed once per timeslice."""
    # If cache miss, assume that no budget has been spent
    mem_budget = get_budget(campaign)
    if mem_budget is None:
        # Use the snapshot from the beginning of this timeslice
        mem_budget = campaign.previous_budget_snapshot 

    
    # Back up in database.
    campaign.previous_budget_snapshot = mem_budget + campaign.timeslice_budget
    campaign.remaining_daily_budget -= campaign.timeslice_budget
    campaign.put()
    
    # Update in memory
    key = _make_campaign_ts_budget_key(campaign)
    memcache.incr(key, _to_memcache_int(campaign.timeslice_budget), namespace="budget")
    # TODO: Also do budget logging
    
        
def advance_all():
    campaigns = Campaign.all().fetch(100)
    # We use campaigns as an iterator
    for camp in campaigns:
        if camp.budget is not None:
            advance_timeslice(camp)   
   
def reset_all():
    campaigns = Campaign.all()#.filter("budget >=", 0)
    # We use campaigns as an iterator
    for camp in campaigns:
        if camp.budget is not None:
            daily_reset(camp)

def daily_reset(campaign):
    """ Resets the remaining_daily_budget and timeslice_budget values in the database.
    also resets values in memcache. TODO: Called when initialized and at midnight """
    # Flush from cache
    _delete_memcache(campaign)

    # Reset in db
    campaign.remaining_daily_budget = campaign.budget
    campaign.previous_budget_snapshot = 0.0
    campaign.timeslice_budget = campaign.budget / TIMESLICES * (1 + FUDGE_FACTOR) 
    campaign.put()
    
    # Give us a first timeslice's worth in memory
    advance_timeslice(campaign)
    # TODO: what happens to unspent daily budget?

def _apply_if_able(campaign, cost):
    """ For testing purposes """
    success = has_budget(campaign, cost)
    if success:
        apply_expense(campaign, cost)
    return success


def _make_campaign_ts_budget_key(campaign):
    """Returns a unique budget key based upon campaign.key """
    return 'budget:%s'%(campaign.key())
  
def _to_memcache_int(value):
    """multiplies by 10^5 and converts to an int"""
    return int(value*100000)
    
def _from_memcache_int(value):
    value = float(value)
    return value/100000

def _get_current_timeslice():
    """Returns the current timeslice. Could be used to trigger advance_timeslice"""
    #TODO: use it
    origin = datetime.datetime.combine(datetime.date.today(),
                                       datetime.time.min)
    now = datetime.datetime.now()
    seconds_elapsed = (now-origin).seconds
    # return seconds_elapsed/seconds_per_day*timeslices
    return int(seconds_elapsed*TIMESLICES/SECONDS_PER_DAY)


def _calculate_timeslice_initial_budget(campaign):
    """ Returns the initial budget each remaining timeslice should have. """
    # We use the current budget as a rollover
    rollover_key = _make_campaign_ts_budget_key(campaign)
    rollover_val = memcache.get(rollover_key, namespace="budget")
    
    if rollover_val is not None:
        rollover_budget = _from_memcache_int(rollover_val)
    else:
        #if cache miss, assume 0 expenses, if no budget in db, use 0
        rollover_budget = campaign.timeslice_budget or 0
    
    initial_budget = campaign.budget * (1 + FUDGE_FACTOR) / TIMESLICES
    budget = rollover_budget + initial_budget
    return budget


def _get_memcache(campaign):
    """ Does a raw get from memcache """
    key = _make_campaign_ts_budget_key(campaign)
    return memcache.get(key, namespace="budget")
   
def _set_memcache(campaign, val):
    key = _make_campaign_ts_budget_key(campaign)
    memcache.set(key, _to_memcache_int(val), namespace="budget")


def _delete_memcache(campaign):
    key = _make_campaign_ts_budget_key(campaign)
    memcache.delete(key, namespace="budget")
