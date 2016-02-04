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
import six

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


def group_flavors(request, flavors, extra_specs, exclude_ids=[]):
    groups = collections.defaultdict(list)
    for flavor in flavors:
        if flavor.id in exclude_ids:
            continue
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


def availability_zone_list(request):
    """Utility method to retrieve a list of availability zones."""
    try:
        return api.nova.availability_zone_list(request)
    except Exception:
        exceptions.handle(request,
                          _('Unable to retrieve Nova availability zones.'))
        return []


def network_field_data(request, include_empty_option=False):
    """Returns a list of tuples of all networks.

    Generates a list of networks available to the user (request). And returns
    a list of (id, name) tuples.

    :param request: django http request object
    :param include_empty_option: flag to include a empty tuple in the front of
         the list
    :return: list of (id, name) tuples
    """
    tenant_id = request.user.tenant_id
    networks = []
    if api.base.is_service_enabled(request, 'network'):
        try:
            networks = api.neutron.network_list_for_tenant(request, tenant_id)
            if getattr(settings, 'NECTAR_DEFAULT_NETWORK_ENABLED', False):
                networks = [(n.id, n.name_or_id) for n in networks
                            if not n.shared]
            else:
                networks = [(n.id, n.name_or_id) for n in networks]
            networks.sort(key=lambda obj: obj[1])
            if getattr(settings, 'NECTAR_DEFAULT_NETWORK_ENABLED', False):
                networks.insert(0, ('', 'Default'))
        except Exception as e:
            msg = _('Failed to get network list {0}').format(six.text_type(e))
            exceptions.handle(request, msg)

    if not networks:
        if include_empty_option:
            return [("", _("No networks available")), ]
        return []

    if include_empty_option:
        return [("", _("Select Network")), ] + networks
    return networks


def keypair_field_data(request, include_empty_option=False):
    """Returns a list of tuples of all keypairs.

    Generates a list of keypairs available to the user (request). And returns
    a list of (id, name) tuples.

    :param request: django http request object
    :param include_empty_option: flag to include a empty tuple in the front of
        the list
    :return: list of (id, name) tuples
    """
    keypair_list = []
    try:
        keypairs = api.nova.keypair_list(request)
        keypair_list = [(kp.name, kp.name) for kp in keypairs]
    except Exception:
        exceptions.handle(request, _('Unable to retrieve key pairs.'))

    if not keypair_list:
        if include_empty_option:
            return [("", _("No key pairs available")), ]
        return []

    if include_empty_option:
        return [("", _("Select a key pair")), ] + keypair_list
    return keypair_list


def flavor_field_data(request, include_empty_option=False):
    """Returns a list of tuples of all image flavors.

    Generates a list of image flavors available. And returns a list of
    (id, name) tuples.

    :param request: django http request object
    :param include_empty_option: flag to include a empty tuple in the front of
        the list
    :return: list of (id, name) tuples
    """
    flavors = flavor_list(request)
    if flavors:
        flavors_list = sort_flavor_list(request, flavors)
        if include_empty_option:
            return [("", _("Select Flavor")), ] + flavors_list
        return flavors_list

    if include_empty_option:
        return [("", _("No flavors available")), ]
    return []
