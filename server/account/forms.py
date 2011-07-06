from django import forms
from common.utils import forms as mpforms
from common.utils import fields as mpfields
from account.models import Account, NetworkConfig
from common.constants import (ISO_COUNTRIES, US_STATES)

class AccountForm(mpforms.MPModelForm):
    TEMPLATE = 'account/form/account_form.html'
    countries = ISO_COUNTRIES
    states = US_STATES
    
    phone = mpfields.MPTextField(label="Phone #", required=False)    
    class Meta:
        model = Account
        fields = ("admob_pub_id",
                  "adsense_pub_id",
                  "adsense_company_name",
                  "adsense_test_mode",
                  "brightroll_pub_id",
                  "chartboost_pub_id",
                  "ejam_pub_id",
                  "greystripe_pub_id",
                  "inmobi_pub_id",
                  "jumptap_pub_id",
                  "millenial_pub_id",
                  "mobfox_pub_id",
                  )                        
        
class NetworkConfigForm(mpforms.MPModelForm):
    
    class Meta:
        model = NetworkConfig
    
    def clean(self):
        cleaned_data = self.cleaned_data
        for key, value in cleaned_data.iteritems():
            cleaned_data[key] = value.strip()
        return cleaned_data