# Public/Private
XERO_BASE_URL = "https://api.xero.com"
REQUEST_TOKEN_URL = "%s/oauth/RequestToken" % XERO_BASE_URL
AUTHORIZE_URL = "%s/oauth/Authorize" % XERO_BASE_URL
ACCESS_TOKEN_URL = "%s/oauth/AccessToken" % XERO_BASE_URL
XERO_API_URL = "%s/api.xro/2.0" % XERO_BASE_URL

# Partner
PARTNER_XERO_BASE_URL = "https://api-partner.network.xero.com"
PARTNER_REQUEST_TOKEN_URL = "%s/oauth/RequestToken" % PARTNER_XERO_BASE_URL
PARTNER_AUTHORIZE_URL = AUTHORIZE_URL
PARTNER_ACCESS_TOKEN_URL = "%s/oauth/AccessToken" % PARTNER_XERO_BASE_URL
PARTNER_XERO_API_URL = "%s/api.xro/2.0" % PARTNER_XERO_BASE_URL