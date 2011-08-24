from string import Template   
import random                 
from ad_server.renderers.base_html_renderer import BaseHTMLRenderer

class PureHTMLRenderer(BaseHTMLRenderer):
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
        # must pass in parameters to fully render template
        # TODO: NOT SURE WHY I CAN'T USE: html_data = c.html_data % dict(track_pixels=success)
        context.update({"html_data": creative.html_data, "w": format_tuple[0], "h": format_tuple[1]})
        
        if 'full' in adunit.format:
            context['trackingPixel'] = ""
            trackImpressionHelper = "<script>\nfunction trackImpressionHelper(){\n%s\n}\n</script>"%success
            context.update(trackImpressionHelper=trackImpressionHelper)
        else:
            context['trackImpressionHelper'] = ''    
            
        super(PureHTMLRenderer, cls).network_specific_rendering(header_context, 
                                                             creative=None,  
                                                             format_tuple=None,
                                                             context=None,
                                                             keywords=None,
                                                             adunit=None,
                                                             success=None,
                                                             **kwargs)
                


    TEMPLATE = Template("$html_data")
