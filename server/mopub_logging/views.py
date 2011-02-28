import logging
import datetime
import traceback
import sys

from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

from google.appengine.api import mail
from google.appengine.api import memcache

from reporting import models as r_models
from reporting import query_managers

from mopub_logging import mp_logging

MAX_KEYS = 100
MAX_TAIL = 10000

def increment_stats(stats):
    # datastore get
    key_name = stats.key()
    stats_obj = Counter.get_by_key(key_name)
    if stats_obj:
        stats_obj += stats
    else:
        stats_obj = stats    

    # datastore put
    logging.info("putting in key_name: %s value: %s,%s"%(key_name,stats.request_count,stats.impression_count))
    logging.info("putting in key_name: %s NEW value: %s,%s"%(key_name,stats_obj.request_count,stats_obj.impression_count))
    stats_obj.put()
    
def update_stats(stats_dict,publisher,advertiser,date_hour,attribute,req=None,incr=1):
    publisher = publisher or None
    advertiser = advertiser or None
    key = r_models.StatsModel.get_key_name(publisher=publisher,
                                           advertiser=advertiser,
                                           date_hour=date_hour)

    if not key in stats_dict:
      stats_dict[key] = r_models.StatsModel(publisher=publisher,
                                            advertiser=advertiser,
                                            date_hour=date_hour)

    if attribute:
      # stats_dict[key].attribute += incr
      setattr(stats_dict[key],attribute,getattr(stats_dict[key],attribute)+incr) 
    if req:      
      stats_dict[key].reqs.append(req)
    
class LogTaskHandler(webapp.RequestHandler):
  def get(self):
      # inspect headers of the task
      retry_count = self.request.headers.get('X-AppEngine-TaskRetryCount',None)
      
      # grab parameters from the message of the task
      account_name = self.request.get("account_name")
      time_bucket = int(self.request.get("time"))

      head_index = 1 # starts at one for a particular time_bucket

      # get the last index for a given time bucket
      tail_key = mp_logging.INDEX_KEY_FORMAT%dict(account_name=account_name,time=time_bucket)
      tail_index_str = memcache.get(tail_key)
      tail_index = int(tail_index_str or MAX_TAIL)

      logging.info("account: %s time: %s start: %s stop: %s"%(account_name,time_bucket,head_index,tail_index))

      stats_dict = {}      
      start = head_index
      # paginate the keys
      memcache_misses = 0
      
      while start <= tail_index: 
          # get another MAX_KEYS or go to the end
          stop = start + MAX_KEYS - 1 if (start+MAX_KEYS-1) < tail_index else tail_index
          keys = [mp_logging.LOG_KEY_FORMAT%dict(account_name=account_name,time=time_bucket,log_index=i) 
                   for i in range(start,stop+1)]

          logging.info("we have %d keys (start:%s stop:%s)"%(len(keys),start,stop))
          
          # grab logs from memcache         
          data_dicts = memcache.get_multi(keys) 
          memcache_misses += len(keys)-len(data_dicts)  
          logging.info("Memcache misses: %d"%(len(keys)-len(data_dicts)))

          for k,d in data_dicts.iteritems():
              if d:
                  uid = d.get('udid',None)
                  adunit = d.get('adunit',None)
                  creative = d.get('creative',None)
                  event = d.get('event',None)

                  req = d.get('req',None)
                  req = int(req) if req else None

                  inst = d.get('inst',None)
                  inst = int(inst) if inst else None

                  req = "%s.%s.%s"%(req,inst,time_bucket)

                  appid = d.get('appid',None)
                  
                  # calculate the datetime object to hour precision
                  now = int(float(d['now']))
                  hour = now-now%3600
                  date_hour = datetime.datetime.fromtimestamp(hour)

                  # attach on the request id once per log line
                  # update_stats(stats_dict,
                  #              publisher=adunit,
                  #              advertiser=None,
                  #              date_hour=date_hour,
                  #              attribute=None,
                  #              req=req)

                  if event == mp_logging.REQ_EVENT:
                      update_stats(stats_dict,
                                   publisher=adunit,
                                   advertiser=None,
                                   date_hour=date_hour,                                   
                                   attribute='request_count')
                  elif event == mp_logging.IMP_EVENT:
                      update_stats(stats_dict,
                                   publisher=adunit,
                                   advertiser=creative,
                                   date_hour=date_hour,
                                   attribute='impression_count')
                  if event == mp_logging.CLK_EVENT:
                      update_stats(stats_dict,
                                   publisher=adunit,
                                   advertiser=creative,
                                   date_hour=date_hour,
                                   attribute='click_count')
                  elif event == mp_logging.CONV_EVENT: 
                      update_stats(stats_dict,
                                   publisher=adunit,
                                   advertiser=creative,
                                   date_hour=date_hour,
                                   attribute='conversion_count')
              else:
                  logging.error("NO value for key %s exists"%k)    

          start += MAX_KEYS # proceed to the next "page"    

      query_manager = query_managers.StatsModelQueryManager(account_name)
      try:
          query_manager.put_stats(stats_dict.values())
      except:
          exception_traceback = ''.join(traceback.format_exception(*sys.exc_info()))
          mail.send_mail(sender="appenginescaletest@gmail.com",
                        to="nafis@mopub.com",
                        subject="Logging error",
                        body="%s"%(exception_traceback))
          logging.error(exception_traceback)
          raise Exception("need to try transaction again")
          
      if not tail_index_str or memcache_misses:
          exception_traceback = ''.join(traceback.format_exception(*sys.exc_info()))
          mail.send_mail(sender="appenginescaletest@gmail.com",
                        to="nafis@mopub.com",
                        subject="Logging error",
                        body="Account: %s time: %s tail: %s misses: %s retry: %s"%(account_name,time_bucket,tail_index_str,memcache_misses,retry_count))
          logging.error("Account: %s time: %s tail: %s misses: %s retry: %s"%(account_name,time_bucket,tail_index_str,memcache_misses,retry_count))
                

application = webapp.WSGIApplication([('/_ah/queue/bulk-log-processor', LogTaskHandler),
                                     ],
                                     debug=True)

def main():
    run_wsgi_app(application)

if __name__ == "__main__":
    main()