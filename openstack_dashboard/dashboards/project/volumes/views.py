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

from django.utils.translation import ugettext_lazy as _

from horizon import exceptions
from horizon import tabs

from openstack_dashboard import api
from openstack_dashboard.dashboards.project.volumes \
    import tabs as project_tabs


class IndexView(tabs.TabbedTableView):
    tab_group_class = project_tabs.VolumeAndSnapshotTabs
    template_name = 'project/volumes/index.html'

    def get_context_data(self, **kwargs):
        context = super(IndexView, self).get_context_data(**kwargs)
        quotas = self.get_quotas()
        if quotas:
            context['quotas_per_type'] = [
                (name, quota) for name, quota in sorted(quotas.items())
                if quota['gigabytes']['limit'] > 0
                or quota['gigabytes']['in_use'] > 0]
        return context

    def get_quotas(self):
        if not api.base.is_service_enabled(self.request, 'volume'):
            return
        try:
            quotas = api.cinder.tenant_volume_type_quota_get(
                self.request,
                self.request.user.tenant_id)
            return quotas
        except Exception:
            msg = _("Unable to retrieve volume storage usage information.")
            exceptions.handle(self.request, msg)
