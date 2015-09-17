from django.conf import settings
if getattr(settings, 'NEUTRON_DISABLED', False):
    PANEL = 'networks'
    PANEL_DASHBOARD = 'project'
    PANEL_GROUP = 'project'
    REMOVE_PANEL = True
