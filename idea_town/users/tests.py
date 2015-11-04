from django.conf import settings
from django.core.urlresolvers import reverse
from django.test import TestCase, Client
from django.test.utils import override_settings
from django.contrib.auth.models import User

from rest_framework import fields

from allauth.account.signals import user_signed_up
from allauth.socialaccount.signals import pre_social_login
from allauth.socialaccount.models import SocialLogin

from .models import UserProfile
from ..experiments.models import (Experiment, UserInstallation)

import json

import logging
logger = logging.getLogger(__name__)


class UserProfileTests(TestCase):

    maxDiff = None

    def setUp(self):
        self.username = 'johndoe2'
        self.password = 'trustno1'
        self.email = '%s@example.com' % self.username

        self.user = User.objects.create_user(
            username=self.username,
            email=self.email,
            password=self.password)

        UserProfile.objects.filter(user=self.user).delete()

    def test_get_profile_nonexistent(self):
        """Profile should be created on first attempt to get"""

        profiles_count = UserProfile.objects.filter(user=self.user).count()
        self.assertEqual(0, profiles_count)

        profile = UserProfile.objects.get_profile(self.user)
        self.assertIsNotNone(profile)
        self.assertEqual(self.user, profile.user)

        profiles_count = UserProfile.objects.filter(user=self.user).count()
        self.assertEqual(1, profiles_count)

    def test_get_profile_exists(self):
        """Existing profile should be returned on get"""
        expected_title = 'chief cat wrangler'

        expected_profile = UserProfile(user=self.user, title=expected_title)
        expected_profile.save()

        result_profile = UserProfile.objects.get_profile(user=self.user)
        self.assertIsNotNone(result_profile)
        self.assertEqual(expected_title, result_profile.title)


class MeViewSetTests(TestCase):

    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        cls.username = 'johndoe'
        cls.password = 'top_secret'
        cls.email = '%s@example.com' % cls.username
        cls.user = User.objects.create_user(
            username=cls.username,
            email=cls.email,
            password=cls.password)

        cls.experiments = dict((obj.slug, obj) for (obj, created) in (
            Experiment.objects.get_or_create(
                slug="test-%s" % idx, defaults=dict(
                    title="Test %s" % idx,
                    description="This is a test"
                )) for idx in range(1, 4)))

        cls.addonData = {
            'name': 'Idea Town',
            'url': settings.ADDON_URL
        }

        cls.url = reverse('me-list')

    def setUp(self):
        self.client = Client()

    def test_get_anonymous(self):
        """/api/me resource should contain no data for unauth'd user"""
        resp = self.client.get(self.url)
        data = json.loads(str(resp.content, encoding='utf8'))

        self.assertEqual(len(data.keys()), 0)

    def test_get_logged_in(self):
        """/api/me resource should contain data for auth'd user"""
        self.client.login(username=self.username,
                          password=self.password)

        resp = self.client.get(self.url)
        self.assertJSONEqual(
            str(resp.content, encoding='utf8'),
            {
                'id': self.email,
                'addon': self.addonData,
                'installed': []
            }
        )

        experiment = self.experiments['test-1']

        UserInstallation.objects.create(
            experiment=experiment,
            user=self.user
        )

        resp = self.client.get(self.url)
        # HACK: Use a rest framework field to format dates as expected
        date_field = fields.DateTimeField()
        self.assertJSONEqual(
            str(resp.content, encoding='utf8'),
            {
                'id': self.email,
                'addon': self.addonData,
                'installed': [
                    {
                        'id': experiment.pk,
                        'url': 'http://testserver/api/experiments/%s' %
                               experiment.pk,
                        'slug': experiment.slug,
                        'title': experiment.title,
                        'description': experiment.description,
                        'measurements': experiment.measurements.rendered,
                        'version': experiment.version,
                        'changelog_url': experiment.changelog_url,
                        'contribute_url': experiment.contribute_url,
                        'thumbnail': None,
                        'xpi_url': experiment.xpi_url,
                        'addon_id': experiment.addon_id,
                        'details': [],
                        'contributors': [],
                        'created': date_field.to_representation(
                            experiment.created),
                        'modified': date_field.to_representation(
                            experiment.modified),
                    }
                ]
            }
        )


class InviteOnlyModeTests(TestCase):

    def setUp(self):
        self.username = 'newuserdoe2'
        self.password = 'trustno1'
        self.email = '%s@example.com' % self.username

        self.user = User.objects.create_user(
            username=self.username,
            email=self.email,
            password=self.password)

        UserProfile.objects.filter(user=self.user).delete()

    @override_settings(ACCOUNT_INVITE_ONLY_MODE=True)
    def test_invite_only_signup(self):
        """User.is_active should be False on signup with invite mode"""
        self.user.is_active = True
        user_signed_up.send(sender=self.user.__class__,
                            request=None,
                            user=self.user)

        self.assertEqual(False, self.user.is_active)

        profile = UserProfile.objects.get_profile(self.user)
        self.assertEqual(True, profile.invite_pending)

    @override_settings(ACCOUNT_INVITE_ONLY_MODE=True)
    def test_invite_only_mozillacom_autoactivation(self):
        """Users with @mozilla.com email addresses should be auto-activated"""
        self.user.is_active = True
        self.user.email = 'someone@mozilla.com'

        user_signed_up.send(sender=self.user.__class__,
                            request=None,
                            user=self.user)

        self.assertEqual(True, self.user.is_active)

        profile = UserProfile.objects.get_profile(self.user)
        self.assertEqual(False, profile.invite_pending)

    @override_settings(ACCOUNT_INVITE_ONLY_MODE=False)
    def test_open_signup(self):
        """User.is_active should be True on signup without invite mode"""
        self.user.is_active = True
        user_signed_up.send(sender=self.user.__class__,
                            request=None,
                            user=self.user)
        self.assertEqual(True, self.user.is_active)

        profile = UserProfile.objects.get_profile(self.user)
        self.assertEqual(False, profile.invite_pending)


    def test_auto_activate_after_settings_change(self):
        """Pending invitations should be auto-activated on sign-in after invite mode turned off"""
        sociallogin = SocialLogin(user=self.user)

        with self.settings(ACCOUNT_INVITE_ONLY_MODE=True):

            self.user.is_active = True
            user_signed_up.send(sender=self.user.__class__,
                                request=None,
                                user=self.user)

            self.assertEqual(False, self.user.is_active)

            profile = UserProfile.objects.get_profile(self.user)
            self.assertEqual(True, profile.invite_pending)

            pre_social_login.send(sender=SocialLogin,
                                  request=None,
                                  sociallogin=sociallogin)

            self.assertEqual(False, self.user.is_active)

            profile = UserProfile.objects.get_profile(self.user)
            self.assertEqual(True, profile.invite_pending)

        with self.settings(ACCOUNT_INVITE_ONLY_MODE=False):

            pre_social_login.send(sender=SocialLogin,
                                  request=None,
                                  sociallogin=sociallogin)

            self.assertEqual(True, self.user.is_active)

            profile = UserProfile.objects.get_profile(self.user)
            self.assertEqual(False, profile.invite_pending)
