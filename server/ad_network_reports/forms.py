from common.utils import djangoforms
from common.utils import fields as mpfields
from django.forms.widgets import TextInput
from models import AdNetworkLoginCredentials

class LoginInfoForm(djangoforms.ModelForm):
    password_str = mpfields.MPTextField()
    username_str = mpfields.MPTextField()

    def __unicode__(self):
        return str(self.fields)
    class Meta:
        model = AdNetworkLoginCredentials
        fields = ('client_key', 'email')
        # Password is excluded because we never get an encrypted password from
        # the front-end and it must be encrypted in the db.
        exclude = ('account', 'password', 'password_iv', 'username',
                'username-iv')
