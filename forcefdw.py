from multicorn import ForeignDataWrapper
from multicorn.utils import log_to_postgres, ERROR, DEBUG

import urllib
import urllib2
import json
import pprint

class DatabaseDotComForeignDataWrapper(ForeignDataWrapper):

    def __init__(self, options, columns):
        super(DatabaseDotComForeignDataWrapper, self).__init__(options, columns)
        self.columns = columns

        self.obj_type = options.get('obj_type', None)
        if self.obj_type is None:
            log_to_postgres('You MUST set the obj_type',
            ERROR)
        self.client_id = options.get('client_id', None)
        if self.client_id is None:
            log_to_postgres('You MUST set the client_id',
            ERROR)
        self.client_secret = options.get('client_secret', None)
        if self.client_secret is None:
            log_to_postgres('You MUST set the client_secret',
            ERROR)
        self.username = options.get('username', None)
        if self.username is None:
            log_to_postgres('You MUST set the username',
            ERROR)
        self.password = options.get('password', None)
        if self.password is None:
            log_to_postgres('You MUST set the password',
            ERROR)
        self.login_server = options.get('login_server', 'https://login.salesforce.com')

        self.oauth = self.get_token()

    def get_token(self):

        # Do OAuth username/password
        token_url = '%s/services/oauth2/token' % self.login_server

        params = urllib.urlencode({
          'grant_type': 'password',
          'client_id': self.client_id,
          'client_secret': self.client_secret,
          'username': self.username,
          'password': self.password
        })

        log_to_postgres('Getting token from %s' % token_url, DEBUG)

        try:
            data = urllib2.urlopen(token_url, params).read()
        except urllib2.URLError, e:
            if hasattr(e, 'code'):
                if e.code == 400:
                    log_to_postgres(
                        'Bad Request', ERROR, 
                        'Check the client_id, client_secret, username and password')
                else:
                    log_to_postgres('HTTP status %d' % e.code, ERROR)
            elif hasattr(e, 'reason'):
                log_to_postgres('Error posting to URL %s: %d %s' % 
                                (token_url, e.reason[0], e.reason[1]), ERROR,
                                'Check the login_server')
            else:
                log_to_postgres('Unknown error %s' % e, ERROR)
	log_to_postgres('Got token %s' % data, DEBUG)
        oauth = json.loads(data)
	log_to_postgres('Logged in to %s as %s' % (self.login_server, self.username))

        return oauth     

    def execute(self, quals, columns, retry = True):
        
        cols = '';        
        for column_name in list(columns):
            cols += ',%s' % column_name
        cols = cols[1:]

        where = ''
        parameters = []
        for qual in quals:
            operator = 'LIKE' if qual.operator == '~~' else qual.operator
            where += ' AND %s %s \'%s\'' % (
                qual.field_name, operator, qual.value)
        where = where[5:]

        query = 'SELECT '+cols+' FROM '+self.obj_type
        if len(where) > 0:
            query += ' WHERE %s ' % where

        log_to_postgres('SOQL query is %s' % query) 

        params = urllib.urlencode({
          'q': query
        })

        query_url = (self.oauth['instance_url'] + 
                    '/services/data/v23.0/query?%s' % params)

        headers = {
          'Authorization': 'OAuth %s' % self.oauth['access_token']
        }

        req = urllib2.Request(query_url, None, headers)
        try:
            data = urllib2.urlopen(req).read()
        except urllib2.URLError, e:
            if hasattr(e, 'code'):
                if e.code == 401 and retry:
                    log_to_postgres('Invalid token %s - trying refresh' % 
                                    self.oauth['access_token']) 
                    self.oauth = self.get_token()
                    for line in self.execute(quals, columns, False):
                        yield line
                    return
                else:
                    log_to_postgres('HTTP status %d' % e.code, ERROR)
            elif hasattr(e, 'reason'):
                log_to_postgres('Error posting to URL %s: %d %s' % 
                                (token_url, e.reason[0], e.reason[1]), ERROR)
            else:
                log_to_postgres('Unknown error %s' % e, ERROR)
	log_to_postgres('Raw response is %s' % data, DEBUG)
        result = json.loads(data)
        for record in result['records']:
            line = {}
            for column_name in list(columns):
                line[column_name] = record[column_name]
            yield line
