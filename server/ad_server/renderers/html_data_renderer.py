from ad_server.renderers.base_html_renderer import BaseHtmlRenderer

class HtmlDataRenderer(BaseHtmlRenderer):
    """ For now, just do the standard """
    
    TEMPLATE = 'html_data.html'
    
    def _setup_html_context(self):
        self.html_context['html_data'] = self.creative.html_data
        self.html_context['random_value'] = self.random_val
        super(HtmlDataRenderer, self)._setup_html_context()
