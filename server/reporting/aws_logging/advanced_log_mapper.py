#!/usr/bin/python
import sys
from datetime import datetime

# for EMR so imported modules can be found within each task
sys.path.append('.')

import utils
from parse_utils import parse_logline


# [/m/ad,/ /m/req, /m/imp, /m/clk, /m/conv]

# return format:
# key:      k:adunit_id:creative_id:country_code:brand_name:marketing_name:device_os:device_os_version:time
# value:    [/m/ad count, /m/req count, /m/imp count, /m/clk count, /m/conv count]
def format_kv_pair(handler, param_dict, country_code, user_agent_info, date_hour):
    brand_name = user_agent_info.get('brand_name', utils.DEFAULT_VALUE)
    marketing_name = user_agent_info.get('marketing_name', utils.DEFAULT_VALUE)
    device_os = user_agent_info.get('device_os', utils.DEFAULT_VALUE)
    device_os_version = user_agent_info.get('device_os_version', utils.DEFAULT_VALUE)
           
    if handler == utils.AD:
        return 'k:%s:%s:%s:%s:%s:%s:%s:%s' % (param_dict.get('id'), '', country_code, brand_name, marketing_name, device_os, device_os_version, date_hour), '[1, 0, 0, 0, 0]'
    if handler == utils.REQ:
        return 'k:%s:%s:%s:%s:%s:%s:%s:%s' % (param_dict.get('id'), param_dict.get('cid'), country_code, brand_name, marketing_name, device_os, device_os_version, date_hour), '[0, 1, 0, 0, 0]'
    if handler == utils.IMP:
        return 'k:%s:%s:%s:%s:%s:%s:%s:%s' % (param_dict.get('id'), param_dict.get('cid'), country_code, brand_name, marketing_name, device_os, device_os_version, date_hour), '[0, 0, 1, 0, 0]'
    if handler == utils.CLK:
        return 'k:%s:%s:%s:%s:%s:%s:%s:%s' % (param_dict.get('id'), param_dict.get('cid'), country_code, brand_name, marketing_name, device_os, device_os_version, date_hour), '[0, 0, 0, 1, 0]'
    # /m/conv handler counting not implemented yet
    return None, None
        
    
# abstract out core logic on parsing on handler params; this function is used for both mrjob (local testing) and boto (remote EMR job)
def generate_kv_pairs(line):
    logline_dict = parse_logline(line)
    
    if logline_dict:
        handler = logline_dict.get('path')
        param_dict = logline_dict.get('params')
        country_code = logline_dict.get('country_code')
        user_agent_info = logline_dict.get('user_agent')
        
        # ex: 14/Mar/2011:15:04:09 -0700
        log_date = logline_dict.get('date')
        log_time = logline_dict.get('time')
        
        if None not in [handler, param_dict, country_code, user_agent_info, log_date, log_time]:
            try:
                # construct datetime object           
                date_hour = datetime.strptime(log_date + ':' + log_time, '%d/%b/%Y:%H:%M:%S')

                # resolution is hour
                hour_k, hour_v = format_kv_pair(handler, param_dict, country_code, user_agent_info, date_hour.strftime('%y%m%d%H'))

                if hour_k and 'None' not in hour_k:
                    return hour_k, hour_v
            except:
                return None, None
                
    return None, None
                


def main():
    try:
        for line in sys.stdin:
            hour_k, hour_v = generate_kv_pairs(line)
            if hour_k and hour_v:
                print "%s\t%s" % (hour_k, hour_v)
    except:
        pass


if __name__ == '__main__':
    main()
             
