import re
import time
from datetime import datetime
from google.appengine.ext import webapp

register = webapp.template.create_template_register()

def currency(value):
	if value:
		return "$%1.2f" % value
	else:
		return "$0.00"
		
def currency_no_symbol(value):
	if value:
		return "%1.2f" % value
	else:
		return ""

def percentage(value):
	return "%1.1f%%" % ((value or 0) * 100)
	
def format_date(value):
	return value.strftime("%a, %b %d, %Y")
	
def truncate(value, arg):
	if len(value) > arg:
		return "%s..." % value[:(arg-3)]
	else:
		return value

def time_ago_in_words(value):
	if value:
		if type(value) == str or type(value) == unicode:
			value = datetime(*time.strptime(value, "%a %b %d %H:%M:%S +0000 %Y")[0:5])

		d = datetime.now() - value
		if d.days < 1:
			if d.seconds < 60:
				return "less than a minute"
			elif d.seconds < 120:
				return "about a minute"
			elif d.seconds < (60 * 60):
				return "%d minutes" % (d.seconds / 60)
			elif d.seconds < (2 * 60 * 60):
				return "about an hour"
			elif d.seconds < (24 * 60 * 60):
				return "%d hours" % (d.seconds / 60 / 60)
		elif d.days < 2:
			return "one day"
		else:
			return "%d days" % (d.days)

register.filter(currency)
register.filter(currency_no_symbol)
register.filter(percentage)
register.filter(format_date)
register.filter(truncate)
register.filter(time_ago_in_words)