from django.conf import settings
from django.template.defaultfilters import floatformat  # noqa
from django.http import HttpResponse
from django.utils import translation
from django.utils.translation import ugettext_lazy as _
from django.shortcuts import render

import json
import requests
import time
from datetime import datetime

from horizon import exceptions

from openstack_dashboard import api
from openstack_dashboard import usage

class Gnocchi(object):
    def postJson(self, url, headers, payload):
        r = requests.post(url, headers=headers, data=payload)

        if r.status_code in [200, 201]:
            return r.json()

        if r.status_code in [202]:
            return True

        print "Error: " + str(r.status_code)
        print r.content
        return False

    def findMetric(self, gnocchi, name, token):
        headers = {'Content-Type': "application/json",
        'X-Auth-Token': token}
        url = gnocchi + "/v1/metric"
        r = requests.get(url, headers=headers)
        if r.status_code in [200]:
            for record in r.json():
                if record['name'] == name:
                    return record['id']

    def listMetrics(self, gnocchi, token):
        headers = {'Content-Type': "application/json",
        'X-Auth-Token': token}
        url = gnocchi + "/v1/metric"
        r = requests.get(url, headers=headers)
        if r.status_code in [200]:
            return r.content

    def listResources(self, gnocchi, token):
        headers = {'Content-Type': "application/json",
        'X-Auth-Token': token}
        url = gnocchi + "/v1/resource/generic"
        r = requests.get(url, headers=headers)
        if r.status_code in [200]:
            return r.content

    def queryMeasures(self, gnocchi, metric, token, qStart=None, qStop=None):
        headers = {'Content-Type': "application/json",
        'X-Auth-Token': token}

        timeQuery = True
        if not qStart or not qStop:
            timeQuery = False
            now = time.time()
            qStop = now
            qStart = now - 3600

        timerange="?start=" + str(qStart) + "&stop=" + str(qStop)
        url = gnocchi + "/v1/metric/" + metric + "/measures" + timerange

        requestStart = time.time()
        r = requests.get(url, headers=headers)
        requestTime = time.time() - requestStart

        if not r.status_code in [200]:
            return "This is odd: " + str(r.status_code) + "..and also: " + r.content

        return r.json()
