import logging
import time
import random

from google.appengine.api import memcache
from google.appengine.api import taskqueue

from publisher.query_managers import AdUnitQueryManager

REQ_EVENT = 0
IMP_EVENT = 1
CLK_EVENT = 2
CONV_EVENT = 3

TASK_QUEUE_NAME = 'bulk-log-processor'

LOG_KEY_FORMAT = 'k:%(account_name)s:%(time)s:%(log_index)02d'
INDEX_KEY_FORMAT = 'k:%(account_name)s:%(time)s'
TASK_NAME = 't-%(account_name)s-%(time)s' # note time will be bucketed

TIME_BUCKET = 10
MEMCACHE_ALIVE_TIME = 0#6*TIME_BUCKET

REQ_QUEUE_NAME = "network-request-%02d"
NUM_REQ_QUEUES = 1


def log(request,event,adunit=None,creative=None,manager=None,adunit_id=None,creative_id=None,udid=None):
    
    # if this is the second request because of a 
    # native failure we just bail in order to 
    # Note if logging an adnetwork request, we pass
    # in request = None.
    if request:
        exclude_creatives = request.get_all("exclude")
        if exclude_creatives:
            return    

    # get parameters from the request or args
    adunit_id = adunit_id 
    if adunit:
        adunit_id = adunit_id or str(adunit.key()) 
    creative_id = creative_id 
    if creative:
        creative_id = creative_id or str(creative.key()) 
    
    if request:
        adunit_id = adunit_id or request.get('id', None)
        creative_id = creative_id or request.get('cid', None)
        udid = udid or request.get('udid', None)
        request_id = request.get('reqcnt',None)
        instance_id = request.get('inst',None)
    else:
        request_id = None
        instance_id = None
    
    # if trying to record the request of a adunit and creative
    # i.e. request of a network creative
    # we add a "fire-and-forget" taskqueue entry so that the
    # data shows up in the apache-style request logs    
    if adunit_id and creative_id and event == REQ_EVENT:
        logging.info("fire and forget--adunit: %s creative:%s"%(adunit_id,creative_id))
        task = taskqueue.Task(params=dict(id=adunit_id,cid=creative_id),
                              method='GET',
                              url='/m/req')
        queue_num = random.randint(0,NUM_REQ_QUEUES-1)                      
        queue_name = REQ_QUEUE_NAME%queue_num
        task.add(queue_name)
            
    # get account name from the adunit
    adunit_qmanager = manager or AdUnitQueryManager(adunit_id)
    adunit = adunit or adunit_qmanager.get_adunit()
    
    account_name = str(adunit.account.key())
    
    # calculate time bucket
    now = time.time()
    time_bucket = int(now)/TIME_BUCKET # maybe divide by 10 for every second
    
    
    # get the new index for this account and time bucket
    index_key = INDEX_KEY_FORMAT%dict(account_name=account_name,time=time_bucket)
    log_index = memcache.incr(index_key,initial_value=0) # starts at 1
    
    logging_data = dict(event=event,
                        adunit=adunit_id,
                        creative=creative_id,
                        now=now,
                        udid=udid,
                        req=request_id,
                        inst=instance_id)
    
    # put the log data into appropriate place
    log_key = LOG_KEY_FORMAT%dict(account_name=account_name,time=time_bucket,log_index=log_index)
    memcache.set(log_key,logging_data,time=MEMCACHE_ALIVE_TIME)
    logging.info("just put %s=%s"%(log_key,logging_data))
    
    # send to appropriately named task_queue
    task_name = TASK_NAME%dict(account_name=account_name,time=time_bucket)
    logging.info('task: %s'%task_name)
    
    try:
        t = taskqueue.Task(name=task_name,params={'account_name':account_name,'time':time_bucket},countdown=TIME_BUCKET*1.10,method='GET')
        t.add(TASK_QUEUE_NAME)
    except taskqueue.TaskAlreadyExistsError:
        logging.info("task %s already exists"%task_name)
    except Exception, e:    
        logging.warning(e)
