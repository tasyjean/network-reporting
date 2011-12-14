import logging
import os
import sys
import urllib2
import urllib


# Paths only needed for testing
if os.path.exists('/home/ubuntu/'):
    sys.path.append('/home/ubuntu/mopub/server')
else:
    sys.path.append('/Users/tiagobandeira/Documents/mopub/server')
from ad_network_reports.scrapers.scraper import Scraper, NetworkConfidential
from ad_network_reports.scrapers.network_scrape_record import \
        NetworkScrapeRecord
from ad_network_reports.scrapers.unauthorized_login_exception import \
        UnauthorizedLogin
from datetime import date, timedelta

REVENUE_HEADER = 'Net Revenue$'
REQUEST_HEADER = 'Requests'
IMPRESSION_HEADER = 'Paid Impressions'
CLICK_HEADER = 'Clicks'
APP_HEADER = 'Site'
# Yes, jumptaps app name is the same as our adunit name...
ADUNIT_HEADER = 'Spot'

class JumpTapScraper(Scraper):

    NETWORK_NAME = 'jumptap'
    SITE_STAT_URL = 'https://pa.jumptap.com/pa-2.0/pub-services/v10/report.html'

    def __init__(self, login_info):
        """Create a Jumptap scraper object.

        Take login credentials and extra info which contains a generator of app
        level publisher ids and adunit level publisher ids for the account.
        """
        if isinstance(login_info, tuple):
            credentials, self.publisher_ids, self.adunit_publisher_ids = \
                    login_info
            self.publisher_ids = set(self.publisher_ids)
            self.adunit_publisher_ids = set(self.adunit_publisher_ids)
        else:
            credentials = login_info
            self.publisher_ids = ['']
            self.adunit_publisher_ids = iter([])
        super(JumpTapScraper, self).__init__(credentials)

    def test_login_info(self):
        """Test the username and password.

        Raise a 401 error if username or password are incorrect otherwise
        return None.
        """
        self.get_site_stats(date.today() - timedelta(days = 1))

    def get_site_stats(self, from_date):
        # Create log file.
        logger = logging.getLogger('jumptap_log_' + self.key)
        hdlr = logging.FileHandler('/var/tmp/jumptap_%s.log' % self.key)
        formatter = logging.Formatter('%(asctime)s %(levelname)s'
                ' %(message)s')
        hdlr.setFormatter(formatter)
        logger.addHandler(hdlr)
        logger.setLevel(logging.DEBUG)

        to_date = from_date

        records = []
        for publisher_id in self.publisher_ids:
            query_dict = {"user": self.username,
                          "pass": self.password,
                          "fromDate": from_date.strftime("%m/%d/%Y"),
                          "toDate": to_date.strftime("%m/%d/%Y"),
                          "sites": publisher_id,
                          "groupBy": "spot"}

            req = urllib2.Request(self.SITE_STAT_URL,
                                  urllib.urlencode(query_dict))
            try:
                response = urllib2.urlopen(req)
            except urllib2.HTTPError as e:
                if e.code in (401, 403):
                    raise UnauthorizedLogin("Invalid login for Jumptap")
                raise

            headers = response.readline().split(',')
            logger.info(headers)

            revenue_index = headers.index(REVENUE_HEADER)
            request_index = headers.index(REQUEST_HEADER)
            impression_index = headers.index(IMPRESSION_HEADER)
            click_index = headers.index(CLICK_HEADER)
            app_index = headers.index(APP_HEADER)
            adunit_index = headers.index(ADUNIT_HEADER)

            revenue = 0
            attempts = 0
            impressions = 0
            clicks = 0

            for line in response:
                logger.info(line)
                vals = line.split(',')
                if vals[0] != 'Totals' and vals[adunit_index] in \
                        self.adunit_publisher_ids or not \
                        self.adunit_publisher_ids:
                    revenue += float(vals[revenue_index])
                    attempts += int(vals[request_index])
                    impressions += int(vals[impression_index])
                    clicks += int(vals[click_index])

            nsr = NetworkScrapeRecord(revenue = revenue,
                                      attempts = attempts,
                                      impressions = impressions,
                                      clicks = clicks,
                                      app_tag = publisher_id)

            records.append(nsr)

        return records

if __name__ == '__main__':
    NC = NetworkConfidential()
    #NC.username = 'com2ususa'
    #NC.password = 'com2us1001'
#    publisher_ids = [u'pa_com2us_usa_inc__op_3d_lab_i_tes_iph_app',
#            u'pa_com2us_usa_inc__slice_it__drd_app']
#    adunit_publisher_ids = iter([
#        u'pa_com2us_usa_inc__op_3d_lab_a_tes_drd_app_banner',
#        u'pa_com2us_usa_inc__op_3d_lab_i_tes_iph_app_home_me_banner',
#        u'pa_com2us_usa_inc__op_3d_lab_i_tes_iph_app_home_me_medrect',
#        u'pa_com2us_usa_inc_slice_it_drd_app_banner',
#        u'pa_com2us_usa_inc__slice_it__drd_app_banner2'])

#    NC.username = 'chesscom'
#    NC.password = 'Y7u8i9o0'
#    publisher_ids = ['pa_chess_com_llc_chess_com_-_pla_iph_app',
#            'pa_chess_com_llc_chess_com_-_and_drd_app']

    NC.username = 'komastudios'
    NC.password = 'nH0J4od4'
    publisher_ids = [u'pa_koma_studios_ug_penalty_kick_iph_app',
            u'pa_koma_studios_ug_penalty_kick_an_drd_app']

    adunit_publisher_ids = iter([])
    NC.ad_network_name = 'jumptap'
    SCRAPER = JumpTapScraper((NC, publisher_ids, adunit_publisher_ids))
    print SCRAPER.get_site_stats(date.today() - timedelta(days = 1))
