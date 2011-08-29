from ad_server.networks.server_side import ServerSide
import logging
import urllib
import urllib2

from xml.dom import minidom
from ad_server.debug_console import trace_logging

class AdMobServerSide(ServerSide):
    base_url = None
    pub_id_attr = 'admob_pub_id'
    network_name = 'AdMob'


    @property  
    def payload(self):
        data = {'rt': 'api',
                'u': self.client_context.user_agent,
                'i': self.client_context.client_ip,
                'o': self.client_context.mopub_id,
                'm': 'live',
                's': self.get_pub_id(),
                # 'longitude': , # long
                # 'latitude': , # lat
                # 'int_cat': , # MobFox category type
                'v': 'api_mopub',
              }
              
        return urllib.urlencode(data) + '&' + self._add_extra_headers()

    def bid_and_html_for_response(self, response):
        return 0.0, content
        
