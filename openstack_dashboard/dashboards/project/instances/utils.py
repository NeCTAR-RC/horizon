# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import collections
import logging

from django.conf import settings
from django.core import cache
from django.utils.translation import ugettext_lazy as _

from horizon import exceptions

from openstack_dashboard import api

LOG = logging.getLogger(__name__)


def flavor_list(request):
    """Utility method to retrieve a list of flavors."""
    try:
        return api.nova.flavor_list(request)
    except Exception:
        exceptions.handle(request,
                          _('Unable to retrieve instance flavors.'))
        return []


def flavor_extra_specs(request, flavor_id):
    _cache = cache.cache
    try:
        key = 'horizon__nova__extra_specs__%s' % flavor_id
        specs = _cache.get(key)
        if specs is None:
            specs = api.nova.flavor_get_extras(request, flavor_id, raw=True)
            _cache.set(key, specs, 3600)
    except Exception:
        exceptions.handle(request,
                          _('Unable to retrieve instance flavor specs.'))
        specs = {}
    return specs


def group_flavors(request, flavors, extra_specs):
    groups = collections.defaultdict(list)
    for flavor in flavors:
        group_name = extra_specs.get(flavor.id, {}).get('flavor_class:name')
        groups[group_name].append(flavor)

    choice_groups = []
    group_order = getattr(settings, 'CREATE_INSTANCE_FLAVOR_GROUP_ORDER', [])
    for group in group_order + filter(lambda g: g not in group_order,
                                      sorted(groups.keys())):
        if group not in groups:
            continue
        flavors = sort_flavor_list(request, groups[group])
        if group is None:
            # Add groupless flavors to the root.
            choice_groups.extend(flavors)
        else:
            choice_groups.append((group, flavors))
    return choice_groups


def sort_flavor_list(request, flavors):
    """Utility method to sort a list of flavors.
        By default, returns the available flavors, sorted by RAM
        usage (ascending). Override these behaviours with a
        CREATE_INSTANCE_FLAVOR_SORT dict
        in local_settings.py.
    """
    def get_key(flavor, sort_key):
        try:
            return getattr(flavor, sort_key)
        except AttributeError:
            LOG.warning('Could not find sort key "%s". Using the default '
                        '"ram" instead.', sort_key)
            return getattr(flavor, 'ram')
    try:
        flavor_sort = getattr(settings, 'CREATE_INSTANCE_FLAVOR_SORT', {})
        sort_key = flavor_sort.get('key', 'ram')
        rev = flavor_sort.get('reverse', False)
        if not callable(sort_key):
            key = lambda flavor: get_key(flavor, sort_key)
        else:
            key = sort_key
        flavor_list = [(flavor.id, '%s' % flavor.name)
                   for flavor in sorted(flavors, key=key, reverse=rev)]
        return flavor_list
    except Exception:
        exceptions.handle(request,
                          _('Unable to sort instance flavors.'))
        return []
