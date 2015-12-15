# Copyright 2012 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2012 Nebula, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Views for managing instances.
"""
from collections import OrderedDict
import logging

from django.core.urlresolvers import reverse
from django.core.urlresolvers import reverse_lazy
from django import http
from django import shortcuts
from django.utils.translation import ugettext_lazy as _
from django.views import generic
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from django.utils.decorators import method_decorator

import requests
import json
import time
from datetime import datetime, timedelta

from horizon import exceptions
from horizon import forms
from horizon import messages
from horizon import tables
from horizon import tabs
from horizon.utils import memoized
from horizon import workflows
from keystoneclient.auth.identity import v2
from keystoneclient import session
from gnocchiclient.v1 import client

from openstack_dashboard import api

from openstack_dashboard.dashboards.project.instances \
    import console as project_console
from openstack_dashboard.dashboards.project.instances \
    import forms as project_forms
from openstack_dashboard.dashboards.project.instances \
    import tables as project_tables
from openstack_dashboard.dashboards.project.instances \
    import tabs as project_tabs
from openstack_dashboard.dashboards.project.instances \
    import workflows as project_workflows

LOG = logging.getLogger(__name__)


class IndexView(tables.DataTableView):
    table_class = project_tables.InstancesTable
    template_name = 'project/instances/index.html'
    page_title = _("Instances")

    def has_more_data(self, table):
        return self._more

    def get_data(self):
        marker = self.request.GET.get(
            project_tables.InstancesTable._meta.pagination_param, None)
        search_opts = self.get_filters({'marker': marker, 'paginate': True})
        # Gather our instances
        try:
            instances, self._more = api.nova.server_list(
                self.request,
                search_opts=search_opts)
        except Exception:
            self._more = False
            instances = []
            exceptions.handle(self.request,
                              _('Unable to retrieve instances.'))

        if instances:
            try:
                api.network.servers_update_addresses(self.request, instances)
            except Exception:
                exceptions.handle(
                    self.request,
                    message=_('Unable to retrieve IP addresses from Neutron.'),
                    ignore=True)

            # Gather our flavors and images and correlate our instances to them
            try:
                flavors = api.nova.flavor_list(self.request)
            except Exception:
                flavors = []
                exceptions.handle(self.request, ignore=True)

            try:
                # TODO(gabriel): Handle pagination.
                images, more, prev = api.glance.image_list_detailed(
                    self.request)
            except Exception:
                images = []
                exceptions.handle(self.request, ignore=True)

            full_flavors = OrderedDict([(str(flavor.id), flavor)
                                       for flavor in flavors])
            image_map = OrderedDict([(str(image.id), image)
                                    for image in images])

            # Loop through instances to get flavor info.
            for instance in instances:
                if hasattr(instance, 'image'):
                    # Instance from image returns dict
                    if isinstance(instance.image, dict):
                        if instance.image.get('id') in image_map:
                            instance.image = image_map[instance.image['id']]

                try:
                    flavor_id = instance.flavor["id"]
                    if flavor_id in full_flavors:
                        instance.full_flavor = full_flavors[flavor_id]
                    else:
                        # If the flavor_id is not in full_flavors list,
                        # get it via nova api.
                        instance.full_flavor = api.nova.flavor_get(
                            self.request, flavor_id)
                except Exception:
                    msg = ('Unable to retrieve flavor "%s" for instance "%s".'
                           % (flavor_id, instance.id))
                    LOG.info(msg)
        return instances

    def get_filters(self, filters):
        filter_action = self.table._meta._filter_action
        if filter_action:
            filter_field = self.table.get_filter_field()
            if filter_action.is_api_filter(filter_field):
                filter_string = self.table.get_filter_string()
                if filter_field and filter_string:
                    filters[filter_field] = filter_string
        return filters


class LaunchInstanceView(workflows.WorkflowView):
    workflow_class = project_workflows.LaunchInstance

    def get_initial(self):
        initial = super(LaunchInstanceView, self).get_initial()
        initial['project_id'] = self.request.user.tenant_id
        initial['user_id'] = self.request.user.id
        return initial


def console(request, instance_id):
    data = _('Unable to get log for instance "%s".') % instance_id
    tail = request.GET.get('length')
    if tail and not tail.isdigit():
        msg = _('Log length must be a nonnegative integer.')
        messages.warning(request, msg)
    else:
        try:
            data = api.nova.server_console_output(request,
                                                  instance_id,
                                                  tail_length=tail)
        except Exception:
            exceptions.handle(request, ignore=True)
    return http.HttpResponse(data.encode('utf-8'), content_type='text/plain')


def vnc(request, instance_id):
    try:
        instance = api.nova.server_get(request, instance_id)
        console_url = project_console.get_console(request, 'VNC', instance)[1]
        return shortcuts.redirect(console_url)
    except Exception:
        redirect = reverse("horizon:project:instances:index")
        msg = _('Unable to get VNC console for instance "%s".') % instance_id
        exceptions.handle(request, msg, redirect=redirect)


def spice(request, instance_id):
    try:
        instance = api.nova.server_get(request, instance_id)
        console_url = project_console.get_console(request, 'SPICE',
                                                  instance)[1]
        return shortcuts.redirect(console_url)
    except Exception:
        redirect = reverse("horizon:project:instances:index")
        msg = _('Unable to get SPICE console for instance "%s".') % instance_id
        exceptions.handle(request, msg, redirect=redirect)


def rdp(request, instance_id):
    try:
        instance = api.nova.server_get(request, instance_id)
        console_url = project_console.get_console(request, 'RDP', instance)[1]
        return shortcuts.redirect(console_url)
    except Exception:
        redirect = reverse("horizon:project:instances:index")
        msg = _('Unable to get RDP console for instance "%s".') % instance_id
        exceptions.handle(request, msg, redirect=redirect)


def metric_data(request, instance_id, metric_name, time_range):
    keystone_url = api.base.url_for(request,
                                    'identity',
                                    endpoint_type='publicURL')

    version = keystone_url.rsplit('/', 1)[-1]

    auth = v2.Token(
                auth_url=keystone_url,
                token=request.user.token.id,
                tenant_id=request.user.tenant_id)

    sess = session.Session(auth=auth)
    gnocchi_client = client.Client(sess)

    resource = gnocchi_client.resource.get("instance", instance_id)

    if metric_name in resource['metrics']:
        metric = resource['metrics'][metric_name]
        now = time.time()
        datenow = datetime.now()
        if time_range == "None":
            start = now - 21600
            start = datetime.fromtimestamp(time.mktime(time.localtime(start))).strftime('%Y-%m-%dT%H:%M:%S')
        else:
            start = now - float(time_range)
            start = datetime.fromtimestamp(time.mktime(time.localtime(start))).strftime('%Y-%m-%dT%H:%M:%S')
        now = datetime.fromtimestamp(time.mktime(time.localtime(now))).strftime('%Y-%m-%dT%H:%M:%S')
        
        measures = gnocchi_client.metric.get_measures(str(metric), start, now)
        while datetime.strptime(measures[-1][0], '%Y-%m-%dT%H:%M:%S+00:00') < datenow - timedelta(minutes=measures[-1][1]):
            paged = gnocchi_client.metric.get_measures(str(metric), measures[-1][0], now)
            measures = measures + paged
    else:
        measures = ""

    f = open('/tmp/' +metric_name, 'w+' )
    f.write('Start: ' + start + '\n')
    f.write('Now:' + now + '\n')
    f.write('Total records: ' + str(len(measures)) + '\n')
    f.write(str(measures))
    f.close()

    if len(measures) > 0:
        graphdata = [0] * len(measures)
        for i in range(len(measures)):
            if len(measures[i]) > 1:
                hasdata = True
                timestamp = datetime.strptime(measures[i][0], '%Y-%m-%dT%H:%M:%S+00:00')
                measuredate = datetime.fromtimestamp(time.mktime((timestamp.timetuple()))).strftime('%Y-%m-%dT%H:%M:%S')
                newdict = {'x': measuredate, 'y': measures [i][2]}
                graphdata[i] = newdict
            else:
                hasdata = False

        series = []
        if hasdata:
            seriesdata = {'name': str(metric_name), 'data': graphdata}
            series.append(seriesdata)

        jsondata = {'series': series, 'settings': {'axes_x': False, 'auto_size': False}}
    else:
        jsondata = {'series': [], 'settings': {}}

    return http.HttpResponse(json.dumps(jsondata), content_type='application/json')


class SerialConsoleView(generic.TemplateView):
    template_name = 'project/instances/serial_console.html'

    def get_context_data(self, **kwargs):
        context = super(SerialConsoleView, self).get_context_data(**kwargs)
        context['instance_id'] = self.kwargs['instance_id']
        instance = None
        try:
            instance = api.nova.server_get(self.request,
                                           self.kwargs['instance_id'])
        except Exception:
            context["error_message"] = _(
                "Cannot find instance %s.") % self.kwargs['instance_id']
            # name is unknown, so leave it blank for the window title
            # in full-screen mode, so only the instance id is shown.
            context['instance_name'] = ''
            return context
        context['instance_name'] = instance.name
        try:
            console_url = project_console.get_console(self.request,
                                                      "SERIAL", instance)[1]
            context["console_url"] = console_url
        except exceptions.NotAvailable:
            context["error_message"] = _(
                "Cannot get console for instance %s.") % self.kwargs[
                'instance_id']
        return context


class UpdateView(workflows.WorkflowView):
    workflow_class = project_workflows.UpdateInstance
    success_url = reverse_lazy("horizon:project:instances:index")

    def get_context_data(self, **kwargs):
        context = super(UpdateView, self).get_context_data(**kwargs)
        context["instance_id"] = self.kwargs['instance_id']
        return context

    @memoized.memoized_method
    def get_object(self, *args, **kwargs):
        instance_id = self.kwargs['instance_id']
        try:
            return api.nova.server_get(self.request, instance_id)
        except Exception:
            redirect = reverse("horizon:project:instances:index")
            msg = _('Unable to retrieve instance details.')
            exceptions.handle(self.request, msg, redirect=redirect)

    def get_initial(self):
        initial = super(UpdateView, self).get_initial()
        initial.update({'instance_id': self.kwargs['instance_id'],
                        'name': getattr(self.get_object(), 'name', '')})
        return initial


class RebuildView(forms.ModalFormView):
    form_class = project_forms.RebuildInstanceForm
    template_name = 'project/instances/rebuild.html'
    success_url = reverse_lazy('horizon:project:instances:index')
    page_title = _("Rebuild Instance")

    def get_context_data(self, **kwargs):
        context = super(RebuildView, self).get_context_data(**kwargs)
        context['instance_id'] = self.kwargs['instance_id']
        context['can_set_server_password'] = api.nova.can_set_server_password()
        return context

    def get_initial(self):
        return {'instance_id': self.kwargs['instance_id']}


class DecryptPasswordView(forms.ModalFormView):
    form_class = project_forms.DecryptPasswordInstanceForm
    template_name = 'project/instances/decryptpassword.html'
    success_url = reverse_lazy('horizon:project:instances:index')
    page_title = _("Retrieve Instance Password")

    def get_context_data(self, **kwargs):
        context = super(DecryptPasswordView, self).get_context_data(**kwargs)
        context['instance_id'] = self.kwargs['instance_id']
        context['keypair_name'] = self.kwargs['keypair_name']
        return context

    def get_initial(self):
        return {'instance_id': self.kwargs['instance_id'],
                'keypair_name': self.kwargs['keypair_name']}


class DetailView(tabs.TabView):
    tab_group_class = project_tabs.InstanceDetailTabs
    template_name = 'project/instances/detail.html'
    redirect_url = 'horizon:project:instances:index'
    page_title = _("Instance Details: {{ instance.name }}")
    image_url = 'horizon:project:images:images:detail'
    volume_url = 'horizon:project:volumes:volumes:detail'

    def get_context_data(self, **kwargs):
        context = super(DetailView, self).get_context_data(**kwargs)
        instance = self.get_data()
        if instance.image:
            instance.image_url = reverse(self.image_url,
                                         args=[instance.image['id']])
        instance.volume_url = self.volume_url
        context["instance"] = instance
        context["url"] = reverse(self.redirect_url)
        context["actions"] = self._get_actions(instance)
        return context

    def _get_actions(self, instance):
        table = project_tables.InstancesTable(self.request)
        return table.render_row_actions(instance)

    @memoized.memoized_method
    def get_data(self):
        instance_id = self.kwargs['instance_id']

        try:
            instance = api.nova.server_get(self.request, instance_id)
        except Exception:
            redirect = reverse(self.redirect_url)
            exceptions.handle(self.request,
                              _('Unable to retrieve details for '
                                'instance "%s".') % instance_id,
                              redirect=redirect)
            # Not all exception types handled above will result in a redirect.
            # Need to raise here just in case.
            raise exceptions.Http302(redirect)

        status_label = [label for (value, label) in
                        project_tables.STATUS_DISPLAY_CHOICES
                        if value.lower() == (instance.status or '').lower()]
        if status_label:
            instance.status_label = status_label[0]
        else:
            instance.status_label = instance.status

        try:
            instance.volumes = api.nova.instance_volumes_list(self.request,
                                                              instance_id)
            # Sort by device name
            instance.volumes.sort(key=lambda vol: vol.device)
        except Exception:
            msg = _('Unable to retrieve volume list for instance '
                    '"%(name)s" (%(id)s).') % {'name': instance.name,
                                               'id': instance_id}
            exceptions.handle(self.request, msg, ignore=True)

        try:
            instance.full_flavor = api.nova.flavor_get(
                self.request, instance.flavor["id"])
        except Exception:
            msg = _('Unable to retrieve flavor information for instance '
                    '"%(name)s" (%(id)s).') % {'name': instance.name,
                                               'id': instance_id}
            exceptions.handle(self.request, msg, ignore=True)

        try:
            instance.security_groups = api.network.server_security_groups(
                self.request, instance_id)
        except Exception:
            msg = _('Unable to retrieve security groups for instance '
                    '"%(name)s" (%(id)s).') % {'name': instance.name,
                                               'id': instance_id}
            exceptions.handle(self.request, msg, ignore=True)

        try:
            api.network.servers_update_addresses(self.request, [instance])
        except Exception:
            msg = _('Unable to retrieve IP addresses from Neutron for '
                    'instance "%(name)s" (%(id)s).') % {'name': instance.name,
                                                        'id': instance_id}
            exceptions.handle(self.request, msg, ignore=True)

        return instance

    def get_tabs(self, request, *args, **kwargs):
        instance = self.get_data()
        return self.tab_group_class(request, instance=instance, **kwargs)

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super(DetailView, self).dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        response = http.HttpResponseRedirect(reverse('horizon:project:instances:detail', kwargs={'instance_id': self.get_data().id}))
        response.set_cookie("time_limit", request.POST.get("time_limit"))
        return response


class ResizeView(workflows.WorkflowView):
    workflow_class = project_workflows.ResizeInstance
    success_url = reverse_lazy("horizon:project:instances:index")

    def get_context_data(self, **kwargs):
        context = super(ResizeView, self).get_context_data(**kwargs)
        context["instance_id"] = self.kwargs['instance_id']
        return context

    @memoized.memoized_method
    def get_object(self, *args, **kwargs):
        instance_id = self.kwargs['instance_id']
        try:
            instance = api.nova.server_get(self.request, instance_id)
        except Exception:
            redirect = reverse("horizon:project:instances:index")
            msg = _('Unable to retrieve instance details.')
            exceptions.handle(self.request, msg, redirect=redirect)
        flavor_id = instance.flavor['id']
        flavors = self.get_flavors()
        if flavor_id in flavors:
            instance.flavor_name = flavors[flavor_id].name
        else:
            try:
                flavor = api.nova.flavor_get(self.request, flavor_id)
                instance.flavor_name = flavor.name
            except Exception:
                msg = _('Unable to retrieve flavor information for instance '
                        '"%s".') % instance_id
                exceptions.handle(self.request, msg, ignore=True)
                instance.flavor_name = _("Not available")
        return instance

    @memoized.memoized_method
    def get_flavors(self, *args, **kwargs):
        try:
            flavors = api.nova.flavor_list(self.request)
            return OrderedDict((str(flavor.id), flavor) for flavor in flavors)
        except Exception:
            redirect = reverse("horizon:project:instances:index")
            exceptions.handle(self.request,
                              _('Unable to retrieve flavors.'),
                              redirect=redirect)

    def get_initial(self):
        initial = super(ResizeView, self).get_initial()
        _object = self.get_object()
        if _object:
            initial.update(
                {'instance_id': self.kwargs['instance_id'],
                 'name': getattr(_object, 'name', None),
                 'old_flavor_id': _object.flavor['id'],
                 'old_flavor_name': getattr(_object, 'flavor_name', ''),
                 'flavors': self.get_flavors()})
        return initial


class AttachInterfaceView(forms.ModalFormView):
    form_class = project_forms.AttachInterface
    template_name = 'project/instances/attach_interface.html'
    modal_header = _("Attach Interface")
    form_id = "attach_interface_form"
    submit_label = _("Attach Interface")
    submit_url = "horizon:project:instances:attach_interface"
    success_url = reverse_lazy('horizon:project:instances:index')

    def get_context_data(self, **kwargs):
        context = super(AttachInterfaceView, self).get_context_data(**kwargs)
        context['instance_id'] = self.kwargs['instance_id']
        args = (self.kwargs['instance_id'],)
        context['submit_url'] = reverse(self.submit_url, args=args)
        return context

    def get_initial(self):
        return {'instance_id': self.kwargs['instance_id']}


class DetachInterfaceView(forms.ModalFormView):
    form_class = project_forms.DetachInterface
    template_name = 'project/instances/detach_interface.html'
    modal_header = _("Detach Interface")
    form_id = "detach_interface_form"
    submit_label = _("Detach Interface")
    submit_url = "horizon:project:instances:detach_interface"
    success_url = reverse_lazy('horizon:project:instances:index')

    def get_context_data(self, **kwargs):
        context = super(DetachInterfaceView, self).get_context_data(**kwargs)
        context['instance_id'] = self.kwargs['instance_id']
        args = (self.kwargs['instance_id'],)
        context['submit_url'] = reverse(self.submit_url, args=args)
        return context

    def get_initial(self):
        return {'instance_id': self.kwargs['instance_id']}


