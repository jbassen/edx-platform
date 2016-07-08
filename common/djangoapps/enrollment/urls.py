"""
URLs for the Enrollment API

"""
from django.conf import settings
from django.conf.urls import patterns, url

from .views import (
    EnrollmentView,
    EnrollmentListView,
    EnrollmentCourseDetailView
)

USERNAME_PATTERN = '(?P<username>[\w.@+-]+)'

urlpatterns = patterns(
    'enrollment.views',
    # First, you'll need an urls entry
    url(
        r'^enrollment/roster/{course_key}$'.format(course_key=settings.COURSE_ID_PATTERN),
        EnrollmentCourseDetailView.as_view(),  # You'll need to create a new view in `views.py`
        name='courseenrollmentroster',  # This is some recognizable name
    ),
    url(
        r'^enrollment/{username},{course_key}$'.format(username=USERNAME_PATTERN,
                                                       course_key=settings.COURSE_ID_PATTERN),
        EnrollmentView.as_view(),
        name='courseenrollment'
    ),
    url(
        r'^enrollment/{course_key}$'.format(course_key=settings.COURSE_ID_PATTERN),
        EnrollmentView.as_view(),
        name='courseenrollment'
    ),
    url(r'^enrollment$', EnrollmentListView.as_view(), name='courseenrollments'),
    url(
        r'^course/{course_key}$'.format(course_key=settings.COURSE_ID_PATTERN),
        EnrollmentCourseDetailView.as_view(),
        name='courseenrollmentdetails'
    ),
)
