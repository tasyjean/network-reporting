from string import Template   
import random                 
from ad_server.renderers.base_html_renderer import BaseHTMLRenderer

class BrightRollRenderer(BaseHTMLRenderer):
    """ For now, just do the standard """
    @classmethod
    def network_specific_rendering(cls, header_context, 
                                   creative=None,  
                                   format_tuple=None,
                                   context=None,
                                   keywords=None,
                                   adunit=None,
                                   fail_url=None,
                                   success=None,
                                   **kwargs):   
        html_data = creative.html_data.replace(r'%(track_pixels)s',success)
        context.update(html_data=html_data)
        header_context.add_header("X-Scrollable","1")
        header_context.add_header("X-Interceptlinks","0")
        super(BrightRollRenderer, cls).network_specific_rendering(header_context, 
                                                                  creative=None,  
                                                                  format_tuple=None,
                                                                  context=None,
                                                                  keywords=None,
                                                                  adunit=None,
                                                                  success=None,
                                                                  **kwargs)
                

    TEMPLATE = Template('$html_data')
