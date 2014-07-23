from xml.dom.minidom import parseString
from xml.etree.ElementTree import tostring, SubElement, Element
from datetime import datetime
from dateutil.parser import parse
import urllib
import requests
from urlparse import parse_qs

from .constants import XERO_API_URL
from .exceptions import *


class Manager(object):
    DECORATED_METHODS = ('get', 'save', 'filter', 'report_filter', 'all', 'put')
    
    # For some endpoints we just want the raw XML response back
    RAW_RESPONSE_ENTITIES = ('Reports',) 

    DATETIME_FIELDS = (u'UpdatedDateUTC', u'Updated', u'FullyPaidOnDate', u'CreatedDateUTC',
            u'ExpectedPaymentDate', u'PlannedPaymentDate', u'DateOfBirth', u'StartDate',
            u'EndDate')
    DATE_FIELDS = (u'DueDate', u'Date', u'JournalDate')
    BOOLEAN_FIELDS = (u'IsSupplier', u'IsCustomer')

    MULTI_LINES = (u'LineItem', u'Phone', u'Address', u'TaxRate', 
            u'JournalLine', u'TrackingCategory', u'Payment',
            u'TimesheetLine', u'NumberOfUnit', u'EarningsRate', u'DeductionType',
            u'ReimbursementType', u'LeaveType', u'EarningsRates', u'DeductionTypes',
            u'ReimbursementTypes', u'LeaveTypes', u'Option')

    PLURAL_EXCEPTIONS = {
            'Addresse': 'Address',
            'TrackingCategories': 'TrackingCategory'}

    def __init__(self, name, oauth, api_name):
        self.oauth = oauth
        self.name = name
        
        self.api_url = oauth.api_url
        if (api_name == "payroll"):
            # Payroll endpoints have a different url prefix
            self.api_url = self.api_url.replace("api.xro/2.0", "payroll.xro/1.0")

        # setup our singular variants of the name
        # only if the name ends in 0
        if name in self.PLURAL_EXCEPTIONS:
            self.singular = self.PLURAL_EXCEPTIONS[name]
        elif name[-1] == "s":
            self.singular = name[:len(name)-1]
        else:
            self.singular = name

        for method_name in self.DECORATED_METHODS:
            method = getattr(self, method_name)
            setattr(self, method_name, self._get_data(method))

    def walk_dom(self, dom):
        tree_list = tuple()
        for node in dom.childNodes:
            tagName = getattr(node, 'tagName', None)
            if tagName:
                tree_list += (tagName, self.walk_dom(node),)
            else:
                data = node.data.strip()
                if data:
                    tree_list += (node.data.strip(),)
        return tree_list

    def convert_to_dict(self, deep_list):
        out = {}
        if len(deep_list) > 2:
            lists = [l for l in deep_list if isinstance(l, tuple)]
            keys = [l for l in deep_list if isinstance(l, unicode)]
            for key, data in zip(keys, lists):

                if ((key in self.MULTI_LINES) or (key == self.singular)):
                    # our data is a collection and needs to be handled as such
                    if out:
                        if isinstance(out, dict):
                            # Some field names are both multi and not. If there's
                            # already a populated dict, just go with it
                            out[key] = self.convert_to_dict(data)
                        else:
                            out.append(self.convert_to_dict(data))
                    else:
                        out = [self.convert_to_dict(data)]

                elif len(data) == 1:
                    # we're setting a value
                    # check to see if we need to apply any special
                    # formatting to the value
                    val = data[0]
                    if key in self.BOOLEAN_FIELDS:
                        val = True if val.lower() == 'true' else False
                    if key in self.DATETIME_FIELDS:
                        val = parse(val)
                    if key in self.DATE_FIELDS:
                        val = parse(val).date()
                    
                    if isinstance(out, dict):
                        out[key] = val
                    else:
                        out.append(val)

                elif len(data) > 1:
                    if isinstance(out, dict):
                        out[key] = self.convert_to_dict(data)
                    else:
                        out.append(self.convert_to_dict(data))

        elif len(deep_list) == 2:
            key = deep_list[0]
            data = deep_list[1]
            out[key] = self.convert_to_dict(data)
        else:
            out = deep_list[0]
        return out

    def dict_to_xml(self, root_elm, data):
        for key in data.keys():
            sub_data = data[key]
            elm = SubElement(root_elm, key)

            is_list = isinstance(sub_data, list) or isinstance(sub_data, tuple)
            is_plural = key[len(key)-1] == "s"
            plural_name = key[:len(key)-1]

            # Key references a dict. Unroll the dict
            # as it's own XML node with subnodes
            if isinstance(sub_data, dict):
                self.dict_to_xml(elm, sub_data)

            # Key references a list/tuple
            elif is_list:
                # key name is a plural. This means each item
                # in the list needs to be wrapped in an XML
                # node that is a singular version of the list name.
                if is_plural:
                    for d in sub_data:
                        plural_name = self.PLURAL_EXCEPTIONS.get(plural_name, plural_name)
                        self.dict_to_xml(SubElement(elm, plural_name), d)

                # key name isn't a plural. Just insert the content
                # as an XML node with subnodes
                else:
                    for d in sub_data:
                        self.dict_to_xml(elm, d)

            # Normal element - just inser the data.
            else:
                elm.text = str(sub_data)

        return root_elm

    def _prepare_data_for_save(self, data):
        if isinstance(data, list) or isinstance(data, tuple):
            root_elm = Element(self.name)
            for d in data:
                sub_elm = SubElement(root_elm, self.singular)
                self.dict_to_xml(sub_elm, d)
        else:
            root_elm = self.dict_to_xml(Element(self.singular), data)

        return tostring(root_elm)

    def _get_results(self, data):
        response = data[u'Response']
        result = response.get(self.name, {})

        if isinstance(result, tuple) or isinstance(result, list):
            return result

        if isinstance(result, dict) and self.singular in result:
            return result[self.singular]

    def _get_data(self, func):
        def wrapper(*args, **kwargs):
            uri, method, body, headers = func(*args, **kwargs)
            cert = getattr(self.oauth, 'client_cert', None)
            response = getattr(requests, method)(uri, data=body, headers=headers, auth=self.oauth, cert=cert)

            if response.status_code == 200:
                if response.headers['content-type'] == 'application/pdf':
                    return response.text
                # parseString takes byte content, not unicode.
                dom = parseString(response.text.encode(response.encoding))
                if self.name in self.RAW_RESPONSE_ENTITIES:
                  return dom
                else:
                  data = self.convert_to_dict(self.walk_dom(dom))
                  return self._get_results(data)

            elif response.status_code == 400:
                raise XeroBadRequest(response)

            elif response.status_code == 401:
                raise XeroUnauthorized(response)

            elif response.status_code == 403:
                raise XeroForbidden(response)

            elif response.status_code == 404:
                raise XeroNotFound(response)

            elif response.status_code == 500:
                raise XeroInternalError(response)

            elif response.status_code == 501:
                raise XeroNotImplemented(response)

            elif response.status_code == 503:
                # Two 503 responses are possible. Rate limit errors
                # return encoded content; offline errors don't.
                # If you parse the response text and there's nothing
                # encoded, it must be a not-available error.
                payload = parse_qs(response.text)
                if payload:
                    raise XeroRateLimitExceeded(response, payload)
                else:
                    raise XeroNotAvailable(response)
            else:
                raise XeroExceptionUnknown(response)

        return wrapper

    def get(self, id, headers=None):
        uri = '/'.join([self.api_url, self.name, id])
        return uri, 'get', None, headers

    def save_or_put(self, data, method='post', headers=None):
        uri = '/'.join([self.api_url, self.name])
        body = {'xml': self._prepare_data_for_save(data)}
        return uri, method, body, headers

    def save(self, data):
        return self.save_or_put(data, method='post')

    def put(self, data):
        return self.save_or_put(data, method='put')

    def prepare_filtering_date(self, val):
        if isinstance(val, datetime):
            val = val.strftime('%a, %d %b %Y %H:%M:%S GMT')
        else:
            val = '"%s"' % val
        return {'If-Modified-Since': val}

    def filter(self, **kwargs):
        headers = None
        offset = None        
        page = None
        uri = '/'.join([self.api_url, self.name])
        if kwargs:
            if 'since' in kwargs:
                val = kwargs['since']
                headers = self.prepare_filtering_date(val)
                del kwargs['since']
                
            if 'offset' in kwargs:
                offset = kwargs.pop('offset')
            
            if 'page' in kwargs:
                page = kwargs.pop('page')

            def get_filter_params():
                if key in self.BOOLEAN_FIELDS:
                    return 'true' if kwargs[key] else 'false'
                elif key in self.DATETIME_FIELDS:
                    return kwargs[key].isoformat()
                else:
                    return '"%s"' % str(kwargs[key])

            def generate_param(key):
                parts = key.split("__")
                field = key.replace('_', '.')
                fmt = '%s==%s'
                if len(parts) == 2:
                    # support filters:
                    # Name__Contains=John becomes Name.Contains("John")
                    if parts[1] in ["contains", "startswith", "endswith"]:
                        field = parts[0]
                        fmt = ''.join(['%s.', parts[1], '(%s)'])

                return fmt % (
                    field,
                    get_filter_params()
                )

            query_string_items = []

            params = [generate_param(key) for key in kwargs.keys()]
            if params:
                query_string_items.append('where=' + urllib.quote('&&'.join(params)))
                
            if offset:
                query_string_items.append('offset={0}'.format(offset))

            if page:
                query_string_items.append('page={0}'.format(page))

            if len(query_string_items) > 0:
                uri += "?" + '&'.join(query_string_items)

        return uri, 'get', None, headers
        
    def report_filter(self, id, headers=None, **kwargs):
        uri = '/'.join([self.api_url, self.name, id])
        if kwargs:
            if 'since' in kwargs:
                val = kwargs['since']
                headers = self.prepare_filtering_date(val)
                del kwargs['since']

            def get_filter_params():
                if key in self.BOOLEAN_FIELDS:
                    return 'true' if kwargs[key] else 'false'
                elif key in self.DATETIME_FIELDS:
                    return kwargs[key].isoformat()
                else:
                    return '%s' % str(kwargs[key])
  
            def generate_param(key):
                fmt = '%s=%s'
                return fmt % (
                    key,
                    get_filter_params()
                )

            params = [generate_param(key) for key in kwargs.keys()]

            if params:
                uri += '?' + '&'.join(params)
        
        return uri, 'get', None, headers

    def all(self):
        uri = '/'.join([self.api_url, self.name])
        return uri, 'get', None, None
