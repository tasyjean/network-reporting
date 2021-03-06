import logging
import re
import hashlib


import datetime
from common.constants import (KB, MB, GB)

from google.appengine.ext import db


# matches sequence: space, 2 char, - or _, 2 char, 0 or more ;, followed by char that's not a char, number, - or _
COUNTRY_PAT = re.compile(r' [a-zA-Z][a-zA-Z][-_](?P<ccode>[a-zA-Z][a-zA-Z]);*[^a-zA-Z0-9-_]')

MB_PER_SHARD = 10

def get_country_code(headers, default='XX'):
    return headers.get('X-AppEngine-country', default)

def get_user_agent(request):
    return request.get('ua') or request.headers.get('User-Agent', 'None')

def get_client_ip(request):
    return request.get('ip') or request.remote_addr

# dte:pub:adv:CC:BN:MN:OS:OSVER
STAT_KEY = "%s:%s:%s:%s:%s:%s:%s:%s"


def cust_sum(vals):
    tot = 0
    for val in vals:
        if tot == 0 and isinstance(val, float):
            tot = 0.0
        if tot == 0 and isinstance(val, str):
            tot = val
        elif not isinstance(val, str):
            tot += val
    return tot


def chunks(list, chunk_size):
    '''Generator function that creates chunk_size lists from list
    '''
    for idx in xrange(0, len(list), chunk_size):
        yield list[idx:idx+chunk_size]

# Must be len 8, must have format YYMMDDHH
# I'm not getting rid of this, but this is stupid, I should've jsut used strftime...duh....
def parse_time(time_str):
    if len(time_str) != 8:
        return None
    year = 2000 + int(time_str[:2])
    month = int(time_str[2:4])
    day = int(time_str[4:6])
    hour = int(time_str[6:])
    return datetime.datetime(year=year, month=month, day=day, hour=hour)

def clone_entity(ent, **extra_args):
    """Clones an entity ent, adding or overriding certain attributes
    as specified by extra_args

    Args:
        ent: entity to clone
        extra_args: constructor arguments to override/add to the entity being clone

    Returns:
        a cloned, possibly updated, version of ent
    """
    klass = ent.__class__
    #build old object property dict
    props = dict((k, v.__get__(ent, klass)) for k,v in klass.properties().iteritems())
    #update with new stuff
    props.update(extra_args)
    #create new object
    return klass(**props)

def make_mopub_id(raw_udid):
    """
    we get one of 4 things
    RAW_UDID
    md5:MD5(mopub-<RAW_UDID>)
    sha1:SHA1(mopub-<RAW_UDID>)
    sha:SHA(<RAW_UDID>)

    moput_id is the part after the semicolon
    """
    return raw_udid.split(':')[-1]

def build_key(template, template_dict):
    """ I got tired of not knowing what's what when building a key.
    This takes a dictionary and turns all db.Models into str(db.Model.key()), and all
    db.Key()s into str(db.Key())s
    """
    new_vals = {}
    for k,v in template_dict.iteritems():
        if isinstance(v, db.Model):
            new_vals[k] = str(v.key())
        elif isinstance(v, db.Key):
            new_vals[k] = str(v)
    template_dict.update(new_vals)
    return template % template_dict


def campaign_stats(stat, type):
    if type == 'network':
        return [int(stat.request_count), int(stat.impression_count), stat.fill_rate, int(stat.click_count), stat.ctr]
    elif 'gtee' in type:
        return [int(stat.impression_count), int(stat.click_count), stat.ctr, stat.revenue]
    elif 'promo' in type:
        return [int(stat.impression_count), int(stat.click_count), stat.ctr, int(stat.conversion_count), stat.conv_rate]


def app_stats(stat):
    return [int(stat.request_count), int(stat.impression_count), stat.fill_rate, int(stat.click_count), stat.ctr]


def to_uni(obj, encoding='utf-8'):
    if isinstance(obj, basestring):
        if not isinstance(obj, unicode):
            obj = unicode(obj, encoding=encoding, errors='replace')
    return obj

def to_ascii(obj, encoding='utf-8'):
    if isinstance(obj, unicode):
        obj = obj.encode(encoding, 'replace')
    return obj

def get_url_for_blob(blob, ssl=True):
    from google.appengine.api import images
    url = images.get_serving_url(blob)
    # by default, app engine serves a maximum dimension of 512, adding =s0
    # forces the actual dimensions
    url += '=s0'
    if ssl:
        return url.replace('http:', 'https:')
    return url

def secure_url_from_url(url):
    return url.replace('http:', 'https:')

def get_all(Model, limit=300, testing=False):
    cnt = 0
    models = list(Model.all().fetch(limit=limit, batch_size=300))
    new_models = models
    while new_models:
        cnt += 1
        print cnt, len(models)
        new_models = list(Model.all().filter('__key__ >', models[-1]).run(limit=limit, batch_size=300))
        models += new_models
        # in testing mode return right away
        if testing: return models
    return models

def put_all(models, limit=300):
    cnt = 0
    for sub_models in chunks(models, limit):
        db.put(sub_models)
        cnt += len(sub_models)
        print "put %d/%d" % (cnt, len(models))

def get_udid_appid(request):
    """
    This is necessary because of a temporary error in Android's conversion tracking URL; there was a
    missing ampersand between the 'id' and 'udid' fields. This function properly parses the
    following requests:

    ?id=123&udid=456
    ?id=123udid=456
    ?udid=456&id=123
    """
    udid = request.get('udid').upper()
    mobile_appid = request.get('id')

    # If we have we can't request udid, we have a broken URL
    if not udid:
        query_string = request.query_string
        result = re.search('id=(?P<id>.*?)(?P<ampersand>&?)udid=(?P<udid>.*?)$', query_string)

        if (result):
            return result.group('udid').upper(), result.group('id')
            # note: if result.group('ampersand') is empty string, we have a broken url
            # though the return groups are the same regardless
        else:
            return None, None

    # Otherwise, there's no need to do special processing. Simply return the request parameters
    return udid, mobile_appid

def clone_entity(e, skip_auto_now=False, skip_auto_now_add=False, **extra_args):
    """Clones an entity, adding or overriding constructor attributes.

    The cloned entity will have exactly the same property values as the original
    entity, except where overridden. By default it will have no parent entity or
    key name, unless supplied.
    
    Args:
    e: The entity to clone
    
    skip_auto_now: If True then all DateTimeProperty propertes will be skipped
    which have the 'auto_now' flag set to True
    
    skip_auto_now_add: If True then all DateTimeProperty propertes will be
    skipped which have the 'auto_now_add' flag set to True
    
    extra_args: Keyword arguments to override from the cloned entity and pass
    to the constructor.
    
    Returns:
    A cloned, possibly modified, copy of entity e.
    """

    klass = e.__class__
    props = {}
    for k, v in klass.properties().iteritems():
        if not (type(v) == db.DateTimeProperty and \
                ((skip_auto_now and getattr(v, 'auto_now')) or \
                 (skip_auto_now_add and getattr(v, 'auto_now_add')))):
            if type(v) == db.ReferenceProperty:
                value = getattr(klass, k).get_value_for_datastore(e)
            else:
                value = v.__get__(e, klass)
            props[k] = value
    props.update(extra_args)
    return klass(**props)
