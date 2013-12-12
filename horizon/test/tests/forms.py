# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from django import shortcuts

from horizon import forms
from horizon.test import helpers as test


class TestForm(forms.SelfHandlingForm):

    name = forms.CharField(max_length="255")

    def handle(self, request, data):
        return True


class FormErrorTests(test.TestCase):

    template = 'horizon/common/_form_fields.html'

    def setUp(self):
        super(FormErrorTests, self).setUp()
        self.form = TestForm(self.request)

    def _render_form(self):
        return shortcuts.render(self.request, self.template,
                                {'form': self.form})

    def test_set_warning(self):
        warning_text = 'WARNING 29380'
        self.form.set_warning(warning_text)
        self.assertEqual([warning_text], self.form.warnings)
        resp = self._render_form()
        self.assertIn(warning_text, resp.content)

    def test_api_error(self):
        error_text = 'ERROR 12938'
        self.form.full_clean()
        self.form.api_error(error_text)
        self.assertEqual([error_text], self.form.non_field_errors())
        resp = self._render_form()
        self.assertIn(error_text, resp.content)
