# magic import
import common.utils.test.setup

from account.models import Account, NetworkConfig
from publisher.models import App

from network_scraping.models import *

TEST_JUMPTAP_PUB_ID = '12345'
TEST_ADMOB_PUB_ID = 'a14a9ed9bf1fdcd'
TEST_IAD_PUB_ID = '362641118' # NOT IN NetworkConfig
TEST_INMOBI_PUB_ID ='4028cb962b75ff06012b792fc5fb0045'
TEST_MOBFOX_PUB_ID = 'fb8b314d6e62912617e81e0f7078b47e'

""" Office Jerk """
# JumpTap login info
jumptap_login_info = AdNetworkLoginInfo(account = account, ad_network_name = 'jumptap', username = 'vrubba',
                                        password = 'fluik123!')
jumptap_login_info.put()

# InMobi login info
inmobi_login_info = AdNetworkLoginInfo(account = account, ad_network_name = 'inmobi', username = 'info@fluik.com',
                                    password = 'fluik123!')
inmobi_login_info.put()

""" Chess.com """
# iAd login info                                        
iad_login_info = AdNetworkLoginInfo(account = account, ad_network_name = 'iad', username = 'chesscom',
                                       password = 'Faisal1Chess')
iad_login_info.put()

# JumpTap login info
jumptap_login_info = AdNetworkLoginInfo(account = account, ad_network_name = 'jumptap', username = 'chesscom',
                                        password = 'Y7u8i9o0')
jumptap_login_info.put()

# InMobi login info
inmobi_login_info = AdNetworkLoginInfo(account = account, ad_network_name = 'inmobi', username = 'chesscom@gmail.com',
                                    password = 'Y7u8i9o0')
inmobi_login_info.put()

""" Flashlight Zaphrox """
# JumpTap login info
jumptap_login_info = AdNetworkLoginInfo(account = account, ad_network_name = 'jumptap', username = 'zaphrox',
                                        password = 'JR.7x89re0')
jumptap_login_info.put()

# InMobi login info
inmobi_login_info = AdNetworkLoginInfo(account = account, ad_network_name = 'inmobi', username = 'JR.7x89re0',
                                    password = '1Bom.7fG8k')
inmobi_login_info.put()


account = Account()
account.put()

# AdMob login info
admob_login_info = AdNetworkLoginInfo(account = account, ad_network_name = 'admob', username = 'njamal@stanford.edu',
                                      password = 'xckjhfn3xprkxksm', client_key = 'k907a03ee39cecb699b5ad45c5eded01')
admob_login_info.put()

# JumpTap login info
jumptap_login_info = AdNetworkLoginInfo(account = account, ad_network_name = 'jumptap', username = 'vrubba',
                                        password = 'fluik123!')
jumptap_login_info.put()

# iAd login info                                        
iad_login_info = AdNetworkLoginInfo(account = account, ad_network_name = 'iad', username = 'rawrmaan@me.com',
                                       password = '606mCV&#dS')
iad_login_info.put()

# InMobi login info
inmobi_login_info = AdNetworkLoginInfo(account = account, ad_network_name = 'inmobi', username = '4028cb8b2b617f70012b792fe65e00a2',
                                    password = '84585161')
inmobi_login_info.put()

# MobFox login info
mobfox_login_info = AdNetworkLoginInfo(account = account, ad_network_name = 'mobfox', publisher_ids = ['fb8b314d6e62912617e81e0f7078b47e'])
mobfox_login_info.put()

# Only needed for jumptap
network_config = NetworkConfig(jumptap_pub_id = self.TEST_JUMPTAP_PUB_ID)
network_config.put()

# name corresponds to jumptap login info
app = App(account = account, name = "Office Jerk", network_config = network_config)
app.put()

network_app_mappers = []
network_app_mappers.append(AdNetworkAppMapper(application = app, ad_network_name = 'admob', publisher_id = self.TEST_ADMOB_PUB_ID, ad_network_login = admob_login_info))
network_app_mappers.append(AdNetworkAppMapper(application = app, ad_network_name = 'jumptap', publisher_id = self.TEST_JUMPTAP_PUB_ID, ad_network_login = jumptap_login_info, send_email = True))
network_app_mappers.append(AdNetworkAppMapper(application = app, ad_network_name = 'iad', publisher_id = self.TEST_IAD_PUB_ID, ad_network_login = iad_login_info))
network_app_mappers.append(AdNetworkAppMapper(application = app, ad_network_name = 'inmobi', publisher_id = self.TEST_INMOBI_PUB_ID, ad_network_login = inmobi_login_info))
network_app_mappers.append(AdNetworkAppMapper(application = app, ad_network_name = 'mobfox', publisher_id = self.TEST_MOBFOX_PUB_ID, ad_network_login = mobfox_login_info))
db.put(network_app_mappers)