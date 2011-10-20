import sys
import time

sys.path.append('/home/ubuntu/mopub/server') # only needed for testing
#sys.path.append('/Users/tiagobandeira/Documents/mopub/server') # only needed for testing
from ad_network_reports.scrapers.network_scrape_record import \
        NetworkScrapeRecord
from ad_network_reports.scrapers.scraper import Scraper, NetworkConfidential
from BeautifulSoup import BeautifulSoup
from datetime import date, datetime
from pyvirtualdisplay import Display
from selenium import webdriver

class IAdScraper(Scraper):

    NETWORK_NAME = 'iad'
    SS_FNAME = 'ScraperScreen_%s.png'
    STATS_PAGE = 'https://iad.apple.com/itcportal/#app_homepage'
    LOGIN_TITLE = 'iTunes Connect - iAd Network Sign In'
    SITE_ID_IDENTIFIER = '&siteid='
    APP_STATS = ('revenue', 'ecpm', 'requests', 'impressions', 'fill_rate',
            'ctr')
    MONEY_STATS = ['revenue', 'ecpm']
    PCT_STATS = ['fill_rate', 'ctr']

    def __init__(self, credentials):
        super(IAdScraper, self).__init__(credentials)

        self.authenticate()

    def __del__(self):
        self.browser.quit()
        self.disp.stop()

    def authenticate(self):
        # Must have selenium running or something
        self.disp = Display(visible = 0, size = (1024, 768))
        self.disp.start()
        self.browser = webdriver.Chrome('/usr/bin/chromedriver')
        # Set max wait time to find an element on a page
        self.browser.implicitly_wait(10)
        self.browser.get(self.STATS_PAGE)

        time.sleep(1)
        login = self.browser.find_element_by_css_selector('#accountname')
        login.clear()
        login.send_keys(self.username)
        account_password = \
                self.browser.find_element_by_css_selector('#accountpassword')
        account_password.clear()
        account_password.send_keys(self.password)
        self.browser.find_element_by_name('appleConnectForm').submit()
        # There are some redirects and shit that happens, chill out for a bit
        time.sleep(3)

        if self.browser.title == self.LOGIN_TITLE:
            raise Exception(self.browser.find_element_by_css_selector(
                'span.dserror').text)
        # We should now have cookies

    def test_login_info(self):
        """Login info has already been tested in the constructor (via the
        authenticate method) so we pass.

        Return None.
        """
        pass

    def get_ss(self):
        self.browser.get_screenshot_as_file('/home/ubuntu/' + self.SS_FNAME %
                time.time())

    def set_dates(self, start_date, end_date):
        # Set up using custom stuff
        self.browser.find_element_by_css_selector('select'). \
                find_element_by_css_selector('option[value=customDateRange]'). \
                click()
        time.sleep(1)
        self.set_date('#gwt-debug-date-range-selector-start-date-box',
                start_date)
        self.set_date('#gwt-debug-date-range-selector-end-date-box', end_date)

    def get_cal_date(self):
        # Wait for page to load
        time.sleep(1)
        return datetime.strptime(self.browser.find_element_by_css_selector(
            'td.datePickerMonth').text, '%b %Y').date()

    def set_date(self, selector, test_date):
        # Open up the date box
        time.sleep(1)
        self.browser.find_element_by_css_selector(selector).click()
        time.sleep(1)
        curr_date = self.get_cal_date()
        # Which way do we go
        if curr_date > test_date:
            button = 'td>div.datePickerPreviousButton'
        else:
            button = 'td>div.datePickerNextButton'
        # GO ALL THE WAY
        while curr_date.month != test_date.month or curr_date.year != \
                test_date.year:
            self.browser.find_element_by_css_selector(button).click()
            curr_date = self.get_cal_date()
        days = self.browser.find_elements_by_css_selector('.datePickerDay')
        for day in days:
            if 'datePickDayIsFiller' in day.get_attribute('class'):
                continue
            if day.text == str(test_date.day):
                day.click()
                break

    def get_site_stats(self, start_date):
        end_date = start_date

        # Set the dates
        self.set_dates(start_date, end_date)
        # read the shit
        page = None
        while page is None:
            try:
                page = self.browser.page_source
            except:
                print "failed getting source"
        soup = BeautifulSoup(page)
        # Find all the apps since their TR's aren't named easily
        apps = soup.findAll('td', {'class':'td_app'})
        # Get all the tr's
        app_rows = [app.parent for app in apps]
        records = []

        for index, row in enumerate(app_rows):
            # app_name = row.findAll('p', {"class":"app_text"})[0].text
            app_dict = {}
            # Find desired stats
            for stat in self.APP_STATS:
                class_name = 'td_' + stat
                data = str(row.findAll('td', {"class":class_name})[0].text)
                if stat in self.MONEY_STATS:
                    # Skip the dollar sign
                    data = float(filter(lambda x: x.isdigit() or x == '.',
                        data))
                elif stat in self.PCT_STATS:
                    # Don't include the % sign
                    data = float(filter(lambda x: x.isdigit() or x == '.',
                        data))
                else:
                    data = int(filter(lambda x: x.isdigit() or x == '.',
                        data))

                app_dict[stat] = data

            time.sleep(4)
            self.browser.find_elements_by_css_selector('.app_text')[index]. \
                    click()
            time.sleep(1)
            app_dict['apple_id'] = self.browser.current_url[self.browser.
                    current_url.find(self.SITE_ID_IDENTIFIER) + len(self.
                        SITE_ID_IDENTIFIER):]
            self.browser.back()
            time.sleep(1)

            nsr = NetworkScrapeRecord(revenue = app_dict['revenue'],
                                      attempts = app_dict['requests'],
                                      impressions = app_dict['impressions'],
                                      fill_rate = app_dict['fill_rate'],
                                      clicks = int(app_dict['ctr'] * app_dict[
                                          'impressions']),
                                      ctr = app_dict['ctr'],
                                      ecpm = app_dict['ecpm'],
                                      app_tag = app_dict['apple_id'])
            records.append(nsr)
        return records

if __name__ == '__main__':
    NC = NetworkConfidential()
    NC.username = 'chesscom'
    NC.password = 'Faisal1Chess'
    NC.ad_network_name = 'iad'
    SCRAPER = IAdScraper(NC)
    print SCRAPER.get_site_stats(date.today())
