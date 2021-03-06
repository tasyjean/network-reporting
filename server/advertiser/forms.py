from __future__ import with_statement
from datetime import datetime
import re

from django import forms
from django.forms.util import ErrorList
from django.utils.safestring import SafeString
from google.appengine.api import files, images
from google.appengine.ext.db import Key

from advertiser.models import (Order, LineItem, Creative, TextAndTileCreative,
                               ImageCreative, HtmlCreative)
from advertiser.widgets import CustomizableSplitDateTimeWidget
from common.constants import (COUNTRIES, IOS_VERSION_CHOICES,
                              ANDROID_VERSION_CHOICES)
from common.utils import helpers
from common.utils.date_magic import utc_to_pacific, pacific_to_utc
from common.utils.timezones import Pacific_tzinfo
from publisher.query_managers import AdUnitQueryManager, AdUnitContextQueryManager


class OrderForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        # TODO: figure out if there is a less hacky way to get this
        instance = args[9] if len(args) > 9 else kwargs.get('instance', None)
        if instance and not instance.is_order:
            # TODO: figure out what type of exception this should really be, ValueError?
            raise Exception("Campaign instance must be an order.")

        super(forms.ModelForm, self).__init__(*args, **kwargs)

    def save(self, *args, **kwargs):
        order = super(OrderForm, self).save(*args, **kwargs)

        # TODO: this is dumb, do something else
        order.campaign_type = 'order'
        order.save()

        return order

    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        name = name.strip()
        if not name:
            raise forms.ValidationError("This field is required.")
        return name

    def clean_advertiser(self):
        advertiser = self.cleaned_data.get('advertiser', '')
        advertiser = advertiser.strip()
        if not advertiser:
            raise forms.ValidationError("This field is required.")
        return advertiser

    class Meta:
        model = Order
        fields = ('name', 'advertiser', 'description')


class LineItemForm(forms.ModelForm):
    adgroup_type = forms.ChoiceField(choices=(('gtee', 'Guaranteed'),
                                              ('promo', 'Promotional')),
                                     label='Line Item Type:')
    # non-db field
    gtee_priority = forms.ChoiceField(choices=(('high', 'High'),
                                               ('normal', 'Normal'),
                                               ('low', 'Low')),
                                      initial='normal', label='Priority:',
                                      required=False)
    # non-db field
    promo_priority = forms.ChoiceField(choices=(('normal', 'Normal'),
                                                ('backfill', 'Backfill')),
                                       initial='normal', label='Priority:',
                                       required=False)
    # name =
    start_datetime = forms.DateTimeField(
        input_formats=('%m/%d/%Y %I:%M %p', '%m/%d/%Y %H:%M'),
        label='Start Time:', required=False,
        widget=CustomizableSplitDateTimeWidget(
            date_attrs={'class': 'date', 'placeholder': 'MM/DD/YYYY'},
            time_attrs={'class': 'time', 'placeholder': 'HH:MM'},
            date_format='%m/%d/%Y', time_format='%I:%M %p'))
    end_datetime = forms.DateTimeField(
        input_formats=('%m/%d/%Y %I:%M %p', '%m/%d/%Y %H:%M'),
        label='Stop Time:', required=False,
        widget=CustomizableSplitDateTimeWidget(
            date_attrs={'class': 'date', 'placeholder': 'MM/DD/YYYY'},
            time_attrs={'class': 'time', 'placeholder': 'HH:MM'},
            date_format='%m/%d/%Y', time_format='%I:%M %p'))
    bid_strategy = forms.ChoiceField(choices=(('cpm', 'CPM'),
                                              ('cpc', 'CPC')), label='Rate:')
    # bid =
    # non-db field
    budget = forms.FloatField(label='Budget:', required=False,
                              widget=forms.TextInput(attrs={'class': 'float'}))
    # daily_budget =
    # full_budget =
    budget_type = forms.ChoiceField(choices=(('daily', 'USD/day'),
                                             ('full_campaign', 'total USD')),
                                    initial='daily', required=False)
    budget_strategy = forms.ChoiceField(choices=(('evenly', 'Spread Evenly'),
                                                 ('allatonce', 'All at once')),
                                        initial='allatonce',
                                        label='Delivery Speed:', required=False,
                                        widget=forms.RadioSelect)

    # Targeting
    # site_keys defined in __init__

    # Geo Targeting
    accept_targeted_locations = forms.TypedChoiceField(
        choices=(('0', 'Not Located'),
                 ('1', 'Located')),
        coerce=lambda x: bool(int(x)), initial=True,
        required=False, widget=forms.Select)
    targeted_countries = forms.MultipleChoiceField(
        choices=COUNTRIES, label='Country:', required=False,
        widget=forms.SelectMultiple(attrs={'data-placeholder': 'Ex: United States, ...'}))
    # non-db field
    region_targeting_type = forms.ChoiceField(
        choices=(('all', 'All Regions'),
                 ('regions_and_cities', 'Specific State / Metro Area / DMA (Wi-Fi Required), or Specific City within Country'),
                 ('zip_codes', 'Specific ZIP Codes within Country (Wi-Fi Required)')),
        initial='all', label='Region:', required=False,
        widget=forms.RadioSelect)
    targeted_regions = forms.Field(required=False, widget=forms.SelectMultiple(
            attrs={'data-placeholder': 'Ex: Ohio, Miami-Ft. Lauderdale FL, ...'}))
    targeted_cities = forms.Field(required=False, widget=forms.SelectMultiple(
            attrs={'data-placeholder': 'Ex: New York, NY, US, ...'}))
    targeted_zip_codes = forms.Field(required=False, widget=forms.Textarea(
            attrs={'class': 'input-text', 'placeholder': 'Ex: 94117 27705', 'rows': 3, 'cols': 50}))

    # Connectivity Targeting
    # non-db field
    connectivity_targeting_type = forms.ChoiceField(
        choices=(('all', 'All Carriers and Wi-Fi'),
                 ('wi-fi', 'Wi-Fi Only'),
                 ('carriers', 'Selected Carriers')),
        initial='all', label='Connectivity:', required=False,
        widget=forms.RadioSelect)
    targeted_carriers = forms.Field(required=False, widget=forms.SelectMultiple(
            attrs={'data-placeholder': 'Ex: Verizon, ...'}))

    # Device Targting
    device_targeting = forms.TypedChoiceField(
        choices=(('0', 'All'),
                 ('1', 'Filter by device and OS')),
        coerce=lambda x: bool(int(x)), initial=False,
        label='Device:', required=False, widget=forms.RadioSelect)
    target_iphone = forms.BooleanField(initial=True, label='iPhone',
                                       required=False)
    target_ipod = forms.BooleanField(initial=True, label='iPod', required=False)
    target_ipad = forms.BooleanField(initial=True, label='iPad', required=False)
    ios_version_min = forms.ChoiceField(choices=IOS_VERSION_CHOICES[1:],
                                        label='Min', required=False)
    ios_version_max = forms.ChoiceField(choices=IOS_VERSION_CHOICES,
                                        label='Max', required=False)
    target_android = forms.BooleanField(initial=True, label='Android',
                                        required=False)
    android_version_min = forms.ChoiceField(choices=ANDROID_VERSION_CHOICES[1:],
                                            label='Min', required=False)
    android_version_max = forms.ChoiceField(choices=ANDROID_VERSION_CHOICES,
                                            label='Max', required=False)
    target_other = forms.BooleanField(initial=True, label='Other',
                                      required=False)

    # User Targeting
    # included_apps defined in __init__
    # excluded_apps defined in __init__

    # Keywords
    keywords = forms.CharField(
        label='Keywords:', required=False, widget=forms.Textarea(
            attrs={'class': 'input-text', 'rows': 3, 'cols': 50}))

    # Frequency Caps
    daily_frequency_cap = forms.IntegerField(
        initial=0, label='Frequency Caps:', required=False,
        widget=forms.TextInput(attrs={'class': 'float'}))
    hourly_frequency_cap = forms.IntegerField(
        initial=0, required=False,
        widget=forms.TextInput(attrs={'class': 'float'}))

    # Allocation
    # allocation_percentage =

    def __init__(self, *args, **kwargs):
        # initial
        if len(args) > 5:
            initial = args[5]
        else:
            if 'initial' not in kwargs or not kwargs['initial']:
                kwargs['initial'] = {}
            initial = kwargs['initial']

        # instance
        instance = args[9] if len(args) > 9 else kwargs.get('instance', None)

        if instance:
            # TODO: make sure you cannot change adgroup_type except for priority
            # gtee
            if 'gtee' in instance.adgroup_type:
                self._init_gtee_line_item(instance, initial)

            elif instance.adgroup_type == 'backfill_promo':
                initial['adgroup_type'] = 'promo'
                initial['promo_priority'] = 'backfill'

            if instance.start_datetime:
                initial['start_datetime'] = utc_to_pacific(instance.start_datetime)
            if instance.end_datetime:
                initial['end_datetime'] = utc_to_pacific(instance.end_datetime)

            # TODO: can't change the start date after a campaign has started.
            # TODO: not change the end date after a campaign has completed

            if instance.targeted_regions or instance.targeted_cities:
                initial['region_targeting_type'] = 'regions_and_cities'
            elif instance.targeted_zip_codes:
                initial['region_targeting_type'] = 'zip_codes'

            initial['targeted_zip_codes'] = '\n'.join(instance.targeted_zip_codes)

            if instance.targeted_carriers == ['Wi-Fi']:
                initial['connectivity_targeting_type'] = 'wi-fi'
            elif instance.targeted_carriers:
                initial['connectivity_targeting_type'] = 'carriers'

        # allows us to set choices on instantiation
        site_keys = kwargs.pop('site_keys', [])
        apps_choices = kwargs.pop('apps_choices', [])

        super(forms.ModelForm, self).__init__(*args, **kwargs)

        # set choices based on the users adunits
        # TODO: can we do this a nicer way so we can declare this field with the other fields?
        self.fields['site_keys'] = forms.MultipleChoiceField(choices=site_keys,
                                                             required=False)

        self.fields['included_apps'] = forms.MultipleChoiceField(
            choices=apps_choices, required=False, widget=forms.SelectMultiple(
                attrs={'data-placeholder': ' '}))
        self.fields['excluded_apps'] = forms.MultipleChoiceField(
            choices=apps_choices, required=False, widget=forms.SelectMultiple(
                attrs={'data-placeholder': ' '}))

    def _init_gtee_line_item(self, instance, initial):
        if 'high' in instance.adgroup_type:
            initial['gtee_priority'] = 'high'
        elif 'low' in instance.adgroup_type:
            initial['gtee_priority'] = 'low'
        initial['adgroup_type'] = 'gtee'

        if instance.budget_type == 'daily':
            initial['budget'] = instance.daily_budget
        else:
            initial['budget'] = instance.full_budget

        if initial['budget'] != None and instance.bid_strategy == 'cpm':
            initial['budget'] = int(1000.0 * initial['budget'] / instance.bid)

    def clean_adgroup_type(self):
        adgroup_type = self.cleaned_data.get('adgroup_type', None)
        if not adgroup_type:
            raise forms.ValidationError("This field is required.")
        return adgroup_type

    def clean_name(self):
        name = self.cleaned_data.get('name', '')
        name = name.strip()
        if not name:
            raise forms.ValidationError("This field is required.")
        return name

    def clean_start_datetime(self):
        start_datetime = self.cleaned_data.get('start_datetime', None)
        if start_datetime:
            # if this is a new campaign, it must start in the future
            if not self.instance and start_datetime.date() < datetime.now(tz=Pacific_tzinfo()).date():
                raise forms.ValidationError("Start time must be in the future")
            start_datetime = pacific_to_utc(start_datetime)
        return start_datetime

    def clean_end_datetime(self):
        end_datetime = self.cleaned_data.get('end_datetime', None)
        if end_datetime:
            end_datetime = pacific_to_utc(end_datetime)
        return end_datetime

    def clean_site_keys(self):
        return [Key(site_key) for site_key in self.cleaned_data.get('site_keys', [])]

    def clean_targeted_zip_codes(self):
        targeted_zip_codes = self.cleaned_data.get('targeted_zip_codes', None)
        if targeted_zip_codes:
            targeted_zip_codes = targeted_zip_codes.split()
            for targeted_zip_code in targeted_zip_codes:
                if not re.match('^\d{5}$', targeted_zip_code):
                    raise forms.ValidationError('Malformed ZIP code %s.' % targeted_zip_code)
        return targeted_zip_codes

    def clean_included_apps(self):
        return [Key(app_key) for app_key in self.cleaned_data.get('included_apps', [])]

    def clean_excluded_apps(self):
        return [Key(app_key) for app_key in self.cleaned_data.get('excluded_apps', [])]

    def clean_keywords(self):
        keywords = self.cleaned_data.get('keywords', None)
        if keywords:
            if len(keywords) > 500:
                raise forms.ValidationError('Maximum 500 characters for keywords')
            keywords = "\n".join([keyword.strip() for keyword in keywords.split("\n") if keyword.strip()])
        return keywords

    def clean(self):
        cleaned_data = super(LineItemForm, self).clean()

        self._clean_start_and_end_datetime(cleaned_data)

        if cleaned_data.get('adgroup_type', '') == 'gtee':
            self._clean_gtee_adgroup_type(cleaned_data)
            self._clean_gtee_budget(cleaned_data)

        elif cleaned_data.get('adgroup_type', '') == 'promo':
            self._clean_promo_adgroup_type(cleaned_data)
            self._clean_promo_budget(cleaned_data)

        self._clean_geographical_targeting(cleaned_data)
        self._clean_connectivity_targeting(cleaned_data)

        return cleaned_data

    def _clean_gtee_adgroup_type(self, data):
        priority = data.get('gtee_priority', None)
        if not priority:
            self._errors['gtee_priority'] = ErrorList()
            self._errors['gtee_priority'].append('This field is required')
        elif priority in ['low', 'high']:
            data['adgroup_type'] = 'gtee_%s' % priority

    def _clean_gtee_budget(self, data):
        budget = data.get('budget', None)
        if not budget:
            data['daily_budget'] = None
            data['full_budget'] = None
            return

        for field in ['bid_strategy', 'bid', 'budget_type', 'budget_strategy']:
            if not data.get(field):
                self._errors[field] = ErrorList()
                self._errors[field].append('This field is required')
                return

        if data['budget_type'] == 'daily':
            data['daily_budget'] = self._calculate_budget(budget)
            data['full_budget'] = None
        else:
            if not data['end_datetime'] and (data['budget_strategy'] != 'allatonce'):
                self._errors['budget_strategy'] = ErrorList()
                self._errors['budget_strategy'].append('Delivery speed \
                                                       must be all at once \
                                                       for total budget \
                                                       with no stop time')
            data['full_budget'] = self._calculate_budget(budget)
            data['daily_budget'] = None

    def _clean_promo_adgroup_type(self, data):
        priority = data.get('promo_priority', None)
        if not priority:
            self._errors['promo_priority'] = ErrorList()
            self._errors['promo_priority'].append('This field is required')
        elif priority == 'backfill':
            data['adgroup_type'] = 'backfill_promo'

    def _clean_promo_budget(self, data):
        """
        Promo campaigns are currently unbudgeted, so we remove all
        budgeting information if they've somehow been set (we shouldn't
        be exposing budgeting controls in the UI).
        """
        data['daily_budget'] = None
        data['full_budget'] = None
        data['budget_type'] = None
        data['budget_strategy'] = None

    def _calculate_budget(self, budget):
        if self.data.get('bid_strategy', 'cpm') == 'cpm':
            return float(budget) / 1000.0 * float(self.data.get('bid', 0.0))
        else:
            return budget

    def _clean_start_and_end_datetime(self, data):
        start = data.get('start_datetime', None) or datetime.now()
        data['start_datetime'] = start
        end = data.get('end_datetime')
        if end and end <= start:
            self._errors['end_datetime'] = ErrorList()
            self._errors['end_datetime'].append('End datetime must be after start datetime')

    def _clean_geographical_targeting(self, cleaned_data):
        if ('accept_targeted_locations' in cleaned_data and
                'targeted_countries' in cleaned_data and
                cleaned_data['accept_targeted_locations'] is False and
                not cleaned_data['targeted_countries']):
            self._errors['accept_targeted_locations'] = ErrorList()
            self._errors['accept_targeted_locations'].append('You must select some geography to target against.')
        if ('region_targeting_type' in cleaned_data and
                cleaned_data['region_targeting_type'] != 'regions_and_cities'):
            cleaned_data['targeted_regions'] = []
            cleaned_data['targeted_cities'] = []
        if ('region_targeting_type' in cleaned_data and
                cleaned_data['region_targeting_type'] != 'zip_codes'):
            cleaned_data['targeted_zip_codes'] = []

    def _clean_connectivity_targeting(self, cleaned_data):
        if ('connectivity_targeting_type' in cleaned_data and
                cleaned_data['connectivity_targeting_type'] == 'wi-fi'):
            cleaned_data['targeted_carriers'] = ['Wi-Fi']
        elif ('connectivity_targeting_type' in cleaned_data and
                cleaned_data['connectivity_targeting_type'] != 'carriers'):
            cleaned_data['targeted_carriers'] = []

    def save(self, *args, **kwargs):
        if self.instance and self.instance.site_keys:
            adunits = AdUnitQueryManager.get(self.instance.site_keys)
            AdUnitContextQueryManager.cache_delete_from_adunits(adunits)

        line_item = super(LineItemForm, self).save(*args, **kwargs)

        if line_item.site_keys:
            adunits = AdUnitQueryManager.get(line_item.site_keys)
            AdUnitContextQueryManager.cache_delete_from_adunits(adunits)

        return line_item

    class Meta:
        model = LineItem
        fields = (
            'adgroup_type',
            'gtee_priority',
            'promo_priority',
            'name',
            'start_datetime',
            'end_datetime',
            'bid_strategy',
            'bid',
            'budget',
            'daily_budget',
            'full_budget',
            'budget_type',
            'budget_strategy',
            'site_keys',
            'device_targeting',
            'target_iphone',
            'target_ipod',
            'target_ipad',
            'ios_version_min',
            'ios_version_max',
            'target_android',
            'android_version_min',
            'android_version_max',
            'target_other',
            'accept_targeted_locations',
            'targeted_countries',
            'region_targeting_type',
            'targeted_cities',
            'targeted_regions',
            'targeted_zip_codes',
            'connectivity_targeting_type',
            'targeted_carriers',
            'included_apps',
            'excluded_apps',
            'keywords',
            'daily_frequency_cap',
            'hourly_frequency_cap',
            'allocation_percentage',
        )


class AbstractCreativeForm(forms.ModelForm):
    # Creative
    name = forms.CharField(
        initial='Creative', label='Creative Name:', required=True)
    custom_width = forms.IntegerField(
        label='Custom Size:', required=False,
        widget=forms.TextInput(attrs={'class': 'number'}))
    custom_height = forms.IntegerField(
        required=False, widget=forms.TextInput(attrs={'class': 'number'}))
    landscape = forms.BooleanField(label='Landscape:', required=False)
    # ad_group
    # active
    # was_active
    # deleted
    ad_type = forms.ChoiceField(
        choices=(('image', 'Image'),
                 ('text_icon', 'Text and Tile'),
                 ('html', 'HTML')),
        initial='image', label='Creative Type:', required=False,
        widget=forms.RadioSelect)
    tracking_url = forms.CharField(
        label='Impression Tracking URL:', required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Optional'}))
    url = forms.CharField(label='Click URL:', required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Optional'}))
    # display_url
    conv_appid = forms.CharField(
        label='Conversion Tracking URL:', required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Optional'}))
    # format_predicates
    format = forms.ChoiceField(
        choices=(('320x50', '320 x 50 (Banner)'),
                 ('300x250', '300 x 250 (MRect)'),
                 ('full', 'Phone Full Screen'),
                 ('728x90', '728 x 90 (Tablet Leaderboard)'),
                 ('160x600', '160 x 600 (Tablet Skyscraper)'),
                 ('full_tablet', 'Tablet Full Screen'),
                 ('custom', 'Custom')),
        initial='320x50', label='Format:', required=False)
    launchpage = forms.CharField(
        label='Intercept URL:', required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Optional'}))
    # account
    # t

    # TextAndTileCreative
    line1 = forms.CharField(label='Line 1:', required=False)
    line2 = forms.CharField(label='Line 2:', required=False)
    # image_blog
    # image_serve_url
    action_icon = forms.ChoiceField(
        choices=(('download_arrow4', SafeString('<img src="/images/download_arrow4.png" width="40" height="40"/>')),
                 ('access_arrow', SafeString('<img src="/images/access_arrow.png" width="40" height="40"/>')),
                 ('none', 'None')),
        initial='download_arrow4', label='Action Icon:', required=False,
        widget=forms.RadioSelect)
    color = forms.CharField(
        initial='000000', label='Background Color:', required=False)
    font_color = forms.CharField(
        initial='FFFFFF', label='Font Color:', required=False)
    gradient = forms.BooleanField(
        initial=True, label='Gradient:', required=False)

    # HtmlCreative
    html_data = forms.CharField(
        label='HTML Body:', required=False,
        widget=forms.Textarea(attrs={'placeholder': 'HTML Body Content',
                                     'rows': 10}))
    ormma_html = forms.BooleanField(label='MRAID Ad:', required=False)

    # ImageCreative
    # image_blog
    # image_serve_url
    # image_width
    # image_height

    # This field is used to populate image_blob, image_serve_url, image_width,
    # and image_height.
    image_file = forms.FileField(label='Image File:', required=False)

    def _init_image_form(self, *args, **kwargs):
        instance = kwargs.get('instance', None)
        initial = kwargs.get('initial', None)
        text_tile = kwargs.get('text_tile', False)

        if instance:
            if instance.image_blob:
                if text_tile:
                    image_url = helpers.get_url_for_blob(instance.image_blob)
                else:
                    try:
                        image_url = instance.image_serve_url
                    except:
                        image_url = None

            else:
                image_url = None
            if not initial:
                initial = {}
            initial.update(image_url=image_url)
            kwargs.update(initial=initial)

    def _save_form(self, obj, commit, image=True):
        if image:
            if self.files.get('image_file'):
                self._save_image_file(obj)
            else:
                commit = False

        if not obj.conv_appid and obj.url:
            obj.conv_appid = self._get_appid(obj.url)

        if commit:
            obj.put()

        return obj

    def _save_image_file(self, obj):
        self.files['image_file'].open()
        image_data = self.files['image_file'].read()
        img = images.Image(image_data)
        obj.image_width = img.width
        obj.image_height = img.height

        fname = files.blobstore.create(mime_type='image/png')
        with files.open(fname, 'a') as f:
            f.write(image_data)
        files.finalize(fname)
        blob_key = files.blobstore.get_blob_key(fname)
        obj.image_blob = blob_key
        obj.image_serve_url = helpers.get_url_for_blob(obj.image_blob)

    def _get_appid(self, url):
        pattern = ''
        if 'itunes' in url:
            # itunes url
            # http://itunes.apple.com/il/app/imosaic-project/id335853048?mt=8
            # in this case: 335853048
            pattern = re.compile("http://itunes\.apple\.com.*id(\d+)")
        elif 'phobos' in url:
            # old phobos urls
            # http://phobos.apple.com/WebObjects/MZStore.woa/wa/viewSoftware?id=386584429&mt=8
            pattern = re.compile("http://phobos\.apple\.com.*id=(\d+)")
        else:
            # market://details?id=com.example.admob.lunarlander
            # in this case: com.example.admob.lunarlander
            # NOTE: there can not be any other characters after the id
            pattern = re.compile("market://.*id\=(.+)$")

        match = pattern.search(url)
        if match:
            store_id = match.group(1)
            return store_id

        return None

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError("This field is required.")
        return name

    def clean_url(self):
        url = self.cleaned_data.get('url', None)
        if url:
            if url.find("://") == -1:
                raise forms.ValidationError("You need to specify a protocol (like http://) at the beginning of your url")
        return url

    def clean_image_file(self):
        data = self.cleaned_data.get('image_file', None)

        if data:
            img = self.files.get('image_file', None)
            is_valid_image_type = any([str(img).lower().endswith(ftype) for ftype in ['.png',
                                                                                      '.jpeg',
                                                                                      '.jpg',
                                                                                      '.gif']])
            if not (img and is_valid_image_type):
                extension = _get_filetype_extension(img)
                if extension:
                    raise forms.ValidationError('Filetype (.%s) not supported.' % extension)
                else:
                    raise forms.ValidationError('Filetype not supported.')

        # Check to make sure an image file or url was provided.
        # We only need to check this if it's a new form being submitted
        if not self.instance and 'image_file' in self.Meta.fields:
            if not (self.cleaned_data.get('image_file', None) or \
                    self.cleaned_data.get('image_url', None)):
                raise forms.ValidationError('You must upload an image file for a creative of this type.')

        return data


SHARED_CREATIVE_FIELDS = ('name', 'custom_width', 'custom_height', 'landscape',
                          'ad_type', 'tracking_url', 'url', 'conv_appid',
                          'format', 'launchpage')


class NewCreativeForm(AbstractCreativeForm):
    class Meta:
        model = Creative
        fields = SHARED_CREATIVE_FIELDS + ('line1', 'line2', 'action_icon',
                                           'color', 'font_color', 'gradient',
                                           'html_data', 'ormma_html',
                                           'image_file')


class ImageCreativeForm(AbstractCreativeForm):
    def __init__(self, *args, **kwargs):
        self._init_image_form(*args, **kwargs)
        super(ImageCreativeForm, self).__init__(*args, **kwargs)

    def save(self, commit=True):
        obj = super(ImageCreativeForm, self).save(commit=False)
        return self._save_form(obj, commit)

    class Meta:
        model = ImageCreative
        fields = SHARED_CREATIVE_FIELDS + ('image_file', )


class TextAndTileCreativeForm(AbstractCreativeForm):
    def __init__(self, *args, **kwargs):
        kwargs.update(text_tile=True)
        self._init_image_form(*args, **kwargs)
        del kwargs['text_tile']
        super(TextAndTileCreativeForm, self).__init__(*args, **kwargs)

    def save(self, commit=True):
        obj = super(TextAndTileCreativeForm, self).save(commit=False)
        return self._save_form(obj, commit)

    class Meta:
        model = TextAndTileCreative
        fields = SHARED_CREATIVE_FIELDS + ('line1', 'line2', 'action_icon',
                                           'color', 'font_color', 'gradient',
                                           'image_file')


class HtmlCreativeForm(AbstractCreativeForm):
    def save(self, commit=True):
        obj = super(HtmlCreativeForm, self).save(commit=False)
        return self._save_form(obj, commit, image=False)

    class Meta:
        model = HtmlCreative
        fields = SHARED_CREATIVE_FIELDS + ('html_data', 'ormma_html')


MPX_FILTER_LEVELS = (
          ('a', 'Strict - Only allow ads appropriate for family audiences'),
          ('b', 'Moderate - Allow ads for general audiences'),
          ('c', 'Low - Allow ads for mature audiences, including alcohol and dating ads'),
          ('d', 'No filtering - Allow ads including those with provocative or suggestive imagery. \
                 MoPub always blocks illegal, pornographic and deceptive ads.')
         )


class ContentFilterForm(forms.Form):
    level = forms.ChoiceField(choices=MPX_FILTER_LEVELS, widget=forms.RadioSelect)


def _get_filetype_extension(filename):
    if not type(filename) == str:
        filename = str(filename)
    if filename.find('.') >= 0:
        return filename.split('.')[-1]
    return None
