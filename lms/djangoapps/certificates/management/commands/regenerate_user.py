"""Django management command to force certificate regeneration for one user"""

import logging
import copy
from optparse import make_option
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from opaque_keys.edx.locations import SlashSeparatedCourseKey
from xmodule.modulestore.django import modulestore
from certificates.models import BadgeAssertion
from certificates.api import regenerate_user_certificates

use_cme = settings.FEATURES.get('USE_CME_REGISTRATION', False)
if use_cme:
    from cme_registration.models import CmeUserProfile

LOGGER = logging.getLogger(__name__)


class Command(BaseCommand):
    help = """Put a request on the queue to recreate the certificate for a particular user in a particular course."""

    option_list = BaseCommand.option_list + (
        make_option('-n', '--noop',
                    action='store_true',
                    dest='noop',
                    default=False,
                    help="Don't grade or add certificate requests to the queue"),
        make_option('--insecure',
                    action='store_true',
                    dest='insecure',
                    default=False,
                    help="Don't use https for the callback url to the LMS, useful in http test environments"),
        make_option('-c', '--course',
                    metavar='COURSE_ID',
                    dest='course',
                    default=False,
                    help='The course id (e.g., mit/6-002x/circuits-and-electronics) for which the student named in'
                         '<username> should be graded'),
        make_option('-u', '--user',
                    metavar='USERNAME',
                    dest='username',
                    default=False,
                    help='The username or email address for whom grading and certification should be requested'),
        make_option('-G', '--grade',
                    metavar='GRADE',
                    dest='grade_value',
                    default=None,
                    help='The grade string, such as "Distinction", which should be passed to the certificate agent'),
        make_option('-T', '--template',
                    metavar='TEMPLATE',
                    dest='template_file',
                    default=None,
                    help='The template file used to render this certificate, like "QMSE01-distinction.pdf"'),
        make_option(
            '-d',
            '--designation',
            metavar='DESIGNATION',
            dest='designation',
            default=None,
            help='Professional designation to pass to certificate generator',
        ),
    )

    def handle(self, *args, **options):

        # Scrub the username from the log message
        cleaned_options = copy.copy(options)
        if 'username' in cleaned_options:
            cleaned_options['username'] = '<USERNAME>'
        LOGGER.info(
            (
                u"Starting to create tasks to regenerate certificates "
                u"with arguments %s and options %s"
            ),
            unicode(args),
            unicode(cleaned_options)
        )

        if options['course']:
            # try to parse out the course from the serialized form
            try:
                course_id = CourseKey.from_string(options['course'])
            except InvalidKeyError:
                LOGGER.warning(
                    (
                        u"Course id %s could not be parsed as a CourseKey; "
                        u"falling back to SlashSeparatedCourseKey.from_deprecated_string()"
                    ),
                    options['course']
                )
                course_id = SlashSeparatedCourseKey.from_deprecated_string(options['course'])
        else:
            raise CommandError("You must specify a course")

        user = options['username']
        if not (course_id and user):
            raise CommandError('both course id and student username are required')

        student = None
        if '@' in user:
            student = User.objects.get(email=user, courseenrollment__course_id=course_id)
        else:
            student = User.objects.get(username=user, courseenrollment__course_id=course_id)

        course = modulestore().get_course(course_id, depth=2)

        designation = options['designation']

        if not designation and use_cme:
            designations = CmeUserProfile.objects.filter(user=student).values('professional_designation')
            if len(designations):
                designation = designations[0]['professional_designation']

        if not options['noop']:
            LOGGER.info(
                (
                    u"Adding task to the XQueue to generate a certificate "
                    u"for student %s in course '%s'."
                ),
                student.id,
                course_id
            )

            # Add the certificate request to the queue
            ret = regenerate_user_certificates(
                student, course_id, course=course,
                designation=designation,
                forced_grade=options['grade_value'],
                template_file=options['template_file'],
                insecure=options['insecure']
            )

            try:
                badge = BadgeAssertion.objects.get(user=student, course_id=course_id)
                badge.delete()
                LOGGER.info(u"Cleared badge for student %s.", student.id)
            except BadgeAssertion.DoesNotExist:
                pass

            LOGGER.info(
                (
                    u"Added a certificate regeneration task to the XQueue "
                    u"for student %s in course '%s'. "
                    u"The new certificate status is '%s'."
                ),
                student.id,
                unicode(course_id),
                ret
            )

        else:
            LOGGER.info(
                (
                    u"Skipping certificate generation for "
                    u"student %s in course '%s' "
                    u"because the noop flag is set."
                ),
                student.id,
                unicode(course_id)
            )

        LOGGER.info(
            (
                u"Finished regenerating certificates command for "
                u"user %s and course '%s'."
            ),
            student.id,
            unicode(course_id)
        )
