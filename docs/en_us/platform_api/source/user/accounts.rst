.. _User Accounts API:

##################################################
User API User Accounts Resource
##################################################

With the User API **User Accounts** resource, you can complete the following
tasks.

* `Get and Update the User's Account Information`_

.. _Get and Update the User's Account Information:

**********************************************
Get and Update the User's Account Information
**********************************************

.. autoclass:: user_api.accounts.views.AccountView

**Example response showing the user's account information**

.. code-block:: json

    HTTP 200 OK
    Content-Type: application/json
    Vary: Accept
    Allow: GET, HEAD, OPTIONS, PATCH

    {
      "username": "John", 
      "name": "John Doe", 
      "language": "", 
      "gender": "m", 
      "year_of_birth": 1987, 
      "level_of_education": "m", 
      "goals": "Professional Development", 
      "country": US, 
      "mailing_address": "123 Main Street, Anytown, MA 02144", 
      "email": "johndoe@company.com", 
      "date_joined": "2015-03-18T13:42:40Z"
    } 
