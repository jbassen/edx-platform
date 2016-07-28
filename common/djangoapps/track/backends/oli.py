"""
OLI analytics service event tracker backend.
"""
from __future__ import absolute_import

import json
import logging
from urlparse import urljoin

from django.contrib.auth.models import User
from requests_oauthlib import OAuth1Session

from student.models import anonymous_id_for_user
from track.backends import BaseBackend


LOG = logging.getLogger(__name__)


class OLIAnalyticsBackend(BaseBackend):
    """
    Transmit events to the OLI analytics service
    """
    def __init__(
            self,
            url=None,
            path=None,
            key=None,
            secret=None,
            course_ids=None,
            **kwargs
    ):
        super(OLIAnalyticsBackend, self).__init__(**kwargs)

        self.url = url
        self.path = path
        self.key = key
        self.secret = secret

        # only courses with id in this set will have their data sent
        self.course_ids = set()
        if course_ids is not None:
            self.course_ids = set(course_ids)

        self.oauth = OAuth1Session(self.key, client_secret=self.secret)

    def send(self, event):
        """
        Forward the event to the OLI analytics server
        Exact API here: https://docs.google.com/document/d/1ZB-qwP0bV7ko_xJdJNX1PYKvTyYd4I8CBltfac4dlfw/edit?pli=1#
        OAuth 1 with nonce and body signing
        """
        if not (self.url and self.secret and self.key):
            return None

        # Only currently passing problem_check events, which are CAPA only
        if event.get('event_type') != 'problem_check':
            return None

        if event.get('event_source') != 'server':
            return None

        context = event.get('context')
        if not context:
            return None

        course_id = context.get('course_id')
        if not course_id or course_id not in self.course_ids:
            return None

        user_id = context.get('user_id')
        if not user_id:
            LOG.info('user_id attribute missing from event for OLI service')
            return None

        event_data = event.get('event')
        if not event_data:
            LOG.info('event_data attribute missing from event for OLI service')
            return None

        problem_id = event_data.get('problem_id')
        if not problem_id:
            LOG.info('problem_id attribute missing from event for OLI service')
            return None

        grade = event_data.get('grade')
        if grade is None:
            LOG.info('grade attribute missing from event for OLI service')
            return None

        max_grade = event_data.get('max_grade')
        if max_grade is None:
            LOG.info('max_grade attribute missing from event for OLI service')
            return None

        timestamp = event.get('time')
        if not timestamp:
            LOG.info('time attribute missing from event for OLI service')
            return None

        # put the most expensive operation (DB access) at the end, to not do it needlessly
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            LOG.info('Can not find a user with user_id: %s', user_id)
            return None

        request_payload_string = json.dumps({
            'payload': {
                'course_id': course_id,
                'resource_id': problem_id,
                'student_id': anonymous_id_for_user(user, None),
                'grade': grade,
                'max_grade': max_grade,
                'timestamp': timestamp.isoformat(),
            },
        })

        endpoint = urljoin(self.url, self.path)

        try:
            response = self.oauth.put(endpoint, request_payload_string)
        except Exception as error:
            LOG.info(
                "Unable to send event to OLI analytics service: %s: %s: %s",
                endpoint,
                request_payload_string,
                error,
            )
            return None

        if response.status_code == 200:
            return 'OK'
        else:
            LOG.info('OLI analytics service returns error status code: %s.', response.status_code)
            return 'Error'
