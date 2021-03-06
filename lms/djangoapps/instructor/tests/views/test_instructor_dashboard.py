"""
Unit tests for instructor_dashboard.py.
"""
import ddt
from mock import patch

from django.conf import settings
from django.core.urlresolvers import reverse
from django.test.client import RequestFactory
from django.test.utils import override_settings

from courseware.tabs import get_course_tab_list
from courseware.tests.factories import UserFactory
from courseware.tests.helpers import LoginEnrollmentTestCase

from student.tests.factories import AdminFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.utils import XssTestMixin
from xmodule.modulestore.tests.factories import CourseFactory
from shoppingcart.models import PaidCourseRegistration, Order, CourseRegCodeItem
from course_modes.models import CourseMode
from student.roles import CourseFinanceAdminRole
from student.models import CourseEnrollment


@ddt.ddt
class TestInstructorDashboard(ModuleStoreTestCase, LoginEnrollmentTestCase, XssTestMixin):
    """
    Tests for the instructor dashboard (not legacy).
    """

    def setUp(self):
        """
        Set up tests
        """
        super(TestInstructorDashboard, self).setUp()
        self.course = CourseFactory.create(
            grading_policy={"GRADE_CUTOFFS": {"A": 0.75, "B": 0.63, "C": 0.57, "D": 0.5}},
            display_name='<script>alert("XSS")</script>'
        )

        self.course_mode = CourseMode(course_id=self.course.id,
                                      mode_slug="honor",
                                      mode_display_name="honor cert",
                                      min_price=40)
        self.course_mode.save()
        # Create instructor account
        self.instructor = AdminFactory.create()
        self.client.login(username=self.instructor.username, password="test")

        # URL for instructor dash
        self.url = reverse('instructor_dashboard', kwargs={'course_id': self.course.id.to_deprecated_string()})

    def get_dashboard_enrollment_message(self):
        """
        Returns expected dashboard enrollment message with link to Insights.
        """
        return 'Enrollment data is now available in <a href="http://example.com/courses/{}" ' \
               'target="_blank">Example</a>.'.format(unicode(self.course.id))

    def get_dashboard_analytics_message(self):
        """
        Returns expected dashboard demographic message with link to Insights.
        """
        return 'For analytics about your course, go to <a href="http://example.com/courses/{}" ' \
               'target="_blank">Example</a>.'.format(unicode(self.course.id))

    def test_instructor_tab(self):
        """
        Verify that the instructor tab appears for staff only.
        """
        def has_instructor_tab(user, course):
            """Returns true if the "Instructor" tab is shown."""
            request = RequestFactory().request()
            request.user = user
            tabs = get_course_tab_list(request, course)
            return len([tab for tab in tabs if tab.name == 'Instructor']) == 1

        self.assertTrue(has_instructor_tab(self.instructor, self.course))
        student = UserFactory.create()
        self.assertFalse(has_instructor_tab(student, self.course))

    def test_default_currency_in_the_html_response(self):
        """
        Test that checks the default currency_symbol ($) in the response
        """
        CourseFinanceAdminRole(self.course.id).add_users(self.instructor)
        total_amount = PaidCourseRegistration.get_total_amount_of_purchased_item(self.course.id)
        response = self.client.get(self.url)
        self.assertTrue('${amount}'.format(amount=total_amount) in response.content)

    def test_course_name_xss(self):
        """Test that the instructor dashboard correctly escapes course names
        with script tags.
        """
        response = self.client.get(self.url)
        self.assert_xss(response, '<script>alert("XSS")</script>')

    @override_settings(PAID_COURSE_REGISTRATION_CURRENCY=['PKR', 'Rs'])
    def test_override_currency_settings_in_the_html_response(self):
        """
        Test that checks the default currency_symbol ($) in the response
        """
        CourseFinanceAdminRole(self.course.id).add_users(self.instructor)
        total_amount = PaidCourseRegistration.get_total_amount_of_purchased_item(self.course.id)
        response = self.client.get(self.url)
        self.assertIn('{currency}{amount}'.format(currency='Rs', amount=total_amount), response.content)

    @patch.dict(settings.FEATURES, {'DISPLAY_ANALYTICS_ENROLLMENTS': False})
    @override_settings(ANALYTICS_DASHBOARD_URL='')
    def test_no_enrollments(self):
        """
        Test enrollment section is hidden.
        """
        response = self.client.get(self.url)
        # no enrollment information should be visible
        self.assertFalse('<h2>Enrollment Information</h2>' in response.content)

    @patch.dict(settings.FEATURES, {'DISPLAY_ANALYTICS_ENROLLMENTS': True})
    @override_settings(ANALYTICS_DASHBOARD_URL='')
    def test_show_enrollments_data(self):
        """
        Test enrollment data is shown.
        """
        response = self.client.get(self.url)

        # enrollment information visible
        self.assertTrue('<h2>Enrollment Information</h2>' in response.content)
        self.assertTrue('<td>Verified</td>' in response.content)
        self.assertTrue('<td>Audit</td>' in response.content)
        self.assertTrue('<td>Honor</td>' in response.content)
        self.assertTrue('<td>Professional</td>' in response.content)

        # dashboard link hidden
        self.assertFalse(self.get_dashboard_enrollment_message() in response.content)

    @patch.dict(settings.FEATURES, {'DISPLAY_ANALYTICS_ENROLLMENTS': True})
    @override_settings(ANALYTICS_DASHBOARD_URL='')
    def test_show_enrollment_data_for_prof_ed(self):
        # Create both "professional" (meaning professional + verification)
        # and "no-id-professional" (meaning professional without verification)
        # These should be aggregated for display purposes.
        users = [UserFactory() for _ in range(2)]
        CourseEnrollment.enroll(users[0], self.course.id, mode="professional")
        CourseEnrollment.enroll(users[1], self.course.id, mode="no-id-professional")

        response = self.client.get(self.url)

        # Check that the number of professional enrollments is two
        self.assertContains(response, "<td>Professional</td><td>2</td>")

    @patch.dict(settings.FEATURES, {'DISPLAY_ANALYTICS_ENROLLMENTS': False})
    @override_settings(ANALYTICS_DASHBOARD_URL='http://example.com')
    @override_settings(ANALYTICS_DASHBOARD_NAME='Example')
    def test_show_dashboard_enrollment_message(self):
        """
        Test enrollment dashboard message is shown and data is hidden.
        """
        response = self.client.get(self.url)

        # enrollment information hidden
        self.assertFalse('<td>Verified</td>' in response.content)
        self.assertFalse('<td>Audit</td>' in response.content)
        self.assertFalse('<td>Honor</td>' in response.content)
        self.assertFalse('<td>Professional</td>' in response.content)

        # link to dashboard shown
        expected_message = self.get_dashboard_enrollment_message()
        self.assertTrue(expected_message in response.content)

    @override_settings(ANALYTICS_DASHBOARD_URL='')
    @override_settings(ANALYTICS_DASHBOARD_NAME='')
    def test_dashboard_analytics_tab_not_shown(self):
        """
        Test dashboard analytics tab isn't shown if insights isn't configured.
        """
        response = self.client.get(self.url)
        analytics_section = '<li class="nav-item"><a href="" data-section="instructor_analytics">Analytics</a></li>'
        self.assertFalse(analytics_section in response.content)

    @override_settings(ANALYTICS_DASHBOARD_URL='http://example.com')
    @override_settings(ANALYTICS_DASHBOARD_NAME='Example')
    def test_dashboard_analytics_points_at_insights(self):
        """
        Test analytics dashboard message is shown
        """
        response = self.client.get(self.url)
        analytics_section = '<li class="nav-item"><a href="" data-section="instructor_analytics">Analytics</a></li>'
        self.assertTrue(analytics_section in response.content)

        # link to dashboard shown
        expected_message = self.get_dashboard_analytics_message()
        self.assertTrue(expected_message in response.content)

    def add_course_to_user_cart(self, cart, course_key):
        """
        adding course to user cart
        """
        reg_item = PaidCourseRegistration.add_to_order(cart, course_key)
        return reg_item

    @patch.dict('django.conf.settings.FEATURES', {'ENABLE_PAID_COURSE_REGISTRATION': True})
    def test_total_credit_cart_sales_amount(self):
        """
        Test to check the total amount for all the credit card purchases.
        """
        student = UserFactory.create()
        self.client.login(username=student.username, password="test")
        student_cart = Order.get_cart_for_user(student)
        item = self.add_course_to_user_cart(student_cart, self.course.id)
        resp = self.client.post(reverse('shoppingcart.views.update_user_cart'), {'ItemId': item.id, 'qty': 4})
        self.assertEqual(resp.status_code, 200)
        student_cart.purchase()

        self.client.login(username=self.instructor.username, password="test")
        CourseFinanceAdminRole(self.course.id).add_users(self.instructor)
        single_purchase_total = PaidCourseRegistration.get_total_amount_of_purchased_item(self.course.id)
        bulk_purchase_total = CourseRegCodeItem.get_total_amount_of_purchased_item(self.course.id)
        total_amount = single_purchase_total + bulk_purchase_total
        response = self.client.get(self.url)
        self.assertIn('{currency}{amount}'.format(currency='$', amount=total_amount), response.content)

    @ddt.data(
        (True, True, True),
        (True, False, False),
        (True, None, False),
        (False, True, False),
        (False, False, False),
        (False, None, False),
    )
    @ddt.unpack
    def test_ccx_coaches_option_on_admin_list_management_instructor(
            self, ccx_feature_flag, enable_ccx, expected_result
    ):
        """
        Test whether the "CCX Coaches" option is visible or hidden depending on the value of course.enable_ccx.
        """
        with patch.dict(settings.FEATURES, {'CUSTOM_COURSES_EDX': ccx_feature_flag}):
            self.course.enable_ccx = enable_ccx
            self.store.update_item(self.course, self.instructor.id)

            response = self.client.get(self.url)

            self.assertEquals(
                expected_result,
                'CCX Coaches are able to create their own Custom Courses based on this course' in response.content
            )

    def test_grade_cutoffs(self):
        """
        Verify that grade cutoffs are displayed in the correct order.
        """
        response = self.client.get(self.url)
        self.assertIn('D: 0.5, C: 0.57, B: 0.63, A: 0.75', response.content)
