Database.com FDW for PostgreSQL
===============================

This Python module implements the multicorn.ForeignDataWrapper interface to allow you to create foreign tables in PostgreSQL 9.1+ that map to sobjects in database.com/Force.com.

Pre-requisites
--------------

* [PostgreSQL 9.1+](http://www.postgresql.org/)
* [Python](http://python.org/)
* [Multicorn](http://multicorn.org)

Installation
------------

1. [Create a Remote Access Application](http://wiki.developerforce.com/page/Getting_Started_with_the_Force.com_REST_API#Setup), since you will need a client ID and client secret so that that the FDW can login via OAuth and use the REST API.
2. [Install Multicorn](http://multicorn.org/#installation)
3. Build the FDW module:
```
$ cd Database.com-FDW-for-PostgreSQL
$ python setup.py sdist
$ sudo python setup.py install
```
4. In the PostgreSQL client, create the extension and foreign server:
   ```
   CREATE EXTENSION multicorn;
   CREATE SERVER multicorn_force FOREIGN DATA WRAPPER multicorn
   OPTIONS (
       wrapper 'forcefdw.DatabaseDotComForeignDataWrapper'
   );
   ```
5. Create a foreign table. You can use any subset of fields from the sobject, but note that field names are case sensitive and must be quoted in the DDL:
   ```
   CREATE FOREIGN TABLE contacts (
       "FirstName" character varying,
       "LastName" character varying,
       "Email" character varying
   ) SERVER multicorn_force OPTIONS (
       obj_type 'Contact',
       client_id 'CONSUMER_KEY_FROM_REMOTE_ACCESS_APP,
       client_secret 'CONSUMER_SECRET_FROM_REMOTE_ACCESS_APP',
       username 'user@domain.com',
       password '********'
   );
   ```
6. Query the foreign table as if it were any other table. You will see some diagnostics as the FDW interacts with database.com/Force.com. Note that you will have to quote field names, just as you did when creating the table. Here are some examples:
   ```
   SELECT * FROM contacts;
   NOTICE:  Logged in to https://login.salesforce.com as pat@superpat.com
   NOTICE:  SOQL query is SELECT LastName,Email,FirstName FROM Contact
    FirstName |              LastName               |           Email           
   -----------+-------------------------------------+---------------------------
    Rose      | Gonzalez                            | rose@edge.com
    Sean      | Forbes                              | sean@edge.com
    Jack      | Rogers                              | jrogers@burlington.com
    Pat       | Stumuller                           | pat@pyramid.net
    Andy      | Young                               | a_young@dickenson.com
    Tim       | Barr                                | barr_tim@grandhotels.com
   ...etc...
   postgres=# SELECT "Email" FROM contacts WHERE "LastName" LIKE 'G%';
   NOTICE:  SOQL query is SELECT LastName,Email FROM Contact WHERE LastName LIKE 'G%' 
          Email       
   -------------------
    rose@edge.com
    jane_gray@uoa.edu
    agreen@uog.com
   (3 rows)
   postgres=# SELECT COUNT(*) FROM contacts WHERE "LastName" LIKE 'G%';
   NOTICE:  SOQL query is SELECT LastName,Email,FirstName FROM Contact WHERE LastName LIKE 'G%' 
    count 
   -------
        3
   (1 row)

   ```
