"""
Tests for experimentation views
"""


from datetime import timedelta
from uuid import uuid4

import six
from django.urls import reverse
from django.utils.timezone import now
from rest_framework.test import APITestCase

from common.djangoapps.course_modes.models import CourseMode
from common.djangoapps.course_modes.tests.factories import CourseModeFactory
from edx_toggles.toggles.testutils import override_waffle_flag
from lms.djangoapps.course_blocks.transformers.tests.helpers import ModuleStoreTestCase
from lms.djangoapps.experiments.views_custom import MOBILE_UPSELL_FLAG
from common.djangoapps.student.tests.factories import CourseEnrollmentFactory, UserFactory
from xmodule.modulestore.tests.factories import CourseFactory

CROSS_DOMAIN_REFERER = 'https://ecommerce.edx.org'


class Rev934LoggedOutTests(APITestCase):
    def test_not_logged_in(self):
        """Test mobile app upsell API is not available if not logged in"""
        url = reverse('api_experiments:rev_934')

        # Not-logged-in returns 401
        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)


class Rev934Tests(APITestCase, ModuleStoreTestCase):
    """Test mobile app upsell API"""
    @classmethod
    def setUpClass(cls):
        super(Rev934Tests, cls).setUpClass()
        cls.url = reverse('api_experiments:rev_934')

    def setUp(self):
        super(Rev934Tests, self).setUp()
        self.user = UserFactory(username='robot-mue-1-6pnjv')  # Username that hashes to bucket 1
        self.client.login(
            username=self.user.username,
            password=UserFactory._DEFAULT_PASSWORD,  # pylint: disable=protected-access
        )

    @override_waffle_flag(MOBILE_UPSELL_FLAG, active=False)
    def test_flag_off(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        expected = {
            'show_upsell': False,
            'upsell_flag': False,
        }
        self.assertEqual(response.data, expected)

    @override_waffle_flag(MOBILE_UPSELL_FLAG, active=True)
    def test_no_course_id(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    @override_waffle_flag(MOBILE_UPSELL_FLAG, active=True)
    def test_bad_course_id(self):
        response = self.client.get(self.url, {'course_id': 'junk'})
        self.assertEqual(response.status_code, 400)

    @override_waffle_flag(MOBILE_UPSELL_FLAG, active=True)
    def test_simple_course(self):
        course = CourseFactory.create(start=now() - timedelta(days=30))
        response = self.client.get(self.url, {'course_id': str(course.id)})
        self.assertEqual(response.status_code, 200)
        expected = {
            'show_upsell': False,
            'upsell_flag': True,
            'experiment_bucket': 1,
            'user_upsell': True,
            'basket_url': None,  # No verified mode means no basket link
        }
        self.assertEqual(response.data, expected)

    @override_waffle_flag(MOBILE_UPSELL_FLAG, active=True)
    def test_verified_course(self):
        course = CourseFactory.create(
            start=now() - timedelta(days=30),
            run='test',
            display_name='test',
        )
        CourseModeFactory.create(
            mode_slug=CourseMode.VERIFIED,
            course_id=course.id,
            min_price=10.00,
            sku=six.text_type(uuid4().hex)
        )

        response = self.client.get(self.url, {'course_id': str(course.id)})
        self.assertEqual(response.status_code, 200)
        result = response.data
        self.assertIn('basket_url', result)
        self.assertTrue(bool(result['basket_url']))
        expected = {
            'show_upsell': True,
            'price': u'$10.00',
            'basket_url': result['basket_url'],
            # Example basket_url: u'/verify_student/upgrade/org.0/course_0/test/'
        }
        self.assertEqual(result, expected)

    @override_waffle_flag(MOBILE_UPSELL_FLAG, active=True)
    def test_expired_verified_mode(self):
        course = CourseFactory.create(
            start=now() - timedelta(days=30),
            run='test',
            display_name='test',
        )
        CourseModeFactory.create(
            mode_slug=CourseMode.VERIFIED,
            course_id=course.id,
            min_price=10,
            sku=six.text_type(uuid4().hex),
            expiration_datetime=now() - timedelta(days=30),
        )

        response = self.client.get(self.url, {'course_id': str(course.id)})
        self.assertEqual(response.status_code, 200)
        expected = {
            'show_upsell': False,
            'upsell_flag': True,
            'experiment_bucket': 1,
            'user_upsell': True,
            'basket_url': None,  # Expired verified mode means no basket link
        }
        self.assertEqual(response.data, expected)

    @override_waffle_flag(MOBILE_UPSELL_FLAG, active=True)
    def test_not_started_course(self):
        course = CourseFactory.create(
            start=now() + timedelta(days=30),
            end=now() + timedelta(days=60),
            run='test',
            display_name='test',
        )
        CourseModeFactory.create(
            mode_slug=CourseMode.VERIFIED,
            course_id=course.id,
            min_price=10,
            sku=six.text_type(uuid4().hex)
        )

        response = self.client.get(self.url, {'course_id': str(course.id)})
        self.assertEqual(response.status_code, 200)
        expected = {
            'show_upsell': False,
            'upsell_flag': True,
            'course_running': False,
        }
        self.assertEqual(response.data, expected)

    @override_waffle_flag(MOBILE_UPSELL_FLAG, active=True)
    def test_ended_course(self):
        course = CourseFactory.create(
            start=now() - timedelta(days=60),
            end=now() - timedelta(days=30),
            run='test',
            display_name='test',
        )
        CourseModeFactory.create(
            mode_slug=CourseMode.VERIFIED,
            course_id=course.id,
            min_price=10,
            sku=six.text_type(uuid4().hex)
        )

        response = self.client.get(self.url, {'course_id': str(course.id)})
        self.assertEqual(response.status_code, 200)
        expected = {
            'show_upsell': False,
            'upsell_flag': True,
            'course_running': False,
        }
        self.assertEqual(response.data, expected)

    @override_waffle_flag(MOBILE_UPSELL_FLAG, active=True)
    def test_already_upgraded(self):
        course = CourseFactory.create(
            start=now() - timedelta(days=30),
            run='test',
            display_name='test',
        )
        course_mode = CourseModeFactory.create(
            mode_slug=CourseMode.VERIFIED,
            course_id=course.id,
            min_price=10,
            sku=six.text_type(uuid4().hex)
        )
        CourseEnrollmentFactory.create(
            is_active=True,
            mode=course_mode,
            course_id=course.id,
            user=self.user
        )

        response = self.client.get(self.url, {'course_id': str(course.id)})
        self.assertEqual(response.status_code, 200)
        result = response.data
        self.assertIn('basket_url', result)
        self.assertTrue(bool(result['basket_url']))
        expected = {
            'show_upsell': False,
            'upsell_flag': True,
            'experiment_bucket': 1,
            'user_upsell': False,
            'basket_url': result['basket_url'],
            # Example basket_url: u'/verify_student/upgrade/org.0/course_0/test/'
        }
        self.assertEqual(result, expected)
