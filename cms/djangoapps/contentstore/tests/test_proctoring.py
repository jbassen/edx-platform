"""
Tests for the edx_proctoring integration into Studio
"""

from mock import patch
import ddt
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory

from contentstore.signals import listen_for_course_publish

from edx_proctoring.api import get_all_exams_for_course


@ddt.ddt
@patch.dict('django.conf.settings.FEATURES', {'ENABLE_PROCTORED_EXAMS': True})
class TestProctoredExams(ModuleStoreTestCase):
    """
    Tests for the publishing of proctored exams
    """

    def setUp(self):
        """
        Initial data setup
        """
        super(TestProctoredExams, self).setUp()

        self.course = CourseFactory.create(
            org='edX',
            course='900',
            run='test_run',
            enable_proctored_exams=True
        )

    def _verify_exam_data(self, sequence, expected_active):
        """
        Helper method to compare the sequence with the stored exam,
        which should just be a single one
        """
        exams = get_all_exams_for_course(unicode(self.course.id))

        self.assertEqual(len(exams), 1)

        exam = exams[0]
        self.assertEqual(exam['course_id'], unicode(self.course.id))
        self.assertEqual(exam['content_id'], unicode(sequence.location))
        self.assertEqual(exam['exam_name'], sequence.display_name)
        self.assertEqual(exam['time_limit_mins'], sequence.default_time_limit_minutes)
        self.assertEqual(exam['is_proctored'], sequence.is_proctored_enabled)
        self.assertEqual(exam['is_active'], expected_active)

    @ddt.data(
        (True, 10, True, True, False),
        (True, 10, False, True, False),
        (True, 10, True, True, True),
    )
    @ddt.unpack
    def test_publishing_exam(self, is_time_limited, default_time_limit_minutes,
                             is_procted_enabled, expected_active, republish):
        """
        Happy path testing to see that when a course is published which contains
        a proctored exam, it will also put an entry into the exam tables
        """

        chapter = ItemFactory.create(parent=self.course, category='chapter', display_name='Test Section')
        sequence = ItemFactory.create(
            parent=chapter,
            category='sequential',
            display_name='Test Proctored Exam',
            graded=True,
            is_time_limited=is_time_limited,
            default_time_limit_minutes=default_time_limit_minutes,
            is_proctored_enabled=is_procted_enabled
        )

        listen_for_course_publish(self, self.course.id)

        self._verify_exam_data(sequence, expected_active)

        if republish:
            # update the sequence
            sequence.default_time_limit_minutes += sequence.default_time_limit_minutes
            self.store.update_item(sequence, self.user.id)

            # simulate a publish
            listen_for_course_publish(self, self.course.id)

            # reverify
            self._verify_exam_data(sequence, expected_active)

    def test_unpublishing_proctored_exam(self):
        """
        Make sure that if we publish and then unpublish a proctored exam,
        the exam record stays, but is marked as is_active=False
        """

        chapter = ItemFactory.create(parent=self.course, category='chapter', display_name='Test Section')
        sequence = ItemFactory.create(
            parent=chapter,
            category='sequential',
            display_name='Test Proctored Exam',
            graded=True,
            is_time_limited=True,
            default_time_limit_minutes=10,
            is_proctored_enabled=True
        )

        listen_for_course_publish(self, self.course.id)

        exams = get_all_exams_for_course(unicode(self.course.id))
        self.assertEqual(len(exams), 1)

        sequence.is_time_limited = False
        sequence.is_proctored_enabled = False

        self.store.update_item(sequence, self.user.id)

        listen_for_course_publish(self, self.course.id)

        self._verify_exam_data(sequence, False)

    def test_dangling_exam(self):
        """
        Make sure we filter out all dangling items
        """

        chapter = ItemFactory.create(parent=self.course, category='chapter', display_name='Test Section')
        ItemFactory.create(
            parent=chapter,
            category='sequential',
            display_name='Test Proctored Exam',
            graded=True,
            is_time_limited=True,
            default_time_limit_minutes=10,
            is_proctored_enabled=True
        )

        listen_for_course_publish(self, self.course.id)

        exams = get_all_exams_for_course(unicode(self.course.id))
        self.assertEqual(len(exams), 1)

        self.store.delete_item(chapter.location, self.user.id)

        # republish course
        listen_for_course_publish(self, self.course.id)

        # look through exam table, the dangling exam
        # should be disabled
        exams = get_all_exams_for_course(unicode(self.course.id))
        self.assertEqual(len(exams), 1)

        exam = exams[0]
        self.assertEqual(exam['is_active'], False)

    @patch.dict('django.conf.settings.FEATURES', {'ENABLE_PROCTORED_EXAMS': False})
    def test_feature_flag_off(self):
        """
        Make sure the feature flag is honored
        """

        chapter = ItemFactory.create(parent=self.course, category='chapter', display_name='Test Section')
        ItemFactory.create(
            parent=chapter,
            category='sequential',
            display_name='Test Proctored Exam',
            graded=True,
            is_time_limited=True,
            default_time_limit_minutes=10,
            is_proctored_enabled=True
        )

        listen_for_course_publish(self, self.course.id)

        exams = get_all_exams_for_course(unicode(self.course.id))
        self.assertEqual(len(exams), 0)

    def test_advanced_setting_off(self):
        """
        Make sure the feature flag is honored
        """

        self.course = CourseFactory.create(
            org='edX',
            course='901',
            run='test_run2',
            enable_proctored_exams=False
        )

        chapter = ItemFactory.create(parent=self.course, category='chapter', display_name='Test Section')
        ItemFactory.create(
            parent=chapter,
            category='sequential',
            display_name='Test Proctored Exam',
            graded=True,
            is_time_limited=True,
            default_time_limit_minutes=10,
            is_proctored_enabled=True
        )

        listen_for_course_publish(self, self.course.id)

        # there shouldn't be any exams because we haven't enabled that
        # advanced setting flag
        exams = get_all_exams_for_course(unicode(self.course.id))
        self.assertEqual(len(exams), 0)
