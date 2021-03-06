from common.wurfl.wurfl_dicts import (BRAND_MAR,
                                     BRAND_OS,
                                     BRAND_OSVER,
                                     MAR_OS,
                                     MAR_OSVER,
                                     MAR_BRAND,
                                     OS_BRAND,
                                     OS_MAR,
                                     OS_OSVER,
                                     OSVER_BRAND,
                                     OSVER_MAR,
                                     OSVER_OS,
                                     )
from common.constants import (MAR,
                              BRND,
                              OS,
                              OS_VER,
                              )

WURFL_DICTS = [BRAND_MAR, BRAND_OS, BRAND_OSVER, MAR_OS, MAR_OSVER, MAR_BRAND, OS_BRAND, OS_MAR, OS_OSVER, OSVER_BRAND, OSVER_MAR, OSVER_OS]

class WurflQueryManager():

    def __init__(self, dicts = None):
        if dicts is None:
            self.BRAND_MAR, self.BRAND_OS, self.BRAND_OSVER, self.MAR_OS, self.MAR_OSVER, self.MAR_BRAND, self.OS_BRAND, self.OS_MAR, self.OS_OSVER, self.OSVER_BRAND, self.OSVER_MAR, self.OSVER_OS = WURFL_DICTS
        else:
            self.BRAND_MAR, self.BRAND_OS, self.BRAND_OSVER, self.MAR_OS, self.MAR_OSVER, self.MAR_BRAND, self.OS_BRAND, self.OS_MAR, self.OS_OSVER, self.OSVER_BRAND, self.OSVER_MAR, self.OSVER_OS = dicts 
        return


    def get_market_name(self, market):
        if 'N/A' in market:
            return 'N/A'
        brand = self.MAR_BRAND[market]
        if isinstance(brand, list):
            if len(brand) == 1:
                brand = brand[0]
            else:
                if len(brand) == 0:
                    brand = ''
                else:
                    brand = reduce(lambda x,y: x + ' ' + y, brand)
        brand = brand.replace('_', ' ')
        market = market.replace("_", ' ')
        return brand + ' ' + market

    def get_osver_name(self, osver):
        osver = osver.replace("_", ' ')
        return osver 

    def get_brand_name(self, brand):
        return brand.replace('_', ' ')

    def get_os_name(self, os):
        return os.replace('_', ' ')

    def get_wurfl_name(self, val, dim):
        if dim == MAR:
            return self.get_market_name(val)
        elif dim == BRND:
            return self.get_brand_name(val)
        elif dim == OS:
            return self.get_os_name(val)
        elif dim == OS_VER:
            return self.get_osver_name(val)

    #need to get brand name attached to marketing name
    def reports_get_marketing(self, os, os_ver, brand):
        brand_mars = None
        os_mars = None
        if brand is not None:
            brand_mars = self.BRAND_MAR[brand]
        if os and os_ver is None:
            os_mars = self.OS_MAR[os]
        elif (os and os_ver) or (os_ver and os is None):
            os_mars = self.OSVER_MAR[os_ver]
        #brand, os, and os_ver are all None, return all marketing names (fuuucckkkk)
        if brand is None and os is None and os_ver is None:
            return self.OS_MAR['Android'] + self.OS_MAR['iPhone_OS']
        #return only those names in both the os set and the brand set
        if os_mars and brand_mars:
            ret = []
            for mar in os_mars:
                if mar in brand_mars:
                    ret.append(mar)
            return ret
        #brand_mars is none, return only the os stuff
        elif os_mars:
            return os_mars
        #os_mars is none, return only brand stuff
        else:
            return brand_mars


    def reports_get_brand(self, os, os_ver):
        #if os_ver is not none use it, regardless of what os is
        if os_ver:
            return self.OSVER_BRAND[os_ver]
        elif os:
            return self.OS_BRAND[os]
        #both are none, return all, using keys ensures uniqueness
        else:
            return self.OS_BRAND['Android'] + self.OS_BRAND['iPhone_OS']

    def reports_get_os(self, brand, market):
        if market:
            return self.MAR_OS[market]
        elif brand:
            return self.BRAND_OS[brand]
        else:
            return ['Android', 'iPhone_OS']

    def reports_get_osver(self, brand, market, os):
        os_osvers = None
        brand_osvers = None
        if os is not None:
            os_osvers = self.OS_OSVER[os]
        if brand and market is None:
            brand_osvers = self.BRAND_OSVER[brand]
        elif (brand and market) or (market and brand is None):
            brand_osvers = self.MAR_OSVER[market]
        #brand, market, and os are all None, return all os_vers (fuuucckkkk)
        if brand is None and market is None and os is None:
            return self.OS_OSVER['Android'] + self.OS_OSVER['iPhone_OS']
        #return only those names in both the os set and the brand set
        if os_osvers and brand_osvers:
            ret = []
            for mar in os_osvers:
                if mar in brand_osvers:
                    ret.append(mar)
            return ret
        #brand_osvers is none, return only the os stuff
        elif os_osvers:
            return os_osvers
        #os_osvers is none, return only brand stuff
        else:
            return brand_osvers





