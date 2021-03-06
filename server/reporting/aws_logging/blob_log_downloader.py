import os
import sys
import time
import urllib2
import traceback

from datetime import datetime
from optparse import OptionParser

import multiprocessing
from multiprocessing.pool import ThreadPool


ROOT_DIR = '~/aws_logs/'
HOST = 'http://%s.latest.mopub-inc.appspot.com' % ('38-aws')
MAX_TRIES = 3
SLEEP_DELAY = 10

def get_json_for_hour(timestamp, start_key=None):
    if start_key:
        url = '%s/files/download?dh=%s&start_key=%s' % (HOST, timestamp, start_key) 
    else:
        url = '%s/files/download?dh=%s' % (HOST, timestamp)
        
    request = urllib2.Request(url)
    
    tries = 0
    while True:
        try:
            json = urllib2.urlopen(request).read()
            info = eval(json)
            print len(info['urls'])
            return info
        except KeyboardInterrupt:
            sys.exit('received control-c while getting json for hour')
        except:
            traceback.print_exc()
            tries += 1
            print 'try count:', tries
            if tries < MAX_TRIES:
                print 'sleeping for %i seconds...' % (SLEEP_DELAY)
                time.sleep(SLEEP_DELAY) # sleep 10 secs
            else:
                sys.exit('cannot download json: %s' %(e))
    
    
def download_blob_by_url(blob_url, dir_path, year, month_day, hour):
    tries = 0
    while True:
        try:
            url = HOST + blob_url
            request = urllib2.Request(url)
            blob = urllib2.urlopen(request).read()
        
            # ex: blob-log-2011-0622-1500-123456.blog
            file_name = '-'.join(['blob', 'log', year, month_day, hour, datetime.now().strftime('%f')]) + '.blog'
            abs_file_path = os.path.join(dir_path, file_name)
            with open(abs_file_path, 'w') as f:
                f.write(blob)
            return 'written to %s\n\turl: %s' % (abs_file_path, blob_url)
        except KeyboardInterrupt:
            sys.exit('thread received control-c')
        except:
            traceback.print_exc()
            tries += 1
            print 'try count: %i, url: %s' % (tries, blob_url)
            if tries < MAX_TRIES:
                print 'sleeping for %i seconds...' % (SLEEP_DELAY)
                time.sleep(SLEEP_DELAY) # sleep 10 secs
            else:
                return 'error for %s-%s-%s\n\turl: %s' % (year, month_day, hour, blob_url)
    

def download_blob_logs(pool, timestamp, url_list):
    root_dir = ROOT_DIR.replace('~', os.path.expanduser('~'))
    year = timestamp[:4]
    month_day = timestamp[4:8]
    hour = timestamp[-2:] + '00'
    
    day_dir = 'day-' + year + '-' + month_day
    hour_dir = 'hour-' + year + '-' + month_day + '-' + hour
    dir_path = os.path.join(root_dir, day_dir, hour_dir)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    
    async_results = [pool.apply_async(download_blob_by_url, (url, dir_path, year, month_day, hour)) for url in url_list]
    
    # print status message from each process
    print
    print
    for ar in async_results:
        print ar.get(0xFFFF)
    print
    print


def process_hour(timestamp, num_workers):
    url_list = []
    
    info = get_json_for_hour(timestamp)
    url_list.extend(info['urls'])
    
    while 'start_key' in info:
        info = get_json_for_hour(timestamp, info['start_key'])
        url_list.extend(info['urls'])
    print 'retrieved %i urls for hour %s' % (len(url_list), timestamp)
    
    pool = ThreadPool(processes=num_workers)
    try:
        download_blob_logs(pool, timestamp, url_list)
    except KeyboardInterrupt:
        sys.exit('controller received control-c')
    except:
        traceback.print_exc()
    

def main():
    start = time.time()

    parser = OptionParser()
    parser.add_option('-t', '--timestamp (YYYYMMDD or YYYYMMDDHH)', dest='timestamp')
    parser.add_option('-n', '--num_workers', type='int', dest='num_workers', default=multiprocessing.cpu_count())
    (options, args) = parser.parse_args()
        
    if not options.timestamp:
        sys.exit('timestamp must be specified')
    
    ts = options.timestamp
    
    if len(ts) == 10: # hour
        print 'processing hour %s with %i threads' % (ts, options.num_workers)
        process_hour(ts, options.num_workers)
    elif len(ts) == 8: # day
        print 'processing day %s with %i threads' % (ts, options.num_workers)
        for h in range(24): # simulate hours 00-23
            hour_ts = ts + '0' + str(h) if h < 10 else ts + str(h)
            process_hour(hour_ts, options.num_workers)
    else:
        sys.exit('timestamp format invalid; either YYYYMMDD or YYYYMMDDHH')
    
    elapsed = time.time() - start
    print "parallelized download of logs from blobstore for %s took %i minutes and %i seconds" % (ts, elapsed/60, elapsed%60)
    
        
if __name__ == '__main__':
    main()    
