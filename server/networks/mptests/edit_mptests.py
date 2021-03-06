import os
import sys

sys.path.append(os.environ['PWD'])

import common.utils.test.setup

from nose.tools import ok_, \
       eq_

from django.core.urlresolvers import reverse

import simplejson as json
from collections import defaultdict

from google.appengine.ext import db

from networks.mptests.network_test_case import NetworkTestCase, \
        requires_network_with_mappers, \
        requires_network_with_pub_ids, \
        requires_non_custom_network_type, \
        DEFAULT_BID, \
        DEFAULT_HTML, \
        DEFAULT_PUB_ID
from common.utils.test.test_utils import dict_eq, \
        model_eq, \
        confirm_all_models
from common.constants import NETWORKS

from networks.views import NETWORKS_WITH_PUB_IDS

from account.query_managers import NetworkConfigQueryManager
from advertiser.query_managers import AdGroupQueryManager, \
        AdvertiserQueryManager, \
        CreativeQueryManager
from publisher.query_managers import AppQueryManager, \
        AdUnitQueryManager

from account.models import NetworkConfig
from advertiser.models import AdGroup
from ad_network_reports.models import AdNetworkAppMapper, \
        LoginStates

from ad_network_reports.forms import LoginCredentialsForm
from networks.forms import NetworkCampaignForm, \
        NetworkAdGroupForm, \
        AdUnitAdGroupForm


class EditNetworkGetTestCase(NetworkTestCase):
    def setUp(self):
        super(EditNetworkGetTestCase, self).setUp()

        self.network_type = self.network_type_to_test()
        self.set_up_existing_apps_and_adunits()
        self.existing_apps = self.get_apps_with_adunits(self.account)

        self.existing_campaign = self.generate_network_campaign(
                self.network_type, self.account, self.existing_apps)

        if self.network_type in NETWORKS_WITH_PUB_IDS:
            for app_idx, app in enumerate(self.existing_apps):
                nc = NetworkConfig()
                pub_id = '%s_%s' % (DEFAULT_PUB_ID, app_idx)
                setattr(nc, '%s_pub_id' % self.network_type, pub_id)
                NetworkConfigQueryManager.put(nc)
                app.network_config = nc
                AppQueryManager.put(app)

                for adunit_idx, adunit in enumerate(app.adunits):
                    nc = NetworkConfig()
                    setattr(nc, '%s_pub_id' % self.network_type, '%s_%s' %
                            (pub_id, adunit_idx))
                    NetworkConfigQueryManager.put(nc)
                    adunit.network_config = nc
                    AdUnitQueryManager.put(adunit)

        self.url = reverse('edit_network',
                kwargs={'campaign_key': str(self.existing_campaign.key())})

    def network_type_to_test(self):
        return 'admob'

    def mptest_edit_campaign_for_other_account(self):
        """Attempting to edit a campaign from another account should result in
        an error.

        Author: Tiago Bandeira
        """
        self.login_secondary_account()

        confirm_all_models(self.client.get,
                           args=[self.url],
                           response_code=404)

    def mptest_context(self):
        """The context given to the template should be valid.

        Author: Tiago Bandeira
        """
        response = confirm_all_models(self.client.get,
                                      args=[self.url])
        context = response.context

        adgroups = AdvertiserQueryManager.get_adgroups_dict_for_account(
                self.account).values()
        adgroups_by_adunit = {}
        for adgroup in adgroups:
            adgroups_by_adunit[adgroup.site_keys[0]] = adgroup

        network_data = {'name': self.network_type,
                        'pretty_name': NETWORKS[self.network_type],
                        'show_login': False,
                        'login_state': LoginStates.NOT_SETUP}

        dict_eq(network_data, context['network'])

        eq_(self.account.key(), context['account'].key())

        ok_(not context['custom_campaign'] or (context['custom_campaign'] and
            self.network_type in ('custom', 'custom_native')))

        ok_(isinstance(context['campaign_form'], NetworkCampaignForm))

        eq_(str(self.existing_campaign.key()), context['campaign_key'])

        ok_(isinstance(context['login_form'], LoginCredentialsForm))

        ok_(isinstance(context['adgroup_form'], NetworkAdGroupForm))

        eq_(len(self.existing_apps), len(context['apps']))
        for app_idx, app in enumerate(context['apps']):
            pub_id = '%s_%s' % (DEFAULT_PUB_ID, app_idx)
            eq_(getattr(app.network_config, '%s_pub_id' % self.network_type),
                    pub_id)

            for adunit_idx, adunit in enumerate(app.adunits):
                ok_(isinstance(adunit.adgroup_form, AdUnitAdGroupForm))
                ok_(adunit.key() in adgroups_by_adunit)
                model_eq(adunit.adgroup_form.instance,
                        adgroups_by_adunit[adunit.key()])

                eq_(getattr(adunit.network_config, '%s_pub_id' %
                    self.network_type), '%s_%s' % (pub_id, adunit_idx))

        ok_(not context['reporting'])


class EditNetworkPostTestCase(NetworkTestCase):
    def setUp(self):
        super(EditNetworkPostTestCase, self).setUp()

        self.network_type = self.network_type_to_test()
        self.set_up_existing_apps_and_adunits()
        self.existing_apps = self.get_apps_with_adunits(self.account)

        self.existing_campaign = self.generate_network_campaign(self.network_type,
            self.account, self.existing_apps)

        for app_idx, app in enumerate(self.existing_apps):
            pub_id = '%s_%s' % (DEFAULT_PUB_ID, app_idx)
            setattr(app.network_config, '%s_pub_id' % self.config_network_type(),
                    pub_id)
            AppQueryManager.update_config_and_put(app, app.network_config)

            for adunit_idx, adunit in enumerate(app.adunits):
                adunit_pub_id = '%s_%s' % (pub_id, adunit_idx)
                setattr(adunit.network_config, '%s_pub_id' % self.config_network_type(),
                        adunit_pub_id)
                AdUnitQueryManager.update_config_and_put(adunit, adunit.network_config)

        self.url = reverse('edit_network',
                kwargs={'campaign_key': str(self.existing_campaign.key())})

        self.post_data = {}

        self.edited = defaultdict(dict)
        for adgroup in self.existing_campaign.adgroups:
            self.edited[adgroup.key()] = {'created': 'EXCLUDE'}

    def network_type_to_test(self):
        return 'admob'

    def config_network_type(self):
        return self.network_type_to_test()

    def mptest_no_change(self):
        """No change to network campaign

        Author: Andrew He
                Tiago Bandeira (6/4/2012)
        """
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'})

    @requires_non_custom_network_type
    def mptest_activates_adgroup(self):
        """Setting adgroup.active to True should work.

        Author: Andrew He
                Tiago Bandeira (6/4/2012)
        """
        # Prepare a request that marks one of the adunits as 'enabled'.
        app = self.existing_apps[0]
        adunit = app.adunits[0]

        adgroup = AdGroupQueryManager.get_network_adgroup(
                self.existing_campaign, adunit.key(), self.account.key())

        adunit_active_key = '%s-active' % adunit.key()
        self.post_data[adunit_active_key] = True

        self.edited[adgroup.key()]['active'] = True
        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    @requires_network_with_pub_ids
    def mptest_only_allows_activating_adgroups_with_pub_ids(self):
        """Setting adgroup.active to True should not work if there's no pub ID.

        Author: Andrew He
                Tiago Bandeira (6/4/2012)
        """
        # Prepare a request that marks one of the adunits as 'enabled' without
        # giving it a pub ID.
        app = self.existing_apps[0]
        adunit = app.adunits[0]

        adunit_pub_id_key = '%s-%s_pub_id' % (adunit.network_config.key(),
                self.config_network_type())
        adunit_active_key = '%s-active' % adunit.key()
        self.post_data[adunit_pub_id_key] = ''
        self.post_data[adunit_active_key] = True

        # Send the request.
        response = confirm_all_models(self.client.post,
                                      args=[self.url, self.post_data],
                                      kwargs={'HTTP_X_REQUESTED_WITH':
                                          'XMLHttpRequest'})

        response_json = json.loads(response.content)

        # Check that the request fails and returns a validation error for the
        # specific adunit.
        eq_(response_json['success'], False)
        ok_(adunit_pub_id_key in response_json['errors'])

    def mptest_deactivates_adgroup(self):
        """Setting adgroup.active to False should work.

        Author: Andrew He
                Tiago Bandeira (6/4/2012)
        """
        app = self.existing_apps[0]
        adunit = app.adunits[0]

        # Manually edit one of the existing adgroups to be active.
        campaign = self.existing_campaign
        adgroup = AdGroupQueryManager.get_network_adgroup(
                self.existing_campaign, adunit.key(), self.account.key(),
                get_from_db=True)
        adgroup.active = True
        adgroup.put()

        # Prepare a request that marks this adunit as 'disabled'.
        adunit_active_key = '%s-active' % adunit.key()
        self.post_data[adunit_active_key] = False

        self.edited[adgroup.key()]['active'] = False
        # Send the request and check db state.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    @requires_network_with_pub_ids
    def mptest_updates_network_configs(self):
        """All network config objects should be updated with correct pub IDs.

        Author: Andrew He
                Tiago Bandeira (6/4/2012)
        """
        # Prepare a request that changes the pub IDs for one app and one adunit.
        app_to_modify = self.existing_apps[0]
        adunit_to_modify = app_to_modify.adunits[0]

        new_app_pub_id = 'TEST_APP_PUB_ID'
        app_pub_id_key = '%s-%s_pub_id' % (app_to_modify.network_config.key(),
                self.config_network_type())
        self.post_data[app_pub_id_key] = new_app_pub_id

        new_adunit_pub_id = 'TEST_ADUNIT_PUB_ID'
        adunit_pub_id_key = '%s-%s_pub_id' % (adunit_to_modify.network_config.key(),
                self.config_network_type())
        self.post_data[adunit_pub_id_key] = new_adunit_pub_id

        self.edited = {}
        self.edited.update({app_to_modify.network_config.key(): {'%s_pub_id' %
                    self.config_network_type(): new_app_pub_id},
                  adunit_to_modify.network_config.key(): {'%s_pub_id' %
                    self.config_network_type(): new_adunit_pub_id}})

        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    @requires_network_with_mappers
    def mptest_updates_mapper_when_updating_pub_id(self):
        """If an app is given a new pub ID, a new mapper should be created.

        Author: Andrew He
                Tiago Bandeira (6/4/2012)
        """
        print self.network_type

        # Prepare a request that changes the pub ID for one app.
        app = self.existing_apps[0]
        adunit = app.adunits[0]

        new_app_pub_id = 'TEST_APP_PUB_ID'
        app_pub_id_key = '%s-%s_pub_id' % (app.network_config.key(),
                self.config_network_type())
        self.post_data[app_pub_id_key] = new_app_pub_id

        # Prepare a login
        login = self.generate_ad_network_login(self.network_type, self.account)

        self.edited = {}
        self.edited[app.network_config.key()] = {'%s_pub_id' %
                self.config_network_type(): new_app_pub_id}

        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           added={AdNetworkAppMapper: 1},
                           edited=self.edited)

        # Fetch all mappers for our app and this network type.
        mappers = AdNetworkAppMapper.all(). \
            filter('application in', self.existing_apps). \
            filter('ad_network_name =', self.network_type).fetch(1000)

        # There should only be one mapper: the one for the app we just updated.
        eq_(len(mappers), 1)

        mapper = mappers[0]
        eq_(mapper.publisher_id, new_app_pub_id)
        eq_(mapper.ad_network_name, self.network_type)
        eq_(mapper.ad_network_login.key(), login.key())

    def mptest_updates_cpms(self):
        """Update CPM (bid)

        Author: Andrew He
                Tiago Bandeira (6/4/2012)
        """
        # Prepare a request that changes the CPM for one adunit.
        app = self.existing_apps[0]
        adunit = app.adunits[0]

        new_bid = 100.0
        adunit_bid_key = '%s-bid' % adunit.key()
        self.post_data[adunit_bid_key] = new_bid

        adgroup_key = AdGroupQueryManager.get_network_adgroup(
                self.existing_campaign, adunit.key(), self.account.key()).key()

        self.edited[adgroup_key]['bid'] = new_bid

        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    def mptest_updates_description(self):
        """Update details for a campaign

        Author: Tiago Bandeira (7/17/2012)
        """
        # Prepare a request that changes a few advanced targeting settings.
        self.post_data['description'] = 'description'

        self.edited = {self.existing_campaign.key(): {'description': 'description'}}

        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    def mptest_updates_advanced_targeting(self):
        """Update advanced targeting for a campaign

        Author: Andrew He
                Tiago Bandeira (6/4/2012)
        """
        # Prepare a request that changes a few advanced targeting settings.
        self.post_data['device_targeting'] = '1'
        self.post_data['ios_version_max'] = '4.0'
        self.post_data['targeted_countries'] = 'UG'

        for adgroup in self.existing_campaign.adgroups:
            self.edited[adgroup.key()]['device_targeting'] = True
            self.edited[adgroup.key()]['ios_version_max'] = '4.0'
            self.edited[adgroup.key()]['targeted_countries'] = ['UG']

        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    def mptest_multiple_targeted_countries(self):
        """Set up multiple geo predicates

        Author: Tiago Bandeira (7/17/2012)
        """
        # Prepare a request that changes a few advanced targeting settings.
        self.post_data['targeted_countries'] = [u'AD', u'US']

        for adgroup in self.existing_campaign.adgroups:
            self.edited[adgroup.key()]['targeted_countries'] = [u'AD', u'US']

        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    def mptest_updates_keywords_and_targeted_countries(self):
        """Set up keywords and multiple geo predicates

        Author: Tiago Bandeira (7/17/2012)
        """
        # Prepare a request that changes a few advanced targeting settings.
        self.post_data['targeted_countries'] = [u'AD', u'US']
        self.post_data['keywords'] = 'abc de, fm\n g'

        for adgroup in self.existing_campaign.adgroups:
            self.edited[adgroup.key()]['targeted_countries'] = [u'AD', u'US']
            self.edited[adgroup.key()]['keywords'] = ['abc de', 'fm', 'g']

        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    def mptest_updates_targeted_countries_with_region_targeting_type(self):
        """Set up geo predicates with a mallicios post to try and set targeted_cities when region_targeting_type is set to all

        Author: Tiago Bandeira (8/7/2012)
        """
        # Prepare a request that changes a few advanced targeting settings.
        self.post_data['targeted_countries'] = [u'AD', u'US']
        self.post_data['region_targeting_type'] = 'all'
        self.post_data['targeted_cities'] = [u'-22.90277778,-43.2075:21:Rio de Janeiro:BR', u'-23.5475,-46.63611111:27:Sao Paolo:BR']

        for adgroup in self.existing_campaign.adgroups:
            self.edited[adgroup.key()]['targeted_countries'] = [u'AD', u'US']

        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    def mptest_updates_targeted_cities_with_region_targeting_type(self):
        """Set up targeted_cities when geo predicates is already set

        Author: Tiago Bandeira (8/7/2012)
        """
        # adgroups are already targeting brazil
        adgroups = list(self.existing_campaign.adgroups)
        for adgroup in adgroups:
            adgroup.targeted_countries = [u'BR']
        AdGroupQueryManager.put(adgroups)

        # Prepare a request that changes a few advanced targeting settings.
        self.post_data['region_targeting_type'] = 'regions_and_cities'
        self.post_data['targeted_cities'] = [u'-22.90277778,-43.2075:21:Rio de Janeiro:BR', u'-23.5475,-46.63611111:27:Sao Paolo:BR']

        for adgroup in self.existing_campaign.adgroups:
            self.edited[adgroup.key()]['targeted_cities'] = [u'-22.90277778,-43.2075:21:Rio de Janeiro:BR', u'-23.5475,-46.63611111:27:Sao Paolo:BR']

        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    def mptest_clear_targeted_cities(self):
        """Set up targeted_cities when geo predicates is already set

        Author: Tiago Bandeira (8/7/2012)
        """
        # adgroups are already targeting brazil
        adgroups = list(self.existing_campaign.adgroups)
        for adgroup in adgroups:
            adgroup.targeted_countries = [u'BR']
            adgroup.targeted_cities = [u'-22.90277778,-43.2075:21:Rio de Janeiro:BR', u'-23.5475,-46.63611111:27:Sao Paolo:BR']
        AdGroupQueryManager.put(adgroups)

        # Prepare a request that changes a few advanced targeting settings.
        self.post_data['targeted_countries'] = [u'AD', u'US']

        for adgroup in self.existing_campaign.adgroups:
            self.edited[adgroup.key()]['targeted_countries'] = [u'AD', u'US']
            self.edited[adgroup.key()]['targeted_cities'] = []

        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    def mptest_modify_targeted_cities(self):
        """Modify the list of targeted_cities

        Author: Tiago Bandeira (8/7/2012)
        """
        # adgroups are already targeting brazil
        adgroups = list(self.existing_campaign.adgroups)
        for adgroup in adgroups:
            adgroup.targeted_countries = [u'BR']
            adgroup.targeted_cities = [u'-22.90277778,-43.2075:21:Rio de Janeiro:BR', u'-23.5475,-46.63611111:27:Sao Paolo:BR']
        AdGroupQueryManager.put(adgroups)

        # Prepare a request that changes a few advanced targeting settings.
        self.post_data['region_targeting_type'] = 'regions_and_cities'
        self.post_data['targeted_cities'] = [u'-23.5475,-46.63611111:27:Sao Paolo:BR']

        for adgroup in self.existing_campaign.adgroups:
            self.edited[adgroup.key()]['targeted_cities'] = [u'-23.5475,-46.63611111:27:Sao Paolo:BR']

        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    def mptest_updates_allocation_and_fcaps(self):
        """Update allocation and frequency capping on an adgroup

        Author: Andrew He
                Tiago Bandeira (6/4/2012)
        """
        # Prepare a request that changes the allocation / frequency capping
        # options for one adunit.
        app = self.existing_apps[0]
        adunit = app.adunits[0]

        new_allocation_percentage = 50.0
        allocation_percentage_key = '%s-allocation_percentage' % adunit.key()
        self.post_data[allocation_percentage_key] = new_allocation_percentage

        new_daily_frequency_cap = 24
        daily_frequency_cap_key = '%s-daily_frequency_cap' % adunit.key()
        self.post_data[daily_frequency_cap_key] = new_daily_frequency_cap

        new_hourly_frequency_cap = 5
        hourly_frequency_cap_key = '%s-hourly_frequency_cap' % adunit.key()
        self.post_data[hourly_frequency_cap_key] = new_hourly_frequency_cap

        adgroup = AdGroupQueryManager.get_network_adgroup(
                self.existing_campaign, adunit.key(), self.account.key())

        self.edited[adgroup.key()]['allocation_percentage'] = \
                new_allocation_percentage
        self.edited[adgroup.key()]['daily_frequency_cap'] = \
                new_daily_frequency_cap
        self.edited[adgroup.key()]['hourly_frequency_cap'] = \
                new_hourly_frequency_cap

        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    def mptest_edit_campaign_for_other_account(self):
        """Attempting to edit a campaign from another account should result in
        an error.

        Author: Tiago Bandeira
        """
        self.login_secondary_account()

        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           response_code=404)


class EditJumptapNetworkTestCase(EditNetworkPostTestCase):
    def network_type_to_test(self):
        return 'jumptap'


class EditIAdNetworkTestCase(EditNetworkPostTestCase):
    def network_type_to_test(self):
        return 'iad'


class EditInmobiNetworkTestCase(EditNetworkPostTestCase):
    def network_type_to_test(self):
        return 'inmobi'


class EditMobfoxNetworkTestCase(EditNetworkPostTestCase):
    def network_type_to_test(self):
        return 'mobfox'


class EditMillennialNetworkTestCase(EditNetworkPostTestCase):
    def network_type_to_test(self):
        return 'millennial'


class EditMillennialS2SNetworkTestCase(EditNetworkPostTestCase):
    def network_type_to_test(self):
        return 'millennial_s2s'

    def config_network_type(self):
        return 'millennial'


class EditAdsenseNetworkTestCase(EditNetworkPostTestCase):
    def network_type_to_test(self):
        return 'adsense'


class EditEjamNetworkTestCase(EditNetworkPostTestCase):
    def network_type_to_test(self):
        return 'ejam'


class EditBrightrollNetworkTestCase(EditNetworkPostTestCase):
    def network_type_to_test(self):
        return 'brightroll'


class EditCustomNetworkTestCase(EditNetworkPostTestCase):
    def network_type_to_test(self):
        return 'custom'

    def mptest_modify_custom_html(self):
        """Set custom_html and turn on the adgroup.

        Author: Tiago Bandeira (6/4/2012)
        """
        custom_html = 'custom_html'

        # Prepare a request that marks one of the adunits as 'enabled' without
        # giving it a pub ID.
        app = self.existing_apps[0]
        adunit = app.adunits[0]

        adunit_custom_html_key = '%s-custom_html' % adunit.key()
        adunit_active_key = '%s-active' % adunit.key()
        self.post_data[adunit_custom_html_key] = custom_html
        self.post_data[adunit_active_key] = True

        adgroup = AdGroupQueryManager.get_network_adgroup(
                self.existing_campaign, adunit.key(), self.account.key(),
                get_from_db=True)

        self.edited[adgroup.key()]['active'] = True
        for creative in adgroup.creatives:
            self.edited[creative.key()]['html_data'] = custom_html

        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    def mptest_only_allows_activating_adgroups_with_custom_html(self):
        """Setting adgroup.active to True should not work if there's no custom_html.

        Author: Tiago Bandeira (6/4/2012)
        """
        # Prepare a request that marks one of the adunits as 'enabled' without
        # giving it a pub ID.
        app = self.existing_apps[0]
        adunit = app.adunits[0]

        adunit_custom_html_key = '%s-custom_html' % adunit.key()
        adunit_active_key = '%s-active' % adunit.key()
        self.post_data[adunit_custom_html_key] = ''
        self.post_data[adunit_active_key] = True

        # Send the request.
        response = confirm_all_models(self.client.post,
                                      args=[self.url, self.post_data],
                                      kwargs={'HTTP_X_REQUESTED_WITH':
                                          'XMLHttpRequest'})

        response_json = json.loads(response.content)

        # Check that the request fails and returns a validation error for the
        # specific adunit.
        eq_(response_json['success'], False)
        ok_(adunit_custom_html_key in response_json['errors'])

    def mptest_target_preexisting_html(self):
        """Setting adgroup.active to True should work if there is custom_html.

        Author: Tiago Bandeira (8/7/2012)
        """
        # Prepare a request that marks one of the adunits as 'enabled' without
        # giving it a pub ID.
        app = self.existing_apps[0]
        adunit = app.adunits[0]

        adunit_active_key = '%s-active' % adunit.key()
        self.post_data[adunit_active_key] = True

        adgroup = AdGroupQueryManager.get_network_adgroup(
                self.existing_campaign, adunit.key(), self.account.key())
        self.edited[adgroup.key()]['active'] = True

        # Send the request.
        response = confirm_all_models(self.client.post,
                                      args=[self.url, self.post_data],
                                      kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                                      edited=self.edited)

    def mptest_invalid_target_preexisting_html(self):
        """Setting adgroup.active to True should not work if there's no custom_html.

        Author: Tiago Bandeira (8/7/2012)
        """
        custom_html = ''

        # Prepare a request that marks one of the adunits as 'enabled' without
        # giving it a pub ID.
        app = self.existing_apps[0]
        adunit = app.adunits[0]

        adgroup = AdGroupQueryManager.get_network_adgroup(
                self.existing_campaign, adunit.key(), self.account.key(),
                get_from_db=True)
        creatives = list(adgroup.creatives)
        for cr in creatives:
            cr.html_data = custom_html
        CreativeQueryManager.put(creatives)

        adunit_custom_html_key = '%s-custom_html' % adunit.key()
        adunit_active_key = '%s-active' % adunit.key()
        self.post_data[adunit_active_key] = True

        # Send the request.
        response = confirm_all_models(self.client.post,
                                      args=[self.url, self.post_data],
                                      kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'})

        response_json = json.loads(response.content)

        # Check that the request fails and returns a validation error for the
        # specific adunit.
        eq_(response_json['success'], False)
        ok_(adunit_custom_html_key in response_json['errors'])

class EditCustomNativeNetworkTestCase(EditNetworkPostTestCase):
    def network_type_to_test(self):
        return 'custom_native'

    def mptest_modify_custom_method(self):
        """Set custom_method and turn on the adgroup.

        Author: Tiago Bandeira (6/4/2012)
        """
        custom_method = 'custom_method'

        # Prepare a request that marks one of the adunits as 'enabled' without
        # giving it a pub ID.
        app = self.existing_apps[0]
        adunit = app.adunits[0]

        adunit_custom_method_key = '%s-custom_method' % adunit.key()
        adunit_active_key = '%s-active' % adunit.key()
        self.post_data[adunit_custom_method_key] = custom_method
        self.post_data[adunit_active_key] = True

        adgroup = AdGroupQueryManager.get_network_adgroup(
                self.existing_campaign, adunit.key(), self.account.key(),
                get_from_db=True)

        self.edited[adgroup.key()]['active'] = True
        for creative in adgroup.creatives:
            self.edited[creative.key()]['html_data'] = custom_method

        # Send the request.
        confirm_all_models(self.client.post,
                           args=[self.url, self.post_data],
                           kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                           edited=self.edited)

    def mptest_only_allows_activating_adgroups_with_custom_method(self):
        """Setting adgroup.active to True should not work if there's no custom_method.

        Author: Tiago Bandeira (6/4/2012)
        """
        # Prepare a request that marks one of the adunits as 'enabled' without
        # giving it a pub ID.
        app = self.existing_apps[0]
        adunit = app.adunits[0]

        adunit_custom_method_key = '%s-custom_method' % adunit.key()
        adunit_active_key = '%s-active' % adunit.key()
        self.post_data[adunit_custom_method_key] = ''
        self.post_data[adunit_active_key] = True

        # Send the request.
        response = confirm_all_models(self.client.post,
                                      args=[self.url, self.post_data],
                                      kwargs={'HTTP_X_REQUESTED_WITH':
                                          'XMLHttpRequest'})

        response_json = json.loads(response.content)

        # Check that the request fails and returns a validation error for the
        # specific adunit.
        eq_(response_json['success'], False)
        ok_(adunit_custom_method_key in response_json['errors'])

    def mptest_target_preexisting_html(self):
        """Setting adgroup.active to True should work if there is custom_html.

        Author: Tiago Bandeira (8/7/2012)
        """
        # Prepare a request that marks one of the adunits as 'enabled' without
        # giving it a pub ID.
        app = self.existing_apps[0]
        adunit = app.adunits[0]

        adunit_active_key = '%s-active' % adunit.key()
        self.post_data[adunit_active_key] = True

        adgroup = AdGroupQueryManager.get_network_adgroup(
                self.existing_campaign, adunit.key(), self.account.key())
        self.edited[adgroup.key()]['active'] = True

        # Send the request.
        response = confirm_all_models(self.client.post,
                                      args=[self.url, self.post_data],
                                      kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'},
                                      edited=self.edited)

    def mptest_invalid_target_preexisting_html(self):
        """Setting adgroup.active to True should not work if there's no custom_html.

        Author: Tiago Bandeira (8/7/2012)
        """
        custom_html = ''

        # Prepare a request that marks one of the adunits as 'enabled' without
        # giving it a pub ID.
        app = self.existing_apps[0]
        adunit = app.adunits[0]

        adgroup = AdGroupQueryManager.get_network_adgroup(
                self.existing_campaign, adunit.key(), self.account.key(),
                get_from_db=True)
        creatives = list(adgroup.creatives)
        for cr in creatives:
            cr.html_data = custom_html
        CreativeQueryManager.put(creatives)

        adunit_custom_html_key = '%s-custom_method' % adunit.key()
        adunit_active_key = '%s-active' % adunit.key()
        self.post_data[adunit_active_key] = True

        # Send the request.
        response = confirm_all_models(self.client.post,
                                      args=[self.url, self.post_data],
                                      kwargs={'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'})

        response_json = json.loads(response.content)

        # Check that the request fails and returns a validation error for the
        # specific adunit.
        eq_(response_json['success'], False)
        ok_(adunit_custom_html_key in response_json['errors'])

