from multicorn import ForeignDataWrapper
from multicorn.utils import log_to_postgres, ERROR, DEBUG
from yajl import YajlContentHandler, YajlParser

from Queue import Queue
from threading import Thread

import urllib
import urllib2
import json
import pprint

import collections

class CaseInsensitiveDict(collections.Mapping):
    def __init__(self, d):
        self._d = d
        self._s = dict((k.lower(), k) for k in d)
    def __contains__(self, k):
        return k.lower() in self._s
    def __len__(self):
        return len(self._s)
    def __iter__(self):
        return iter(self._s)
    def __getitem__(self, k):
        return self._d[self._s[k.lower()]]
    def actual_key_case(self, k):
        return self._s.get(k.lower())

# ContentHandler implements a simple state machine to parse the records from 
# the incoming JSON stream, adding them to the queue as maps of column name
# to column value. We skip over any record properties that are not simple 
# values (e.g. attributes, which is an object containing the record's type
# and URL)/
class ContentHandler(YajlContentHandler):
    _column = ''

    # States
    INIT = 0
    IN_OBJECT = 1
    SEEN_RECORDS = 2
    IN_ARRAY = 3 
    IN_RECORD = 4
    SEEN_KEY = 5

    _state = INIT

    _depth = 0

    def __init__(self, queue, column_map):
        self._queue = queue
        self._column_map = column_map

    def handle_value(self, ctx, val):
        if self._state == ContentHandler.SEEN_KEY and self._depth == 0:
            self._state = ContentHandler.IN_RECORD
            self._record[self._column_map[self._column]] = val

    def yajl_null(self, ctx):
        self.handle_value(ctx, None)

    def yajl_boolean(self, ctx, boolVal):
        self.handle_value(ctx, boolVal)

    def yajl_integer(self, ctx, integerVal):
        self.handle_value(ctx, integerVal)

    def yajl_double(self, ctx, doubleVal):
        self.handle_value(ctx, doubleVal)

    def yajl_string(self, ctx, stringVal):
        self.handle_value(ctx, stringVal)

    def yajl_start_map(self, ctx):
        if self._state == ContentHandler.SEEN_KEY:
            self._depth += 1
        elif self._state == ContentHandler.IN_ARRAY:
            self._state = ContentHandler.IN_RECORD
            self._record = {}
        elif self._state == ContentHandler.INIT:
            self._state = ContentHandler.IN_OBJECT

    def yajl_map_key(self, ctx, stringVal):
        if self._state == ContentHandler.IN_RECORD:
            self._state = ContentHandler.SEEN_KEY
            self._column = stringVal
        elif self._state == ContentHandler.IN_OBJECT and stringVal == 'records':
            self._state = ContentHandler.SEEN_RECORDS

    def yajl_end_map(self, ctx):
        if self._state == ContentHandler.SEEN_KEY:
            self._depth -= 1
            if self._depth == 0:
                self._state = ContentHandler.IN_RECORD
        elif self._state == ContentHandler.IN_RECORD:
            self._state = ContentHandler.IN_ARRAY
            self._queue.put(self._record)
        elif self._state == ContentHandler.IN_OBJECT:
            self._state = ContentHandler.INIT

    def yajl_start_array(self, ctx):
        if self._state == ContentHandler.SEEN_RECORDS:
            self._state = ContentHandler.IN_ARRAY

    def yajl_end_array(self, ctx):
        if self._state == ContentHandler.IN_ARRAY:
            self._state = ContentHandler.IN_OBJECT

# Parse the given stream to a queue
def parseToQueue(stream, queue, column_map):
    parser = YajlParser(ContentHandler(queue, column_map))
    parser.parse(stream)
    queue.put(None)

class DatabaseDotComForeignDataWrapper(ForeignDataWrapper):

    def __init__(self, options, columns):
        super(DatabaseDotComForeignDataWrapper, self).__init__(options, columns)
        self.column_map = CaseInsensitiveDict(dict([(x, x) for x in columns]))

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

        queue = Queue()

        try:
            stream = urllib2.urlopen(req);
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
        t = Thread(target=parseToQueue, args=(stream, queue, self.column_map))        
        t.daemon = True
        t.start()
        item = queue.get()
        while item is not None:
            yield item
            queue.task_done()
            item = queue.get()
