from account.query_managers import AccountQueryManager
from google.appengine.api import users
from account.models import Account


class RequestHandler(object):
    def __init__(self,request=None):
      if request:
        self.request = request
        self.account = None
        user = users.get_current_user()
        if user:
          if users.is_current_user_admin():
            account_key_name = request.COOKIES.get("account_impersonation",None)
            if account_key_name:
              self.account = AccountQueryManager().get_by_key_name(account_key_name)
        if not self.account:  
          self.account = Account.current_account()

      super(RequestHandler,self).__init__()  

    def __call__(self,request,*args,**kwargs):
        self.params = request.POST or request.GET
        self.request = request or self.request
        self.account = None
        
        try:
          # Limit date range to 31 days, otherwise too heavy
          self.date_range = min(int(self.params.get('r')),31)  # date range
        except:
          self.date_range = 14
          
        try:
          s = self.request.GET.get('s').split('-')
          self.start_date = date(int(s[0]),int(s[1]),int(s[2]))
        except:
          self.start_date = None
        
        user = users.get_current_user()
        if user:
          if users.is_current_user_admin():
            account_key_name = request.COOKIES.get("account_impersonation",None)
            if account_key_name:
              self.account = AccountQueryManager().get_by_key_name(account_key_name)
        if not self.account:  
          self.account = Account.current_account()
          
        # use the offline stats  
        self.offline = self.params.get("offline",False)   
        self.offline = True if self.offline == "1" else False

        if request.method == "GET":
            return self.get(*args,**kwargs)
        elif request.method == "POST":
            return self.post(*args,**kwargs)    
    def get(self):
        pass
    def put(self):
        pass  