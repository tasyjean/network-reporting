from ad_server.networks.server_side import ServerSide

import cgi
import urllib
import re

from ad_server.debug_console import trace_logging
from common.utils import simplejson


class ChartBoostServerSide(ServerSide):
    base_url = "http://www.chartboost.com/api/"
    pub_id_attr = 'chartboost_pub_id'
    network_name = 'ChartBoost'

    @property
    def url(self):
        data =	{'uuid': self.get_udid(), 'app': self.get_pub_id(), }        
        if "full" in self.adunit.format:
            self.is_full_screen = True
            return self.base_url + "fullscreen.json?" + urllib.urlencode(data)
        else:
            self.is_full_screen = False
            return self.base_url + "banner.json?" + urllib.urlencode(data)
            
    def _bid_and_html_for_response(self,response):
        image_template = """<div style='text-align:center'><a href="%(url)s" target="_blank"><img src="%(banner)s"/></a></div>"""
        trace_logging.warning("Received ChartBoost response: %s"%cgi.escape(response.content))
        # try:
        response_content = simplejson.loads(response.content)
        if self.is_full_screen:
            return 0.0, response_content['url']
        else:    
            content = image_template%response_content
            return 0.0, content          
        # except:    
            trace_logging.info("ChartBoost ad is empty")
            raise Exception("ChartBoost ad is empty")