import logging, os, time
from optparse import OptionParser

from boto.emr.connection import EmrConnection
from boto.emr.step import StreamingStep

from parse_utils import gen_days, gen_report_fname, get_waiting_jobflow
from parse_utils import AWS_ACCESS_KEY, AWS_SECRET_KEY

S3_BUCKET = 's3://mopub-aws-logging'
LOG_URI = S3_BUCKET + '/jobflow_logs/AAreports'  

REPORTING_S3_CODE_DIR = S3_BUCKET + '/reports_code0'

REPORT_MAPPER = REPORTING_S3_CODE_DIR + '/%s_%s_%s_report_mapper.py'
LOG_REDUCER = REPORTING_S3_CODE_DIR + '/log_reducer.py'

ACCOUNT_DIR = S3_BUCKET + '/account_data'


NUM_INSTANCES = 1
MASTER_INSTANCE_TYPE = 'm1.large'
SLAVE_INSTANCE_TYPE = 'm1.large'
KEEP_ALIVE = False

def build_puts(start, end, account):
    input_dir = ACCOUNT_DIR + ('/%s/daily_logs' % account)
    output_dir = ACCOUNT_DIR + ('/%s/reports' % account)

    days = gen_days(start, end)
    input_files = ['log+%s+%s+.adv.lc.stats' % (day.strftime('%y%m%d'), account) for day in days]
    inputs = [input_dir + '/' + file for file in input_files]
    return (inputs, output_dir)


def submit_job(d1, d2, d3, start, end, report_key, account):
    conn = EmrConnection(AWS_ACCESS_KEY, AWS_SECRET_KEY)

    inputs, output_dir = build_puts(start, end, account)
    print inputs
    print output_dir
    instances = 10
    output_name = gen_report_fname(d1, d2, d3, start, end)
    start = start.strftime('%y%m%d')
    end = end.strftime('%y%m%d')

    output = output_dir + '/' + output_name

    gen_report_step = StreamingStep(
            name = 'Generate Report Step',
            mapper = REPORT_MAPPER % (d1, d2, d3),
            reducer = LOG_REDUCER,
            cache_files = [REPORTING_S3_CODE_DIR + '/parse_utils.py#parse_utils.py'],
            input = inputs,
            output = output,
            )

    steps_to_add = [gen_report_step]
    jobid, steps = get_waiting_jobflow(conn)
    jobid = None
    if jobid:
        conn.add_jobflow_steps(jobid, steps_to_add)
    else:
        jobid = conn.run_jobflow(
                name = 'generating report job',
                steps = steps_to_add,
                log_uri = LOG_URI,
                num_instances = instances,
                master_instance_type = MASTER_INSTANCE_TYPE,
                slave_instance_type = SLAVE_INSTANCE_TYPE,
                keep_alive=KEEP_ALIVE,
                enable_debugging=True,
                )
    return jobid, steps, output_name

    while True:
        state = conn.describe_jobflow(jobid).state
        if state in [u'COMPLETED', u'TERMINATED', u'WAITING']:
            return True
        elif state in [u'FAILED']:
            return False
        else:
            time.sleep(10)



