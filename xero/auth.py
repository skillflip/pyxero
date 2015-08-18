import datetime
import requests
from requests_oauthlib import OAuth1
from oauthlib.oauth1 import SIGNATURE_RSA, SIGNATURE_TYPE_AUTH_HEADER
from urlparse import parse_qs
from urllib import urlencode

from .constants import (REQUEST_TOKEN_URL, AUTHORIZE_URL, ACCESS_TOKEN_URL, XERO_API_URL,
                        PARTNER_REQUEST_TOKEN_URL, PARTNER_AUTHORIZE_URL, PARTNER_ACCESS_TOKEN_URL, PARTNER_XERO_API_URL, )
from .exceptions import *


class PrivateCredentials(object):
    """An object wrapping the 2-step OAuth process for Private Xero API access.

    Usage:

     1) Construct a PrivateCredentials() instance:

        >>> from xero.auth import PrivateCredentials
        >>> credentials = PrivateCredentials(<consumer_key>, <rsa_key>)

        rsa_key should be a multi-line string, starting with:

            -----BEGIN RSA PRIVATE KEY-----\n

     2) Use the credentials:

        >>> from xero import Xero
        >>> xero = Xero(credentials)
        >>> xero.contacts.all()
        ...
    """
    def __init__(self, consumer_key, rsa_key):
        self.consumer_key = consumer_key
        self.rsa_key = rsa_key

        # Private API uses consumer key as the OAuth token.
        self.oauth_token = consumer_key

        self.oauth = OAuth1(
            self.consumer_key,
            resource_owner_key=self.oauth_token,
            rsa_key=self.rsa_key,
            signature_method=SIGNATURE_RSA,
            signature_type=SIGNATURE_TYPE_AUTH_HEADER,
        )
        self.oauth.api_url = XERO_API_URL


class PublicCredentials(object):
    """An object wrapping the 3-step OAuth process for Public Xero API access.

    Usage:

     1) Construct a PublicCredentials() instance:

        >>> from xero import PublicCredentials
        >>> credentials = PublicCredentials(<consumer_key>, <consumer_secret>)

     2) Visit the authentication URL:

        >>> credentials.url

        If a callback URI was provided (e.g., https://example.com/oauth),
        the user will be redirected to a URL of the form:

        https://example.com/oauth?oauth_token=<token>&oauth_verifier=<verifier>&org=<organization ID>

        from which the verifier can be extracted. If no callback URI is
        provided, the verifier will be shown on the screen, and must be
        manually entered by the user.

     3) Verify the instance:

        >>> credentials.verify(<verifier string>)

     4) Use the credentials.

        >>> from xero import Xero
        >>> xero = Xero(credentials)
        >>> xero.contacts.all()
        ...
    """
    def __init__(self, consumer_key, consumer_secret,
                 callback_uri=None, verified=False,
                 oauth_token=None, oauth_token_secret=None,
                 scope=None):
        """Construct the auth instance.

        Must provide the consumer key and secret.
        A callback URL may be provided as an option. If provided, the
        Xero verification process will redirect to that URL when

        """
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.callback_uri = callback_uri
        self.verified = verified
        self.scope = scope
        self._oauth = None

        if oauth_token and oauth_token_secret:
            if self.verified:
                # If provided, this is a fully verified set of
                # crednetials. Store the oauth_token and secret
                # and initialize OAuth around those
                self._init_oauth(oauth_token, oauth_token_secret)

            else:
                # If provided, we are reconstructing an initalized
                # (but non-verified) set of public credentials.
                self.oauth_token = oauth_token
                self.oauth_token_secret = oauth_token_secret

        else:
            oauth = OAuth1(
                consumer_key,
                client_secret=self.consumer_secret,
                callback_uri=self.callback_uri
            )

            response = requests.post(url=REQUEST_TOKEN_URL, auth=oauth)

            if response.status_code == 200:
                credentials = parse_qs(response.text)
                self.oauth_token = credentials.get('oauth_token')[0]
                self.oauth_token_secret = credentials.get('oauth_token_secret')[0]

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

    def _init_oauth(self, oauth_token, oauth_token_secret):
        "Store and initialize the OAuth credentials"
        self.oauth_token = oauth_token
        self.oauth_token_secret = oauth_token_secret
        self.verified = True

        self._oauth = OAuth1(
            self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.oauth_token,
            resource_owner_secret=self.oauth_token_secret
        )
        self._oauth.api_url = XERO_API_URL

    @property
    def state(self):
        """Obtain the useful state of this credentials object so that
        we can reconstruct it independently.
        """
        return dict(
            (attr, getattr(self, attr))
            for attr in (
                'consumer_key', 'consumer_secret', 'callback_uri',
                'verified', 'oauth_token', 'oauth_token_secret', 'scope'
            )
            if getattr(self, attr) is not None
        )

    def verify(self, verifier):
        "Verify an OAuth token"

        # Construct the credentials for the verification request
        oauth = OAuth1(
            self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.oauth_token,
            resource_owner_secret=self.oauth_token_secret,
            verifier=verifier
        )

        # Make the verification request, gettiung back an access token
        response = requests.post(url=ACCESS_TOKEN_URL, auth=oauth)

        if response.status_code == 200:
            credentials = parse_qs(response.text)
            # Initialize the oauth credentials
            self._init_oauth(
                credentials.get('oauth_token')[0],
                credentials.get('oauth_token_secret')[0]
            )
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

    @property
    def url(self):
        "Returns the URL that can be visited to obtain a verifier code"
        query_string = {'oauth_token': self.oauth_token}

        if self.scope:
            query_string['scope'] = self.scope

        return AUTHORIZE_URL + '?' + urlencode(query_string)

    @property
    def oauth(self):
        "Returns the requests-compatible OAuth object"
        if self._oauth is None:
            raise XeroNotVerified("Public credentials haven't been verified")
        return self._oauth

class PartnerCredentials(object):
    """An object wrapping the 3-step OAuth process for Partner Xero API access.
    
    Usage is similar to Public Credentials, but with RSA encryption and automatic refresh of expired
    tokens.

    Usage:

     1) Construct a PublicCredentials() instance:

        >>> from xero import PublicCredentials
        >>> credentials = PublicCredentials(<consumer_key>, <consumer_secret>, <rsa_key>)

     2) Visit the authentication URL:

        >>> credentials.url

        If a callback URI was provided (e.g., https://example.com/oauth),
        the user will be redirected to a URL of the form:

        https://example.com/oauth?oauth_token=<token>&oauth_verifier=<verifier>&org=<organization ID>

        from which the verifier can be extracted. If no callback URI is
        provided, the verifier will be shown on the screen, and must be
        manually entered by the user.

     3) Verify the instance:

        >>> credentials.verify(<verifier string>)

     4) Use the credentials.

        >>> from xero import Xero
        >>> xero = Xero(credentials)
        >>> xero.contacts.all()
        ...
    """
    def __init__(self, consumer_key, consumer_secret, rsa_key, client_cert,
                 callback_uri=None, verified=False,
                 oauth_token=None, oauth_token_secret=None, oauth_session_handle=None,
                 oauth_expires_at=None, oauth_authorization_expires_at=None,
                 scope=None):
        """Construct the auth instance.

        Must provide the consumer key, secret, and RSA key.
        
        A callback URL may be provided as an option. If provided, the
        Xero verification process will redirect to that URL when

        """
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.rsa_key = rsa_key
        self.client_cert = client_cert
        self.callback_uri = callback_uri
        self.verified = verified
        self.oauth_session_handle = oauth_session_handle
        self.oauth_expires_at = oauth_expires_at
        self.oauth_authorization_expires_at = oauth_authorization_expires_at
        self.scope = scope
        self._oauth = None

        if oauth_token and oauth_token_secret:
            if self.verified:
                # If provided, this is a fully verified set of
                # credentials. Store the oauth_token and secret
                # and initialize OAuth around those
                self._init_oauth(oauth_token, oauth_token_secret)

            else:
                # If provided, we are reconstructing an initalized
                # (but non-verified) set of public credentials.
                self.oauth_token = oauth_token
                self.oauth_token_secret = oauth_token_secret

        else:
            oauth = OAuth1(
                consumer_key,
                client_secret=self.consumer_secret,
                callback_uri=self.callback_uri,
                rsa_key=self.rsa_key,
                signature_method=SIGNATURE_RSA,
            )

            response = requests.post(url=PARTNER_REQUEST_TOKEN_URL, auth=oauth, cert=client_cert)

            if response.status_code == 200:
                credentials = parse_qs(response.text)
                self.oauth_token = credentials.get('oauth_token')[0]
                self.oauth_token_secret = credentials.get('oauth_token_secret')[0]

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

    def _init_oauth(self, oauth_token, oauth_token_secret):
        "Store and initialize the OAuth credentials"
        self.oauth_token = oauth_token
        self.oauth_token_secret = oauth_token_secret
        self.verified = True

        self._oauth = OAuth1(
            self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.oauth_token,
            resource_owner_secret=self.oauth_token_secret,
            rsa_key=self.rsa_key,
            signature_method=SIGNATURE_RSA,
        )
        self._oauth.client_cert = self.client_cert
        self._oauth.api_url = PARTNER_XERO_API_URL

    @property
    def state(self):
        """Obtain the useful state of this credentials object so that
        we can reconstruct it independently.
        """
        return dict(
            (attr, getattr(self, attr))
            for attr in (
                'consumer_key', 'consumer_secret', 'callback_uri',
                'verified', 'oauth_token', 'oauth_token_secret',
                'oauth_session_handle', 'oauth_expires_at', 
                'oauth_authorization_expires_at', 'scope'
            )
            if getattr(self, attr) is not None
        )

    def verify(self, verifier):
        "Verify an OAuth token"

        # Construct the credentials for the verification request
        oauth = OAuth1(
            self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.oauth_token,
            resource_owner_secret=self.oauth_token_secret,
            verifier=verifier,
            rsa_key=self.rsa_key,
            signature_method=SIGNATURE_RSA,
        )

        # Make the verification request, getting back an access token
        response = requests.post(url=PARTNER_ACCESS_TOKEN_URL, auth=oauth, cert=self.client_cert)
        self._process_access_token_response(response)

    def refresh(self):
        "Refresh an expired token"
        # Construct the credentials for the verification request
        oauth = OAuth1(
            self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.oauth_token,
            resource_owner_secret=self.oauth_token_secret,
            rsa_key=self.rsa_key,
            signature_method=SIGNATURE_RSA,
        )

        # Make the verification request, getting back an access token
        params = {'oauth_session_handle': self.oauth_session_handle}
        response = requests.post(url=PARTNER_ACCESS_TOKEN_URL, params=params, auth=oauth, cert=self.client_cert)
        self._process_access_token_response(response)

    def _process_access_token_response(self, response):
        if response.status_code == 200:
            credentials = parse_qs(response.text)

            # Initialize the oauth credentials
            self._init_oauth(
                credentials.get('oauth_token')[0],
                credentials.get('oauth_token_secret')[0]
            )
            
            self.oauth_expires_in = credentials.get('oauth_expires_in')[0]
            self.oauth_session_handle = credentials.get('oauth_session_handle')[0]
            self.oauth_authorisation_expires_in = credentials.get('oauth_authorization_expires_in')[0]
            
            # Calculate token/auth expiry
            self.oauth_expires_at = datetime.datetime.now() + \
                                    datetime.timedelta(seconds=int(self.oauth_expires_in))
            self.oauth_authorization_expires_at = \
                                    datetime.datetime.now() + \
                                    datetime.timedelta(seconds=int(self.oauth_authorisation_expires_in))
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

    @property
    def url(self):
        "Returns the URL that can be visited to obtain a verifier code"
        query_string = {'oauth_token': self.oauth_token}

        if self.scope:
            query_string['scope'] = self.scope

        return PARTNER_AUTHORIZE_URL + '?' + urlencode(query_string)

    @property
    def oauth(self):
        "Returns the requests-compatible OAuth object"
        if self._oauth is None:
            raise XeroNotVerified("Public credentials haven't been verified")
        return self._oauth
  
