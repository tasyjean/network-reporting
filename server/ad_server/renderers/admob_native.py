from ad_server.renderers.base_native_renderer import BaseNativeRenderer   
try:
    import json
except ImportError:
    try:
        import simplejson as json
    except ImportError:
        from common.utils import simplejson as json

class AdMobNativeRenderer(BaseNativeRenderer):
    """ For now, just do the standard """
    
    def _get_ad_type(self):
        if self.adunit.is_fullscreen():
            return 'admob_full'
        else:
            return 'admob_native'
                
    def _setup_headers(self):
        super(AdMobNativeRenderer, self)._setup_headers()
        nativecontext_dict = {
            "adUnitID": self.adunit.get_pub_id("admob_pub_id"),
            "adWidth": self.adunit.get_width(),
            "adHeight": self.adunit.get_height()
        }
        self.header_context.add_header("X-Nativeparams", 
                                       json.dumps(nativecontext_dict))
