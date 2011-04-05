import logging
import time
from optparse import OptionParser

from boto.emr.connection import EmrConnection
from boto.emr.step import StreamingStep


S3_BUCKET = 'mopub-aws-logging'
LOG_URI = 's3://' + S3_BUCKET + '/jobflow_logs'
MAPPER = 's3://' + S3_BUCKET + '/code/log_mapper.py'
REDUCER = 's3://' + S3_BUCKET + '/code/log_reducer.py'


JOBFLOW_FILE = 'jobflow.txt'
NUM_INSTANCES = 1
MASTER_INSTANCE_TYPE = 'm1.small'
SLAVE_INSTANCE_TYPE = 'm1.small'
KEEP_ALIVE = True
    


def get_waiting_jobflow(conn):
    waiting_jobflow_ids = conn.describe_jobflows([u'WAITING'])
    if len(waiting_jobflow_ids) > 0:
        jobid = waiting_jobflow_ids[0].jobflowid
        print 'found waiting jobflow:', jobid
        return jobid
    else:
        return None

    
def main():
    start = time.time()
        
    parser = OptionParser()
    parser.add_option('-f', '--file', dest='logfile')
    parser.add_option('-n', '--num_instances', dest='num_instances', default=NUM_INSTANCES)
    (options, args) = parser.parse_args()
    
    conn = EmrConnection('AKIAJKOJXDCZA3VYXP3Q', 'yjMKFo61W0mMYhMgphqa+Lc2WX74+g9fP+FVeyoH')

    step = StreamingStep(
        name='logparser step',
        mapper=MAPPER,
        reducer=REDUCER,
        input=options.logfile,
        output=options.logfile+'.out',
    )
    
    # try to find an existing jobflow in waiting mode
    jobid = get_waiting_jobflow(conn)
    if jobid:
        conn.add_jobflow_steps(jobid, [step])
        print 'added step to waiting jobflow:', jobid
        
        # wait while jobflow is still in waiting mode
        while conn.describe_jobflow(jobid).state == u'WAITING':
            print '%s\tjob state: WAITING' % time.strftime('%b %d %Y %H:%M:%S')
            time.sleep(1)
    else:   # spin up a new jobflow    
        jobid = conn.run_jobflow(
            name='logparser job',
            steps=[step],
            log_uri=LOG_URI,
            num_instances=options.num_instances,
            master_instance_type=MASTER_INSTANCE_TYPE,
            slave_instance_type=SLAVE_INSTANCE_TYPE,
            keep_alive=KEEP_ALIVE,
            enable_debugging=True,
        )
        print 'submitted new jobflow:', jobid
        
    # check jobflow status periodically while it's active
    while True:
        state = conn.describe_jobflow(jobid).state
        print '%s\tjob state: %s' % (time.strftime('%b %d %Y %H:%M:%S'), state)
        if state in [u'COMPLETED', u'FAILED', u'TERMINATED', u'WAITING']:
            break
        else:
            time.sleep(10)

    
    elapsed = time.time() - start
    print "job %s took %i minutes and %i seconds" % (jobid, elapsed/60, elapsed%60)
    


if __name__ == "__main__":
    main()