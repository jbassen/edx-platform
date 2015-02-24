# -*- coding: utf-8 -*-

"""
Unit tests for LMS instructor-initiated background tasks helper functions.

Tests that CSV grade report generation works with unicode emails.

"""
import ddt
from mock import Mock, patch
import tempfile
import unicodecsv

from xmodule.modulestore.tests.factories import CourseFactory
from student.tests.factories import UserFactory
from student.models import CourseEnrollment
from xmodule.partitions.partitions import Group, UserPartition

from openedx.core.djangoapps.course_groups.tests.helpers import CohortFactory
from instructor_task.models import ReportStore
from instructor_task.tasks_helper import cohort_students_and_upload, upload_grades_csv, upload_students_csv
from instructor_task.tests.test_base import InstructorTaskCourseTestCase, TestReportMixin

# Stanford-specific
import os
import shutil
from datetime import datetime
import urllib
from pytz import UTC
from courseware.courses import get_course
from courseware.tests.factories import StudentModuleFactory
from courseware.tests.modulestore_config import TEST_DATA_MOCK_MODULESTORE
from opaque_keys.edx.keys import CourseKey
from opaque_keys.edx.locations import Location
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from instructor_task.tasks_helper import (
    push_student_responses_to_s3,
    push_ora2_responses_to_s3,
    UPDATE_STATUS_FAILED,
    UPDATE_STATUS_SUCCEEDED,
)
from django.conf import settings
from django.test.utils import override_settings
from student.tests.factories import CourseEnrollmentFactory
# Stanford-specific

TEST_COURSE_ORG = 'edx'
TEST_COURSE_NAME = 'test_course'
TEST_COURSE_NUMBER = '1.23x'


@ddt.ddt
class TestInstructorGradeReport(TestReportMixin, InstructorTaskCourseTestCase):
    """
    Tests that CSV grade report generation works.
    """
    def setUp(self):
        self.course = CourseFactory.create()

    @ddt.data([u'student@example.com', u'ni\xf1o@example.com'])
    def test_unicode_emails(self, emails):
        """
        Test that students with unicode characters in emails is handled.
        """
        for i, email in enumerate(emails):
            self.create_student('student{0}'.format(i), email)

        self.current_task = Mock()
        self.current_task.update_state = Mock()
        with patch('instructor_task.tasks_helper._get_current_task') as mock_current_task:
            mock_current_task.return_value = self.current_task
            result = upload_grades_csv(None, None, self.course.id, None, 'graded')
        num_students = len(emails)
        self.assertDictContainsSubset({'attempted': num_students, 'succeeded': num_students, 'failed': 0}, result)

    @patch('instructor_task.tasks_helper._get_current_task')
    @patch('instructor_task.tasks_helper.iterate_grades_for')
    def test_grading_failure(self, mock_iterate_grades_for, _mock_current_task):
        """
        Test that any grading errors are properly reported in the
        progress dict and uploaded to the report store.
        """
        # mock an error response from `iterate_grades_for`
        mock_iterate_grades_for.return_value = [
            (self.create_student('username', 'student@example.com'), {}, 'Cannot grade student')
        ]
        result = upload_grades_csv(None, None, self.course.id, None, 'graded')
        self.assertDictContainsSubset({'attempted': 1, 'succeeded': 0, 'failed': 1}, result)

        report_store = ReportStore.from_config()
        self.assertTrue(any('grade_report_err' in item[0] for item in report_store.links_for(self.course.id)))

    def _verify_cohort_data(self, course_id, expected_cohort_groups):
        """
        Verify cohort data.
        """
        cohort_groups_in_csv = []
        with patch('instructor_task.tasks_helper._get_current_task'):
            result = upload_grades_csv(None, None, course_id, None, 'graded')
            self.assertDictContainsSubset({'attempted': 2, 'succeeded': 2, 'failed': 0}, result)
            report_store = ReportStore.from_config()
            report_csv_filename = report_store.links_for(course_id)[0][0]
            with open(report_store.path_to(course_id, report_csv_filename)) as csv_file:
                for row in unicodecsv.DictReader(csv_file):
                    cohort_groups_in_csv.append(row['Cohort Name'])

        self.assertEqual(cohort_groups_in_csv, expected_cohort_groups)

    def test_cohort_data_in_grading(self):
        """
        Test that cohort data is included in grades csv if cohort configuration is enabled for course.
        """
        cohort_groups = ['cohort 1', 'cohort 2']
        course = CourseFactory.create(cohort_config={'cohorted': True, 'auto_cohort': True,
                                                     'auto_cohort_groups': cohort_groups})
        for _ in range(2):
            CourseEnrollment.enroll(UserFactory.create(), course.id)

        # In auto cohorting a group will be assigned to a user only when user visits a problem
        # In grading calculation we only add a group in csv if group is already assigned to
        # user rather than creating a group automatically at runtime
        expected_groups = ['', '']
        self._verify_cohort_data(course.id, expected_groups)

    def test_unicode_cohort_data_in_grading(self):
        """
        Test that cohorts can contain unicode characters.
        """
        cohort_groups = [u'ÞrÖfessÖr X', u'MàgnëtÖ']
        course = CourseFactory.create(cohort_config={'cohorted': True})

        # Create users and manually assign cohorts
        user1 = UserFactory.create(username='user1')
        user2 = UserFactory.create(username='user2')
        CourseEnrollment.enroll(user1, course.id)
        CourseEnrollment.enroll(user2, course.id)
        cohort1 = CohortFactory(course_id=course.id, name=u'ÞrÖfessÖr X')
        cohort2 = CohortFactory(course_id=course.id, name=u'MàgnëtÖ')
        cohort1.users.add(user1)
        cohort2.users.add(user2)

        self._verify_cohort_data(course.id, cohort_groups)

    def test_unicode_user_partitions(self):
        """
        Test that user partition groups can contain unicode characters.
        """
        user_groups = [u'ÞrÖfessÖr X', u'MàgnëtÖ']
        user_partition = UserPartition(
            0,
            'x_man',
            'X Man',
            [
                Group(0, user_groups[0]),
                Group(1, user_groups[1])
            ]
        )

        # Create course with group configurations
        self.initialize_course(
            course_factory_kwargs={
                'user_partitions': [user_partition]
            }
        )

        _groups = [group.name for group in self.course.user_partitions[0].groups]
        self.assertEqual(_groups, user_groups)

    @patch('instructor_task.tasks_helper._get_current_task')
    @patch('instructor_task.tasks_helper.iterate_grades_for')
    def test_unicode_in_csv_header(self, mock_iterate_grades_for, _mock_current_task):
        """
        Tests that CSV grade report works if unicode in headers.
        """
        # mock a response from `iterate_grades_for`
        mock_iterate_grades_for.return_value = [
            (
                self.create_student('username', 'student@example.com'),
                {'section_breakdown': [{'label': u'\u8282\u540e\u9898 01'}], 'percent': 0},
                'Cannot grade student'
            )
        ]
        result = upload_grades_csv(None, None, self.course.id, None, 'graded')
        self.assertDictContainsSubset({'attempted': 1, 'succeeded': 1, 'failed': 0}, result)


@ddt.ddt
class TestStudentReport(TestReportMixin, InstructorTaskCourseTestCase):
    """
    Tests that CSV student profile report generation works.
    """
    def setUp(self):
        self.course = CourseFactory.create()

    def test_success(self):
        self.create_student('student', 'student@example.com')
        task_input = {'features': []}
        with patch('instructor_task.tasks_helper._get_current_task'):
            result = upload_students_csv(None, None, self.course.id, task_input, 'calculated')
        report_store = ReportStore.from_config()
        links = report_store.links_for(self.course.id)

        self.assertEquals(len(links), 1)
        self.assertDictContainsSubset({'attempted': 1, 'succeeded': 1, 'failed': 0}, result)

    @ddt.data([u'student', u'student\xec'])
    def test_unicode_usernames(self, students):
        """
        Test that students with unicode characters in their usernames
        are handled.
        """
        for i, student in enumerate(students):
            self.create_student(username=student, email='student{0}@example.com'.format(i))

        self.current_task = Mock()
        self.current_task.update_state = Mock()
        task_input = {
            'features': [
                'id', 'username', 'name', 'email', 'language', 'location',
                'year_of_birth', 'gender', 'level_of_education', 'mailing_address',
                'goals'
            ]
        }
        with patch('instructor_task.tasks_helper._get_current_task') as mock_current_task:
            mock_current_task.return_value = self.current_task
            result = upload_students_csv(None, None, self.course.id, task_input, 'calculated')
        #This assertion simply confirms that the generation completed with no errors
        num_students = len(students)
        self.assertDictContainsSubset({'attempted': num_students, 'succeeded': num_students, 'failed': 0}, result)


@override_settings(MODULESTORE=TEST_DATA_MOCK_MODULESTORE)
class TestReponsesReport(TestReportMixin, ModuleStoreTestCase):
    """
    Tests that CSV student responses report generation works.
    """
    def test_unicode(self):
        course_key = CourseKey.from_string('edX/unicode_graded/2012_Fall')
        self.course = get_course(course_key)
        self.problem_location = Location("edX", "unicode_graded", "2012_Fall", "problem", "H1P1")

        self.student = UserFactory(username=u'student\xec')
        CourseEnrollmentFactory.create(user=self.student, course_id=self.course.id)

        StudentModuleFactory.create(
            course_id=self.course.id,
            module_state_key=self.problem_location,
            student=self.student,
            grade=0,
            state=u'{"student_answers":{"fake-problem":"caf\xe9"}}',
        )

        result = push_student_responses_to_s3(None, None, self.course.id, None, 'generated')
        self.assertEqual(result, "succeeded")


class TestInstructorOra2Report(TestReportMixin, InstructorTaskCourseTestCase):
    """
    Tests that ORA2 response report generation works.
    """
    def setUp(self):
        self.course = CourseFactory.create(org=TEST_COURSE_ORG,
                                           number=TEST_COURSE_NUMBER,
                                           display_name=TEST_COURSE_NAME)

        self.current_task = Mock()
        self.current_task.update_state = Mock()

    def tearDown(self):
        if os.path.exists(settings.ORA2_RESPONSES_DOWNLOAD['ROOT_PATH']):
            shutil.rmtree(settings.ORA2_RESPONSES_DOWNLOAD['ROOT_PATH'])

    def test_report_fails_if_error(self):
        with patch('instructor_task.tasks_helper.collect_ora2_data') as mock_collect_data:
            mock_collect_data.side_effect = KeyError

            with patch('instructor_task.tasks_helper._get_current_task') as mock_current_task:
                mock_current_task.return_value = self.current_task

                self.assertEqual(push_ora2_responses_to_s3(None, None, self.course.id, None, 'generated'), UPDATE_STATUS_FAILED)

    @patch('instructor_task.tasks_helper.datetime')
    def test_report_stores_results(self, mock_time):
        start_time = datetime.now(UTC)
        mock_time.now.return_value = start_time

        test_header = ['field1', 'field2']
        test_rows = [['row1_field1', 'row1_field2'], ['row2_field1', 'row2_field2']]

        with patch('instructor_task.tasks_helper._get_current_task') as mock_current_task:
            mock_current_task.return_value = self.current_task

            with patch('instructor_task.tasks_helper.collect_ora2_data') as mock_collect_data:
                mock_collect_data.return_value = (test_header, test_rows)

                with patch('instructor_task.models.LocalFSReportStore.store_rows') as mock_store_rows:
                    return_val = push_ora2_responses_to_s3(None, None, self.course.id, None, 'generated')

                    timestamp_str = start_time.strftime('%Y-%m-%d-%H%M')
                    course_id_string = urllib.quote(self.course.id.to_deprecated_string().replace('/', '_'))
                    filename = u'{}_ORA2_responses_{}.csv'.format(course_id_string, timestamp_str)

                    self.assertEqual(return_val, UPDATE_STATUS_SUCCEEDED)
                    mock_store_rows.assert_called_once_with(self.course.id, filename, [test_header] + test_rows)


class MockDefaultStorage(object):
    """Mock django's DefaultStorage"""
    def __init__(self):
        pass

    def open(self, file_name):
        """Mock out DefaultStorage.open with standard python open"""
        return open(file_name)


@patch('instructor_task.tasks_helper.DefaultStorage', new=MockDefaultStorage)
class TestCohortStudents(TestReportMixin, InstructorTaskCourseTestCase):
    """
    Tests that bulk student cohorting works.
    """
    def setUp(self):
        self.course = CourseFactory.create()
        self.cohort_1 = CohortFactory(course_id=self.course.id, name='Cohort 1')
        self.cohort_2 = CohortFactory(course_id=self.course.id, name='Cohort 2')
        self.student_1 = self.create_student(username=u'student_1\xec', email='student_1@example.com')
        self.student_2 = self.create_student(username='student_2', email='student_2@example.com')
        self.csv_header_row = ['Cohort Name', 'Exists', 'Students Added', 'Students Not Found']

    def _cohort_students_and_upload(self, csv_data):
        """
        Call `cohort_students_and_upload` with a file generated from `csv_data`.
        """
        with tempfile.NamedTemporaryFile() as temp_file:
            temp_file.write(csv_data.encode('utf-8'))
            temp_file.flush()
            with patch('instructor_task.tasks_helper._get_current_task'):
                return cohort_students_and_upload(None, None, self.course.id, {'file_name': temp_file.name}, 'cohorted')

    def test_username(self):
        result = self._cohort_students_and_upload(
            u'username,email,cohort\n'
            u'student_1\xec,,Cohort 1\n'
            u'student_2,,Cohort 2'
        )
        self.assertDictContainsSubset({'total': 2, 'attempted': 2, 'succeeded': 2, 'failed': 0}, result)
        self.verify_rows_in_csv(
            [
                dict(zip(self.csv_header_row, ['Cohort 1', 'True', '1', ''])),
                dict(zip(self.csv_header_row, ['Cohort 2', 'True', '1', ''])),
            ],
            verify_order=False
        )

    def test_email(self):
        result = self._cohort_students_and_upload(
            'username,email,cohort\n'
            ',student_1@example.com,Cohort 1\n'
            ',student_2@example.com,Cohort 2'
        )
        self.assertDictContainsSubset({'total': 2, 'attempted': 2, 'succeeded': 2, 'failed': 0}, result)
        self.verify_rows_in_csv(
            [
                dict(zip(self.csv_header_row, ['Cohort 1', 'True', '1', ''])),
                dict(zip(self.csv_header_row, ['Cohort 2', 'True', '1', ''])),
            ],
            verify_order=False
        )

    def test_username_and_email(self):
        result = self._cohort_students_and_upload(
            u'username,email,cohort\n'
            u'student_1\xec,student_1@example.com,Cohort 1\n'
            u'student_2,student_2@example.com,Cohort 2'
        )
        self.assertDictContainsSubset({'total': 2, 'attempted': 2, 'succeeded': 2, 'failed': 0}, result)
        self.verify_rows_in_csv(
            [
                dict(zip(self.csv_header_row, ['Cohort 1', 'True', '1', ''])),
                dict(zip(self.csv_header_row, ['Cohort 2', 'True', '1', ''])),
            ],
            verify_order=False
        )

    def test_prefer_email(self):
        """
        Test that `cohort_students_and_upload` greedily prefers 'email' over
        'username' when identifying the user.  This means that if a correct
        email is present, an incorrect or non-matching username will simply be
        ignored.
        """
        result = self._cohort_students_and_upload(
            u'username,email,cohort\n'
            u'student_1\xec,student_1@example.com,Cohort 1\n'  # valid username and email
            u'Invalid,student_2@example.com,Cohort 2'      # invalid username, valid email
        )
        self.assertDictContainsSubset({'total': 2, 'attempted': 2, 'succeeded': 2, 'failed': 0}, result)
        self.verify_rows_in_csv(
            [
                dict(zip(self.csv_header_row, ['Cohort 1', 'True', '1', ''])),
                dict(zip(self.csv_header_row, ['Cohort 2', 'True', '1', ''])),
            ],
            verify_order=False
        )

    def test_non_existent_user(self):
        result = self._cohort_students_and_upload(
            'username,email,cohort\n'
            'Invalid,,Cohort 1\n'
            'student_2,also_fake@bad.com,Cohort 2'
        )
        self.assertDictContainsSubset({'total': 2, 'attempted': 2, 'succeeded': 0, 'failed': 2}, result)
        self.verify_rows_in_csv(
            [
                dict(zip(self.csv_header_row, ['Cohort 1', 'True', '0', 'Invalid'])),
                dict(zip(self.csv_header_row, ['Cohort 2', 'True', '0', 'also_fake@bad.com'])),
            ],
            verify_order=False
        )

    def test_non_existent_cohort(self):
        result = self._cohort_students_and_upload(
            'username,email,cohort\n'
            ',student_1@example.com,Does Not Exist\n'
            'student_2,,Cohort 2'
        )
        self.assertDictContainsSubset({'total': 2, 'attempted': 2, 'succeeded': 1, 'failed': 1}, result)
        self.verify_rows_in_csv(
            [
                dict(zip(self.csv_header_row, ['Does Not Exist', 'False', '0', ''])),
                dict(zip(self.csv_header_row, ['Cohort 2', 'True', '1', ''])),
            ],
            verify_order=False
        )

    def test_too_few_commas(self):
        """
        A CSV file may be malformed and lack traling commas at the end of a row.
        In this case, those cells take on the value None by the CSV parser.
        Make sure we handle None values appropriately.

        i.e.:
            header_1,header_2,header_3
            val_1,val_2,val_3  <- good row
            val_1,,  <- good row
            val_1    <- bad row; no trailing commas to indicate empty rows
        """
        result = self._cohort_students_and_upload(
            u'username,email,cohort\n'
            u'student_1\xec,\n'
            u'student_2'
        )
        self.assertDictContainsSubset({'total': 2, 'attempted': 2, 'succeeded': 0, 'failed': 2}, result)
        self.verify_rows_in_csv(
            [
                dict(zip(self.csv_header_row, ['', 'False', '0', ''])),
            ],
            verify_order=False
        )

    def test_only_header_row(self):
        result = self._cohort_students_and_upload(
            u'username,email,cohort'
        )
        self.assertDictContainsSubset({'total': 0, 'attempted': 0, 'succeeded': 0, 'failed': 0}, result)
        self.verify_rows_in_csv([])

    def test_carriage_return(self):
        """
        Test that we can handle carriage returns in our file.
        """
        result = self._cohort_students_and_upload(
            u'username,email,cohort\r'
            u'student_1\xec,,Cohort 1\r'
            u'student_2,,Cohort 2'
        )
        self.assertDictContainsSubset({'total': 2, 'attempted': 2, 'succeeded': 2, 'failed': 0}, result)
        self.verify_rows_in_csv(
            [
                dict(zip(self.csv_header_row, ['Cohort 1', 'True', '1', ''])),
                dict(zip(self.csv_header_row, ['Cohort 2', 'True', '1', ''])),
            ],
            verify_order=False
        )

    def test_carriage_return_line_feed(self):
        """
        Test that we can handle carriage returns and line feeds in our file.
        """
        result = self._cohort_students_and_upload(
            u'username,email,cohort\r\n'
            u'student_1\xec,,Cohort 1\r\n'
            u'student_2,,Cohort 2'
        )
        self.assertDictContainsSubset({'total': 2, 'attempted': 2, 'succeeded': 2, 'failed': 0}, result)
        self.verify_rows_in_csv(
            [
                dict(zip(self.csv_header_row, ['Cohort 1', 'True', '1', ''])),
                dict(zip(self.csv_header_row, ['Cohort 2', 'True', '1', ''])),
            ],
            verify_order=False
        )

    def test_move_users_to_new_cohort(self):
        self.cohort_1.users.add(self.student_1)
        self.cohort_2.users.add(self.student_2)

        result = self._cohort_students_and_upload(
            u'username,email,cohort\n'
            u'student_1\xec,,Cohort 2\n'
            u'student_2,,Cohort 1'
        )
        self.assertDictContainsSubset({'total': 2, 'attempted': 2, 'succeeded': 2, 'failed': 0}, result)
        self.verify_rows_in_csv(
            [
                dict(zip(self.csv_header_row, ['Cohort 1', 'True', '1', ''])),
                dict(zip(self.csv_header_row, ['Cohort 2', 'True', '1', ''])),
            ],
            verify_order=False
        )

    def test_move_users_to_same_cohort(self):
        self.cohort_1.users.add(self.student_1)
        self.cohort_2.users.add(self.student_2)

        result = self._cohort_students_and_upload(
            u'username,email,cohort\n'
            u'student_1\xec,,Cohort 1\n'
            u'student_2,,Cohort 2'
        )
        self.assertDictContainsSubset({'total': 2, 'attempted': 2, 'skipped': 2, 'failed': 0}, result)
        self.verify_rows_in_csv(
            [
                dict(zip(self.csv_header_row, ['Cohort 1', 'True', '0', ''])),
                dict(zip(self.csv_header_row, ['Cohort 2', 'True', '0', ''])),
            ],
            verify_order=False
        )
