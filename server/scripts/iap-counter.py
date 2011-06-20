import os, sys
sys.path.append("/Applications/GoogleAppEngineLauncher.app/Contents/Resources/GoogleAppEngine-default.bundle/Contents/Resources/google_appengine")
sys.path.append("/Applications/GoogleAppEngineLauncher.app/Contents/Resources/GoogleAppEngine-default.bundle/Contents/Resources/google_appengine")
sys.path.append("/Applications/GoogleAppEngineLauncher.app/Contents/Resources/GoogleAppEngine-default.bundle/Contents/Resources/google_appengine/lib/django")
sys.path.append("/Applications/GoogleAppEngineLauncher.app/Contents/Resources/GoogleAppEngine-default.bundle/Contents/Resources/google_appengine/lib/webob")
sys.path.append("/Applications/GoogleAppEngineLauncher.app/Contents/Resources/GoogleAppEngine-default.bundle/Contents/Resources/google_appengine/lib/yaml/lib")
sys.path.append("/Applications/GoogleAppEngineLauncher.app/Contents/Resources/GoogleAppEngine-default.bundle/Contents/Resources/google_appengine/lib/fancy_urllib")
sys.path.append('/'.join(os.getcwd().split("/")[:-1]))
sys.path.append('.')


from google.appengine.ext import db
from google.appengine.ext.remote_api import remote_api_stub
from userstore.models import InAppPurchaseEvent


LIMIT = 300




def auth_func():
    return "olp@mopub.com", "N47935"
  

def main():
    total_count = 0
    
    app_id = 'mopub-inc'
    host = '38-aws.latest.mopub-inc.appspot.com'
    remote_api_stub.ConfigureRemoteDatastore(app_id, '/remote_api', auth_func, host)

    mobile_users = {}

    keys = InAppPurchaseEvent.all(keys_only=True).fetch(LIMIT+1)
    while len(keys) > 300:
        total_count += LIMIT
        print total_count
        last_key = keys[-1]
        keys = InAppPurchaseEvent.all(keys_only=True).filter('__key__ >=', last_key).fetch(LIMIT+1)
        for key in keys:
            mobile_user_key = key.parent()
            mobile_users[str(mobile_user_key)] = mobile_users.get(str(mobile_user_key), 0) + 1

    total_count += len(keys)
    print 'final events:', total_count
    print 'total users:', len(mobile_users)
    print

    freq_dict = {}
    for user, count in mobile_users.iteritems():
        freq_dict[count] = freq_dict.get(count, 0) + 1
        

    for bucket, freq in freq_dict.iteritems():
        print bucket, freq
    
        


if __name__ == '__main__':
    main()
