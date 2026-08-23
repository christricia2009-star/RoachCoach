ROACH COACH RADAR
CLOUDKIT BACKEND SETUP
======================

FILE PLACEMENT
--------------

The repository must contain these files:

    api/
        index.py

    backend/
        cloudkit_client.py

    requirements_cloudkit.txt

    README.txt


CLOUDKIT CONTAINER
------------------

Container:

    iCloud.com.TrueFamily.RoachCoachRadar

The CloudKit client defaults to this container automatically.

The production environment is also the default.


VERCEL ENVIRONMENT VARIABLES
----------------------------

Set these variables in Vercel:

    CLOUDKIT_CONTAINER_ID

    CLOUDKIT_ENVIRONMENT

    CLOUDKIT_SERVER_KEY_ID

    CLOUDKIT_SERVER_PRIVATE_KEY


VALUES
------

CLOUDKIT_CONTAINER_ID:

    iCloud.com.TrueFamily.RoachCoachRadar

CLOUDKIT_ENVIRONMENT:

    production

CLOUDKIT_SERVER_KEY_ID:

    Your CloudKit Server-to-Server Key ID

CLOUDKIT_SERVER_PRIVATE_KEY:

    The complete private EC key associated with the
    CloudKit Server-to-Server Key.


IMPORTANT PRIVATE KEY FORMAT
----------------------------

The private key must be stored as the complete PEM value.

Example:

-----BEGIN PRIVATE KEY-----
...
-----END PRIVATE KEY-----

If Vercel stores the newlines as literal "\n" characters,
cloudkit_client.py converts them back into real newlines
automatically.


DEPLOYMENT
----------

Deploy the repository normally through Vercel.

The CloudKit-specific Python dependencies are listed in:

    requirements_cloudkit.txt

Make sure the Vercel Python build installs the dependencies
listed in that file.


ENDPOINTS
---------

Health:

    GET /health

Trucks:

    GET /trucks

All active sightings:

    GET /sightings

Sightings for a truck:

    GET /trucks/{truck_id}/sightings

Radar:

    POST /radar/observations


CLOUDKIT RECORD TYPES
---------------------

The CloudKit client expects these record types:

    Truck

    Sighting


TRUCK FIELDS
------------

Truck:

    name
    cuisineType
    socialLinks
    averageConfidenceScore
    menuHighlights
    imageURL


SIGHTING FIELDS
---------------

Sighting:

    truckId
    latitude
    longitude
    note
    photoURL
    confidenceLevel
    timestamp
    expiresAt


DATABASE
--------

The CloudKit client uses the PUBLIC database.

This means the server does not use the user's private
CloudKit database.

The CloudKit API endpoint is:

    https://api.apple-cloudkit.com


TROUBLESHOOTING
---------------

If /health works but /trucks or /sightings returns:

    CloudKit unavailable

check the following:

1. CLOUDKIT_SERVER_KEY_ID exists in Vercel.

2. CLOUDKIT_SERVER_PRIVATE_KEY exists in Vercel.

3. The private key is the private EC key belonging to the
   CloudKit Server-to-Server key.

4. CLOUDKIT_CONTAINER_ID is exactly:

       iCloud.com.TrueFamily.RoachCoachRadar

5. CLOUDKIT_ENVIRONMENT is:

       production

6. The CloudKit container is available to the Apple Developer
   account associated with the application.

7. The Truck and Sighting record types exist in the CloudKit
   container.

8. The fields listed above use the exact capitalization shown
   above.


DO NOT PUT SECRETS IN GITHUB
----------------------------

Never commit the CloudKit private key to this repository.

Only store the private key in Vercel Environment Variables.


FINAL DEPLOYMENT CHECK
----------------------

After deploying, test:

    /health

Expected response:

    {
      "status": "ok",
      "cloudkit": true
    }

Then test:

    /trucks

Then:

    /sightings

If /health works but the other two endpoints fail, the
problem is CloudKit authentication, CloudKit schema, or
CloudKit permissions rather than the FastAPI routing.
